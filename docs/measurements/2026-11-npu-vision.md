# LFM3-Omni vision encoder on the Hexagon NPU (2026-11-24)

Plan: `docs/superpowers/plans/2026-11-24-npu-vision-qnn.md` (approach A, QNN + ONNX).
Spec: `docs/superpowers/specs/2026-11-24-npu-vision-design.md`.

## Headline

| | ONNX on CPU (fp32) | llama.cpp mmproj on CPU | **NPU split (this work)** |
|:---|---:|---:|---:|
| Encode, one frame | 1190 ms | 1424 ms | **253-268 ms** (median of 20 per frame) |
| Landscape frames answered right (12 test + 1080p) | n/a | 12/12 * | **13/13** |
| Portrait frame (360x640, out of scope) | n/a | n/a | fails (see below) |
| Cosine vs ONNX fp32, landscape frames | 1.0 | n/a | **0.985-0.994** mean |

\* The 12 cases were *chosen* as the ones llama.cpp on CPU answered right (Task 4), so 12/12 there is true by construction.

Targets: ≤ 300 ms encode is **met**. A cosine mean of at least 0.98 is **met on landscape frames only**.
The camera is always landscape, so portrait is out of scope; a non-16:9 camera would not be (see below).
The whole "ask, then hear the answer" path is still **not** under 1 s. Answering from ready-made features has a
2.3-2.9 s ttft, almost all of it the LM prefilling 220 image tokens. See "What is still slow".

## Setup

- Box: Radxa Dragon Q8B, SC8280XP, Hexagon v68 CDSP. Ubuntu, Python 3.14 venv, onnxruntime 1.32.0.
- Runtime: `qcom-qnn-sdk-v68` 0.1.0-2 (QNN 2.42.0), unpacked without root. The user is in group `render` for `/dev/fastrpc-cdsp`.
- Converter: QAIRT 2.42.0.251225 run locally in WSL. No photos were uploaded anywhere.
- Model: Liquid's `vision_encoder.onnx`. Contrib ops (RMSNorm, rotary, MHA) are decomposed to standard ONNX ops
  (`cortex_core/npu/decompose.py`, cosine 1.0 vs the original), then folded.
- **Split:** v68 can only multiply two activations at 8 x 8 bit. 16-bit activations are needed for accuracy: w8a8
  everywhere gave cosine 0.40. So the attention cores of 6 layers (Q.K^T, softmax, P.V) run on the CPU
  (onnxruntime, 8 threads). Everything else runs on the NPU as 7 segments, w8a16, per-channel weights, calibrated on
  52 full landscape frames from the box camera (40 normal, 12 dim). See `cortex_core/npu/split.py` and `core/scripts/npu/`.
- Runner: `libcortex_npu.so` (`core/tools/cortex-npu/`). It loads the 7 context binaries once (~0.4 s; 3.1 s on the
  first run after boot) and calls `graphExecute` per segment with the HTP in burst mode. Python
  (`cortex_core/npu/qnn.py`, `split_encoder.py`) quantises inputs and dequantises outputs.
- `python -m cortex_core.npu.run_npu` runs the whole bench as one supervised child process under a timeout, and
  opens the NPU once (see "Box reset" below).

## Per-frame stage time (scene_640, median of 10)

| npu0 | cpu1 | npu2 | cpu3 | npu4 | cpu5 | npu6 | cpu7 | npu8 | cpu9 | npu10 | cpu11 | npu12 | total |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| 29.2 | 16.8 | 21.7 | 16.9 | 21.9 | 16.9 | 21.8 | 16.9 | 21.9 | 16.9 | 21.8 | 16.9 | 17.7 | **257** |

NPU 156 ms (including numpy quantise/dequantise), CPU attention 102 ms.

## Per frame (final run, 20 timed runs each, CPU reference warmed)

"tok < 0.9" is the share of the 220 tokens whose cosine to the CPU features is under 0.9. A layout or token-order
bug shows up here even when the mean looks fine.
CPU MHz is the min-max over all cores, sampled after each of the 20 runs.

| frame | size | light | CPU ms | NPU ms med/p90 | cos mean/min | tok < 0.9 | CPU MHz | CPU °C max | NPU answer | match |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| t001 | 640x360 | dim | 1191 | 256 / 256 | 0.986 / 0.40 | 3.2% | 2438-2995 | 54.7 | The large toy in front of you is a plush shark. | ✓ |
| t002 | 640x360 | dim | 1190 | 253 / 257 | 0.990 / 0.68 | 2.7% | 2438-2995 | 62.1 | This toy is a plush shark. | ✓ |
| t003 | 640x360 | dim | 1188 | 255 / 257 | 0.987 / 0.53 | 2.7% | 2438-2995 | 63.1 | The plush toy is teal (a blue-green) with a white belly. | ✓ |
| t004 | 640x360 | dim | 1188 | 253 / 257 | 0.989 / 0.58 | 1.8% | 2438-2995 | 56.7 | A teal plush shark toy is directly in front of you. | ✓ |
| t005 | 640x360 | normal | 1188 | 257 / 259 | 0.990 / 0.77 | 1.8% | 2438-2995 | 64.4 | The person's hand is holding a black computer mouse. | ✓ |
| t006 | 640x360 | normal | 1188 | 257 / 263 | 0.993 / 0.83 | 0.9% | 2438-2995 | 57.4 | A black computer mouse is in front of you. | ✓ |
| t007 | 640x360 | normal | 1190 | 257 / 268 | 0.988 / 0.42 | 1.8% | 2438-2995 | 60.4 | The mouse is black. | ✓ |
| t008 | 640x360 | normal | 1190 | 255 / 267 | 0.994 / 0.87 | 0.5% | 2438-2995 | 57.7 | This is a television remote control. | ✓ |
| t009 | 640x360 | normal | 1187 | 255 / 257 | 0.992 / 0.78 | 1.8% | 2438-2995 | 60.4 | A white television remote control is lying on the bed. | ✓ |
| t010 | 640x360 | normal | 1190 | 268 / 271 | 0.985 / 0.66 | 4.1% | 2438-2995 | 57.0 | A black smartphone is resting on the desk in front of you. | ✓ |
| t011 | 640x360 | normal | 1189 | 256 / 258 | 0.989 / 0.75 | 2.3% | 2438-2995 | 61.1 | This is a smartphone (an iPhone), shown with its screen on and home button visible. | ✓ |
| t012 | 640x360 | normal | 1188 | 255 / 256 | 0.992 / 0.73 | 1.4% | 2438-2995 | 57.4 | The device with the cable plugged in is a black portable power bank (power station). | ✓ |
| h008 (t008 upscaled) | 1920x1080 | normal | 1190 | 256 / 257 | 0.989 / 0.48 | 2.7% | 2438-2995 | 63.4 | This is a white television remote control resting on a gray bed sheet. | ✓ |
| **p001 (t001 rotated)** | **360x640** | dim | 1187 | 257 / 259 | **0.683 / 0.39** | **95.9%** | 2438-2995 | 61.4 | The large toy in front of me is a soft, teal‑colored plush **hand**. | **✗** |

