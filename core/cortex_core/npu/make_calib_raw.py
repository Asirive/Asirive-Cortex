"""Calibration inputs for QAIRT quantisation of the vision encoder.

    python -m cortex_core.npu.make_calib_raw <calib_dir> <out_dir>

Each *.jpg in calib_dir becomes <out_dir>/<name>.raw (prepare()'s pixel_values, raw little-endian float32),
and <out_dir>/input_list.txt gets one line per frame: "pixel_values:=<absolute path>".
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from .vision_prep import prepare

INPUT_NAME = "pixel_values"


def make_calib_raw(calib_dir: Path, out_dir: Path) -> Path:
    frames = sorted(Path(calib_dir).glob("*.jpg"))
    if not frames:
        raise ValueError(f"no .jpg frames in {calib_dir}")
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for f in frames:
        raw = out / (f.stem + ".raw")
        prepare(np.asarray(Image.open(f).convert("RGB"))).astype("<f4").tofile(raw)
        lines.append(f"{INPUT_NAME}:={raw.as_posix()}")
    lst = out / "input_list.txt"
    lst.write_text("\n".join(lines) + "\n")
    return lst


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m cortex_core.npu.make_calib_raw <calib_dir> <out_dir>")
    print(make_calib_raw(Path(sys.argv[1]), Path(sys.argv[2])))
