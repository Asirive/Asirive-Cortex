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

**Status (2026-11-26):** see section 9 for what is real vs stubbed. Python: `python3 -m pytest core`; engine C++: `sh core/scripts/engine/box_build.sh` (85 tests, on the box).

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
   it enters the danger zone ("ahead", then at most one "close"), no repeats
   for the same obstacle, cooldown, anything standing on the ground at cane
   height ignored. V3 safety was switched off because it spammed.
9. Safety keeps running when the user turns the camera off.

## 3a. Brain rules (from the approved design)

- Listening starts/stops on a button TAP (toggle, haptic tick). No wake word
  in alpha. The button only turns automatic listening on and off; the VAD
  decides where each question starts and ends (no push-to-talk).
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
- Gemini Live is OFF by default (cost): on by voice command (not built). Gemini
  takeover (built, 2026-11-26, Haziq's call) happens ONLY when the LM itself is
  not sure (its silent `second_opinion` call) AND the box reaches the gateway;
  offline it says "I'm not sure". No hedge detector, no "check that" trigger.
  Gemini gets VIDEO, not a photo (Haziq): the last few seconds at 1 frame/s, to
  Gemini 3.8 Live Extended Thinking, thinking LOW.
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
| Safety | `safety/` (`config.py`, `perceive.py`, `warn.py`, `engine.py`), `tests/safety_sim.py` | New (no V3 code), built and validated in simulation only (`docs/measurements/2026-11-safety-sim.md`, 100 seeds x 26 scenes): ToF 8x8 + IMU per frame -> tilt -> level-frame points -> head/body band per sector -> grounded test (object's image columns walk down; support at cane height = the cane's, not warned) -> time-to-contact warnings "ahead"/"close" on left/right/both motors, each obstacle once, cooldowns, sector hand-over, 30 s bearing memory. Overhangs 99-100 %, median lead 1.35-1.7 s; sunlight/dark targets late (sensor range); false alarms 2-8 % of wall/pole/person approaches; glass invisible. Degraded (sensor error, no frames, lens covered) vibrates + cue every 5 s. Eye height must be set at fitting (app question not built). Glasses I/O: `safety/glasses.py` (CDC protocol v1, `GlassesSensor`/`GlassesOut`, button pipe to the brain, bring-up CLI `--grid/--imu/--buzz`), entry point uses it (`/dev/cortex-glasses-safety`, udev rule `deploy/udev/`); tested over a pty and against the firmware's own C framing (`tests/test_glasses_link.py`). Zone/IMU mounting maps unverified (identity). NOT built: SCHED_FIFO/mlockall, the audio cue sink (cues are logged); never run on hardware. |
| Supervisor | `supervisor/`, `deploy/` | Built: ordered start, backoff, heartbeat stall detection, watchdog petting only when safety+link healthy, systemd launcher. Units pass `systemd-analyze verify` apart from the venv path. NOT run on a real device or with a real hardware watchdog; the degraded cue is only logged (haptic hardware hook TODO). `link` and `ota` entry points are heartbeat-only stubs. |
| Owner stop | `link/owner_control.py` | Built and fuzzed (500 random frames). Needs the real USB/BLE transport and the real `Controls` (agent/voice/power) behind it. |
| Engine bench | `engine/` (`sysinfo.py`) | Building (plan `docs/superpowers/plans/2026-11-24-lfm-baseline-and-tui.md`): system readers (temps, RAM, CPU load, power) streaming llama-server client, bench runner (warmup, medians/p90, 1 s target flag, JSON + Markdown report, state_dir/bench/latest.json) and NPU probe (fastrpc nodes, cdsp state, QNN libs) built and unit-tested. Baseline run on the Q8B 2026-11-24, see `docs/measurements/2026-11-lfm3-omni-baseline.md` (`scripts/build_llama.sh` builds llama.cpp). Stdlib only. |
| TUI | `tui/` (`python -m cortex_core.tui`, needs `CORTEX_DEV_BUILD=1`) | Skeleton: system, engine baseline, NPU and log panels in Asirive colours, q/? keys. Live mode (`sh /opt/cortex/scripts/engine/live_tui.sh` on the box): the engine in-process with the real camera (`engine/capture.py`, ffmpeg MJPEG to 640x360 RGB, 5 fps) and mic (PipeWire `pw-record`, 16 kHz mono); space = listen button, / = type a question, r = reset, q = quit; shows the conversation, level meter, view age and per-answer timings. `--nav` hosts the agent harness (Brain over the newest bundle in `/var/lib/cortex/nav/bundles`, GPS from `/run/cortex/gps.sock`): typed and spoken turns go through tool dispatch, the camera follows the mode's cadence, and a MODE · TRIP · TOOLS panel shows mode, state line, GPS, last cue and tool calls. llama.cpp/QNN output goes to `bench/engine/live_native.log`, not the screen. Textual is in `requirements-dev.txt` only; installed in the box venv. |
| NPU vision | `npu/` (`run_npu.py`, `split_encoder.py`, `qnn.py`, `split.py`, `decompose.py`), `tools/cortex-npu/`, `scripts/npu/` | Built and measured on the box: vision encoder split into 7 NPU segments (QNN HTP v68, w8a16) + 6 CPU attention islands, run in-process by `libcortex_npu.so`; 255 ms/frame, 12/12 answers match CPU (`docs/measurements/2026-11-npu-vision.md`). Context binaries, calibration and test photos live on the box only. Not wired into a brain yet; calibrated on the ZV-1F, not the product camera. |
| Engine core | `tools/cortex-engine/` (`libcortex_engine.so`, C API `include/cortex_engine.h`, CLI `cortex-engine`), `engine/native.py`, `engine/native_bench.py`, `scripts/engine/` | Built and measured on the box (`docs/measurements/2026-11-engine-core.md`): NPU vision encoder + LFM3-Omni Q4_0 in one native runtime; the latest frame is read into the LM in the background, an ask only reads the question. TTFT 115 ms median, 12/12 with a fresh conversation per case (11/12 with one running conversation: earlier turns bias the answer); refresh 1.42 s; never on cpu0. C++ tests (`sh core/scripts/engine/box_build.sh`). Hands-free voice in (`docs/measurements/2026-11-voice-in.md`): button-toggled listening, Silero VAD v4 in C++, audio encoded on cpu1-3 while the user talks; VAD end of speech → first token 108–306 ms; barge-in cancels the answer. Speech out (`docs/measurements/2026-11-speech-out.md`): every answer spoken in the model's own voice on the headphone jack while it is made (codec thread on cpu3, speaker thread, UCM route applied at open), mic muted while Cortex talks, the button cuts it; spoken question → first sound 600–641 ms; 12/12 spoken, gapless 8/12 (the LM makes audio 9–26 % slower than real time with a view in context). Tool calls (`tool_call` event, `ce_tool_result`, `ce_say`, `ce_set_state`; registry `contracts/tools/tools.json`, loader/parser `brain/tools.py`). Limits: `n_ctx` 8192, `max_tokens` 2048, `max_speech_s` 180. 85 C++ tests. |
| Nav | `nav/` (`bundle.py`, `geo.py`, `places.py`, `walk.py`, `transit.py`, `follower.py`, `service.py`, `build.py`) | Built, unit-tested on a synthetic city (`tests/nav_city.py`) and run on the real Singapore bundle on the server (`docs/measurements/2026-11-nav-bundle.md`: 52 MB, routes 40–115 ms, search 9–37 ms); whole trips simulated end to end through the Brain (`tests/test_nav_e2e.py` + `tests/nav_sim.py`: walk, wait, ride, walk, jitter, weak GPS, detour; on the real bundle when present); NOT yet run on the box. Bundle: versioned `.npy` arrays memory-mapped at load + manifest with SHA-256 per file, never overwritten. Places: trigram index, SG aliases (amk, ktph, blk...), postal codes, kind bonus (stations/malls over shop units and bus stops), distance ranking; names warmed on a thread at start. A place has several ways in (`pacc_*`: an area's outline + mapped entrances) and routes end at the quickest. Walking: A* to one node or several (stairs 3x, crossings +10/+25 m, road 1.3x), turn/crossing/steps instructions; `nearest_many` vectorised snapping for the builder. Transit: frequency-based RAPTOR (wait = headway/2 per LTA band), Pareto by rides, fewest rides within +5 min, short trips walk. Follower: off-route after 3 fixes beyond max(25 m, 1.5x accuracy), back after 2; before boarding, 100 m from the stop at a walk for 3 fixes is off route (one fast fix = boarded); prewarn 40 m; at-stop, boarded, next stop, alight next/now, arrived. Service: the nav tools, saved places from `/var/lib/cortex/nav/saved_places.json` (box only), live arrivals via an injected provider with headway fallback (`link/provision.arrivals_client`: the gateway's `/device/bus-arrivals` over the box's mTLS identity; the live TUI wires it when `--identity-dir` holds a claimed identity), reroute on off-route. |
| Brain | `brain/brain.py`, `brain/modes.py`, `brain/tools.py`, `brain/prompt.py`, `brain/tool_eval.py` (+ `data/tool_eval.json`) | Built and tested against a scripted engine (`tests/test_brain.py`); NOT yet run with the real LM. Dispatch: parse -> validate -> mode gate -> run on a thread ("Checking." after 0.7 s); template tools speak a fixed sentence, LM tools go back to the model (chain <= 4); one malformed call gets an error to retry, a second ends with "Sorry, I couldn't do that."; typed and spoken (voice queue) calls. Modes: code owns them (`ModeMachine.force` from the trip, `request` from the LM's `set_mode`), EXPLORE remembers where the trip is; `vision_s` per mode (None = view only when the user talks). Nav cues wait for the turn; get-off-now / off-route cut it. `set_state` only when the line changes. M0 tool-call eval written; box run pending (the box hard-shuts down under sustained load, see change log). Stand-in run on the server (`run --llama-server URL`, LFM3-1.7B on CPU, `docs/measurements/2026-11-tool-eval.md`): tool 95 %, args 94 %, 2 chit-chat calls (`set_mode IDLE`) -> FAIL on chit-chat only. |
| GPS | `link/gps.py`, `link/phone_link.py` (`location` op), `link/__main__.py` | Built and tested (`tests/test_gps.py`). The app sends `location` as a signed phone-link op; `parse_fix` validates it; the link forwards it as a unix datagram to `/run/cortex/gps.sock` (dropped when nobody listens, never blocks) and, on dev builds only (`CORTEX_DEV_BUILD=1`), appends it to `/var/lib/cortex/nav/recordings/gps-YYYYMMDD.jsonl` (never leaves the box). `GpsListener` feeds the brain; `replay()` plays a recording back. App side: `apps/mobile/lib/location_stream.dart` (`fixArgs` matches `parse_fix`: t in seconds, unknown speed/course left out; `LocationStreamer` sends the newest fix at most once a second on one signed connection, reconnects every 3 s; started by the Shell on the owner's phone over a real `BoxLink`), tested against a fake box (`apps/mobile/test/location_stream_test.dart`) and against the real Python phone link, forwarder and listener (`tests/test_phone_gps_cross.py` runs `apps/mobile/test/real_box_location_test.dart` through `flutter test`; skipped without Flutter); NOT yet run on a phone. |
| Glasses firmware | `../firmware/glasses/` (ESP-IDF, TinyUSB composite UVC+UAC2+CDC) | Written, NOT built with ESP-IDF, never on hardware. Portable parts (framing, haptic player, heartbeat fail-safe, button, USB descriptors) host-compiled and tested (`tests/test_glasses_firmware.py`). Spec `docs/architecture/GLASSES-USB.md`. No MCU OTA transport, no OV5640 autofocus. |
| Memory | `memory/` (`items.py`, `look.py`, `store.py`, `memory.py`), brain `on_view` + `search_memory`, nav `where()`, phone-link op `memory` | Built and tested on the server against a scripted engine (`tests/test_memory.py`, `tests/test_memory_brain.py`). Spec `docs/superpowers/specs/2026-11-26-memory-design.md`. Built-in items (keys, wallet, phone, glasses, bag, cane) + the user's own (app op `memory`: list/add/remove/forget); text only, never images. Scans only views the engine already has, only while the brain is idle (no turn, not talking, no cue), >= 30 s apart, <= 10 per 10 min (box load budget, to be measured); cut by typing, speech start or an urgent cue (a cut scan stores nothing). A sighting: item, looks, spot (scene words), named place (saved place, else nearest named place <= 75 m), time; GPS cleared after 30 days; same item and place within 10 min merges; 20 kept per item. Recall `search_memory` (LM-phrased): spot, place, ago, looks, the previous different place. Library in the brain process plus the link (one SQLite file in WAL mode), not its own process. NOT built: engine `ce_peek` (C++, needs the box; until then `Engine.can_peek` is False and memory only recalls), the app screen, a scan accuracy eval with real photos. The scan prompt has never seen the real LM. |
| Gemini takeover | `brain/takeover.py`, tool `second_opinion`, `link/provision.second_opinion_client`, `engine/capture.jpeg`/`FrameRing`/`fresh_clip`, TUI `gateway_takeover`; gateway `internal/gemini` + `POST /device/second-opinion` | Built and tested on the server (`tests/test_takeover.py`; box -> real Go gateway -> stand-in Gemini Live in `tests/test_gateway_session.py`). 2026-11-26 switched to video: `Camera.ring` keeps 1 frame/s (newest 4, RAM only); the clip holds only frames taken since the camera was last turned on (`Brain.camera_since`) and newest <= 2 s old; the gateway opens a Gemini Live session (gemini-3.8-live-extended-thinking, LOW, AUDIO + output transcription) and returns the transcribed answer. Real run on the server (real keys, synthetic frames): 7-8 s with 4 frames, ~3 s without; bus number, motion and pole side right in 2/2. Spec `docs/superpowers/specs/2026-11-26-gemini-takeover-design.md`. The LM calls `second_opinion(question)` instead of guessing (silent, so nothing wrong is said first); the brain sends the newest frame (camera on and frame <= 2 s old only; else no image) and the question over mTLS; the gateway asks Gemini with the server's key (never on the box), caps 6/min and 100/day per device, logs neither; Gemini's answer (<= 2 sentences, Cortex's speaking rules in its system prompt) is spoken as a template and kept in the conversation. Unreachable gateway (3 s connect cap) -> "I'm not sure, and I can't check online right now."; refused / Gemini down -> "...couldn't check that just now." NOT measured: how often the real LM calls it when it should (no eval cases yet), latency on the box, real camera frames. Streamed (2026-11-26): sentences Gemini has finished are spoken as they arrive (`Brain._run_tool` speaks a tool's early sentences from the turn thread; `Takeover.run(say=)`; box client reads NDJSON), the rest is the template; real API: first sentence at 3.4-3.9 s vs 6.3-7.4 s for the whole answer; cut mid-answer -> "Sorry, I lost the rest of that answer." |
| Headless brain | `brain/headless.py`, `python -m cortex_core.brain`, `deploy/cortex-brain.service`; link op `button` (`link/__main__.button_sink`); app `DeviceLink.talk()` | Built and tested on the server only (`tests/test_headless.py`, `tests/test_phone_link.py`); NEVER run on the box. The live session without the TUI, started by systemd at boot with nobody logged in: says "Cortex ready." once it can listen, speaks problems (no mic / camera / map) instead of printing them, reads presses from `/run/cortex/button.fifo` (glasses via safety, the app's talk button via the link's signed `button` op; tap = listen on/off or cut, long = not assigned, ignored), honours the app's `assistant.paused` (stops listening, ignores the button, says so) and `mic.muted` (drops the mic), READY=1 after start and WATCHDOG=1 only while the voice/vision/button threads live. Mic: `capture.find_mic` now uses PipeWire only when its socket exists (`pipewire_running`), else ALSA direct, because a boot service has no PipeWire. NOT built: the app's on-screen talk button (no Flutter SDK on the server), a voice for long press. The unit sources `bench/engine/qnn.env` (a dev path) and needs the `cortex` user to reach the NPU, camera and sound devices: unverified. |
| Not started | check, Gemini Live voice switch, mypy gate | |

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
- 2026-11-24: `cortex_core/engine/llama_client.py`: streaming client for llama-server's /v1/chat/completions (image + audio input parts, optional audio output), measures time to first token and first audio, never raises (HTTP errors and connection failures become a failed RunResult).
- 2026-11-24: `cortex_core/engine/bench.py` (+ `cases.example.json`) and `npu_probe.py`: baseline runner and NPU reachability probe, CLIs `python -m cortex_core.engine.bench` / `python -m cortex_core.engine.npu_probe`. Bench media (photos, voice WAVs) stay on the box, never in git.
- 2026-11-24: `cortex_core/tui/` dev terminal UI skeleton + `requirements-dev.txt` (Textual 8.2.8). Refuses to start without CORTEX_DEV_BUILD=1; reads state_dir/bench/latest.json and npu.json plus live /proc and /sys numbers.
- 2026-11-24: Baseline review fixes. llama_client sends `cache_prompt: false`, records prompt/cached token counts, and treats mid-stream errors and empty output as failures. bench samples temperature/power while the case runs, judges speaking cases on first audio only, and rewrites the report after every case (Ctrl+C keeps finished cases, marked partial). The TUI tolerates odd JSON, its engine panel spans the full width at 80x24, and its tests skip when Textual is not installed.
- 2026-11-24: LFM3-Omni baseline on the Q8B (llama.cpp b12679, CPU + Vulkan GPU) and NPU probe, results in `docs/measurements/2026-11-lfm3-omni-baseline.md`. `scripts/build_llama.sh` added (OpenCL only if a platform exists, else Vulkan). `sysinfo.read_power_w` now skips offline and zero-reading supplies (the Q8B's idle USB-C ports read 0 V, which printed a false "0.00 W").
- 2026-11-24: Vision encoder on the Hexagon NPU (`cortex_core/npu/`, `tools/cortex-npu/`): ONNX contrib ops decomposed, graph split into NPU segments + CPU attention islands (v68 cannot do 16-bit activation x activation MatMul), QAIRT 2.42 w8a16 context binaries, in-process QNN runner. 255 ms/frame vs 1190 ms CPU, 12/12 answers match. `python -m cortex_core.npu.run_npu` reruns the cases.
- 2026-11-24: Engine core (`tools/cortex-engine/`): C++ runtime with four LM memory slots (history, view, next view, conversation), background view read preempted by an ask, scene skip (feature cosine ≥ 0.98), big-core gate (ask > island > background read), one NPU open per process (`Vision::shared`). C API + ctypes binding `cortex_core/engine/native.py`; `python -m cortex_core.engine.native_bench` reruns the 12 cases. TTFT 1.23 s → 115 ms.
- 2026-11-24: Engine voice in: `ce_set_listening` (the button) + `ce_push_audio` (16 kHz mic), Silero VAD v4 ported to C++ (`src/vad.cpp`, weights on the box only), LFM3 audio stream encoded on an audio thread (cpu1-3) and decoded into the conversation slot while the user talks; speech_start / speech_end events, voice-marked token and done events (`wait_ms`, `end_to_first_ms`). Text-only sampling (bans `<|audio_start|>`/`<|mixed_start|>`). Python: `Engine.set_listening`, `push_audio`, `next_voice`. CLI: `cortex-engine --config C.json --wav F.wav [--frames DIR]`.
- 2026-11-24: Live dev TUI (`tui/live*.py`, `engine/capture.py`, `scripts/engine/live_tui.sh`). Camera and mic run as ffmpeg / pw-record child processes on cpu1-3. The ZV-1F mic is held open by PipeWire, so ALSA direct is busy: `find_mic` prefers PipeWire. Checked on the box: room speech answered in 191 ms end-to-first, view refresh 1.43 s, think tags hidden while they stream. Speech out not built yet (step 4).
- 2026-11-24: Engine speech out: `src/speaker.cpp` (ring + paced writer; ALSA by dlopen, `null` and `wav:` sinks, adaptive prebuffer), `src/speech.cpp` (the llama.cpp lfm3a MIXED loop: text + depthformer audio frames, golden-identical), `CodecThread` (codes → 24 kHz PCM on its own mtmd context on cpu3), islands on a small-core pool during an answer (`island_small_cpus`). Engine: `speak` on by default, sound_start / sound_end events, mic muted from the answer's start to `mute_tail_ms` after its sound, `ce_cancel` cuts the sound, a bad speaker falls back to text. TUI: space cuts Cortex off while it talks, LAST ANSWER shows first sound, gaps, LM / codec ms per frame. `native_bench` records frames, gaps and codec ms.
- 2026-11-25: Engine (`bb49178`, `d2af51f`): codec output tied to its answer; no echo questions, full-length answers, no stutter. 73 C++ tests.
- 2026-11-26: Agent harness step 1 (`docs/superpowers/specs/2026-11-26-agent-harness-and-nav-design.md`). Engine tool calls: config `tools` / `tool_bias` / `tts_language`; every answer opens with `<think></think>` (LFM3 wrote it into answers otherwise); a first-token `<tool_call>` makes the answer a silent call (`tool_call` event, done `stop:"tool"`, status `awaiting_tool`); `ce_tool_result` (LM answers or a fixed `say` is spoken), `ce_say` (TTS on slots 4/5, audio-only speech loop), `ce_set_state`; done carries `kind`. S's limit excludes the TTS head's cells. Python: `Engine.tool_result`, `say`, `set_state`; stale refusal errors are drained before each call. Registry `contracts/tools/tools.json` (11 M1 tools, modes, spoken_by) + `cortex_core/brain/tools.py` (LFM lines, Gemini declarations, XML call parser, argument validation; finds the registry in the repo or `/opt/cortex/contracts`). 82 C++ tests.
- 2026-11-26: Engine limits broadened: config `n_ctx` (default 8192), `max_tokens` 2048, `max_history_tokens` 1536, `max_speech_s` 180 (cap 600); bad values refused; status reports them. +86 MB RSS, TTFT unchanged. 85 C++ tests.
- 2026-11-26: `cortex_core/nav/` (bundle format, geo, places, walking A*, frequency RAPTOR, follower, tool service, assembler shared by the server builder and tests) and `brain/prompt.py`, `brain/tool_eval.py` (M0 eval). Tests: `test_nav_*`, `test_brain_tool_eval.py` on the synthetic city `tests/nav_city.py`.
- 2026-11-26: Agent harness step 2. `brain/brain.py` (dispatcher, chains, malformed retry, Checking., cues, state line) and `brain/modes.py` (mode machine, vision cadence); `link/gps.py` + phone-link `location` op + link forwarding/dev recording; live TUI `--nav` hosts the brain (TRIP panel, GPS listener, mode-paced vision). Nav on real Singapore data: station detection (nodes, areas, named stop positions joined by name, network tags, monorail LRTs, names cleaned of line codes) gives all 11 MRT/LRT lines; places from osmium areas (multipolygons like VivoCity); unit-number addresses dropped; places reached by several nodes (`pacc_off`/`pacc_node`, new bundle arrays) with multi-target A*; kind bonus in search; plural-correct summaries. Builder tested on a pyosmium-written OSM file (`tests/test_navbundle_build.py`). 293 Python tests.
- 2026-11-26: End-to-end trip tests, 308 Python tests (`tests/nav_sim.py` GPS simulator, `tests/test_nav_e2e.py`: Brain + scripted LM tool calls + simulated fixes to "You have arrived", synthetic city and real Singapore bundle); follower: walking away from the boarding stop is off route (reroutes). Server: `infra/navbundle/lta_fetch.py`.
- 2026-11-26: `tool_eval run --llama-server URL --model NAME` (typed cases against any llama.cpp server; a stand-in, not the gate). `bus_arrivals` wording in `contracts/tools/tools.json` makes the model pass the bus number (args 86 -> 94 % on LFM3-1.7B). Dev machine now runs the whole suite with 0 skipped (textual, pillow, onnx, onnxruntime, Go): 363 Python tests.
- 2026-11-26: Live bus arrivals end to end: `link/provision.arrivals_client` (mTLS GET to the gateway, `ArrivalsError` -> headway fallback), TUI `--identity-dir`; tested against the real Go gateway and a stand-in DataMall (`tests/test_gateway_session.py`). 365 Python tests.
- 2026-11-26: App GPS stream: `apps/mobile/lib/location_stream.dart` sends the phone's fixes as signed `location` ops (wire format checked against `parse_fix`); 7 Flutter tests, 70 app tests total. Not run on a phone yet.
- 2026-11-26: Brain: `set_mode IDLE` while IDLE is a no-op; when the LM has said nothing yet it answers the user itself instead of a bare "Okay." (small LMs call it on small talk); already answered or repeated: the template, so no double answer and no loop. 4 tests in `tests/test_brain.py`; 369 Python tests.
- 2026-11-26: Cross-language GPS test: the app's Dart `LocationStreamer` against the real `PhoneLink.serve` -> `GpsForwarder` -> `GpsListener` (phone -1 and NaN speed/course dropped, t in seconds). 370 Python tests.
- 2026-11-26: Safety rebuilt from scratch (V3 safety not used): grounded test + time-to-contact warner + bearing memory, designed against an independent simulator (`tests/safety_sim.py`; sensor sub-rays, walker gait, IMU bias, latency). Results and limits in `docs/measurements/2026-11-safety-sim.md`. Unit tests rewritten (`tests/test_safety.py`), sim gate `tests/test_safety_sim.py`. Config keys changed (versioned, `version: 1`); eye height comes from fitting. Hardware I/O still stubbed.
- 2026-11-26: Glasses link: ESP32-S3 firmware (`firmware/glasses/`: composite UVC MJPEG 640x480 + UAC2 16 kHz stereo mic / mono speaker + CDC safety channel; VL53L7CX 15 Hz with LSM6DSO FIFO per frame, 2 ERM motors on LEDC, button, heartbeat fail-safe that vibrates "degraded" when the box's beats stop) and the box side (`safety/glasses.py`, entry point on the real port, udev rule, button fifo). Protocol cross-tested Python <-> the firmware's C; descriptors checked byte by byte against TinyUSB headers. Not built with ESP-IDF (toolchain not installed), not run on hardware. 448 Python tests.
- 2026-11-26: Gemini takeover: tool `second_opinion` (spoken_by template), `brain/takeover.py`, brain `takeover=`, system prompt tells the LM to call it instead of guessing (and to use tools for lost things), box client `provision.second_opinion_client` (offline vs refused told apart), `capture.jpeg` (Pillow, else ffmpeg) + `fresh_jpeg` + `Camera.latest_age`, TUI wiring from `--identity-dir`. Gateway side in infra. 502 Python tests.
- 2026-11-26: Memory (`cortex_core/memory/`): built-in + user items, scan prompt and a strict parser (list items only, hedges and repeats dropped), SQLite store (merge, keep 20, GPS cleared after 30 days, WAL shared with the link), scan policy (idle only, 30 s gap, 10 per 10 min), recall tool `search_memory` (registry + 3 eval cases). Brain: `memory=`, `on_view`, scans hold the turn lock and are cut by a typed ask (`_take_turn`), speech start or an urgent cue; cues wait for a scan. Engine binding `Engine.peek`/`can_peek` (C `ce_peek` not written: box). Nav `where()`. Phone-link op `memory`. Live TUI `--memory-db`. Not run on the box or with the real LM. 488 Python tests.
- 2026-11-26: Gemini takeover sends video: `capture.FrameRing` (1 frame/s, newest 4, RAM only, gaps cut the clip), `Camera.ring`, `fresh_clip(cam, since)` replaces `fresh_jpeg`; `Takeover(ask, clip=)` with `run(question, camera_on, since)`; `Brain.camera_since` so frames from while the camera was off are never sent; box client posts `frames_jpeg`, 30 s answer cap. Gateway: Gemini Live.
- 2026-11-26: Headless brain service (`brain/headless.py`, `cortex-brain.service`): boots to "Cortex ready." with no screen or SSH; button pipe shared by the glasses and the app (`button` phone-link op, app `talk()`); app pause/mute flags; spoken problems; watchdog. `capture.pipewire_running` so a boot service uses ALSA. 513 Python tests.
- 2026-11-26: Gemini answers stream: `Takeover.run(..., say=)` returns only the unsaid rest as the template, `takeover.LOST` on a mid-answer drop; `Brain._run_tool` passes `early` to tools and speaks queued sentences from the turn thread (engine calls stay on one thread); `second_opinion_client` asks for NDJSON and falls back to a plain JSON gateway. 525 Python tests.
