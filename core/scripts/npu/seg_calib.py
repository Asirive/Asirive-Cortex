"""Write calibration inputs for one NPU segment: run the ORT chain on each calib frame up to that segment."""
import glob, os, sys
import numpy as np, onnxruntime as ort
split, raws, k, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
order = [f"npu{i}" if i % 2 == 0 else f"cpu{i}" for i in range(k + 1)]
sess = [ort.InferenceSession(f"{split}/{n}.onnx", providers=["CPUExecutionProvider"]) for n in order]
os.makedirs(out, exist_ok=True)
lines = []
for f in sorted(glob.glob(f"{raws}/*.raw")):
    env = {"pixel_values": np.fromfile(f, "<f4").reshape(11, 20, 2, 2, 1536)}
    for s in sess[:-1]:
        names = [o.name for o in s.get_outputs()]
        env.update(zip(names, s.run(names, {i.name: env[i.name] for i in s.get_inputs()})))
    parts = []
    for j, i in enumerate(sess[-1].get_inputs()):
        p = f"{out}/{os.path.basename(f)[:-4]}_{j}.raw"
        np.ascontiguousarray(env[i.name], "<f4").tofile(p)
        parts.append(f"{i.name}:={p}")
    lines.append(" ".join(parts))
open(f"{out}/input_list.txt", "w").write("\n".join(lines) + "\n")
print(k, len(lines), "frames", [i.name for i in sess[-1].get_inputs()])
