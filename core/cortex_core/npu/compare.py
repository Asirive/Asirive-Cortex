"""Image-feature files and how close two sets of features are.

File format (shared with core/tools/cortex-embd): FEAT.f32 is raw little-endian float32 [n_tokens, n_embd];
FEAT.f32.json next to it holds at least {"n_tokens": .., "n_embd": ..} (extra keys are allowed).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".json")


def load_feat(path: Path) -> np.ndarray:
    path = Path(path)
    meta = json.loads(_meta_path(path).read_text())
    n, d = int(meta["n_tokens"]), int(meta["n_embd"])
    a = np.fromfile(path, dtype="<f4")
    if a.size != n * d:
        raise ValueError(f"{path}: {a.size} floats, expected {n}x{d}")
    return a.reshape(n, d).astype(np.float32, copy=False)


def save_feat(path: Path, a: np.ndarray, **extra) -> None:
    path = Path(path)
    if a.ndim != 2:
        raise ValueError(f"features must be [n_tokens, n_embd], got {a.shape}")
    np.ascontiguousarray(a, dtype="<f4").tofile(path)
    _meta_path(path).write_text(json.dumps({"n_tokens": a.shape[0], "n_embd": a.shape[1], **extra}) + "\n")


def cosine_rows(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """(mean, min) cosine similarity between matching rows (tokens) of a and b."""
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")
    a64, b64 = a.astype(np.float64), b.astype(np.float64)
    num = (a64 * b64).sum(axis=1)
    den = np.linalg.norm(a64, axis=1) * np.linalg.norm(b64, axis=1)
    cos = num / np.maximum(den, 1e-30)
    return float(cos.mean()), float(cos.min())
