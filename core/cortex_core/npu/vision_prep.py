"""Prepare one camera frame for LFM3-Omni's vision encoder at the fixed NPU input size.

Contract of Liquid's `vision_encoder.onnx` (LFM3-Omni-2B-ONNX):
  input  pixel_values   float32 [blocks_h, blocks_w, 2, 2, 1536]
         one block = 2x2 patches of 16 px (32x32 px); 1536 = channel(3) x time(2) x 16 x 16,
         a still image repeats the frame in both time slots
  output image_features float32 [blocks_h * blocks_w, 2048]
Pixels: bicubic resize to multiples of 32, then x / 255, then (x - 0.5) / 0.5  (processor_config.json).

The NPU graph is compiled for one shape: 640x352 (a 640x360 camera frame rounded to the 32 px grid, as the
model's own processor does -> 220 image tokens). Frames of another shape are fitted inside it keeping their
aspect ratio; a leftover of less than one block is stretched away like the model's processor would, a bigger
leftover is padded with neutral grey (0.0 after normalising).
"""
from __future__ import annotations

import numpy as np
from PIL import Image

INPUT_W, INPUT_H = 640, 352
MEAN = (0.5, 0.5, 0.5)
STD = (0.5, 0.5, 0.5)
PATCH, MERGE, TEMPORAL = 16, 2, 2
BLOCK = PATCH * MERGE


def fit_box(w: int, h: int) -> tuple[int, int]:
    """Size the frame is resized to inside INPUT_W x INPUT_H (before any padding)."""
    scale = min(INPUT_W / w, INPUT_H / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    if INPUT_W - nw < BLOCK and INPUT_H - nh < BLOCK:
        return INPUT_W, INPUT_H
    return nw, nh


def prepare(rgb: np.ndarray) -> np.ndarray:
    """RGB uint8 [H, W, 3] -> pixel_values float32 [INPUT_H/32, INPUT_W/32, 2, 2, 1536]."""
    h, w = rgb.shape[:2]
    nw, nh = fit_box(w, h)
    img = np.asarray(Image.fromarray(rgb, "RGB").resize((nw, nh), Image.BICUBIC), dtype=np.float32)
    img = (img / 255.0 - np.array(MEAN, np.float32)) / np.array(STD, np.float32)
    canvas = np.zeros((INPUT_H, INPUT_W, 3), np.float32)  # 0.0 = neutral grey after normalising
    top, left = (INPUT_H - nh) // 2, (INPUT_W - nw) // 2
    canvas[top:top + nh, left:left + nw] = img
    gh, gw = INPUT_H // PATCH, INPUT_W // PATCH
    x = canvas.transpose(2, 0, 1)  # C, H, W
    x = x.reshape(3, gh // MERGE, MERGE, PATCH, gw // MERGE, MERGE, PATCH)
    x = x.transpose(1, 4, 2, 5, 0, 3, 6)  # bh, bw, mh, mw, C, py, px
    x = np.repeat(x[:, :, :, :, :, None], TEMPORAL, axis=5)  # bh, bw, mh, mw, C, T, py, px
    return np.ascontiguousarray(x.reshape(gh // MERGE, gw // MERGE, MERGE, MERGE, 3 * TEMPORAL * PATCH * PATCH),
                                dtype=np.float32)
