"""Reference data for engine_tests, made on the box with the Python NPU path (the oracle). Not in git.

    python make_goldens.py --split DIR --lib libcortex_npu.so --qnn-lib QNN_LIB_DIR --frames REVIEW_DIR \
        --out /var/lib/cortex/bench/engine/golden [--write-io islands.json]

Writes <out>/<stem>.pv.f32 (prepare() of every review frame) and island1_{q,k,v,out}.f32 (the inputs and output
of the first CPU attention island for t001, taken from the real NPU chain). --write-io merges island_map.py's
output into <split>/io.json under "islands".
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from cortex_core.npu.vision_prep import prepare


def main() -> int:
    ap = argparse.ArgumentParser()
    for a in ("--split", "--lib", "--qnn-lib", "--frames", "--out"):
        ap.add_argument(a, required=True)
    ap.add_argument("--write-io")
    a = ap.parse_args()
    split, out = Path(a.split), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.write_io:
        io = json.loads((split / "io.json").read_text())
        io["islands"] = json.loads(Path(a.write_io).read_text())
        (split / "io.json").write_text(json.dumps(io))
        print("io.json: islands", sorted(io["islands"]))
    for f in sorted(Path(a.frames).glob("*.jpg")):
        prepare(np.asarray(Image.open(f).convert("RGB"))).astype("<f4").tofile(out / (f.stem + ".pv.f32"))
    from cortex_core.npu.qnn import Runtime
    from cortex_core.npu.split_encoder import SplitEncoder

    io = json.loads((split / "io.json").read_text())
    isl = io["islands"]["cpu1"]
    enc = SplitEncoder.from_dir(split, Runtime(a.lib, a.qnn_lib))
    env = {"pixel_values": np.fromfile(out / "t001.pv.f32", "<f4").reshape(11, 20, 2, 2, 1536)}
    for kind, ins, run in enc.stages[:2]:
        env.update(run({n: env[n] for n in ins}))
    for key in ("q", "k", "v", "out"):
        np.asarray(env[isl[key]], "<f4").tofile(out / f"island1_{key}.f32")
    print("goldens in", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
