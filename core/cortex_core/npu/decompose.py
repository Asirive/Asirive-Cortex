"""Rewrite onnxruntime contrib ops in Liquid's vision_encoder.onnx into standard ONNX ops, for QAIRT.

QAIRT's ONNX converter only knows standard ops; the exported encoder uses three onnxruntime fusions:
  SimplifiedLayerNormalization  RMSNorm over the last axis           -> x / sqrt(mean(x^2) + eps) * w
  com.microsoft.RotaryEmbedding  3-D input, non-interleaved, full     -> split halves, x1*c - x2*s | x2*c + x1*s
  com.microsoft.MultiHeadAttention  q, k, v only (no bias / masks)    -> reshape, MatMul, Softmax, MatMul
Shapes the rewrite needs (head size, scale) are computed with Shape ops, so once the input shape is fixed
(fix_input_shape) a constant-folding pass turns them into constants.

    python -m cortex_core.npu.decompose IN.onnx OUT.onnx [--shape 11,20,2,2,1536]
"""
from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import numpy as np
import onnx
from onnx import helper, numpy_helper

CONTRIB_OPS = {("", "SimplifiedLayerNormalization"), ("com.microsoft", "RotaryEmbedding"),
               ("com.microsoft", "MultiHeadAttention")}


class _B:
    """Collects replacement nodes and constants with unique names."""

    def __init__(self, prefix: str, ids):
        self.prefix, self.ids, self.nodes, self.inits = prefix, ids, [], []

    def name(self, tag: str) -> str:
        return f"{self.prefix}/{tag}_{next(self.ids)}"

    def const(self, value, dtype) -> str:
        n = self.name("c")
        self.inits.append(numpy_helper.from_array(np.asarray(value, dtype=dtype), n))
        return n

    def op(self, op_type: str, inputs, out: str | None = None, **attrs) -> str:
        out = out or self.name(op_type)
        self.nodes.append(helper.make_node(op_type, list(inputs), [out], name=self.name(op_type + "_n"), **attrs))
        return out


def _attrs(node) -> dict:
    return {a.name: helper.get_attribute_value(a) for a in node.attribute}


def _rms_norm(b: _B, node) -> None:
    a = _attrs(node)
    if a.get("axis", -1) != -1:
        raise NotImplementedError(f"{node.name}: SimplifiedLayerNormalization axis {a['axis']}")
    x, w = node.input[0], node.input[1]
    eps = b.const(a.get("epsilon", 1e-5), np.float32)
    ms = b.op("ReduceMean", [b.op("Mul", [x, x]), b.const([-1], np.int64)], keepdims=1)
    inv = b.op("Reciprocal", [b.op("Sqrt", [b.op("Add", [ms, eps])])])
    b.op("Mul", [b.op("Mul", [x, inv]), w], out=node.output[0])


def _rotary(b: _B, node) -> None:
    a = _attrs(node)
    if a.get("interleaved", 0) or a.get("rotary_embedding_dim", 0) or a.get("is_packed_batching", 0):
        raise NotImplementedError(f"{node.name}: RotaryEmbedding variant {a}")
    x, pos, cos, sin = node.input[:4]
    half = b.op("Gather", [b.op("Shape", [cos]), b.const([1], np.int64)], axis=0)
    head = b.op("Mul", [half, b.const([2], np.int64)])
    shape4 = b.op("Concat", [b.const([0, 0, -1], np.int64), head], axis=0)
    x4 = b.op("Reshape", [x, shape4])
    x1, x2 = b.name("x1"), b.name("x2")
    b.nodes.append(helper.make_node("Split", [x4], [x1, x2], name=b.name("Split_n"), axis=-1, num_outputs=2))
    ax = b.const([2], np.int64)
    c = b.op("Unsqueeze", [b.op("Gather", [cos, pos], axis=0), ax])
    s = b.op("Unsqueeze", [b.op("Gather", [sin, pos], axis=0), ax])
    o1 = b.op("Sub", [b.op("Mul", [x1, c]), b.op("Mul", [x2, s])])
    o2 = b.op("Add", [b.op("Mul", [x2, c]), b.op("Mul", [x1, s])])
    b.op("Reshape", [b.op("Concat", [o1, o2], axis=-1), b.op("Shape", [x])], out=node.output[0])


