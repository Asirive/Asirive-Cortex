"""Export the 16 kHz branch of Silero VAD v4 into a flat, self-describing binary.

Record format (little endian), repeated until EOF, after the 8-byte magic b"SVAD4\\0\\0\\0":
  u32 name_len, name bytes, u32 ndim, ndim x u32 dims, prod(dims) x f32
Also prints every small constant of the 16 kHz branch so the C++ port can be checked against it.
"""
import struct
import sys

import numpy as np
import onnx
from onnx import numpy_helper as nh

m = onnx.load(sys.argv[1])
g = m.graph
top = {t.name: nh.to_array(t) for t in g.initializer}
print("Equal const (sr):", top["onnx::Equal_124"])

iff = [n for n in g.node if n.op_type == "If"][0]
br = {a.name: a.g for a in iff.attribute}
then = br["then_branch"]  # sr == 16000 -> uses model.* weights
consts = {t.name: nh.to_array(t) for t in then.initializer}
for k, v in consts.items():
    if v.size <= 8:
        print("const", k, v.dtype, v.tolist())

lstm_if = [n for n in then.node if n.op_type == "If" and len(n.output) == 3][0]
lb = {a.name: a.g for a in lstm_if.attribute}
lthen = {t.name: nh.to_array(t) for t in lb["then_branch"].initializer}  # uses given h/c
lelse = {t.name: nh.to_array(t) for t in lb["else_branch"].initializer}
lstms = [n for n in lb["then_branch"].node if n.op_type == "LSTM"]
for n in lb["then_branch"].node:
    if n.op_type == "Slice":
        print("lstm slice", n.input, [lthen[i].tolist() for i in n.input[1:]])

out = {}
for k, v in top.items():
    if k.startswith("model.") or k in ("1110", "1111", "1113", "1114", "1116", "1117", "1119", "1120"):
        out[k] = v
for li, n in enumerate(lstms):
    w, r, b = (lthen[i] for i in n.input[1:4])
    out[f"lstm{li}.W"], out[f"lstm{li}.R"], out[f"lstm{li}.B"] = w, r, b
# both LSTM branches should hold the same weights; say so if not
el = [n for n in lb["else_branch"].node if n.op_type == "LSTM"]
for li, n in enumerate(el):
    for j, nm in zip(range(1, 4), "WRB"):
        print(f"lstm{li}.{nm} same in both branches:", np.array_equal(lelse[n.input[j]], out[f"lstm{li}.{nm}"]))
out["spect.mul"] = consts["196"].astype(np.float32).reshape(1)
out["spect.add"] = consts["198"].astype(np.float32).reshape(1)

with open(sys.argv[2], "wb") as f:
    f.write(b"SVAD4\0\0\0")
    for k, v in out.items():
        a = np.ascontiguousarray(v, dtype=np.float32)
        nb = k.encode()
        f.write(struct.pack("<I", len(nb)) + nb + struct.pack("<I", a.ndim))
        f.write(struct.pack(f"<{a.ndim}I", *a.shape))
        f.write(a.tobytes())
        print("wrote", k, list(a.shape))
