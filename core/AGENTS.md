# core/ — AGENTS.md (V4 device runtime)

**Domain:** the V4 device brain on the compute module (Dragon Q8B).
**Owner:** core/device domain agent. **Language: Python** (C for hot paths if
measurements demand it). Decision locked 2026-10-29: Python, hardened as below;
Rust is not used unless a safety or latency measurement forces it.
**RULE: every new file, module, config key or behavior change in core/ MUST
update this AGENTS.md in the same change. No exceptions. This file is the
first thing the domain agent reads and the last thing it writes.**

**Approved design (source of truth for what core/ builds):**
`docs/superpowers/specs/2026-11-24-v4-core-design.md`. Reference architecture:
`docs/architecture/V4-ECOSYSTEM.md`. Inference plan:
`docs/architecture/CORTEX-ENGINE.md`.

**V4 is a new system.** The V3 code lives in `v3_core/` (FROZEN, bug fixes
only). Never import it, never copy or port its code. Take only the IDEAS that
worked (the tool-based agent harness, modes that set how proactive the brain
is) and build them new. V3 safety and V3 memory did not work: do not use them
even as a reference design. Existing V4 code (supervisor, OTA, link, phone
link, contracts) is new code and stays.

**What the product is:** a navigation device used WITH the white cane, not a
replacement for it. Safety exists so users trust the device; it warns only
about what the cane cannot catch (head-level and silent obstacles).

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
| `safety` | VL53L7CX ToF only: head-level and silent obstacles, vibration-only warnings, anti-spam. No model, no network, no phone dependency | real-time (SCHED_FIFO), pinned CPU cores, memory locked |
| `link` | Gateway mTLS session, phone link (USB tether), GPS from the phone, "box online" announcement, USB framing to the glasses ESP32-S3 (later) | high |
| `brain` | THE real-time AI process: button-toggled listening, 2-mic echo + noise cancel, VAD, LFM3-Omni engine (CPU/GPU/NPU split), vision encoder with per-mode cadence and freshness, speech out with barge-in, modes, tool registry, Gemini Live switch/takeover | high |
| `check` | Second-opinion detector (YOLO-World) on the same frames the brain sees; flags objects LFM names but the detector does not see | normal |
| `nav` | Offline Singapore routing (OSM + downloaded LTA static data), route following, indoor/outdoor auto-switch inputs, live LTA arrivals when online | normal |
| `memory` | Automatic object memory (fixed list + user-added items, text only), saved places, SQLite | low |
| `ota` | download/verify/stage/commit/rollback agent | normal |
| `tui` | Dev terminal UI over SSH (Textual, Asirive brand) + session recording. DEV BUILDS ONLY; user builds are headless | low |

Voice, perception and agent are deliberately ONE process (`brain`) so the
sub-1-second path (question end -> first audio) has no process hand-offs
(design doc 6.1, approach B). Everything else talks through the generated
contracts (protobuf) over local sockets; frames reach `check` through shared
memory. No shared mutable state, no importing across services, no service
imports `v3_core`.

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
7. Scope: head-level and silent obstacles only. Never ground hazards (the
   cane) and never things the user can hear (cars). Output is VIBRATION ONLY
   (learned patterns), never tone or speech.
8. Anti-spam is a requirement, not a tuning detail: warn once per obstacle as
   it enters the danger zone, no repeats for the same obstacle, cooldown,
   ground rows ignored. V3 safety was switched off because it spammed.
9. Safety keeps running when the user turns the camera off.

## 3a. Brain rules (from the approved design)

- Listening starts/stops on a button TAP (toggle, haptic tick). No wake word
  in alpha.
- English and Singapore English only in alpha; never answer a non-English
  detection; ignore low-confidence audio; no acting on speech heard while
  Cortex is talking unless it is a clear barge-in.
- Answers describe the CURRENT view: encode a fresh frame while the user is
  still speaking; target first audio < 1 s after the question ends.
- Vision cadence: IDLE only while the user speaks, INDOOR_NAV every 1 s,
  OUTDOOR_NAV about every 2 s.
- Unprompted speech ONLY for: next navigation instruction (incl. indoor cues),
  bus coming, arrived. (ToF warnings are vibration, from `safety`.)
- Positions in relative terms ("right in front of you", clock positions),
  never step counts, never colour as the only identifier.
- Gemini Live is OFF by default (cost): on by voice command, or takeover when
  online and `check` disagrees with LFM or the user says "check that".
