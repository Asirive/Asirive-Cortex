"""The vision encoder as a chain of NPU segments and CPU attention islands (see split.py for the cut).

Each stage is (kind, input names, runner) with runner(feed) -> {output name: array}. The first stage reads
"pixel_values"; the chain's answer is "image_features".
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np

StageSpec = tuple[str, list[str], Callable[[dict], dict]]


class SplitEncoder:
    def __init__(self, stages: list[StageSpec]):
        self.stages = stages
        self.last_ms: dict[str, float] = {}

    def encode(self, pixel_values: np.ndarray) -> np.ndarray:
        env = {"pixel_values": pixel_values}
        self.last_ms = {}
        for i, (kind, ins, run) in enumerate(self.stages):
            missing = [n for n in ins if n not in env]
            if missing:
                raise KeyError(f"{kind}{i} needs {missing}, not produced by an earlier stage")
            t = time.perf_counter()
            env.update(run({n: env[n] for n in ins}))
            self.last_ms[f"{kind}{i}"] = (time.perf_counter() - t) * 1000
        return env["image_features"]

    @classmethod
    def from_dir(cls, d: str | Path, runtime, cpu_threads: int = 8) -> "SplitEncoder":
        """Load npu{k}.bin + cpu{k}.onnx from d; io.json gives each NPU segment's ONNX input/output names."""
        import onnxruntime as ort

        d = Path(d)
        io = json.loads((d / "io.json").read_text())
        so = ort.SessionOptions()
        so.intra_op_num_threads = cpu_threads
        stages: list[StageSpec] = []
        k = 0
        while (d / f"npu{k}.bin").exists() or (d / f"cpu{k}.onnx").exists():
            if k % 2 == 0:
                g = runtime.load(d / f"npu{k}.bin")
                g.bind_names(io[f"npu{k}"]["in"], io[f"npu{k}"]["out"])
                stages.append(("npu", [t.name for t in g.inputs], g))
            else:
                s = ort.InferenceSession(str(d / f"cpu{k}.onnx"), so, providers=["CPUExecutionProvider"])
                ins, outs = [i.name for i in s.get_inputs()], [o.name for o in s.get_outputs()]
                stages.append(("cpu", ins, lambda f, s=s, outs=outs: dict(zip(outs, s.run(outs, f)))))
            k += 1
        if not stages:
            raise FileNotFoundError(f"no npu*.bin / cpu*.onnx in {d}")
        return cls(stages)
