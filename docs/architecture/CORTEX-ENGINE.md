# Cortex Engine — LFM3-Omni Inference Plan

**Status:** plan, nothing built yet. Companion to [V4-ECOSYSTEM.md](V4-ECOSYSTEM.md) §8.
**Rule:** every phase is gated by measurements on real hardware. We only build
the next layer if the numbers say the previous one is not enough.

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

### Phase 0 — Baseline (stock llama.cpp on Dragon Q8B)
Measure: tokens/s (prefill and decode), time-to-first-audio, peak RAM next to
YOLO-World and the safety stack, watts per query, idle draw, thermals.
Also measure quality: tool-call success on our registry, navigation prompts,
speech cue quality vs Supertonic/Cartesia, vs Gemini Live on the same cases.
**Exit:** a numbers table committed to docs, and a decision on Phase 1 targets.

### Phase 1 — Power-aware serving (on llama.cpp)
- Brain idle until wake word / trigger; wake word stays outside the model.
- Encoders on demand: camera frames on trigger or low fps, not continuous.
- KV-cache reuse across turns; bounded context.
- CPU/GPU governor and thermal control tied to interaction state.
- Function-calling adapter bound to the shared tool registry (contracts).
- Gemini escalation hook (confidence/capability triggers).
**Exit:** measured watts-per-interaction improvement vs Phase 0.

### Phase 2 — Hexagon NPU backend
Move the heaviest, most regular work (encoders, prefill) to the NPU via QNN /
Hexagon; decode may stay on CPU/GPU. Pick quantization against accuracy and
watts. Prior art: third-party QHexRT on LFM2.5-230M; nothing for LFM3-Omni.
**Exit:** NPU path beats Phase 1 on watts at equal quality.

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
