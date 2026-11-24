# Vision encoder -> Hexagon v68 (SC8280XP), split build

Tool versions: QAIRT 2.42.0.251225 (public Community zip, matches the box's qcom-qnn-sdk-v68 0.1.0-2 =
libQnnHtp v2.42.0.251225135753), WSL Ubuntu 24.04, uv CPython 3.10.22 venv (numpy 1.26.4, onnx 1.16.1,
onnxruntime 1.18.1, protobuf 3.20.3), libc++/libc++abi/libunwind 18.1.3 + libatomic1 14 unpacked into
~/qairt/libcxx (no sudo). SDK bin/ needs `chmod -R u+x` after a Python zip extract.

1. `python -m cortex_core.npu.decompose vision_encoder.onnx vision_std.onnx` (contrib ops -> standard ops,
   input fixed to 11x20x2x2x1536), then onnxruntime BASIC optimisation saved to vision_std_folded.onnx.
2. `cortex_core.npu.split.split_stages(model, [".../layers.{2,4,..12}/attn/MultiHeadAttention/"])` -> npu0..npu12
   (7 NPU segments) + cpu1..cpu11 (6 attention islands). Why: v68 HTP only multiplies two activations at 8x8 bit
   ("incorrect Value 68, expected >= 73" for a16xa16 and a16xa8), and w8a8 everywhere gives cosine 0.40.
3. `build_segments_wsl.sh`: per segment, seg_calib.py (52 frames through the ORT chain) -> qairt-converter ->
   qairt-quantizer w8 a16 b32 per-channel -> qnn-context-binary-generator (soc_model 37, dsp_arch v68, O 3).
4. Box: `run_split_chain.py FRAME.raw REF.f32 OUT.f32` (qnn-net-run from the unpacked deb + ORT islands).

Result (scene_640): cosine vs ONNX fp32 0.9925 mean / 0.82 min; LM answer unchanged (shark).
NPU NetRun per segment 32.5/25.5/24.7/23.3/25.1/25.2/18.6 ms = 175 ms; CPU islands ~17-22 ms each (8 threads).
