# Asirive Cortex — V4 Ecosystem Architecture

**Status:** living design doc — source of truth for the V4 product and ecosystem.
**Scope:** device (glasses + compute module), companion app, cloud infrastructure.
**Rule:** when docs and code disagree, code wins. This doc describes the V4 target
architecture; the current repo contains deprecated V2/V3 systems being refactored out.

---

## 1. North Star

**Independent door-to-door navigation.** A blind or low-vision user travels from an
origin (house) to a destination (hawker center) — across outdoor walking, indoor
spaces (malls, bus interchanges, MRT), trains and buses — completely alone.
GPS cannot guide indoors. Visual and spatial understanding IS the product.

---

## 2. System at a Glance

```
┌─ GLASSES (sensors only) ─────────────────────────────────┐
│  VL53L7CX ToF (bridge) · OV5640 120° AF camera (brow)    │
│  2× PDM MEMS mic · open-ear speakers · haptic            │
│  ESP32-S3 = dumb I/O bridge (NO AI on the glasses)       │
└───────────────┬ single USB-C (frames+ToF+audio) ─────────┘
┌─ COMPUTE MODULE (pocket) ────────────────────────────────┐
│  Radxa Dragon Q8B (Alpha) → custom SoM + carrier (Final) │
│  8 GB RAM · stock Radxa OS · Python brain + C hot paths  │
│  NPU: YOLO-World · GPU: quantized sub-1B LFM · safety    │
│  wake word · VAD · AEC · dual STT/TTS · agent harness    │
└──┬───────────────────────────────────────┬───────────────┘
   │ USB-C (data + internet; phone never    │ BLE (fallback:
   │ powers the device) + phone GPS relay   │ control/GPS/notify)
┌──┴──────────────────┐              ┌──────┴──────────────┐
│ PHONE (Flutter app) │◄── E2E ─────►│ CLOUD INFRA (Go)    │
│ user + companion    │   encrypted  │ fleet · OTA · data  │
│ modes, VoIP, OTA    │              │ web dashboard       │
└─────────────────────┘              └─────────────────────┘
```

