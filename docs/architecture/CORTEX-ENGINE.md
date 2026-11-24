# Cortex Engine — LFM3-Omni Inference Plan

**Status:** plan, nothing built yet. Companion to [V4-ECOSYSTEM.md](V4-ECOSYSTEM.md) §8.
Updated 2026-11-24 to the approved core design
(`docs/superpowers/specs/2026-11-24-v4-core-design.md` §6.12).
**Rule:** the CPU/GPU/NPU split is the goal from the start (the NPU is the
lowest-power place for the model block). The stock baseline comes first only
to get numbers to beat. Custom kernels / a custom runtime are built only if the
split misses the targets.
**Targets:** first audio < 1 s after the question ends, answers about the
current view (fresh frame encoded while the user speaks), half a day to a full
day of battery.

## 1. Goal

Run LFM3-Omni-2B as the **local-first brain** for full localized navigation on
the compute module, at the lowest power per useful interaction. Gemini Live
remains the online fallback/escalation (more powerful); local leads.

## 2. The model (as of 2026-10-29; Liquid-reported, unverified by us)

- Liquid AI LFM3-Omni-2B, released 2026-10-27. ~2.17B params, 32K context,
  non-reasoning.
- Inputs: text, image, video, audio. Outputs: text, speech (24 kHz), or both.
- Parts: LFM3 backbone (~1.7B per a community card), vision encoder, causal
  audio encoder, LiquidCodec audio tokenizer.
- Runs today on Ollama and llama.cpp (b11960+), GGUF down to Q4_K_M with a
  separate multimodal projector. llama.cpp offers `/v1/realtime` (voice with tool
  calls) and `/tts`. No MLX/ONNX yet. No known NPU path.
- Unknown until we measure: RAM, latency, power, tool-call reliability, speech
  quality, license terms for shipping weights in hardware.

## 3. Phases

### Phase 0 — Baseline (stock llama.cpp on Dragon Q8B, CPU then GPU)
Measure: tokens/s (prefill and decode), time-to-first-audio, peak RAM next to
YOLO-World and the safety stack, watts per query, idle draw, thermals.
Also prove the NPU is reachable from the box's Ubuntu (driver / fastrpc /
Qualcomm runtime), since Phase 2 depends on it.
Also measure quality: tool-call success on our registry, navigation prompts,
speech cue quality vs Supertonic/Cartesia, vs Gemini Live on the same cases.
**Exit:** a numbers table committed to docs, and a decision on Phase 1 targets.
**Status:** CPU/GPU baseline and NPU probe done 2026-11-24, see `docs/measurements/2026-11-lfm3-omni-baseline.md`.
Power (needs a meter) and real-voice quality still open. Headline: voice 0.2–0.7 s on CPU, vision 3.3 s at 640 px,
Vulkan GPU slower and unstable, NPU reachable but no QNN runtime → vision encoder is the first NPU target.

### Phase 1 — Power-aware serving (on llama.cpp)
- Brain idle until wake word / trigger; wake word stays outside the model.
- Encoders on demand: camera frames on trigger or low fps, not continuous.
- KV-cache reuse across turns; bounded context.
- CPU/GPU governor and thermal control tied to interaction state.
- Function-calling adapter bound to the shared tool registry (contracts).
- Gemini escalation hook (confidence/capability triggers).
**Exit:** measured watts-per-interaction improvement vs Phase 0.

### Phase 2 — CPU/GPU/NPU split (the goal)
Model block (backbone) on the Hexagon NPU; vision and audio encoders and the
speech decoder on GPU/CPU, running in parallel (vision encodes while the user
speaks; decode streams while the next frame encodes). Try llama.cpp's
experimental Hexagon backend first (one runtime); fall back to Qualcomm QNN /
Genie if it cannot run LFM3-Omni. Pick quantization against accuracy and
watts. Prior art: third-party QHexRT on LFM2.5-230M; nothing published for
LFM3-Omni, so our own conversion may be needed.
**Exit:** meets the < 1 s target and beats Phase 1 on watts at equal quality.
**Status (2026-11-24):** vision encoder runs on the NPU via QNN. Attention cores stay on the CPU, because v68 only
multiplies activations at 8 bit. Result: 255 ms per 640 px frame vs 1190 ms on CPU, 13/13 landscape answers right
(frames that are not 16:9 get padded and break it; camera must be 16:9 or recalibrated), see
`docs/measurements/2026-11-npu-vision.md`. Still over 1 s overall: the LM prefill of 220 image tokens takes 2.3-2.9 s.
Next: background encode + prefill of the latest frame, then the backbone.

### Phase 3 — Custom runtime (only if needed)
C core, static memory plan, streaming speech-token path, no Python on the hot
path. Start this only if Phases 1-2 miss the power/latency targets.

## 4. Non-negotiables

- Safety T0-T3 never depends on the model and is never starved by it
  (CPU affinity / priority isolation for the safety path).
- Images/video are never stored; frames are processed in flight only.
- Local brain meets the same function-calling contract as Gemini, or Gemini
  stays primary for that tool.
- Fine-tuning for navigation and our tool schemas is expected (supported on a
  single GPU per Liquid).

## 5. Open items

- [ ] Weights license review (commercial use, redistribution on device)
- [ ] Power targets: watts per interaction and idle, tied to the battery choice
- [ ] Escalation policy to Gemini (triggers, thresholds, UX)
- [ ] Contract: tool registry schema shared by both brains (infra contracts)
