"""Run QNN HTP context binaries in-process through libcortex_npu.so (core/tools/cortex-npu).

The shim moves raw bytes; this module turns float arrays into each tensor's fixed-point form and back.
QNN's convention: float = (q + offset) * scale, with offset usually negative.
"""
from __future__ import annotations

import ctypes
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FLOAT_32 = 0x0232
UFIXED_8 = 0x0408
UFIXED_16 = 0x0416
_FIXED = {UFIXED_8: np.uint8, UFIXED_16: np.uint16}


def to_fixed(x: np.ndarray, dtype: int, scale: float, offset: int) -> np.ndarray:
    if dtype == FLOAT_32:
        return np.ascontiguousarray(x, np.float32)
    if dtype not in _FIXED:
        raise ValueError(f"unsupported QNN dtype 0x{dtype:04x}")
    t = _FIXED[dtype]
    q = np.rint(np.asarray(x, np.float32) / np.float32(scale)) - offset
    return np.clip(q, 0, np.iinfo(t).max).astype(t)


def from_fixed(q: np.ndarray, dtype: int, scale: float, offset: int) -> np.ndarray:
    if dtype == FLOAT_32:
        return np.asarray(q, np.float32)
    if dtype not in _FIXED:
        raise ValueError(f"unsupported QNN dtype 0x{dtype:04x}")
    return (q.astype(np.float32) + np.float32(offset)) * np.float32(scale)


def _sanitise(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", name).lstrip("_")


def match_names(qnn_names: list[str], onnx_names: list[str]) -> list[str]:
    """QNN converters replace punctuation in tensor names; map each QNN name back to its ONNX name."""
    by = {_sanitise(n): n for n in onnx_names}
    out = []
    for q in qnn_names:
        key = _sanitise(q)
        if key not in by:
            raise KeyError(f"QNN tensor {q!r} matches none of {onnx_names}")
        out.append(by[key])
    return out


@dataclass
class Tensor:
    name: str
    dtype: int
    scale: float
    offset: int
    shape: tuple[int, ...]
    nbytes: int


class Runtime:
    """One process-wide QNN HTP backend + device (the shim keeps them global)."""

    def __init__(self, lib_path: str | Path, qnn_lib_dir: str | Path, burst: bool = True):
        d = Path(qnn_lib_dir)
        self.lib = lib = ctypes.CDLL(str(lib_path))
        lib.cnpu_last_error.restype = ctypes.c_char_p
        lib.cnpu_init.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        lib.cnpu_load.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.cnpu_num_io.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.cnpu_io_info.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p),
                                     ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_float),
                                     ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint64)]
        lib.cnpu_execute.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        lib.cnpu_free.argtypes = [ctypes.c_void_p]
        self._check(lib.cnpu_init(str(d / "libQnnHtp.so").encode(), str(d / "libQnnSystem.so").encode()), "init")
        if burst:
            self._check(lib.cnpu_set_burst(), "set_burst")

    def _check(self, rc: int, what: str) -> None:
        if rc:
            raise RuntimeError(f"cortex_npu {what}: {self.lib.cnpu_last_error().decode()}")

    def load(self, bin_path: str | Path) -> "Graph":
        h = ctypes.c_void_p()
        self._check(self.lib.cnpu_load(str(bin_path).encode(), ctypes.byref(h)), f"load {bin_path}")
        return Graph(self, h)


class Graph:
    def __init__(self, rt: Runtime, handle: ctypes.c_void_p):
        self.rt, self.h = rt, handle
        self.inputs = [self._info(0, i) for i in range(rt.lib.cnpu_num_io(handle, 0))]
        self.outputs = [self._info(1, i) for i in range(rt.lib.cnpu_num_io(handle, 1))]
        self._out_bufs = [np.empty(t.nbytes, np.uint8) for t in self.outputs]

    def _info(self, is_out: int, i: int) -> Tensor:
        name, dt, sc, off, rank = ctypes.c_char_p(), ctypes.c_int(), ctypes.c_float(), ctypes.c_int(), ctypes.c_int()
        dims, nb = (ctypes.c_uint32 * 8)(), ctypes.c_uint64()
        self.rt._check(self.rt.lib.cnpu_io_info(self.h, is_out, i, ctypes.byref(name), ctypes.byref(dt),
                                                ctypes.byref(sc), ctypes.byref(off), ctypes.byref(rank), dims,
                                                ctypes.byref(nb)), "io_info")
        return Tensor(name.value.decode(), dt.value, sc.value, off.value, tuple(dims[:rank.value]), nb.value)

    def bind_names(self, onnx_inputs: list[str], onnx_outputs: list[str]) -> None:
        """Rename the QNN tensors to the ONNX names the rest of the chain uses."""
        for t, n in zip(self.inputs, match_names([t.name for t in self.inputs], onnx_inputs)):
            t.name = n
        for t, n in zip(self.outputs, match_names([t.name for t in self.outputs], onnx_outputs)):
            t.name = n

    def __call__(self, feed: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        ins = []
        for t in self.inputs:
            if tuple(np.shape(feed[t.name])) != t.shape:  # same byte count in another layout is still wrong
                raise ValueError(f"{t.name}: shape {np.shape(feed[t.name])}, graph wants {t.shape}")
            a = to_fixed(feed[t.name], t.dtype, t.scale, t.offset)
            if a.nbytes != t.nbytes:
                raise ValueError(f"{t.name}: {a.nbytes} bytes, graph wants {t.nbytes} {t.shape}")
            ins.append(a)
        P = ctypes.c_void_p
        in_p = (P * len(ins))(*[a.ctypes.data for a in ins])
        out_p = (P * len(self._out_bufs))(*[b.ctypes.data for b in self._out_bufs])
        self.rt._check(self.rt.lib.cnpu_execute(self.h, in_p, out_p), "execute")
        res = {}
        for t, b in zip(self.outputs, self._out_bufs):
            raw = b.view(np.float32 if t.dtype == FLOAT_32 else _FIXED[t.dtype]).reshape(t.shape)
            res[t.name] = from_fixed(raw, t.dtype, t.scale, t.offset).copy()
        return res
