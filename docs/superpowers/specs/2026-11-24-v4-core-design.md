# V4 Core: design

**Date:** 2026-11-24. **Status:** approved by Haziq, 2026-11-24. **Owner:** Haziq (IRSPlays).
**Covers:** `core/` (the software on the Dragon Q8B), the dev terminal UI, and the small infra additions this needs.
**Replaces the plan parts of:** `core/AGENTS.md` sections 7–8 and `docs/architecture/CORTEX-ENGINE.md` phases (both get rewritten from this doc once approved).

---

## 1. What this is and why

Asirive Cortex V4 alpha is a **navigation device for blind and low-vision people, used together with the white cane, not instead of it**. The person wears glasses (camera, ToF sensor, two mics, open-ear speaker, haptic, ESP32-S3 bridge) wired by USB-C to a pocket box (Radxa Dragon Q8B). The phone app sets it up and gives it GPS and, when available, internet.

Alpha's job is **proof of concept on the chip family the final product will use**: show that the new software, safety, infrastructure and ecosystem run properly on Qualcomm silicon, to win Young Innovators Award 2027 funding for the final custom board. There is no fixed date.

Why a new core instead of V3:
- V3 carried dependencies that were disabled, and a monolith (`v3_core/system.py`, 8,400 lines).
- V3 safety was disabled in the final system because it spammed.
- V3 memory did not work.
- Gemini Live (V3's brain) is expensive, and answers from a stale view: an object removed while the question is being asked is still reported as there.
- Gemini Live transcription hallucinated in loud halls and during presentations, including deciding the speaker used another language.

The **ideas** from V3 that worked are kept: a tool-based agent harness (the brain calls tools such as search places → get directions → start navigation) and **modes** that change how proactive the brain is. **No V3 code is copied or imported.** Existing V4 code (supervisor, OTA, link, phone link, contracts) is new code and stays.

## 2. Goals

1. **Local brain first.** LFM3-Omni-2B on the box is the main brain, online or offline.
2. **Answers start in under 1 second** from the end of the user's question, and describe what is in front of the user **now**.
3. **Efficient compute split.** End goal: model block on the NPU (lowest power), encoders/decoder on GPU/CPU, running in parallel.
4. **Strong speech understanding in noise.** English and Singapore English for alpha.
5. **Full navigation offline:** Singapore walking, bus and MRT routing on the box, indoor guidance from the camera.
6. **Automatic object memory** with real detail.
7. **Head-level and silent-obstacle warnings** from the ToF sensor that people trust and that never spam.
8. **A branded dev terminal UI** showing every function, for development and for judges.
9. **Battery:** half a day to a full day of use.

## 3. Non-goals (alpha)

- Mandarin, Malay, Tamil (later; may involve fine-tuning the audio encoder).
- Replacing the cane, or ground-level hazard detection (the cane does that).
- Step counts or distances in steps ("escalator right in front of you", never "5 steps").
- Google Maps (offline maps cover routing; only LTA DataMall is used online).
- Cloud hosting (home server is fine for alpha; final moves to a secure cloud instance).
- The custom SBC and miniaturisation (final version).

## 4. Anti-goals (would be failure even if it "works")

- Warnings that repeat or fire on things the cane already handles (V3's spam).
- Describing a scene that is no longer there.
- Inventing speech the user did not say, or switching language on its own.
- Talking when not needed: outside the allowed cases (section 6.6) silence is correct.
- Storing images or video in user builds.
- Safety depending on, or being slowed by, the brain.

## 5. Constraints

- **Hardware now:** bare Dragon Q8B (Ubuntu 26.04, Python 3.14). Test input: a mic in the jack, or a Sony camera over USB as camera + mic. Glasses hardware is bought but not wired; the ESP32-S3 work starts after the holidays with a teammate.
- **Glasses hardware (per V4-ECOSYSTEM.md):** VL53L7CX 8×8 ToF on the nose bridge, OV5640 camera, 2 mics (one at the mouth, one at the side for ambient), MAX98357A amp + open-ear speakers, haptic, ESP32-S3 bridge sending camera, ToF, mic and speaker audio over one USB-C.
- **Privacy (existing law):** images and video never stored in user builds. Location 30 days. Memory stores text only.
- **Language:** Python (C only for measured hot paths), as already decided in `core/AGENTS.md`.
- **Existing V4 code stays:** supervisor, OTA (verify, A/B slots, agent), link (gateway mTLS session, provisioning), phone link (USB tether), contracts.
- **Gemini cost:** Gemini Live is used only by command or on takeover, never by default.

## 6. The design

### 6.1 Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | Every part its own process (voice, vision, brain, nav, memory, safety), talking over local messages | Best crash isolation; every frame and audio chunk crosses processes, adding delay and copies on the sub-1-second path | Not picked |
| **B** | **One real-time brain process (audio front-end, listening, LFM engine, vision encoder, speech out); everything else separate** | No hand-offs on the hot path; safety/link/nav/memory still isolated. A brain crash restarts voice and vision together (safety unaffected) | **Picked by Haziq, 2026-11-24** |
| C | One big program (V3 style) | What V3 was; rejected | Rejected |

### 6.2 Processes

| Process | Job | Notes |
|---|---|---|
| `supervisor` | Start, watch, restart, watchdog | Exists |
| `safety` | ToF head-level / silent obstacle warnings, haptic + alert sound | Rebuilt new (6.7). Never waits on anything else |
| `link` | Gateway mTLS session, phone link, USB to the ESP32 (later) | Exists; gains the glasses USB framing later and the "online" announcement (6.11) |
| **`brain`** | Mic → echo/noise cancel → listening → LFM → speech out; vision encoder; modes; tool calls; Gemini switch | New. The only real-time AI process |
| `check` | Second-opinion object detector (YOLO-World) on the same frames the brain sees | New. Feeds the hallucination check (6.5) |
| `nav` | Offline routing, route following, LTA live data when online | New |
| `memory` | Automatic object memory, saved places | New |
| `ota` | Updates | Exists |
| `tui` | Dev terminal UI, recording | New. Dev builds only; user builds are headless |

Processes talk through generated contracts (protobuf) over local sockets. Frames go from `brain` to `check` through shared memory, not copies (builder picks the mechanism).

### 6.3 The brain's real-time loop

- **Starting to listen:** tap the glasses button once → haptic tick → automatic listening (VAD) is on; tap again → off. No wake word for alpha (this replaces "Hey Cortex" in V4-ECOSYSTEM.md).
- **Audio front-end:** two mic channels arrive raw (mouth mic + ambient mic); the box does echo cancellation (open-ear speaker is next to the mics) and noise cancellation using the ambient mic as the noise reference. Done on the box, not the ESP32, so it can be tuned without reflashing.
- **Understanding speech:** LFM3-Omni hears audio directly. Language locked to English (Singapore English included). Anti-hallucination rules (builder designs): ignore audio under a confidence/energy floor, never answer non-English detections, never act on speech that arrived while Cortex itself was speaking unless it is a clear barge-in.
- **Vision freshness:** when the user starts speaking, the vision encoder encodes a new frame **in parallel** while they are still talking, so the answer is about the current view. The frame used must be newer than the end of the question minus a small window (builder sets it from measurements; target ≤ 300 ms).
- **Vision cadence by mode:** IDLE: only while the user speaks. INDOOR_NAV: every 1 s. OUTDOOR_NAV: about every 2 s. Others: builder sets, same principle (power vs need).
- **Speaking:** LFM3-Omni speech output if its quality passes the baseline; otherwise a local TTS. User can talk over it (barge-in) and it stops.
- **Target:** first audio < 1 s after the question ends.

### 6.4 Modes and tools

Modes from V3, rebuilt: **IDLE** (quiet; answers when asked), **OUTDOOR_NAV**, **INDOOR_NAV**, **BUS_WATCH**, **TRANSIT**, **EXPLORE** (describe everything until told to stop). Each mode sets: how proactive the brain is, vision cadence, which tools are offered.

Tools (one registry in `contracts/`, shared by LFM and Gemini): places search, directions (walking / transit), start / stop navigation, navigation state, GPS accuracy, bus arrivals, nearby bus stops, services at a stop, indoor guide, memory search, camera off / on, switch to Gemini, mode change. Builder finalises names and schemas.

Speaking rules carried over as ideas: max two sentences unprompted, relative positions ("right in front of you", "on your left", clock positions), never colour as the only identifier when describing, safety > navigation > information.

### 6.5 Gemini Live

- **Off by default** (cost). Turned on by voice command ("use Gemini" / "switch to Gemini") or by takeover.
- **Takeover**, only when the box has internet:
  1. **Second opinion:** if LFM names an object that `check` does not see in the same frame, the box does not trust LFM's answer: it asks Gemini (online) or says it is not sure (offline).
  2. **"Check that":** the user asks; the same fresh frame and question go to Gemini.
- Known gap: this catches "seeing things that aren't there", not wrong reasoning. Measured during testing.

### 6.6 When Cortex speaks without being asked

Only: the next navigation instruction (including indoor cues like "escalator right in front of you, go up"), a ToF warning, "your bus is coming", "you've arrived". Nothing else interrupts silence.

### 6.7 Safety (new, not V3)

- **Purpose:** trust. Warn about what the cane cannot catch: **head-level obstacles** and **silent obstacles** in the path. Not ground hazards (cane), not noisy things like cars (heard).
- **Input:** VL53L7CX 8×8 ToF only. No model, no network, no phone.
- **Output: vibration only** (decided 2026-11-24). No tone, no speech, so it never clashes with navigation speech. Distinct patterns (builder designs; at least "head-level" vs "obstacle ahead") that the person learns.
- **Anti-spam by design:** warn once per obstacle as it enters the danger zone; no repeat for the same obstacle; cooldown; ignore the ground rows; thresholds in versioned config with safe defaults.
- **Camera off:** safety keeps running.
- **Tuning:** thresholds are set by testing with the live ToF grid in the TUI once the sensor is wired. Until then, built and tested against recorded / simulated ToF frames.
- Keeps the existing isolation rules (own process, own cores, never blocked).

### 6.8 Navigation

- **Offline maps of Singapore:** OpenStreetMap for streets, footpaths and MRT; LTA DataMall static data (bus stops, routes, services) downloaded to the box whenever online; routing works on the last download when offline.
- **Online extra:** LTA DataMall live bus arrivals.
- **GPS:** from the phone app over the link (the box has no GPS). With the camera off, navigation continues on GPS alone.
- **Indoor / outdoor switching: automatic, user can override** (decided 2026-11-24). Cortex switches on its own from signals such as GPS accuracy dropping and the camera seeing a ceiling or walls (builder picks the signals and thresholds); saying "I'm inside" / "I'm outside" overrides a wrong guess. Switching is silent (no announcement).
- **Indoor:** camera-only guidance by the brain (escalators, signs, doors, gates), relative terms, no step counts.

### 6.9 Memory (new design)

- **Automatic:** uses frames the vision encoder already processes (never turns the camera on for memory). So in IDLE it only learns while the user is talking to it.
- **Which objects: a fixed list plus the user's own** (decided 2026-11-24). Built-in: keys, wallet, phone, glasses, bag, cane. The user adds their own items from the app. Nothing outside the list is remembered.
- **What it stores:** text records per object: name, details (colour, shape, distinguishing marks), where last seen, when. Plus saved places. Never images.
- **Recall:** "where are my keys?" → last seen place and time, plus details.
- Store: SQLite on the box; optional sync to the cloud later.

### 6.10 Dev terminal UI

- Runs on the Q8B over SSH. **Dev builds only**; user builds are headless.
- New code, V3's idea: Textual, Asirive brand (near-black ground, #EAFF00 accent, brand fonts where the terminal allows).
- Shows every function: camera with what was recognised, ToF grid, mic level and live transcript, brain responses, tool calls as they happen, mode, latency numbers (time to first audio, tokens/s), CPU/GPU/NPU load, RAM, temperature, battery, link/internet state, safety state, memory events, logs.
- Keys kept from V3's idea: record, ask (type a question), mute, pause, save/copy logs, help, panel focus, force a safety test.
- **Recording:** camera, mic and Cortex audio to a session folder on the box. Dev builds only.

### 6.11 Infra additions

- **Server status on the console** (infra.asirive.com): uptime, playit tunnel up/down, gateway health, connected devices, recent errors.
- **"Box online" announcement:** the box tells the app whether it has internet (through the phone or otherwise). The phone giving internet is useful, not required.

### 6.12 LFM runtime: how we get to the split

1. **Baseline:** stock llama.cpp, CPU then GPU. Measure prefill and decode speed, time to first audio, peak RAM, watts, temperature. Also prove whether the NPU is reachable from the box's Ubuntu (driver / fastrpc / Qualcomm runtime).
2. **Split (end goal):** model block on the NPU, vision and audio encoders and speech decoder on GPU/CPU, running in parallel (vision encodes while the user speaks; decode streams while the next frame encodes). Try llama.cpp's experimental Hexagon NPU support first (one runtime); fall back to Qualcomm's own tools (QNN / Genie) if it cannot run LFM3-Omni.
3. **Custom kernels only if** the split misses the 1 s or battery targets.

Every step ends with a numbers table committed to `docs/`.

## 7. Build order

1. LFM baseline + measurement harness (recorded audio/images, then the Sony camera / jack mic).
2. TUI skeleton early, so every later step is visible.
3. `brain` real-time loop on CPU/GPU: button, listening, audio front-end, LFM, speech out, vision freshness, modes, tool registry.
4. The CPU/GPU/NPU split.
5. `nav` offline (maps, LTA download, routing), then live LTA.
6. `memory` (plus an app screen to add the user's own items, sent to the box over the phone link), `check` + Gemini switch/takeover.
7. `safety` new tiers against simulated ToF; real sensor + tuning when the glasses are wired.
8. Infra: server status, "box online" announcement.

## 8. Document changes that follow approval

- `core/AGENTS.md`: process table (add `brain`, `check`, `tui`; voice/perception/agent fold into `brain`), remove "port from v3_core" wording (ideas only, no code), new build order, safety purpose, button instead of wake word, recording/TUI dev-only rule.
- `docs/architecture/CORTEX-ENGINE.md`: NPU split is the goal from the start, with the baseline first; drop "NPU only if needed".
- `docs/architecture/V4-ECOSYSTEM.md`: button tap instead of wake word; Google Maps not used; offline maps.

## 9. Left to the builder

Mechanisms (shared memory, socket layout), tool names and schemas, mode cadences other than those stated, freshness window value, anti-spam numbers, TUI layout details, measurement harness design, which TTS if LFM speech fails the bar.

## 10. Open items and risks

- **No one has published LFM3-Omni on a Qualcomm NPU.** The split may need our own model conversion and could fail on some layers. The baseline decides how hard this is.
- **NPU access on Ubuntu** on this board is unproven.
- **Weights licence** for shipping LFM3-Omni on a device: not reviewed.
- **Battery capacity** not chosen, so a watts target cannot be set yet; the baseline gives watts per interaction.
- **Mic type:** V4-ECOSYSTEM.md says 2× MP34DT01 digital PDM mics; Haziq described them as analog into the ESP32. Check the parts before ESP32 work (does not change the box side: two raw channels either way).
- Catching wrong reasoning (not just invented objects) remains unsolved.
