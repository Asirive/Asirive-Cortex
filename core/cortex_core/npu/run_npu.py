"""Vision encoder on the Hexagon NPU (split chain), checked against ONNX CPU and answered by the LM.

    python -m cortex_core.npu.run_npu --split DIR --lib libcortex_npu.so --qnn-lib QNN_LIB_DIR \
        --onnx vision_encoder.onnx --cases cases.json --embd cortex-embd --model LM.gguf --mmproj MMPROJ.gguf \
        --out-dir DIR [--runs 20]

For every case: NPU encode timing, cosine vs ONNX fp32 on CPU, `cortex-embd answer` from the NPU features,
and the keyword check (any of "expect"). Writes results.json in --out-dir.
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .compare import cosine_rows, save_feat


@dataclass
class NpuOpen:
    ok: bool
    error: str = ""
    encoder: object = field(default=None, repr=False)


def open_npu(split_dir: Path, lib: Path, qnn_lib_dir: Path) -> NpuOpen:
    split_dir, lib, qnn_lib_dir = Path(split_dir), Path(lib), Path(qnn_lib_dir)
    if not (split_dir / "io.json").is_file() or not list(split_dir.glob("npu*.bin")):
        return NpuOpen(False, f"no split encoder in {split_dir} (need io.json + npu*.bin; see core/scripts/npu)")
    if not lib.is_file():
        return NpuOpen(False, f"{lib} missing: build it with core/tools/cortex-npu/build.sh")
    if not (qnn_lib_dir / "libQnnHtp.so").is_file():
        return NpuOpen(False, f"libQnnHtp.so not in {qnn_lib_dir}: install qcom-qnn-sdk-v68 (QNN 2.42 runtime)")
    from .qnn import Runtime
    from .split_encoder import SplitEncoder

    try:
        return NpuOpen(True, encoder=SplitEncoder.from_dir(split_dir, Runtime(lib, qnn_lib_dir)))
    except (OSError, RuntimeError, KeyError, ValueError) as e:
        return NpuOpen(False, f"NPU load failed: {e}")


def _soc_state() -> dict:
    temps = [int(Path(p).read_text()) / 1000 for p in glob.glob("/sys/class/thermal/thermal_zone*/temp")
             if Path(p).read_text().strip().lstrip("-").isdigit()]
    mhz = [int(Path(p).read_text()) / 1000 for p in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")]
    return {"temp_max_c": max(temps, default=None), "cpu_mhz_mean": round(statistics.mean(mhz)) if mhz else None}


def _answer(embd: str, model: str, mmproj: str, feat: Path, prompt: str) -> tuple[str, dict]:
    r = subprocess.run([embd, "answer", "-m", model, "--mmproj", mmproj, "--feat", str(feat), "-p", prompt],
                       capture_output=True, text=True, timeout=120)
    if r.returncode:
        return f"ERROR: {r.stderr.strip()[-300:]}", {}
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    stats = json.loads(lines.pop()) if lines and lines[-1].startswith("{") else {}
    ans = " ".join(lines).replace("<think></think>", "").strip()
    return ans, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cortex_core.npu.run_npu")
    for a in ("--split", "--lib", "--qnn-lib", "--onnx", "--cases", "--embd", "--model", "--mmproj", "--out-dir"):
        ap.add_argument(a, required=True)
    ap.add_argument("--runs", type=int, default=20)
    a = ap.parse_args(argv)

    import onnxruntime as ort
    from PIL import Image

    from .vision_prep import prepare

    npu = open_npu(Path(a.split), Path(a.lib), Path(a.qnn_lib))
    if not npu.ok:
        print(npu.error)
        return 1
    enc = npu.encoder
    cpu = ort.InferenceSession(a.onnx, providers=["CPUExecutionProvider"])
    cpu_in = cpu.get_inputs()[0].name
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases = json.loads(Path(a.cases).read_text())
    rows = []
    for c in cases:
        img = Image.open(Path(a.cases).parent / c["image"]).convert("RGB")
        pv = prepare(np.asarray(img))
        enc.encode(pv)  # warm
        ms = []
        for _ in range(a.runs):
            t = time.perf_counter()
            feat = enc.encode(pv)
            ms.append((time.perf_counter() - t) * 1000)
        soc = _soc_state()
        t = time.perf_counter()
        ref = cpu.run(None, {cpu_in: pv})[0]
        cpu_ms = (time.perf_counter() - t) * 1000
        ref = np.asarray(ref, np.float32).reshape(-1, ref.shape[-1])
        feat = np.asarray(feat, np.float32).reshape(-1, feat.shape[-1])
        cos_mean, cos_min = cosine_rows(ref, feat)
        fp = out / (Path(c["image"]).stem + ".npu.f32")
        save_feat(fp, feat, image_w=img.width, image_h=img.height)
        ans, stats = _answer(a.embd, a.model, a.mmproj, fp, c["question"] + " One sentence.")
        ok = any(k in ans.lower() for k in c["expect"])
        ms.sort()
        row = {"image": c["image"], "light": c.get("light"), "cpu_ms": round(cpu_ms),
               "npu_median_ms": round(statistics.median(ms)), "npu_p90_ms": round(ms[int(0.9 * (len(ms) - 1))]),
               "cos_mean": round(cos_mean, 5), "cos_min": round(cos_min, 4), "cpu_answer": c.get("cpu_answer"),
               "npu_answer": ans, "match": ok, "ttft_s": stats.get("ttft_s"), **soc}
        rows.append(row)
        print(json.dumps(row), flush=True)
    (out / "results.json").write_text(json.dumps(rows, indent=1))
    print(f"matched {sum(r['match'] for r in rows)}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