**Link model:** USB-C to the phone is primary (frames/audio/internet via iPhone
tether — Personal Hotspot/NCM; no hotspot battery drain on the phone's Wi-Fi).
Bluetooth to the compute module is the degraded control channel. Once local
models mature, the cable/internet dependency shrinks and may disappear.

---

## 3. Hardware Topology

### Glasses (custom, minimal, no-fold)
| Part | Role |
|---|---|
| VL53L7CX 8×8 ToF (64 zones, 60×60° FoV, 3.5 m) on the nose bridge | Overhead + ground hazards (indoor/stairs) |
| OV5640 5 MP 120° autofocus camera, 78 mm ribbon along the brow bar | Visual stream to compute module; close-up reading (signs, prices, bus numbers) — autofocus is a product requirement |
| ESP32-S3 N16R8 on the temple arm | Peripheral hub: DVP camera, I2C ToF, PDM mics, I2S amp, USB to compute module |
| 2× MP34DT01 PDM MEMS mics | Voice + ambient capture |
| MAX98357A I2S amp + 2× 1511 8 Ω open-ear speakers (mono, parallel) | Voice cues; ears stay open for traffic |
| Haptic motor | Mic on/off + status feedback |

**Hard product rules:**
- **Partially-sighted users must keep usable vision** — sensors confined to the
  brow/bridge line, lower visual field always clear. Never block the user's sight.
- **No spatial/directional DSP audio** (deprecated since V2). Voice cues are plain
  clock-position speech: "obstacle at 10 o'clock".
- No-fold frame (78 mm ribbon must never flex at a hinge).
- The ESP32-S3 stays a **dumb bridge**: video + ToF matrix + audio I/O only. No
  wake word, no AI, ever.

### Compute module
- Alpha: Radxa Dragon Q8B (Snapdragon 8cx Gen 3 / SC8280XP, 8 GB RAM, stock Radxa OS).
- V4-Final: custom SoM + custom carrier board (smaller, more powerful) — the
  manufacturing vehicle, funded via grants.
- Own battery set; charges via magnetic pogo-pin dock. Phone is **data only** —
  never powers the device.
- Haptic on the compute module too (e.g. "charging" state).

---

## 4. Plane 1 — Device (edge runtime)

Runs entirely on the compute module (Python + C hot paths):

- **Perception:** YOLO-World open-vocabulary detection on the NPU (QNN); ToF
  hazard fusion (the T0–T3 tier logic from V3, evolved).
- **Safety:** T0–T3 alerts are **hard-coded and model-independent** — no AI model
  sits between a hazard and a haptic/TTS alert. Local-only, never depends on
  phone/infra/cloud.
- **Voice:** wake word ("Hey Cortex") · VAD · AEC (mandatory — open-ear speakers
  beside bridge mics) · STT · TTS. Mic can be muted by voice ("I'm going to the
  door"), confirmed by haptic; wake word re-enables. Wake word + all processing
  live on the compute module.
- **Agent harness:** function-calling runtime with **two interchangeable brains**
  (see §8).
- **Navigation:** offline OSM-based walking maps + routing on-device; LTA bus
  data when online; indoor guidance via visual understanding (headline feature).
- **Memory:** local SQLite always; syncs to infra under the retention rules (§9).

### Voice routing policy
| State | STT | TTS |
|---|---|---|
| Online | Cartesia (fast) | Cloud voices (Cartesia; fast) |
| Offline | Local Whisper-class | Local Supertonic |

Cloud voices are preferred when connected for latency/quality; the local stack
is the guaranteed floor.

---

## 5. Plane 2 — App (Flutter, iOS-first, Android kept)

One app, two modes (role-switched):

- **User mode:** pairing (QR in person or remote invite link), settings, beta
  opt-in, feedback submission, per-companion permission grants, mic controls.
- **Companion mode:** user location (30-day TTL) + WhatsApp-style voice call.
  **Never a live camera feed. Never stored photos/video.** Companions can be
  friends, family, or certified medical professionals — the user grants each
  companion exactly what they choose (flexible per-companion permissions).

App roles beyond UI: **relay** (phone GPS → compute module over USB; internet
via tether), **VoIP** (WebRTC), **provisioning** (USB claim → infra account
link), **OTA delivery** (download → compute module → glasses MCU).

Login: Apple ID + email. iOS designed-in cost: "Always" location + background
navigation mode while tethered. GPS is outdoor-only (off indoors, saves power).

---

## 6. Plane 3 — Cloud Infrastructure (control plane)

- **Fleet gateway (Go):** device registry, device↔app↔gateway channels,
  E2E envelope encryption (device keys at pairing; production PKI at V4-Final),
  dev-only remote commands (alpha team only).
- **OTA service:** signed artifacts, staged rollout + rollback, covering compute
  firmware/models AND the glasses ESP32-S3 firmware
  (chain: infra → app → USB → compute → USB → ESP32-S3).
- **Data store (Postgres):** location (TTL 30 days), call records, LTA/nav data,
  activity logs, feedback (text + trimmed logs — "not too much logs").
- **Web dashboard** (React/Svelte → Go API): fleet view, update rings, feedback
  tab. Dev/alpha on the team's self-host server; VPS once beta users arrive.
- **Production policy:** manufactured devices are **provisionable and updatable
  but never remotely breakable**. Remote command execution exists only for the
  alpha development bench.

---

## 7. Contracts — the Polyglot Glue

The ecosystem is deliberately polyglot: Python (device), Dart (app), Go (infra),
C/Rust (glasses MCU firmware). They stay honest to each other via one
**`contracts/` source of truth** (protobuf + OpenAPI) with codegen per language:

- USB framing: timestamped frame + ToF + audio packets (ESP32-S3 ↔ compute)
- App ↔ device commands (USB + BLE)
- App ↔ infra API (OpenAPI)
- Device ↔ fleet-gateway protocol (E2E encrypted envelopes)
- OTA manifest format (signatures, rings, rollback metadata)
- **Agent tool registry** (§8) — the same function schemas serve both brains

Schemas change first; generated code follows. No hand-written drift.

---

## 8. Agent Harness — Dual Brain, One Toolset

- One tool registry — navigate, bus-arrivals, describe-scene, remember-this,
  camera-snap, … — callable by **Gemini Live (function calling)** or by the
  **local sub-1B model (function calling)**. The tools never know which brain
  calls them. The local stack must support function calling too — the agent
  harness is not a cloud luxury.
- Selection policy: **connected → Gemini** (wins on indoor/spatial/sign
  inference — malls, bus interchanges); **offline → local** (LFM-class quantized
  sub-1B on the GPU now; in-house custom model later).
- "No internet = useless device" is impossible by construction: safety, voice,
  memory and walking navigation all run locally.

### Local model roadmap
1. Pre-made LFM-class sub-1B (quantized, 8 GB SKU) + YOLO-World on NPU — start.
2. Fine-tune a VLM (LFM-VL or similar) for navigation + scene description.
3. In-house custom **non-transformer** sub-1B scene model (research goal:
   scene understanding under 1B parameters) — replace the pre-made model when
   validated. Needs funding, training data and architecture validation.

---

## 9. Data & Privacy Model

| Data | Policy |
|---|---|
| Images / video frames | **Never stored.** Ephemeral relay / in-flight processing only. Zero retention — even on our own infrastructure. |
| Location | Stored, TTL **30 days** |
| Call records | Stored |
| LTA / nav data | Stored |
| Activity logs | Stored (feedback attachments = trimmed logs only) |
| Companion access | Per-companion, user-selected: location + call only. No live feed. No stored media. |

E2E encryption on every device↔app↔infra path. Privacy mic-off is a first-class
UX state with haptic confirmation.

---

## 10. Update Rings & Feedback

| Ring | Who | Gate |
|---|---|---|
| ALPHA | Dev team (Haziq decides) | Internal bench |
| BETA | Users who opt in via the app | Prompted opt-in |
| STABLE | Everyone | Beta runs clean |

**Updates must never fail on a user.** Signed artifacts, staged rollout,
rollback. In-app feedback available in every ring (text + trimmed logs),
mirrored to a feedback tab in the web dashboard. Alpha firmware is signed with
the team key; production = real PKI from V4-Final manufacturing.

---

## 11. Decision Log (locked)

- iOS support mandatory (majority of blind users are on iOS/VoiceOver); Android kept in mind.
- USB-C tether to phone = primary link (data + internet; phone never powers device); BLE = fallback control link.
- Hybrid: Gemini Live + function calling primary when connected; local stack = fallback + full offline autonomy; local does function calling too. Priority may flip local when the custom model matures.
- ESP32-S3 = dumb I/O bridge; all processing on the compute module.
- Wake word "Hey Cortex" on the compute module; voice-commandable mic mute with haptic confirmation.
- Haptics on glasses AND compute module. Magnetic pogo charging dock.
- GPS = phone only, outdoor only (own GPS modules rejected: need sky view, too bulky).
- No-fold frame; partial-sight rule (never block the visual field).
- Autofocus camera kept (close-up reading is a use case).
- Open-ear speakers, mono amp; no spatial audio (deprecated since V2); clock-position voice cues only.
- Images/video zero retention; location TTL 30 d; per-companion consent.
- Update rings alpha→beta→stable; production devices never remotely breakable.
- One device per user (spare/multi-device later).
- Login: Apple ID + email.
- Infra: Go gateway + web dashboard; dev self-host → VPS at beta.
- Test plan: home/room lab first; field tests (MRT, real routes) only after lab-proven.
- Partners: NTU (professor support — injection molding + 3D printing), SVH
  (visually-handicapped org collaboration). V4-Final funded via grants.

---

## 12. Deprecated Systems (explicitly dead)

Do not build on these; they remain in the repo only until refactored out:

- Spatial audio / binaural DSP (dead since V2)
- Kokoro TTS (replaced by Supertonic)
- GLM-4.6V tier-2 cascading fallback
- Flask / NiceGUI / CustomTkinter dashboards
- `apps/laptop_dashboard` + laptop GPU Layer-1 service + ZMQ video path
- RPi5 hardware stack: picamera2/libcamera, BCM GPIO, `/dev/ttyAMA0`,
  raspi-config knobs, Hailo-8L power workarounds
- F-16 Bluetooth mic + earbud audio path (all audio I/O moves to the glasses)
- Phone-hotspot connectivity model
- Legacy memory manager stub, `local_copilot` scaffolding
- Direct device→Supabase sync (superseded by gateway-mediated sync)

---

## 13. Refactor & Migration Map (current repo → V4)

| Area | V4 treatment |
|---|---|
| `core/` | **Heavy refactor.** Decompose the `CortexSystem` monolith (`core/system.py`, ~8.4k lines) into services: perception, safety, voice, agent harness, nav, memory. Preserve proven logic: safety T0–T3, Gemini Live handler patterns, voice pipeline. Strip every deprecated system (§12). Add: local-brain adapter, dual STT/TTS policy, wake word service, offline routing, retention-aware sync. |
| `device/` | **Replace.** New ESP32-S3 firmware (ESP-IDF, C) for the glasses bridge + compute-module board support for Dragon Q8B. Current RPi-specific handlers are reference only. |
| `infra/` | **Greenfield.** Go fleet gateway + OTA + contracts. Current `infra/api/protocol.py` + `infra/supabase/` schema are seeds/reference for message shapes and tables. |
| App | **Greenfield.** Flutter (iOS-first). `apps/laptop_dashboard` is deprecated; its message protocol is the only reference worth keeping. |
| Web dashboard | **Greenfield.** React/Svelte against the Go API (fleet, rings, feedback). |
| `apps/cortex` CLI | Keep as dev/alpha tooling. |
| `tools/` | Keep (sync, converters, setup) — provisioning story improves with the gateway. |
| `tests/` | Keep and extend per domain. |

---

## 14. Build Orchestration (multi-agent)

- **Orchestrator (source of truth for product + ecosystem):** owns this doc, the
  contracts, cross-domain consistency, and arbitrates between domains.
- **Domain agent — core/device:** compute-module runtime + ESP32-S3 firmware +
  local AI stack (Python / C / Rust).
- **Domain agent — app:** Flutter app (Dart, iOS/Android).
- **Domain agent — cloud infra:** Go gateway + OTA + web dashboard.

Workflow: contracts change first → each domain implements against generated
types → orchestrator reviews cross-plane effects. Multi-agent is required
because the ecosystem spans languages, hardware and organizations.

---

## 15. Open Items

- [ ] Compute-module battery target + capacity (researching: small + powerful)
- [ ] Glasses miniaturization (custom PCB vs dev board; NTU partnership)
- [ ] Mic-off quality-of-life flows (door/toilet scenarios)
- [ ] Custom model funding, training data pipeline, architecture validation
- [ ] Spare device / multi-device support (post-alpha)
- [ ] Field-test protocol with SVH (after lab-proven)