Against the CPU answers from the first run, 8 of the 12 landscape answers are word for word the same. All 12 name the
right object. Two lost a detail:
- t006 dropped "wrinkled gray fabric surface".
- t011 swapped "charging cable plugged in" for "home button visible". That is a content change, not a shorter answer.

No throttling: CPU clocks stayed at 2438-2995 MHz and CPU zones at 55-64 °C throughout.

## Frames that need padding break the NPU encoder

The CPU and NPU get the identical prepared input here: a 360x640 frame fitted into the 640x352 canvas, with grey bars
on both sides. Even so, the NPU features disagree with the CPU on 96% of tokens, and the answer goes wrong ("plush hand").
Likely cause: calibration saw only full landscape frames, never large flat grey padding, so the w8a16 ranges do not
cover the activations that padding produces. The 1080p frame fills the canvas with no padding and works.

Decision (Haziq, 2026-11-24): the product camera is always landscape, so portrait frames are out of scope and
nothing is changed. What matters is the **aspect ratio**: any frame that does not fill the 16:9 canvas gets grey
bars. A 4:3 product camera (common for small modules) would hit this on every frame. When the real camera is
chosen, check its aspect ratio: if it is not 16:9, recalibrate with its own frames (already needed anyway) or
crop them to 16:9 before `prepare`.

## Box reset during the review rerun

The box hard-reset once, at 09:39:24. A probe process had opened the NPU, run one frame and exited; the kernel logged
`fastrpc … unmmap pt … ERROR`; the main process reopened the NPU one second later; then the box died, with no kernel
panic or thermal message.
- The unmap error is intermittent. It appeared on the first NPU session after a fresh boot. It did not appear on two
  later sessions, one with the old shim build and one with the new one. So the shim change is not the cause.
- The runner now opens the NPU only once per run. The full 14-frame run then finished with no new unmap error and no reset.
- The QNN/fastrpc root cause is unknown. Anything long-running (the brain) must not close and reopen the NPU rapidly.

## Honest caveats

- **Narrow test set.** 12 frames show 5 objects in one room. This proves "NPU ≈ CPU" on landscape frames. It does not
  prove accuracy in the world.
- **Worst tokens drift.** Min per-token cosine falls to 0.40 (t001). 0.5-4.1% of tokens sit under 0.9 on the
  landscape frames. Fine detail (text, small objects) is the likely casualty. Not yet tested.
- **Dim, not dark.** The "low light" frames are dim (mean brightness 39-75 of 255), not dark. Their cosine means
  (0.986-0.990) sit inside the normal-light range; only the min tokens are lower. Truly dark frames are untested.
- **Wrong camera.** Calibration and test used the Sony ZV-1F, not the product camera. Recalibrate once the real camera is in.
- **Power not measured.** There is no meter. The `pmc8280c-thermal` zone is a stepped alarm sensor (it reads fixed
  levels such as 37 / 88 / 92 °C, and sat at exactly 88.000 °C for minutes with the box idle). It is not a live
  temperature and is not used as one. The runner's pause on it is capped at 60 s, and it fired on 5 frames.
- The NPU number includes Python quantise/dequantise. A C path could shave a few ms per stage. Not worth doing yet.

## What is still slow

Answering from ready-made features still takes **2.3-2.9 s to the first token**, because the LM must prefill 220
image tokens (~95 tok/s on CPU). An NPU encoder alone cannot get "ask → hear" under 1 s. The image has to be encoded
**and prefilled into the KV cache before the user asks**: continuous background encode + prefill of the latest frame,
then only the question tokens at ask time. This is the next piece of work, together with fewer image tokens.

## What it means for approach B (llama.cpp Hexagon v68 port)

Approach A meets the encode target, so B is no longer needed for the vision encoder. B is still the candidate for
the LM backbone (Phase 2 of `docs/architecture/CORTEX-ENGINE.md`), where the prefill cost now sits. Two lessons from
A carry over:
- v68's 8x8-only activation MatMul rules out naive full-NPU attention.
- Any NPU backbone will need the same CPU-attention split, or 8-bit attention that keeps accuracy.
