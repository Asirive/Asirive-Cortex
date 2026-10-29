# core/ — AGENTS.md

**Domain:** the device brain (compute module runtime + hardware support).
**Owner:** core/device domain agent. Language: Python, C for hot paths.
**RULE: every new file, module, config key or behavior change in core/ MUST
update this AGENTS.md in the same change. No exceptions. This file is the
first thing the domain agent reads and the last thing it writes.**

Reference architecture: `docs/architecture/V4-ECOSYSTEM.md`.

---

## What lives here

| Path | Role |
|:---|:---|
| `system.py` | `CortexSystem` orchestrator (V3 monolith, ~8.4k lines, scheduled for decomposition) |
| `layer0_guardian/` | YOLO detection + haptic (L0 Guardian) |
| `layer1_learner/` | YOLOE open-vocabulary detection (L1, config-disabled) |
| `layer1_reflex/` | VAD, STT (Cartesia/Whisper), local TTS (Supertonic) |
| `layer2_thinker/` | Gemini Live handler, audio player, TTS handlers, scene triggers, LTA |
| `layer3_guide/` | Intent router, navigation engine, bus handler, saved locations |
| `layer4_memory/` | Hybrid memory (SQLite + cloud sync) |
| `safety_monitor.py` | Tiered hazard fusion (T0-T3) |
| `safety_audio_coordinator.py`, `audio_alerts.py` | Alert queueing and playback |
| `voice_coordinator.py`, `tts_router.py`, `audio_queue.py` | Voice pipeline and speech routing |
| `conversation_manager.py`, `session_av_recorder.py` | Dialogue state, session recordings |
| `hailo_depth.py`, `hailo_ocr.py` | NPU perception (currently disabled in config) |
| `live_dashboard/` | Textual TUI + 2.4 console dashboard + `*` system-pause keybind |
| `config/` | `config.yaml` (single source of runtime config) + loader |
| `assets/` | Alert audio clips |
| `device/` | Hardware support: `camera/`, `sensors/`, `hardware/` (GPS, BT, button, IMU), `bluetooth_handler.py`, `power_monitor.py`, `static/` |

Entry point is `python -m apps.cortex all` (see `apps/AGENTS.md`).

## Hard rules

1. **Safety T0-T3 never sits behind an AI model** and never depends on phone,
   network or cloud. Haptics and voice alerts are hard-coded paths.
2. **No spatial/directional audio DSP** (deprecated since V2). Voice cues are
   plain clock-position speech: "obstacle at 10 o'clock".
3. **`numpy<2.0` is pinned** (HailoRT 4.20). Do not upgrade.
4. Bug-tag convention in code comments: `M##`, `FIX-`, `H##`, `TB##`, `L##`
   reference specific incidents. Keep the tags when touching that code.
5. Secrets live in `.env` only. Never hardcode keys.

## Deprecated inside core/ (do not extend, delete during V4 refactor)

- `layer3_guide/spatial_audio/` (scrapped in V2)
- `layer1_reflex/kokoro_handler.py`, `layer1_reflex/detection_aggregator.py`
- `layer2_thinker/glm4v_handler.py` (tier-2 fallback never wired)
- `layer4_memory/memory_manager.py` (dead stub)
- `vision_query_handler.py` (import-only, never instantiated)

## V4 direction

- Decompose `system.py` into services: perception, safety, voice, agent
  harness, navigation, memory.
- Dual-brain agent harness, local-first: one function-calling tool registry,
  LFM3-Omni-2B as the default brain, Gemini Live as the online fallback and
  escalation (still more powerful). Local brain must support function calling.
- Inference engine: staged, measurement-gated (llama.cpp baseline, power-aware
  serving, Hexagon NPU backend, custom runtime only if justified). See
  `docs/architecture/CORTEX-ENGINE.md`. Safety T0-T3 must never be starved by it.
- Voice policy: LFM3-Omni speech in/out by default; cloud voices (Cartesia) as
  online fallback; local Supertonic + Whisper-class STT as the floor. AEC
  mandatory.
- Wake word ("Hey Cortex") runs here, never on the glasses MCU.
- Offline walking navigation on bundled map data; indoor guidance via visual
  understanding.
- Retention-aware sync: images/video never leave the device as stored data.

## How to run and check

```bash
python -m apps.cortex all           # full system (Textual TUI)
python -m apps.cortex test          # self-test subsystems
python -m apps.cortex test-live     # minimal Gemini Live probe
py -3 -m compileall core            # syntax gate after changes
```

## Change log (append one line per meaningful change)

- 2026-10-29: Direction set: LFM3-Omni-2B local-first brain, Gemini Live online fallback, staged inference engine (docs only, no code yet).
- 2026-10-12: AGENTS.md created. device/ folded into core/device/ (monorepo layout).
