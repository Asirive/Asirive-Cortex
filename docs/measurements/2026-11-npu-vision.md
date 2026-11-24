# LFM3-Omni vision encoder on the Hexagon NPU (2026-11-24)

Plan: `docs/superpowers/plans/2026-11-24-npu-vision-qnn.md` (approach A, QNN + ONNX).
Spec: `docs/superpowers/specs/2026-11-24-npu-vision-design.md`.

## Headline

| | ONNX on CPU (fp32) | llama.cpp mmproj on CPU | **NPU split (this work)** |
|:---|---:|---:|---:|
| Encode, 640x360 frame | 1190 ms | 1424 ms | **255 ms** (median of 20, all 12 frames 254-258 ms) |
| Answers matching the CPU answer's keywords | n/a | 12/12 | **12/12** |
| Cosine vs ONNX fp32 (mean over frames) | 1.0 | n/a | **0.985-0.994** |

Targets: ≤ 300 ms encode **met**. ≥ 0.98 cosine mean **met** on every frame.
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
  52 frames from the box camera (40 normal, 12 dim). See `cortex_core/npu/split.py` and `core/scripts/npu/`.
- Runner: `libcortex_npu.so` (`core/tools/cortex-npu/`). It loads the 7 context binaries once (416 ms) and calls
  `graphExecute` per segment with the HTP in burst mode. Python (`cortex_core/npu/qnn.py`, `split_encoder.py`)
  quantises inputs and dequantises outputs. Calling `qnn-net-run` per segment cost ~400 ms each (a context reload
  every call), so it cannot serve as the runtime.

## Per-frame stage time (scene_640, median of 10)

| npu0 | cpu1 | npu2 | cpu3 | npu4 | cpu5 | npu6 | cpu7 | npu8 | cpu9 | npu10 | cpu11 | npu12 | total |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 29.2 | 16.8 | 21.7 | 16.9 | 21.9 | 16.9 | 21.8 | 16.9 | 21.9 | 16.9 | 21.8 | 16.9 | 17.7 | **257** |

NPU 156 ms (including numpy quantise/dequantise), CPU attention 102 ms.

## Per frame (`python -m cortex_core.npu.run_npu`, 20 runs each)

| frame | light | CPU ms | NPU ms (med / p90) | cos mean / min | CPU answer | NPU answer | match |
|:---|:---|---:|---:|---:|:---|:---|:---:|
| t001 | low | 1409 | 254 / 256 | 0.986 / 0.40 | The large toy in front of you is a plush shark. | identical | ✓ |
| t002 | low | 1195 | 254 / 268 | 0.990 / 0.68 | This toy is a plush shark. | identical | ✓ |
| t003 | low | 1196 | 254 / 258 | 0.987 / 0.53 | The plush toy is teal (a blue-green) with a white belly. | identical | ✓ |
| t004 | low | 1192 | 257 / 259 | 0.989 / 0.58 | A teal plush shark toy is directly in front of you. | identical | ✓ |
| t005 | normal | 1187 | 257 / 262 | 0.990 / 0.77 | The person's hand is holding a black computer mouse. | identical | ✓ |
| t006 | normal | 1189 | 255 / 257 | 0.993 / 0.83 | A black computer mouse is in front of you, resting on a wrinkled gray fabric surface. | A black computer mouse is in front of you. | ✓ |
| t007 | normal | 1192 | 256 / 260 | 0.988 / 0.42 | The mouse is black. | identical | ✓ |
| t008 | normal | 1190 | 255 / 259 | 0.994 / 0.87 | This object is a television remote control. | This is a television remote control. | ✓ |
| t009 | normal | 1194 | 255 / 259 | 0.992 / 0.78 | A white television remote control is lying on the bed. | identical | ✓ |
| t010 | normal | 1191 | 256 / 261 | 0.985 / 0.66 | A black smartphone is resting on the desk in front of you. | identical | ✓ |
| t011 | normal | 1197 | 256 / 259 | 0.989 / 0.75 | This is a smartphone (an iPhone), shown with its screen on and a charging cable plugged into its bottom port. | …screen on and home button visible. | ✓ |
| t012 | normal | 1191 | 258 / 260 | 0.992 / 0.73 | …a black rectangular power bank (portable power station). | …a black portable power bank (power station). | ✓ |

8 of 12 answers are word-for-word identical. All 12 name the right object. Two answers lost a detail:
- t006 dropped "wrinkled gray fabric surface".
- t011 swapped "charging cable plugged in" for "home button visible". That is a content change, not just a shorter answer.

## Honest caveats

- **Narrow test set.** 12 frames show 5 objects in one room. This proves "NPU ≈ CPU". It does not prove accuracy in the world.
- **Worst tokens drift.** Min per-token cosine falls to 0.40 (t001) and 0.42 (t007). The mean holds, but a few
  image patches are poorly represented. Fine detail (text, small objects) is the likely casualty. Not yet tested.
- **Low light** is slightly worse (cos mean 0.986-0.990 vs 0.985-0.994 overall; min drops lower).
- **Wrong camera.** Calibration and test used the Sony ZV-1F, not the product camera. Recalibrate (a ~40 min
  WSL rebuild) once the real camera is in.
- **Power not measured.** There is no meter. The hottest thermal zone during the run was the PMIC sensor
  (`pmc8280c-thermal`) at 88-92 °C. The CPU zones were not separated in this run. Treat thermals as unknown.
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
