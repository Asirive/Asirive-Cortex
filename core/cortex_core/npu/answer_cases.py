"""Re-answer the test cases from saved NPU features, with any LM file and thread setting.

    python -m cortex_core.npu.answer_cases --cases cases.json --feat-dir DIR --embd cortex-embd \
        --model LM.gguf --mmproj MMPROJ.gguf --out answers.json [--threads N] [--taskset 4-7]

Feature files are <feat-dir>/<image stem>.npu.f32 (+ .json), as run_npu writes them. No NPU is opened.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def answer(embd: str, model: str, mmproj: str, feat: Path, prompt: str, threads: int | None = None,
           prefix: list[str] | tuple[str, ...] = ()) -> tuple[str, dict]:
    """Run `cortex-embd answer`; return (answer text, stats). A failure is returned as "ERROR: ..." text."""
    cmd = [*prefix, embd, "answer", "-m", model, "--mmproj", mmproj, "--feat", str(feat), "-p", prompt]
    if threads:
        cmd += ["-t", str(threads)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode:
        return f"ERROR: {r.stderr.strip()[-300:]}", {}
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    stats = json.loads(lines.pop()) if lines and lines[-1].startswith("{") else {}
    return " ".join(lines).replace("<think></think>", "").strip(), stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cortex_core.npu.answer_cases")
    for a in ("--cases", "--feat-dir", "--embd", "--model", "--mmproj", "--out"):
        ap.add_argument(a, required=True)
    ap.add_argument("--threads", type=int)
    ap.add_argument("--taskset", help="CPU list to pin cortex-embd to, e.g. 4-7")
    ap.add_argument("--prefix", action="append", default=[], help="extra command prefix item (repeatable)")
    a = ap.parse_args(argv)
    prefix = [*(["taskset", "-c", a.taskset] if a.taskset else []), *a.prefix]
    rows = []
    for c in json.loads(Path(a.cases).read_text()):
        feat = Path(a.feat_dir) / (Path(c["image"]).stem + ".npu.f32")
        if feat.is_file():
            ans, stats = answer(a.embd, a.model, a.mmproj, feat, c["question"] + " One sentence.", a.threads, prefix)
        else:
            ans, stats = f"ERROR: no feature {feat}", {}
        ok = not ans.startswith("ERROR:") and any(k in ans.lower() for k in c["expect"])
        row = {"image": c["image"], "answer": ans, "match": ok, "ttft_s": stats.get("ttft_s"),
               "decode_tps": stats.get("decode_tps"), "model": a.model, "threads": a.threads, "taskset": a.taskset,
               "cpu_answer": c.get("cpu_answer")}
        rows.append(row)
        print(json.dumps(row), flush=True)
    Path(a.out).write_text(json.dumps(rows, indent=1))
    print(f"matched {sum(r['match'] for r in rows)}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
