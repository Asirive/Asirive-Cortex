"""Box bench: in-process split encoder (NPU via libcortex_npu.so + CPU islands) vs the ONNX fp32 reference.

usage: python bench_split_encoder.py SPLIT_DIR LIB_SO QNN_LIB_DIR PIXELS.raw REF.f32 [runs]
"""
import statistics
import sys
import time

import numpy as np

from cortex_core.npu.compare import cosine_rows, load_feat
from cortex_core.npu.qnn import Runtime
from cortex_core.npu.split_encoder import SplitEncoder

d, lib, qlib, pix, ref = sys.argv[1:6]
runs = int(sys.argv[6]) if len(sys.argv) > 6 else 10
t = time.perf_counter()
enc = SplitEncoder.from_dir(d, Runtime(lib, qlib))
print(f"load {1000 * (time.perf_counter() - t):.0f} ms")
pv = np.fromfile(pix, "<f4").reshape(11, 20, 2, 2, 1536)
for _ in range(2):
    enc.encode(pv)
walls, per = [], []
for _ in range(runs):
    t = time.perf_counter()
    feat = enc.encode(pv)
    walls.append(1000 * (time.perf_counter() - t))
    per.append(enc.last_ms)
print("cos mean/min vs onnx fp32:", cosine_rows(load_feat(ref), feat))
print(f"encode ms: median {statistics.median(walls):.0f}  min {min(walls):.0f}  max {max(walls):.0f}")
for k in per[0]:
    print(f"  {k:6s} {statistics.median(p[k] for p in per):6.1f} ms")
npu = statistics.median(sum(v for k, v in p.items() if k.startswith("npu")) for p in per)
print(f"  npu total {npu:.0f} ms, cpu total {statistics.median(walls) - npu:.0f} ms")
