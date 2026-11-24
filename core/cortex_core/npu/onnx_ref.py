"""CPU reference for the NPU vision path: Liquid's vision_encoder.onnx on onnxruntime.

    python -m cortex_core.npu.onnx_ref --onnx vision_encoder.onnx --image scene.jpg --out ref.f32 [--runs 3]

Writes features in the cortex-embd format (compare.save_feat) and prints {"n_tokens", "n_embd", "encode_ms"}.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .compare import save_feat
from .vision_prep import prepare


def encode(onnx_path: Path, rgb: np.ndarray, runs: int = 1) -> tuple[np.ndarray, float]:
    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    pv = prepare(rgb)
    feed = {sess.get_inputs()[0].name: pv}
    times, out = [], None
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        out = sess.run(None, feed)[0]
        times.append((time.perf_counter() - t0) * 1000)
    return np.asarray(out, np.float32).reshape(-1, out.shape[-1]), statistics.median(times)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cortex_core.npu.onnx_ref")
    ap.add_argument("--onnx", required=True, type=Path)
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args(argv)
    rgb = np.asarray(Image.open(a.image).convert("RGB"))
    feat, ms = encode(a.onnx, rgb, a.runs)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    save_feat(a.out, feat, encode_ms=round(ms, 1), image_w=rgb.shape[1], image_h=rgb.shape[0])
    print(json.dumps({"n_tokens": feat.shape[0], "n_embd": feat.shape[1], "encode_ms": round(ms, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
