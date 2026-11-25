"""M0: does LFM3-Omni Q4_0 call the right tool with the right arguments, typed and spoken?

    python -m cortex_core.brain.tool_eval wavs --out DIR      # the cases spoken in Cortex's own TTS voice (16 kHz)
    python -m cortex_core.brain.tool_eval run [--spoken DIR] --report OUT.json

Cases: brain/data/tool_eval.json. A case passes "tool" when the first call names the expected tool (or no call is
made when none is expected) and "args" when every expected value is found in that argument (case-insensitive
substring; booleans compared as true/false). Gate (spec §10): >= 90 % right tool, >= 85 % exact args, 0 calls on
chit-chat.

The spoken cases use the model's own TTS voice, not a person: a check of the audio path and the call decision on
speech, not of accents or a noisy street.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from cortex_core.brain import prompt, tools

CASES = Path(__file__).parent / "data" / "tool_eval.json"
GATE = {"tool": 0.90, "args": 0.85, "chitchat_calls": 0}


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(Path(path).read_text())["cases"]


def score(case: dict, call_text: str | None) -> dict:
    """One case's verdict from the tool_call event's text (None: the model answered without a call)."""
    calls = tools.parse_calls(call_text) if call_text else []
    first = calls[0] if calls else None
    expect = case["expect"]
    got = first.name if first else None
    tool_ok = got == expect
    args_ok = tool_ok
    if tool_ok and first is not None:
        for k, want in case.get("args", {}).items():
            have = str(first.args.get(k, "")).strip().lower()
            if want.lower() not in have:
                args_ok = False
    return {"q": case["q"], "expect": expect, "got": got, "args": first.args if first else {},
            "tool_ok": tool_ok, "args_ok": args_ok, "sg": bool(case.get("sg")), "n_calls": len(calls)}


def summarize(rows: list[dict]) -> dict:
    tool_cases = [r for r in rows if r["expect"] is not None]
    chit = [r for r in rows if r["expect"] is None]
    sg = [r for r in rows if r["sg"]]
    frac = lambda xs, k: (sum(r[k] for r in xs) / len(xs)) if xs else 0.0
    s = {
        "n": len(rows),
        "tool": frac(rows, "tool_ok"),
        "args": frac(tool_cases, "args_ok"),
        "chitchat_calls": sum(r["got"] is not None for r in chit),
        "singlish_tool": frac(sg, "tool_ok"),
        "failures": [{"q": r["q"], "expect": r["expect"], "got": r["got"], "args": r["args"]}
                     for r in rows if not r["args_ok"]],
    }
    s["pass"] = s["tool"] >= GATE["tool"] and s["args"] >= GATE["args"] and s["chitchat_calls"] <= GATE["chitchat_calls"]
    return s


def resample_24k_to_16k(x):
    """Cortex's 24 kHz speech -> the mic path's 16 kHz (FFT resample; the clips are short)."""
    import numpy as np

    x = np.asarray(x, dtype=np.float32)
    n_out = int(round(len(x) * 2 / 3))
    X = np.fft.rfft(x)
    Y = np.zeros(n_out // 2 + 1, dtype=complex)
    k = min(len(X), len(Y))
    Y[:k] = X[:k]
    return (np.fft.irfft(Y, n_out) * (n_out / len(x))).astype(np.float32)


def split_wav(pcm, sound_ms: list[float], rate: int = 24000) -> list:
    """The WAV sink's one stream -> one clip per answer, by each answer's sound_end length."""
    out, at = [], 0
    for ms in sound_ms:
        n = int(round(ms * rate / 1000))
        out.append(pcm[at:at + n])
        at += n
    return out


# ------------------------------------------------------------------ box runs (need the engine)

LIB = "/opt/cortex/build/cortex-engine/libcortex_engine.so"
BASE = "/var/lib/cortex/bench/engine/engine.json"


def _config(extra: dict) -> dict:
    cfg = json.loads(Path(BASE).read_text())
    cfg.update({"system_prompt": prompt.SYSTEM, "tools": tools.load().lfm_tools()})
    cfg.update(extra)
    return cfg


def make_wavs(out: Path, cases: list[dict]) -> None:
    import numpy as np

    from cortex_core.engine.native import Engine

    out.mkdir(parents=True, exist_ok=True)
    raw = out / "all_24k.wav"
    lens = []
    with Engine(LIB, _config({"speak": True, "speaker_device": f"wav:{raw}"})) as eng:
        for c in cases:
            for ev in eng.say(c["q"]):
                if ev["type"] == "error":
                    raise RuntimeError(f"say failed: {ev}")
            while True:  # this sentence's sound_end (the sink is paced at real time)
                ev = eng.next_voice(timeout=60)
                if ev["type"] == "sound_end":
                    lens.append(ev["sound_ms"])
                    break
    import wave

    with wave.open(str(raw)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    for i, clip in enumerate(split_wav(pcm, lens)):
        y = resample_24k_to_16k(clip)
        with wave.open(str(out / f"case{i:02d}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"{len(lens)} clips in {out}")


def _wait_answer(get, timeout: float) -> tuple[str | None, dict]:
    call, done = None, {}
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ev = get(max(0.1, end - time.monotonic()))
        if ev["type"] == "tool_call":
            call = ev["text"]
        elif ev["type"] == "done":
            return call, ev
        elif ev["type"] == "error" and "busy" not in ev.get("what", ""):
            return call, {"error": ev.get("what")}
    return call, {"error": "timeout"}


def run(cases: list[dict], spoken: Path | None) -> dict:
    import wave

    import numpy as np

    from cortex_core.engine.native import Engine

    report: dict = {"model": "LFM3-Omni-2B Q4_0", "prompt": prompt.SYSTEM, "when": time.strftime("%Y-%m-%d %H:%M")}
    with Engine(LIB, _config({"speak": False})) as eng:
        rows, ms = [], []
        for c in cases:
            eng.reset_history()
            call, done = None, {}
            for ev in eng.ask(c["q"], 120):
                if ev["type"] == "tool_call":
                    call = ev["text"]
                elif ev["type"] in ("done", "error"):
                    done = ev
            r = score(c, call)
            r["call_ms"] = done.get("total_ms")
            rows.append(r)
            if call:
                ms.append(done.get("total_ms", 0))
            print(("ok " if r["args_ok"] else "XX ") + f"{c['q']!r} -> {r['got']} {r['args']}", flush=True)
        report["typed"] = summarize(rows) | {"rows": rows}
        if ms:
            ms.sort()
            report["typed"]["call_total_ms_median"] = ms[len(ms) // 2]
        if spoken:
            eng.set_listening(True)
            rows = []
            for i, c in enumerate(cases):
                eng.reset_history()
                with wave.open(str(spoken / f"case{i:02d}.wav")) as w:
                    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                pcm = np.concatenate([np.zeros(8000, np.int16), pcm, np.zeros(16000, np.int16)])
                for at in range(0, len(pcm), 320):  # 20 ms chunks at real time, as the mic would
                    eng.push_audio(pcm[at:at + 320])
                    time.sleep(0.02)
                call, done = _wait_answer(lambda t: eng.next_voice(timeout=t), 60)
                r = score(c, call)
                r["error"] = done.get("error")
                rows.append(r)
                print(("ok " if r["args_ok"] else "XX ") + f"[spoken] {c['q']!r} -> {r['got']} {r['args']}", flush=True)
                time.sleep(0.5)
            eng.set_listening(False)
            report["spoken"] = summarize(rows) | {"rows": rows}
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cortex_core.brain.tool_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wavs")
    w.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--spoken", type=Path)
    r.add_argument("--report", type=Path, required=True)
    a = ap.parse_args(argv)
    cases = load_cases()
    if a.cmd == "wavs":
        make_wavs(a.out, cases)
        return 0
    rep = run(cases, a.spoken)
    a.report.write_text(json.dumps(rep, indent=1))
    for k in ("typed", "spoken"):
        if k in rep:
            s = rep[k]
            print(f"{k}: tool {s['tool']:.0%}, args {s['args']:.0%}, chit-chat calls {s['chitchat_calls']}, "
                  f"singlish {s['singlish_tool']:.0%} -> {'PASS' if s['pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
