# NPU vision encoder on the Dragon Q8B — design

Status: approved by Haziq 2026-11-24.
Follows: `docs/measurements/2026-11-lfm3-omni-baseline.md` (CPU/GPU baseline) and the V4 core design
(`docs/superpowers/specs/2026-11-24-v4-core-design.md`, vision freshness ≤300 ms, answer < 1 s).

## Why

The baseline showed talking is already fast on CPU (0.2–0.7 s to first word), but **vision is not**: one 640 px frame
costs ~3.3 s of CPU time before the first word (1280 px: 14 s), and the CPU hits its hottest readings while doing it.
The glasses must last half a day to a full day on battery and stay cool on someone's face. Haziq's call: the NPU is the
way to go for efficiency — less heat, less power — and both NPU routes get tried and compared. If neither is good enough,
the next step is our own inference engine.

## Goal

The LFM3-Omni vision encoder (image → the tokens the language model reads) runs on the SC8280XP's Hexagon v68 NPU,
for a fixed 640x360 camera frame, with:

| measure | target | how |
|---|---|---|
| encode time per frame | **≤300 ms** (stretch: ≤100 ms) | median of 20 runs, after warm-up |
| answer quality | same answers as the CPU path on the test frames | 10+ ZV-1F frames, same question, compare answers; plus cosine similarity of the image tokens vs the CPU reference (≥0.98 mean) |
| power | lower watts-per-frame than CPU | USB-C/DC meter during a loop of encodes (no on-board power sensor) |
| heat | CPU stays cooler than the CPU-only path | CPU thermal zones only (not the PMIC sensor) |

**Non-goals:** moving the language model itself to the NPU (later phase), audio encoder, TTS, the GPU.
**Anti-goals:** a fast encoder that sees the shark as a pillow (quality loss we don't measure); breaking the working CPU
path; any Qualcomm SDK files or calibration photos in git.

## Constraints

- **v68 is fixed-point.** The v68 NPU's fast paths are 8- and 16-bit integer; the encoder must be quantised (our
  understanding; to confirm in the QNN docs for v68). Plan for 16-bit activations / 8-bit weights first, as it usually
  keeps the most quality.
- **Fixed input size.** NPU graphs are compiled for one shape: 640x360 (16:9, what the ZV-1F and glasses camera give,
  and the smallest size that answered correctly in the baseline).
- **Qualcomm tools need Haziq's own sign-in** and licence acceptance (QAIRT SDK, or Qualcomm AI Hub, or the Hexagon
  SDK). Claude does not accept licences or sign in for him.
- Runtime on the box comes from Radxa's apt repo where possible (`qcom-qnn-sdk-v68`, 44 MB), so the box stays
  reproducible.

## Approaches (Haziq: "we gotta try both and see what's better")

### A. QNN with Liquid's vision encoder ONNX — first

1. Take `vision_encoder.onnx` from `LiquidAI/LFM3-Omni-2B-ONNX` (also fp16 / q8 variants) and check that its output
   is the projected image tokens the language model reads (same as llama.cpp's mmproj output).
2. Convert it for v68 at 640x360 into a QNN context binary, quantised with ~50 calibration frames from the ZV-1F.
   Converter: QAIRT SDK on the PC (x86) or Qualcomm AI Hub's cloud compile — whichever Haziq can sign in to.
3. On the box: install `qcom-qnn-sdk-v68`, run the binary on the HTP, time it, compare its output to the CPU ONNX
   reference (cosine similarity).
4. End to end: feed the NPU's image tokens into llama.cpp in place of its own image step (llama.cpp accepts
   pre-computed embeddings through its C API; a small tool, not llama-server, for this measurement), ask the test
   questions, compare answers with the CPU path.

Good: Qualcomm's supported route for this NPU; the same toolchain later moves the language model.
Risk: quantisation quality; the ONNX encoder may not match llama.cpp's projector exactly; glue between QNN and llama.cpp.

### B. llama.cpp's own NPU backend, ported to v68 — second

Upstream llama.cpp b12679 builds its Hexagon backend only for v73, v75, v79, v81, v85. v68 work exists in
[PR #17394](https://github.com/ggml-org/llama.cpp/pull/17394) but is not in the main code.

1. Add v68 to the Hexagon backend starting from that PR; build with Qualcomm's Linux Docker toolchain
   (`ghcr.io/snapdragon-toolchain/arm64-linux`, needs Docker on the PC).
2. Run the mmproj (vision encoder) with the NPU device, same 640 px frames; time it and compare answers.
3. Whatever ops the NPU backend doesn't support fall back to CPU — record which ones, because that is the work list
   for our own engine.

Good: one program, no conversion; whatever we learn is the foundation for our own engine.
Risk: high — v68 support crashed during upstream development; the vision encoder's ops (convolution, attention, layer
norm) may not all be on the NPU.

### Compare and decide

Same frames, same questions, same table for A, B and the CPU baseline: encode ms, answer match, cosine, watts, CPU temp.
Pick the faster one at equal quality. If neither reaches ≤300 ms with equal answers, write up why (which ops, which
limits) — that becomes the brief for our own inference engine (a separate design).

## Rejected

- **Qualcomm's OpenCL GPU driver** (`qcom-adreno-opencl`, in Radxa's repo): may halve vision time, but it is the GPU,
  not the NPU, and won't reach 300 ms or the power goal. Can be a one-off side test later.
- **Smaller images (384 px)**: 1.6 s, and it called the shark a pillow.

## Calls left to the builder

Calibration frame count and scenes (aim for variety: indoor, outdoor, low light); quantisation scheme beyond the
first try; the exact glue program for step A4; file layout under `core/cortex_core/engine/` or a new `npu/` folder.

## What Haziq needs to do

- Sign in to Qualcomm and get the **QAIRT SDK** (or an **AI Hub** API token) — needed for A.
- Install **Docker Desktop** on the PC — needed for B.
- A USB-C/DC **power meter** for the watts comparison (can come last).