- Indoor/outdoor switches automatically and silently; "I'm inside/outside"
  overrides.

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
- The `tui` service and session recording (camera, mic, Cortex audio) exist in
  DEV builds only. User builds are headless and can never record images or
  video (privacy law).

## 5. Updates

OTA client downloads signed artifacts via the app/gateway chain, verifies
signatures, stages to the inactive slot (A/B), health-checks after reboot, and
rolls back automatically on failed boot or failed safety self-test. An update
must never leave the device without a working safety service.

## 6. Quality gates (what "safe and capable" means in CI)

- Type checking (mypy strict) on all services; generated contract types only
  across process boundaries.
- Replay tests: recorded sessions (ToF + frames + audio) replayed through
  `safety` and `brain` with expected outputs (including "no repeat warning"
  cases for anti-spam).
- Latency test for `brain`: question end -> first audio < 1 s on the Q8B.
- Fuzz/property tests on USB framing and contract decoding.
- Latency budget test for `safety` (hazard-in to haptic-out) with a hard
  failure threshold set from Phase 0 measurements.
- Fault-injection tests: kill/stall each service, expect the documented
  degraded behavior.
- Power/thermal soak on the Q8B before any release ring.

## 7. Build order

Already built: contracts, supervisor + units, OTA, link, phone link. Next
(approved 2026-11-24, design doc section 7):
1. LFM3-Omni baseline on stock llama.cpp (CPU, then GPU) + measurement harness;
   prove NPU access from Ubuntu. Numbers table committed to docs/.
2. `tui` skeleton, so every later step is visible.
3. `brain` real-time loop on CPU/GPU (button, audio front-end, LFM, speech out,
   vision freshness, modes, tool registry).
4. The CPU/GPU/NPU split (model block on NPU; encoders/decoder on GPU/CPU).
5. `nav` offline, then live LTA.
6. `memory` (+ app screen for user items), `check` + Gemini switch/takeover.
7. `safety` new, against simulated ToF; real sensor tuning when the glasses
   are wired (ESP32-S3 work starts after the holidays).
8. Infra: server status on the console, "box online" announcement.
Delete `v3_core/` after V4 passes the same bench checks.

## 8. V3: ideas kept, everything else dropped

Kept as IDEAS only (new code): the tool-based agent harness (places ->
directions -> start navigation chain, bus tools, indoor guide, memory search),
modes (IDLE, OUTDOOR_NAV, INDOOR_NAV, BUS_WATCH, TRANSIT, EXPLORE), speaking
rules (short, relative positions, no colour-only identifiers), the dev
terminal UI concept (panels, recording, keys). Not used at all: V3 safety
(`safety_monitor.py`, spammed), V3 memory (`layer4_memory/`, did not work),
spatial audio, Kokoro, GLM, Google Maps, Hailo/RPi5 code, laptop link, the
`system.py` monolith.

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
| Engine bench | `engine/` (`sysinfo.py`) | Building (plan `docs/superpowers/plans/2026-11-24-lfm-baseline-and-tui.md`): system readers (temps, RAM, CPU load, power) done, stdlib only, all paths injectable. |
| Not started | brain (LFM engine, audio front-end, vision, modes, tools), check, nav, memory, tui, new safety tiers, USB framing, mypy gate, replay/latency tests | |

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
- 2026-10-30: `docs/architecture/FIRST-RUN-BOX.md` added: checklist for the first phone-and-box session.
- 2026-11-12: first bring-up on the Q8B (Ubuntu 26.04, Python 3.14.4): 52 tests pass, 6 skip (need Go). Found: the supervisor (user `cortex`) could not restart the other units (polkit denied). Added `deploy/50-cortex.rules` (only user cortex, only `cortex-*` units), installed by `cortex sync units`. Note: the supervisor watchdog is systemd's WatchdogSec via sd_notify, not /dev/watchdog; board-level reset (RuntimeWatchdogSec) is still TODO.
- 2026-11-24: V4 core design approved (`docs/superpowers/specs/2026-11-24-v4-core-design.md`). This file rewritten to match: no V3 code ported (ideas only), process table now `brain` (voice+perception+agent in one real-time process) + `check` + `tui`, new safety scope (head-level/silent, vibration only, anti-spam), brain rules (button toggle, English/Singlish, fresh vision, <1 s, Gemini off by default), new build order starting with the LFM baseline.
- 2026-11-24: `cortex_core/engine/sysinfo.py`: readers for thermal zones, peak RSS, memory used, CPU load and power (power_now or voltage x current; abs() because current_now is negative while discharging). Never raise; missing files mean unknown.
