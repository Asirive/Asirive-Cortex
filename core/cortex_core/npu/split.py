"""Cut an ONNX graph into NPU segments and CPU islands, and run the pieces as one chain.

Hexagon v68 can only multiply two *activations* at 8 x 8 bit, but the vision encoder needs 16-bit activations,
so its attention cores (Q.K^T, softmax, P.V) run on the CPU and everything else on the NPU:

    npu 0 -> cpu (layer 2 attention) -> npu 1 -> cpu (layer 4) -> ... -> npu 6

Each node whose name starts with cpu_prefixes[j] belongs to CPU island j. Every other node goes to the NPU
segment right after the last island it depends on. A tensor that skips over an island (the residual stream)
simply becomes an output of one segment and an input of a later one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import onnx
from onnx import helper


@dataclass
class Stage:
    kind: str  # "npu" | "cpu"
    index: int  # position in the chain
    model: onnx.ModelProto
    inputs: list[str]
    outputs: list[str]


def _types(model: onnx.ModelProto) -> dict[str, onnx.ValueInfoProto]:
    inferred = onnx.shape_inference.infer_shapes(model, strict_mode=False)
    g = inferred.graph
    return {v.name: v for v in list(g.input) + list(g.output) + list(g.value_info)}


def split_stages(model: onnx.ModelProto, cpu_prefixes: list[str]) -> list[Stage]:
    g = model.graph
    inits = {i.name: i for i in g.initializer}
    graph_in = [i.name for i in g.input if i.name not in inits]
    graph_out = [o.name for o in g.output]

    made: dict[str, int] = {n: 0 for n in graph_in}  # stage that produces each tensor
    node_stage = []
    used = [False] * len(cpu_prefixes)
    for node in g.node:
        srcs = [made.get(t, 0) for t in node.input if t and t not in inits]
        j = next((k for k, p in enumerate(cpu_prefixes) if node.name.startswith(p)), None)
        if j is not None:
            used[j] = True
            st = 2 * j + 1
            if any(s > st for s in srcs):
                raise ValueError(f"{node.name} needs a tensor from a later stage")
        else:
            # an island's output is ready for the NPU segment right after that island
            st = max([s + 1 if s % 2 else s for s in srcs] or [0])
        node_stage.append(st)
        for t in node.output:
            made[t] = st
    if not all(used):
        raise ValueError(f"no nodes match {[p for p, u in zip(cpu_prefixes, used) if not u]}")

    types = _types(model)
    produced_in = {}
    for node, st in zip(g.node, node_stage):
        for t in node.output:
            produced_in[t] = st
    consumers: dict[str, set[int]] = {}
    for node, st in zip(g.node, node_stage):
        for t in node.input:
            if t and t not in inits:
                consumers.setdefault(t, set()).add(st)

    stages = []
    for st in range(2 * len(cpu_prefixes) + 1):
        nodes = [n for n, s in zip(g.node, node_stage) if s == st]
        if not nodes:
            continue
        ins, outs, seen = [], [], set()
        for n in nodes:
            for t in n.input:
                if t and t not in inits and produced_in.get(t) != st and t not in seen:
                    seen.add(t)
                    ins.append(t)
        for n in nodes:
            for t in n.output:
                if t in graph_out or any(c != st for c in consumers.get(t, ())):
                    outs.append(t)
        need = {t for n in nodes for t in n.input if t in inits}
        sg = helper.make_graph(nodes, f"stage{st}", [types[t] for t in ins], [types[t] for t in outs],
                               [inits[t] for t in sorted(need)])
        sm = helper.make_model(sg, opset_imports=list(model.opset_import))
        sm.ir_version = model.ir_version
        stages.append(Stage("cpu" if st % 2 else "npu", st, sm, ins, outs))
    return stages


def run_stages(stages: list[Stage], feed: dict, runners: list[Callable[[dict], dict]]) -> dict:
    """Run the stages in order; runners[i](inputs) -> {output name: array}. Returns every tensor produced."""
    env = dict(feed)
    for s, run in zip(stages, runners):
        env.update(run({t: env[t] for t in s.inputs}))
    return env
