"""The 12 test cases through the native engine: push -> refresh -> wait for the view -> ask, once per case.

    python -m cortex_core.engine.native_bench --lib libcortex_engine.so --config engine.json \
        --cases /var/lib/cortex/bench/npu/test/cases.json --out results.json [--still N]

Rows: answer, match (any `expect` keyword), ttft_ms, view prep/encode/read ms, view age. Prints "matched N/12".
--still N re-pushes the last frame N times to measure the scene-skip rate on a still scene. --gap S waits S seconds
between an answer and the next frame (the camera cadence; the last answer joins the history meanwhile). --fresh
clears the conversation before each case (parity with the one-shot cortex-embd bench).
Also records peak RSS (VmHWM) and the engine threads' CPU affinities.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from cortex_core.engine.native import Engine


def row_from_events(case: dict, events: list[dict]) -> dict:
    """One case's view + answer events -> a result row."""
    view = next((e for e in events if e["type"] == "view"), {})
    done = next((e for e in events if e["type"] == "done"), {})
    err = next((e for e in events if e["type"] == "error"), None)
    text = "".join(e["text"] for e in events if e["type"] == "token")
    text = text.replace("<think></think>", "").strip()
    if err:
        text = f"ERROR: {err['what']}" + (f" ({text})" if text else "")
    match = err is None and any(k in text.lower() for k in case["expect"])
    parts = [view.get(k) for k in ("prep_ms", "encode_ms", "read_ms")]
    return {
        "image": case["image"], "answer": text, "match": match,
        "ttft_ms": done.get("ttft_ms"), "total_ms": done.get("total_ms"), "n_out": done.get("n_out"),
        "prep_ms": parts[0], "encode_ms": parts[1], "read_ms": parts[2],
        "refresh_ms": sum(parts) if all(p is not None for p in parts) else None,
        "skipped": view.get("skipped"), "cos": view.get("cos"), "preempted": view.get("preempted"),
        "view_frame_id": done.get("view_frame_id"), "view_age_ms": done.get("view_age_ms"),
    }


def vm_hwm_kb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def main(argv: list[str] | None = None) -> int:
    import numpy as np
    from PIL import Image

    ap = argparse.ArgumentParser(prog="cortex_core.engine.native_bench")
    for a in ("--lib", "--config", "--cases", "--out"):
        ap.add_argument(a, required=True)
    ap.add_argument("--still", type=int, default=10, help="re-push the last frame N times (skip rate)")
    ap.add_argument("--gap", type=float, default=1.0,
                    help="seconds between an answer and the next frame (INDOOR_NAV camera cadence is 1 s)")
    ap.add_argument("--fresh", action="store_true", help="clear the conversation before each case")
    a = ap.parse_args(argv)
    cases = json.loads(Path(a.cases).read_text())
    base = Path(a.cases).parent
    rows, still = [], []
    with Engine(a.lib, json.loads(Path(a.config).read_text())) as eng:
        rgb = None
        for i, c in enumerate(cases, 1):
            img = Path(c["image"])
            img = img if img.is_absolute() else base / img.name
            rgb = np.asarray(Image.open(img).convert("RGB"))
            if a.fresh:
                eng.reset_history()
            if i > 1:
                time.sleep(a.gap)
            eng.push_frame(rgb, i)
            eng.refresh()
            events = [eng.wait_view()]
            if events[0]["type"] == "view":
                events += list(eng.ask(c["question"] + " One sentence."))
            row = row_from_events(c, events)
            rows.append(row)
            print(json.dumps(row), flush=True)
        for j in range(a.still):
            eng.push_frame(rgb, 1000 + j)
            eng.refresh()
            still.append(eng.wait_view())
        status = eng.status()
    ok = [r for r in rows if r["ttft_ms"] is not None]
    med = lambda k: statistics.median(r[k] for r in ok if r[k] is not None) if ok else None  # noqa: E731
    summary = {
        "matched": sum(r["match"] for r in rows), "cases": len(rows),
        "ttft_ms_median": med("ttft_ms"), "refresh_ms_median": med("refresh_ms"),
        "encode_ms_median": med("encode_ms"), "read_ms_median": med("read_ms"),
        "still_frames": len(still), "still_skipped": sum(bool(v.get("skipped")) for v in still),
        "vm_hwm_kb": vm_hwm_kb(), "status": status, "fresh": a.fresh, "gap_s": a.gap,
    }
    Path(a.out).write_text(json.dumps({"rows": rows, "still": still, "summary": summary}, indent=1))
    print(json.dumps(summary))
    print(f"matched {summary['matched']}/{summary['cases']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
