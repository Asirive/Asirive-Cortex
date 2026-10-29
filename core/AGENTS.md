# core/ — AGENTS.md (V4 device runtime)

**Domain:** the V4 device brain on the compute module (Dragon Q8B).
**Owner:** core/device domain agent. **Language: Python** (C for hot paths if
measurements demand it). Decision locked 2026-10-29: Python, hardened as below;
Rust is not used unless a safety or latency measurement forces it.
**RULE: every new file, module, config key or behavior change in core/ MUST
update this AGENTS.md in the same change. No exceptions. This file is the
first thing the domain agent reads and the last thing it writes.**

Reference architecture: `docs/architecture/V4-ECOSYSTEM.md`. Inference plan:
`docs/architecture/CORTEX-ENGINE.md`. The V3 code lives in `v3_core/`
(FROZEN reference, bug fixes only); never import from it in V4 code. Port logic
by reading it, keeping `M##`/`FIX-`/`H##`/`TB##`/`L##` tags on ported code.

**Status:** plan only. No V4 code exists in this folder yet.

---

## 1. Design principle

The device has no SSH in the field. It must boot into a working state, stay
there, recover from its own faults, and update without bricking. Safety is a
separate process that cannot be taken down by the AI side.

## 2. Process model (one process per failure domain)

| Service | Role | Priority |
|:---|:---|:---|
| `supervisor` | Starts/monitors services, health, watchdog petting, boot state | highest |
| `safety` | ToF fusion, T0-T3, haptics, hard-coded alert audio. No model, no network, no phone dependency | real-time (SCHED_FIFO), pinned CPU cores, memory locked |
| `link` | USB framing to glasses MCU, USB/BLE to phone, GPS relay | high |
| `perception` | YOLO-World (NPU), frame handling, no frame storage | normal |
| `voice` | wake word, VAD, AEC, audio routing, mic mute state | high |
| `agent` | tool registry, brain adapters (local LFM3-Omni via engine, Gemini fallback), escalation policy | normal |
| `nav` | offline OSM routing, LTA data, indoor guidance | normal |
| `memory` | local SQLite, retention-aware sync | low |
| `ota` | download/verify/stage/commit/rollback agent | normal |

Services talk through the generated contracts (protobuf) over local sockets.
No shared mutable state, no importing across services, no service imports
`v3_core`.

## 3. Safety rules (hard)

1. `safety` never waits on `agent`, `voice`, `perception`, network or phone.
   Its inputs are the ToF matrix and its own sensors only.
2. Isolated process, own CPU cores (cpuset/isolcpus), `SCHED_FIFO`, `mlockall`,
   preallocated buffers, GC frozen/disabled after startup, no dynamic imports,
   no blocking I/O in the loop. Hot math in C/NumPy only where measured.
3. Heartbeat to the supervisor; if `safety` stalls the supervisor restarts it
   AND the hardware watchdog plus a fail-safe haptic/audio "safety degraded"
   cue fire. If it cannot be restored the device says so and stays in a safe
   state.
4. If the AI side dies, safety and basic voice cues keep working (degraded
   mode, announced once).
5. No spatial/directional audio DSP. Clock-position speech cues only.
6. Safety thresholds live in versioned config validated at load; bad config
   falls back to baked-in safe defaults, never to "off".

## 4. Boot and run without SSH

- `systemd` units per service with `Restart=always`, `WatchdogSec`, `sd_notify`
  readiness, `StartLimit*` backoff, ordered `After=`/`Requires=` (safety first).
- Hardware watchdog enabled; supervisor pets it only when safety and link are
  healthy.
- Boot ready cue within a target time (set by measurement): haptic first, then
  voice "Cortex ready" once perception and voice are up. Safety is live before
  anything speaks.
- Offline-capable from first boot: no service blocks on network.
- Deterministic Python environment: pinned lockfile baked into the image
  (note `numpy<2.0` while HailoRT constraints apply to any Hailo remnants; re-
  verify for the QNN stack), built wheels shipped, no `pip install` at runtime.
- Read-only root with writable overlay for state; crash logs trimmed, rotated.
- Developer SSH exists on the alpha bench only (see infra rules).

## 5. Updates

OTA client downloads signed artifacts via the app/gateway chain, verifies
signatures, stages to the inactive slot (A/B), health-checks after reboot, and
rolls back automatically on failed boot or failed safety self-test. An update
must never leave the device without a working safety service.

## 6. Quality gates (what "safe and capable" means in CI)

- Type checking (mypy strict) on all services; generated contract types only
  across process boundaries.
- Replay tests: recorded sessions (ToF + frames + audio) replayed through
  `safety` with expected alert outputs; every ported V3 bug tag gets a
  regression case.
- Fuzz/property tests on USB framing and contract decoding.
- Latency budget test for `safety` (hazard-in to haptic-out) with a hard
  failure threshold set from Phase 0 measurements.
- Fault-injection tests: kill/stall each service, expect the documented
  degraded behavior.
- Power/thermal soak on the Q8B before any release ring.

## 7. Build order

1. `contracts/` (tool registry, USB framing, device-gateway envelope).
2. `supervisor` + systemd units + watchdog (device that boots and heals).
3. `safety` + `link` (port T0-T3 from `v3_core/safety_monitor.py`, replay tests).
4. `voice` (wake word, VAD, AEC, audio routing).
5. `agent` + engine adapter (CORTEX-ENGINE.md Phase 0 baseline first).
6. `perception`, `nav`, `memory`.
7. `ota` client.
Delete `v3_core/` after V4 passes the same bench checks.

## 8. Reference: what to port from `v3_core/`

Safety T0-T3 fusion (`safety_monitor.py`), Gemini Live handler patterns
(`layer2_thinker/gemini_live_handler.py`), voice pipeline (`voice_coordinator.py`,
`tts_router.py`, `audio_queue.py`), intent routing (`layer3_guide/`), hybrid
memory (`layer4_memory/`). Do NOT port: spatial audio, Kokoro, GLM fallback,
`vision_query_handler.py`, `memory_manager.py`, Hailo/RPi5 code, laptop link.

## Change log (append one line per meaningful change)

- 2026-10-29: New V4 core AGENTS.md created (plan only). Language decision:
  Python, hardened (process isolation, real-time safety, systemd/watchdog,
  A/B OTA). V3 moved to `v3_core/`.
