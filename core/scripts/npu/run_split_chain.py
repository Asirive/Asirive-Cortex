"""Run the split encoder on the box: NPU segments via qnn-net-run, attention islands via onnxruntime."""
import glob, json, os, re, subprocess, sys, time
import numpy as np, onnxruntime as ort
sys.path.insert(0, "/opt/cortex")
from cortex_core.npu.compare import cosine_rows, load_feat
D = "/var/lib/cortex/bench/npu/split"; X = os.path.expanduser("~/qnn-deb/x/usr"); L = f"{X}/lib/aarch64-linux-gnu"
envv = dict(os.environ, LD_LIBRARY_PATH=L, ADSP_LIBRARY_PATH=f"{L};/usr/lib/rfsa/adsp;/usr/lib/dsp/cdsp")
NPU_IO = json.load(open(f"{D}/io.json"))  # {"npu0": {"in": [...], "out": [...]}, ...}
so = ort.SessionOptions(); so.intra_op_num_threads = 8
cpu = {k: ort.InferenceSession(f"{D}/cpu{k}.onnx", so, providers=["CPUExecutionProvider"]) for k in (1, 3, 5, 7, 9, 11)}

def run_npu(k, env, timing):
    io = NPU_IO[f"npu{k}"]; w = f"/tmp/npu{k}"; subprocess.run(["rm", "-rf", w]); os.makedirs(w)
    parts = []
    for j, name in enumerate(io["in"]):
        p = f"{w}/in{j}.raw"; np.ascontiguousarray(env[name], "<f4").tofile(p); parts.append(f"{name}:={p}")
    open(f"{w}/list.txt", "w").write(" ".join(parts) + "\n")
    t = time.perf_counter()
    r = subprocess.run([f"{X}/bin/qnn-net-run", "--backend", f"{L}/libQnnHtp.so", "--retrieve_context", f"{D}/npu{k}.bin",
                        "--input_list", f"{w}/list.txt", "--output_dir", f"{w}/out", "--perf_profile", "burst"],
                       env=envv, capture_output=True, text=True)
    wall = time.perf_counter() - t
    if r.returncode: sys.exit(r.stdout[-2000:] + r.stderr[-2000:])
    ts = {m.group(2): float(m.group(1)) for m in re.finditer(r"([\d.]+)ms \[[^\]]*\]\s*(?:<\w>\s*)?(.*)", r.stdout)}
    a = re.search(r"Executing Graphs", r.stdout); b = re.search(r"Finished Executing Graphs", r.stdout)
    # timestamps in qnn-net-run lines: take the ms value on the warning lines just before/after execution
    ms = [float(x) for x in re.findall(r"^\s*([\d.]+)ms", r.stdout[a.end():b.start()], re.M)] if a and b else []
    files = sorted(glob.glob(f"{w}/out/Result_0/**/*.raw", recursive=True))
    for name in io["out"]:
        base = re.sub(r"[^A-Za-z0-9]", "_", name).lstrip("_")
        hit = [f for f in files if os.path.basename(f)[:-4].lstrip("_") == base or f.endswith(name + ".raw")]
        if not hit: sys.exit(f"npu{k}: no output file for {name}; have {files}")
        env[name] = np.fromfile(hit[0], "<f4").reshape(io["shape"][name])
    timing[f"npu{k}"] = round(wall * 1000)

pv = np.fromfile(sys.argv[1], "<f4").reshape(11, 20, 2, 2, 1536)
env, timing = {"pixel_values": pv}, {}
for k in range(13):
    if k % 2 == 0:
        run_npu(k, env, timing)
    else:
        s = cpu[k]; names = [o.name for o in s.get_outputs()]
        t = time.perf_counter(); env.update(zip(names, s.run(names, {i.name: env[i.name] for i in s.get_inputs()})))
        timing[f"cpu{k}"] = round((time.perf_counter() - t) * 1000)
ref = load_feat(sys.argv[2]); got = env["image_features"]
print("split NPU vs ONNX fp32: cos mean/min", cosine_rows(ref, got))
print("per-stage ms (npu = whole qnn-net-run process incl. load):", timing)
np.ascontiguousarray(got, "<f4").tofile(sys.argv[3]); json.dump({"n_tokens": 220, "n_embd": 2048}, open(sys.argv[3] + ".json", "w"))
