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

**Status:** first slice built (2026-10-29): contracts codegen, OTA verifier + A/B slots, safety skeleton, supervisor + systemd units, owner-stop handler. See section 9 for what is real vs stubbed. 32 tests pass (`python3 -m pytest core`).

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

## 9. Build status (honest)

| Area | Path | State |
|:---|:---|:---|
| Contracts | `cortex_core/contracts/` (generated by `scripts/gen_proto.sh`, committed) | Built. Real protobuf Python from `contracts/proto`. Regenerate after any proto change. |
| OTA verifier | `ota/verify.py` | Built. Same rules as Go `Verify`; a test signs with `cortex-sign` (Go) and verifies in Python, so signing bytes are proven identical. |
| OTA slots | `ota/slots.py` | Built. Atomic state file, A/B, trial boots, auto rollback, anti-rollback counter raised only on commit. Tested with a power cut at every write point (torn temp files included). Slots are image FILES in a directory: the real bootloader/eMMC partition hand-off is NOT built. |
| OTA agent | `ota/agent.py` | Built: verify -> fetch -> stage -> switch, and post-boot self-test commit. Transport (app USB relay / gateway) and the real self-test are NOT built. MCU and model artifacts are ignored (compute firmware only). |
| Safety | `safety/` | Skeleton. Fail-safe loop, heartbeat, config fallback, never-silent degraded mode, import-isolation test. T0-T3 logic is a placeholder, not yet ported from `v3_core/safety_monitor.py`; no ToF driver or haptic/audio sinks (entry point reports "degraded" on purpose); no SCHED_FIFO/mlockall/GC freeze yet (unit file sets FIFO/cpuset). |
| Supervisor | `supervisor/`, `deploy/` | Built: ordered start, backoff, heartbeat stall detection, watchdog petting only when safety+link healthy, systemd launcher. Units pass `systemd-analyze verify` apart from the venv path. NOT run on a real device or with a real hardware watchdog; the degraded cue is only logged (haptic hardware hook TODO). `link` and `ota` entry points are heartbeat-only stubs. |
| Owner stop | `link/owner_control.py` | Built and fuzzed (500 random frames). Needs the real USB/BLE transport and the real `Controls` (agent/voice/power) behind it. |
| Not started | voice, agent, perception, nav, memory, USB framing, mypy gate, replay/latency tests | |

Run: `pip install -r requirements.txt && python3 -m pytest core` (the Go cross-check test skips without Go).

## Change log (append one line per meaningful change)

- 2026-10-29: New V4 core AGENTS.md created (plan only). Language decision:
  Python, hardened (process isolation, real-time safety, systemd/watchdog,
  A/B OTA). V3 moved to `v3_core/`.
- 2026-10-29: First slice: contracts codegen, ota (verify, A/B slots, agent), safety skeleton, supervisor + systemd units, owner-stop handler, 32 tests. Safety tiers, drivers, link transport and bootloader hand-off remain stubs (section 9).

- 2026-10-30: link/identity.py (device P-256 key, PKIX public key for claim, mTLS context, renewal check) and link/cmdverify.py (signed alpha command verifier, cross-checked against the Go signer). Not yet wired into a running service; the connection client itself is not written.

- 2026-10-30: link/session.py (outbound mTLS WebSocket client: Hello, heartbeat, OTA offer hook, signed-command handling, reconnect with backoff), link/provision.py (store the claim reply, certificate renewal), link service entry point dials the gateway once paired. Tested end to end against the real Go gateway (tests/test_gateway_session.py): claim, mTLS connect, online in the console, signed command verified and run, build without verifier refuses, revoke drops the device, renewal keeps the key. NOT done: the phone-to-glasses USB/BLE framing that delivers the claim reply (provision.save is the landing point), real telemetry (heartbeat reports DEGRADED until safety publishes status), wiring OTA offers to the OtaAgent and artifact download, renewal while running (only checked at boot), the phone-side TCP tunnel. Production builds never set CORTEX_ALPHA_BUILD, so debug commands are refused.
- 2026-10-30: `cortex_core/link/phone_link.py` added: phone-to-box link (WebSocket over the USB tether network, UDP beacon, HMAC-signed owner commands, one-time provision). Spec `docs/architecture/PHONE-BOX-LINK.md`. Wired into the link service. `test`/`install` ops answer false until audio/haptic and OTA are connected. 54 tests pass.
- 2026-10-30: `phone_link` provision now refuses a certificate that does not match the box key (closes the junk-provision hole on the hotspot).
- 2026-10-30: review fixes in `phone_link`: `provision` needs the printed claim code, is locked and all-or-nothing, and repeats of the same secret are accepted; beacon works on Python < 3.11 and can be pinned with CORTEX_TETHER_IFACE; link task failures are logged.
