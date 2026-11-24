"""Which input of each CPU attention island is Q, K and V (needs the onnx package; run in the QAIRT venv).

    python island_map.py SPLIT_DIR > islands.json

Island graph (verified 2026-11-24): K -> Transpose(0,2,3,1); Q, V -> Transpose(0,2,1,3); MatMul(Qt, Kt) -> Mul(scale)
-> Softmax -> MatMul(P, Vt) -> Transpose -> Reshape. Q is the transposed input that shares the first MatMul with K.
"""
import json
import sys
from pathlib import Path

import onnx
from onnx import numpy_helper


def island(path: Path) -> dict:
    g = onnx.load(str(path)).graph
    inits = {t.name: numpy_helper.to_array(t) for t in g.initializer}
    consumers = {}
    for n in g.node:
        for i in n.input:
            consumers.setdefault(i, []).append(n)
    tr = {}  # graph input -> its Transpose node
    for inp in g.input:
        (t,) = [n for n in consumers[inp.name] if n.op_type == "Transpose"]
        tr[inp.name] = t
    perm = {k: list(onnx.helper.get_attribute_value(t.attribute[0])) for k, t in tr.items()}
    (k,) = [n for n, p in perm.items() if p == [0, 2, 3, 1]]
    mm1 = [n for n in consumers[tr[k].output[0]] if n.op_type == "MatMul"][0]
    (q,) = [n for n in tr if n != k and tr[n].output[0] in mm1.input]
    (v,) = [n for n in tr if n not in (k, q)]
    mul = [n for n in g.node if n.op_type == "Mul"][0]
    scale = float([inits[i] for i in mul.input if i in inits][0])
    dims = [d.dim_value for d in g.input[0].type.tensor_type.shape.dim]
    return {"q": q, "k": k, "v": v, "out": g.output[0].name, "scale": scale, "n_tok": dims[1], "heads": dims[2],
            "dim": dims[3]}


if __name__ == "__main__":
    d = Path(sys.argv[1])
    out = {p.stem: island(p) for p in sorted(d.glob("cpu*.onnx"), key=lambda p: int(p.stem[3:]))}
    print(json.dumps(out, indent=1))
