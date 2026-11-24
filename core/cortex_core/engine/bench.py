"""LFM3-Omni baseline runner: run each case against a running llama-server, summarise, write a report.

    python -m cortex_core.engine.bench --server http://127.0.0.1:8080 --cases cases.json --media DIR \
        --backend cpu --llama-tag b12000 --model m.gguf --mmproj p.gguf --quant Q4_K_M --pid 1234 \
        --out-json cpu.json --out-md cpu.md --state-dir /var/lib/cortex

The report is rewritten after every case, and Ctrl+C keeps the finished cases (marked partial).
Images and audio in --media are dev data and must never be committed (privacy law).
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import platform
import statistics
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from cortex_core.engine import sysinfo
from cortex_core.engine.llama_client import RunResult, stream_chat, user_message

TARGET_S = 1.0
METRICS = ("ttft_s", "ttfa_s", "prefill_tps", "decode_tps", "wall_s")


@dataclass
class Case:
    id: str
    text: str
    image: Optional[Path]
    audio: Optional[Path]
    audio_out: bool


def load_cases(path: Path, media: Path) -> list[Case]:
    out = []
    for c in json.loads(Path(path).read_text(encoding="utf-8")):
        files = {}
        for key in ("image", "audio"):
            rel = c.get(key)
            files[key] = None if not rel else media / rel
            if files[key] is not None and not files[key].is_file():
                raise ValueError(f"case {c['id']}: {key} file not found: {files[key]}")
        out.append(Case(c["id"], c["text"], files["image"], files["audio"], bool(c.get("audio_out", False))))
    return out


def _p90(values: list[float]) -> float:
    s = sorted(values)
    return s[math.ceil(0.9 * len(s)) - 1]


def summarise(runs: list[RunResult]) -> dict:
    good = [r for r in runs if r.ok]
    failed = [r for r in runs if not r.ok]
    s: dict = {"n_ok": len(good), "n_failed": len(failed)}
    for m in METRICS:
        vals = [getattr(r, m) for r in good if getattr(r, m) is not None]
        s[m] = {"median": statistics.median(vals), "p90": _p90(vals)} if vals else {"median": None, "p90": None}
    prompts = [r.prompt_n for r in good if r.prompt_n is not None]
    cached = [r.cache_n for r in good if r.cache_n is not None]
    s["prompt_n"] = statistics.median(prompts) if prompts else None
    s["cache_n_max"] = max(cached) if cached else None
    all_400 = bool(runs) and not good and all(r.status == 400 for r in runs)
    s["unsupported"] = runs[0].error if all_400 else None
    return s


class _Sampler:
    """Samples the hottest thermal zone and power draw in the background while a case runs."""

    def __init__(self, thermal: Path, power: Path, every_s: float):
        self.thermal, self.power, self.every_s = thermal, power, every_s
        self.temps: list[float] = []
        self.watts: list[float] = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def _sample(self) -> None:
        t = sysinfo.read_temps_c(self.thermal)
        if t:
            self.temps.append(max(t.values()))
        w = sysinfo.read_power_w(self.power)
        if w is not None:
            self.watts.append(w)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.every_s)

    def __enter__(self) -> "_Sampler":
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._t.join()
        self._sample()


def _over_target(s: dict, audio_out: bool) -> Optional[bool]:
    if audio_out:  # a speaking case is judged on first audio only; no audio means no verdict
        first = s["ttfa_s"]["median"]
    else:
        first = s["ttft_s"]["median"]
    return None if first is None else first > TARGET_S


def run_bench(cases: list[Case], base_url: str, *, reps: int = 5, warmup: int = 1, pid: Optional[int] = None,
              chat: Callable = stream_chat, proc: Path = Path("/proc"), thermal: Path = Path("/sys/class/thermal"),
              power: Path = Path("/sys/class/power_supply"), sample_s: float = 0.25,
              on_case: Optional[Callable[[dict], None]] = None) -> dict:
    out: dict = {}
    result = {"cases": out, "target_s": TARGET_S}
    for c in cases:
        msgs = [user_message(c.text, c.image, c.audio)]
        for _ in range(warmup):
            chat(base_url, msgs, audio_out=c.audio_out)
        with _Sampler(thermal, power, sample_s) as smp:
            s = summarise([chat(base_url, msgs, audio_out=c.audio_out) for _ in range(reps)])
        s["peak_rss_mb"] = sysinfo.read_peak_rss_mb(pid, proc) if pid is not None else None
        s["max_temp_c"] = max(smp.temps) if smp.temps else None
        s["power_w"] = statistics.mean(smp.watts) if smp.watts else None
        s["power_max_w"] = max(smp.watts) if smp.watts else None
        s["no_audio"] = c.audio_out and s["ttfa_s"]["median"] is None
        s["over_target"] = _over_target(s, c.audio_out)
        out[c.id] = s
        if on_case is not None:
            on_case(result)
    return result


def _f(v: Optional[float], digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def _pair(m: dict, digits: int = 2) -> str:
    return f"{_f(m['median'], digits)} / {_f(m['p90'], digits)}"


def _verdict(s: dict) -> str:
    if s.get("unsupported"):
        return "unsupported: " + s["unsupported"].replace("|", "/")[:80]
    if s.get("no_audio"):
        return "no audio produced"
    return "n/a" if s["over_target"] is None else ("no" if s["over_target"] else "yes")


def write_report(result: dict, meta: dict, out_json: Path, out_md: Path, state_dir: Optional[Path]) -> None:
    rows = [f"# LFM3-Omni baseline: {meta.get('backend', '?')}", "",
            " · ".join(f"{k}: {v}" for k, v in meta.items()), "",
            "| case | ok/failed | first token s (med/p90) | first audio s (med/p90) | prefill tok/s | decode tok/s "
            "| prompt tok / cached | server peak RAM MB (so far) | max temp °C | power W (mean/max) | < 1 s? |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for cid, s in result["cases"].items():
        rows.append(f"| {cid} | {s['n_ok']}/{s['n_failed']} | {_pair(s['ttft_s'])} | {_pair(s['ttfa_s'])} "
                    f"| {_f(s['prefill_tps']['median'], 1)} | {_f(s['decode_tps']['median'], 1)} "
                    f"| {_f(s.get('prompt_n'), 0)} / {_f(s.get('cache_n_max'), 0)} | {_f(s['peak_rss_mb'], 0)} "
                    f"| {_f(s['max_temp_c'], 1)} | {_f(s['power_w'], 2)} / {_f(s.get('power_max_w'), 2)} "
                    f"| {_verdict(s)} |")
    out_md.write_text("\n".join(rows) + "\n", encoding="utf-8")
    text = json.dumps({"meta": meta, **result}, indent=2)
    out_json.write_text(text, encoding="utf-8")
    if state_dir is not None:
        try:
            (state_dir / "bench").mkdir(parents=True, exist_ok=True)
            (state_dir / "bench" / "latest.json").write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"warning: could not write {state_dir / 'bench' / 'latest.json'} for the TUI: {e}", file=sys.stderr)


def main(argv: Optional[list[str]] = None, chat: Callable = stream_chat) -> int:
    p = argparse.ArgumentParser(prog="python -m cortex_core.engine.bench")
    p.add_argument("--server", default="http://127.0.0.1:8080")
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--media", type=Path, required=True)
    p.add_argument("--backend", choices=("cpu", "gpu"), required=True)
    p.add_argument("--llama-tag", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--mmproj", required=True)
    p.add_argument("--quant", default="Q4_K_M")
    p.add_argument("--pid", type=int)
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--out-json", type=Path, required=True)
    p.add_argument("--out-md", type=Path, required=True)
    p.add_argument("--state-dir", type=Path)
    a = p.parse_args(argv)
    meta = {"backend": a.backend, "llama_cpp": a.llama_tag, "model": a.model, "mmproj": a.mmproj, "quant": a.quant,
            "date": datetime.date.today().isoformat(), "host": platform.node(), "partial": False}
    done: dict = {"cases": {}, "target_s": TARGET_S}

    def save(result: dict) -> None:
        done.update(result)
        write_report(result, meta, a.out_json, a.out_md, a.state_dir)

    rc = 0
    try:
        run_bench(load_cases(a.cases, a.media), a.server, reps=a.reps, warmup=a.warmup, pid=a.pid, chat=chat,
                  on_case=save)
    except KeyboardInterrupt:
        meta["partial"] = True
        write_report({"cases": dict(done["cases"]), "target_s": TARGET_S}, meta, a.out_json, a.out_md, a.state_dir)
        rc = 130
    if a.out_md.exists():
        print(a.out_md.read_text(encoding="utf-8"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