def _mha(b: _B, node) -> None:
    if any(node.input[3:]):
        raise NotImplementedError(f"{node.name}: MultiHeadAttention with bias/mask inputs")
    a = _attrs(node)
    heads = a["num_heads"]
    q, k, v = node.input[:3]
    split = b.const([0, 0, heads, -1], np.int64)
    q4 = b.op("Transpose", [b.op("Reshape", [q, split])], perm=[0, 2, 1, 3])
    kT = b.op("Transpose", [b.op("Reshape", [k, split])], perm=[0, 2, 3, 1])
    v4 = b.op("Transpose", [b.op("Reshape", [v, split])], perm=[0, 2, 1, 3])
    if "scale" in a and a["scale"] != 0:
        scale = b.const(a["scale"], np.float32)
    else:
        hidden = b.op("Cast", [b.op("Gather", [b.op("Shape", [q]), b.const(2, np.int64)], axis=0)], to=1)
        scale = b.op("Reciprocal", [b.op("Sqrt", [b.op("Div", [hidden, b.const(heads, np.float32)])])])
    p = b.op("Softmax", [b.op("Mul", [b.op("MatMul", [q4, kT]), scale])], axis=-1)
    o = b.op("Transpose", [b.op("MatMul", [p, v4])], perm=[0, 2, 1, 3])
    b.op("Reshape", [o, b.const([0, 0, -1], np.int64)], out=node.output[0])


_RULES = {("", "SimplifiedLayerNormalization"): _rms_norm, ("com.microsoft", "RotaryEmbedding"): _rotary,
          ("com.microsoft", "MultiHeadAttention"): _mha}


def decompose(model: onnx.ModelProto) -> onnx.ModelProto:
    """Copy of model with every contrib op replaced; raises NotImplementedError on any com.microsoft op it can't."""
    m = onnx.ModelProto()
    m.CopyFrom(model)
    g, ids, new_nodes = m.graph, itertools.count(), []
    for node in g.node:
        key = (node.domain, node.op_type)
        if key in _RULES:
            b = _B(node.name or node.op_type, ids)
            _RULES[key](b, node)
            new_nodes += b.nodes
            g.initializer.extend(b.inits)
        elif node.domain == "com.microsoft":
            raise NotImplementedError(f"no rewrite for com.microsoft.{node.op_type} ({node.name})")
        else:
            new_nodes.append(node)
    del g.node[:]
    g.node.extend(new_nodes)
    keep = [o for o in m.opset_import if o.domain != "com.microsoft"]
    del m.opset_import[:]
    m.opset_import.extend(keep)
    return m


def fix_input_shape(model: onnx.ModelProto, name: str, shape) -> onnx.ModelProto:
    for i in model.graph.input:
        if i.name == name:
            dims = i.type.tensor_type.shape.dim
            if len(dims) != len(shape):
                raise ValueError(f"{name} has rank {len(dims)}, got shape {shape}")
            for d, v in zip(dims, shape):
                d.Clear()
                d.dim_value = int(v)
            return model
    raise ValueError(f"no graph input {name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cortex_core.npu.decompose")
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--shape", default="11,20,2,2,1536")
    a = ap.parse_args(argv)
    m = onnx.load(str(a.src))
    m = fix_input_shape(decompose(m), m.graph.input[0].name, [int(x) for x in a.shape.split(",")])
    onnx.save(m, str(a.dst), save_as_external_data=True, location=a.dst.name + "_data")
    print(a.dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
