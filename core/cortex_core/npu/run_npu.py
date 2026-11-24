"""Vision encoder on the Hexagon NPU (split chain), checked against ONNX CPU and answered by the LM.

    python -m cortex_core.npu.run_npu --split DIR --lib libcortex_npu.so --qnn-lib QNN_LIB_DIR \
        --onnx vision_encoder.onnx --cases cases.json --embd cortex-embd --model LM.gguf --mmproj MMPROJ.gguf \
        --out-dir DIR [--runs 20]

For every case: NPU encode timing, cosine vs ONNX fp32 on CPU, `cortex-embd answer` from the NPU features,
and the keyword check (any of "expect"). Writes results.json in --out-dir.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .answer_cases import answer
from .compare import cosine_rows, frac_below, save_feat


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


def soc_state(root: str | Path = "/") -> dict:
    """CPU-zone and power-chip (pmc8280c) temperatures (max each) and current CPU frequencies.

    Unreadable files are skipped. The power chip is reported apart from the CPU: it idles ~37 C, ran 88-92 C
    under the NPU bench and trips at 95 C, so it is the one to watch."""
    root = Path(root)
    temps: list[float] = []
    pmic: list[float] = []
    for z in sorted((root / "sys/class/thermal").glob("thermal_zone*")):
        try:
            typ = (z / "type").read_text().strip()
            if typ.startswith("cpu"):
                temps.append(int((z / "temp").read_text()) / 1000)
            elif typ.startswith("pmc8280c"):
                pmic.append(int((z / "temp").read_text()) / 1000)
        except (OSError, ValueError):
            continue
    mhz = []
    for f in (root / "sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_cur_freq"):
        try:
            mhz.append(int(f.read_text()) // 1000)
        except (OSError, ValueError):
            continue
    return {"cpu_temp_c": max(temps, default=None), "pmic_temp_c": max(pmic, default=None), "cpu_mhz_min": min(mhz, default=None),
            "cpu_mhz_max": max(mhz, default=None)}


# cortex-embd builds a grey stand-in image of this size so llama.cpp lays out the same 220 tokens the NPU
# canvas (vision_prep.INPUT_W x INPUT_H) produces. Every frame, whatever its size, is fitted into that canvas.
STAND_IN_W, STAND_IN_H = 640, 360


def save_npu_feat(path: Path, feat: np.ndarray) -> None:
    save_feat(path, feat, image_w=STAND_IN_W, image_h=STAND_IN_H)


def probe_npu(cmd: list[str], timeout: float = 60) -> NpuOpen:
    """Run cmd (the NPU work) in a child process so a QNN hang or crash is reported, not inherited.

    On success the child's stdout is passed through."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return NpuOpen(False, f"NPU run timed out after {timeout:.0f} s (fastrpc busy or CDSP down?)")
    if r.returncode:
        tail = (r.stdout + r.stderr).strip()[-400:]
        return NpuOpen(False, f"NPU run failed with exit code {r.returncode}: {tail}")
    print(r.stdout, end="")
    return NpuOpen(True)


def wait_cool(read_temp, limit: float = 90, resume: float = 80, sleep=time.sleep, step: float = 10,
              max_wait: float = 60) -> float:
    """If the power chip is above limit, pause in steps until it is below resume, at most max_wait seconds.

    pmc8280c is a stepped alarm sensor (37 / 88 / 92 C levels), not a live temperature: it can sit at 88 C
    for minutes with the box idle, so the wait must be capped. Returns seconds waited."""
    t = read_temp()
    if t is None or t <= limit:
        return 0
    waited = 0.0
    while t is not None and t >= resume and waited < max_wait:
        sleep(step)
        waited += step
        t = read_temp()
    return waited


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    child = argv[:1] == ["--child"]
    if child:
        argv = argv[1:]
    ap = argparse.ArgumentParser(prog="cortex_core.npu.run_npu")
    for a in ("--split", "--lib", "--qnn-lib", "--onnx", "--cases", "--embd", "--model", "--mmproj", "--out-dir"):
        ap.add_argument(a, required=True)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=1800, help="whole-run limit, seconds")
    a = ap.parse_args(argv)
    if not child:
        # The NPU is opened exactly once, inside one supervised child: a probe that closed the NPU and a
        # reopen one second later reset the whole box (fastrpc unmap error, 2026-11-24).
        r = probe_npu([sys.executable, "-m", "cortex_core.npu.run_npu", "--child", *argv], a.timeout)
        if not r.ok:
            print(r.error)
            return 1
        return 0

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
        cooled = wait_cool(lambda: soc_state()["pmic_temp_c"])
        img = Image.open(Path(a.cases).parent / c["image"]).convert("RGB")
        pv = prepare(np.asarray(img))
        enc.encode(pv)  # warm
        ms, socs = [], []
        for _ in range(a.runs):
            t = time.perf_counter()
            feat = enc.encode(pv)
            ms.append((time.perf_counter() - t) * 1000)
            socs.append(soc_state())  # sampled right after each run, while clocks are still up
        cpu.run(None, {cpu_in: pv})  # warm, like the NPU
        t = time.perf_counter()
        ref = cpu.run(None, {cpu_in: pv})[0]
        cpu_ms = (time.perf_counter() - t) * 1000
        ref = np.asarray(ref, np.float32).reshape(-1, ref.shape[-1])
        feat = np.asarray(feat, np.float32).reshape(-1, feat.shape[-1])
        cos_mean, cos_min = cosine_rows(ref, feat)
        fp = out / (Path(c["image"]).stem + ".npu.f32")
        save_npu_feat(fp, feat)
        ans, stats = answer(a.embd, a.model, a.mmproj, fp, c["question"] + " One sentence.")
        ok = any(k in ans.lower() for k in c["expect"])
        ms.sort()
        row = {"image": c["image"], "light": c.get("light"), "cpu_ms": round(cpu_ms),
               "npu_median_ms": round(statistics.median(ms)), "npu_p90_ms": round(ms[int(0.9 * (len(ms) - 1))]),
               "cos_mean": round(cos_mean, 5), "cos_min": round(cos_min, 4),
               "tok_below_0_9": round(frac_below(ref, feat), 4), "size": f"{img.width}x{img.height}", "cpu_answer": c.get("cpu_answer"),
               "npu_answer": ans, "match": ok, "ttft_s": stats.get("ttft_s"), "cooled_s": cooled,
               "cpu_mhz_min": min((x["cpu_mhz_min"] for x in socs if x["cpu_mhz_min"]), default=None),
               "cpu_mhz_max": max((x["cpu_mhz_max"] for x in socs if x["cpu_mhz_max"]), default=None),
               "cpu_temp_max_c": max((x["cpu_temp_c"] for x in socs if x["cpu_temp_c"]), default=None),
               "pmic_temp_max_c": max((x["pmic_temp_c"] for x in socs if x["pmic_temp_c"]), default=None)}
        rows.append(row)
        print(json.dumps(row), flush=True)
    (out / "results.json").write_text(json.dumps(rows, indent=1))
    print(f"matched {sum(r['match'] for r in rows)}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
