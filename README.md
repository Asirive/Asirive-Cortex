<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=000000&height=260&section=header&text=ASIRIVE%20CORTEX&fontSize=84&fontColor=FFD700&animation=fadeIn&fontAlignY=35&desc=INDEPENDENT%20NAVIGATION%20FOR%20THE%20VISUALLY%20IMPAIRED&descAlignY=56&descSize=16" width="100%" />

  <br/>

  <img src="https://img.shields.io/badge/STATUS-V4%20ALPHA-FFD700?style=for-the-badge&labelColor=000000" />
  <img src="https://img.shields.io/badge/COMPUTE-QUALCOMM%20SNAPDRAGON-FFD700?style=for-the-badge&labelColor=000000" />
  <img src="https://img.shields.io/badge/SAFETY-%3C100%20MS-FFD700?style=for-the-badge&labelColor=000000" />
  <img src="https://img.shields.io/badge/GLASSES%20BOM-~S%2459-FFD700?style=for-the-badge&labelColor=000000" />
  <img src="https://img.shields.io/badge/iOS-ANDROID-FFD700?style=for-the-badge&labelColor=000000" />
  <img src="https://img.shields.io/badge/LICENSE-GPLv3-FFD700?style=for-the-badge&labelColor=000000" />

  <br/>
  <br/>

  <b>DOOR TO DOOR. ON YOUR OWN.</b>
</div>

---

**CONTENTS**
[01 THE PRODUCT](#01-the-product) | [02 THE JOURNEY](#02-the-journey) | [03 SYSTEM](#03-system) | [04 SAFETY](#04-safety) | [05 VOICE](#05-voice) | [06 NAVIGATION](#06-navigation) | [07 HARDWARE](#07-hardware) | [08 APP](#08-app) | [09 INFRASTRUCTURE](#09-infrastructure) | [10 PRIVACY](#10-privacy) | [11 NUMBERS](#11-numbers) | [12 ROADMAP](#12-roadmap) | [13 REPO](#13-repo) | [14 SETUP](#14-setup) | [15 ABOUT](#15-about)

---

## 01 THE PRODUCT

Asirive Cortex is a wearable navigation system for blind and low-vision users. Custom glasses, a pocket compute module, a companion app, and a cloud control plane. It reads signs, calls out hazards the cane cannot detect, announces bus arrivals, and guides you through places where GPS dies.

The white cane already covers the ground. Cortex does not duplicate it. It speaks only for what the cane cannot perceive: overhead obstacles, stairs up, fast-approaching objects, and visual information. One core rule across the whole system:

> **Indoors, the cane handles the ground. Cortex handles head-height and beyond.**

---

## 02 THE JOURNEY

The product exists for one journey. Origin to destination, alone.

| Segment | What Cortex does |
|:---|:---|
| House to bus stop | Turn-by-turn walking guidance, curb and vehicle alerts |
| At the stop | "Bus 161, arriving in 3 minutes" |
| On board | Stop counting. "Next stop: Bukit Panjang, two stops" |
| MRT transfer | Overhead sign reading, platform guidance |
| Inside the mall | Visual guidance. "Escalator ahead, slightly left" |
| Arrival | "Your table is the third one on the right" |

Outdoor walking, indoor space, trains, buses. Sign-heavy environments where GPS fails and spatial understanding decides everything. That is the target and every architecture decision below serves it.

---

## 03 SYSTEM

Five layers. Safety stays local. Reasoning can go to the cloud. The device never depends on the network to keep you safe.

| Layer | Name | Role | Where it runs |
|:---:|:---|:---|:---|
| **L0** | Guardian | Hazard detection, haptic and voice alerts | Device, offline, **under 100 ms** |
| **L1** | Learner | Open-vocabulary detection (YOLO-World on NPU) | Device |
| **L2** | Thinker | Scene understanding, conversation, function calling | Gemini Live (cloud) and local sub-1B model (offline) |
| **L3** | Guide | Intent routing, navigation, transit, indoor guidance | Device with phone relay |
| **L4** | Memory | Recall, conversation history, telemetry | Local first, retention-aware sync |

```
 GLASSES               COMPUTE MODULE             PHONE             CLOUD
┌─────────────┐  usb-c ┌───────────────┐  usb-c ┌───────────┐ e2e ┌───────────┐
│ VL53L7CX    │───────▶│ SAFETY <100ms │◀──────▶│ COMPANION │◀───▶│ FLEET GW  │
│ OV5640 AF   │bridge  │ AGENT HARNESS │ data   │    APP    │     │ OTA/RINGS │
│ 2x PDM MIC  │esp32-s3│ SUB-1B LOCAL  │ + GPS  │ iOS/DART  │     │ DASHBOARD │
│ OPEN-EAR    │        │ GEMINI ONLINE │        └───────────┘     └───────────┘
│ HAPTIC      │        └───────────────┘
└─────────────┘
```

One agent toolset. Two interchangeable brains. The same functions (navigate, bus-arrivals, describe-scene, camera-snap) are callable by Gemini Live or by the local model through function calling. Connected, Gemini leads on malls, interchanges and signage. Offline, the local model keeps you moving.

---

## 04 SAFETY

What the cane covers and what Cortex covers do not overlap.

| Hazard | Cane covers | Cortex alerts |
|:---|:---:|:---:|
| Walls, benches, curbs, stairs down | Yes | No, indoors |
| Overhead obstacles, signs, branches | No | Yes |
| Stairs going up | No | Yes |
| Fast-approaching vehicles, runners, e-scooters | No | Yes |
| Text, bus numbers, prices, faces | No | Yes |

Threat tiers run from critical (cane-invisible trap: haptic plus voice, always) down to fast-approaching objects at range. Cooldowns prevent alert spam. Safety alerts are hard-coded and model-independent. No AI model sits between a hazard and its warning. They fire with no phone, no cloud and no internet.

---

## 05 VOICE

Audio is the primary interface.

- Two PDM MEMS microphones and open-ear speakers built into the glasses. Ears stay open for traffic.
- Wake word "Hey Cortex" runs on the compute module. A voice command ("I'm going to the door") mutes the microphone, confirmed by haptic. The wake word brings it back.
- Two voices. Conversation and safety never sound alike, so a warning is recognized before a single word is parsed.
- Cloud voices when connected (Cartesia, low latency). Supertonic local speech synthesis when offline. Whisper-class recognition as the offline floor.
- Speak over Cortex and it stops talking. Echo cancellation is mandatory: the speakers sit next to the microphones.

---

## 06 NAVIGATION

| Mode | Trigger | Behavior |
|:---|:---|:---|
| IDLE | Default | Silent unless a hazard fires |
| OUTDOOR_NAV | GPS fix, active route | Turn-by-turn, reads landmarks and signs at turns |
| INDOOR_NAV | GPS lost | Visual guidance: "door left", "escalator ahead" |
| BUS_STOP | Within 50 m of a stop | LTA DataMall arrivals, on-device bus number reading |
| TRANSIT | On bus or MRT | Stop counting, overhead sign reading |

Fourteen agent functions and counting: search_places, get_directions, guide_indoor, get_bus_arrival, zoom_in, search_memory, report_obstacle. Multi-leg routes (Walk to Bus to MRT to Walk). Saved locations act as default origin when GPS is unavailable.

---

## 07 HARDWARE

### Glasses (sensor BOM: about S$59)

| Part | Role |
|:---|:---|
| **VL53L7CX** 8x8 ToF, 90 degree field of view, 3.5 m, nose bridge | Overhead and ground hazard ranging |
| **OV5640** 5 MP 120 degree autofocus camera, 78 mm brow ribbon | Scene stream, close-up reading of signs and prices |
| **ESP32-S3** N16R8, temple arm | I/O bridge. Camera, ToF and audio over one USB-C |
| 2x **MP34DT01** PDM MEMS microphones | Voice and ambient capture |
| **MAX98357A** I2S amplifier, 2x **1511** open-ear speakers | Voice output without blocking hearing |
| Haptic motor | Microphone state, device status |

Design rules: no folding frame (the ribbon must never flex at a hinge). All sensors sit on the brow and bridge line. The lower visual field stays clear, because partially-sighted users keep their remaining sight.

### Compute module

| | Alpha | V4 Final |
|:---|:---|:---|
| Board | Radxa Dragon Q8B | Custom SoM, custom carrier |
| Silicon | Snapdragon 8cx Gen 3, 29+ TOPS AI Engine | Smaller, faster, production |
| Memory | 8 GB, quantized sub-1B models | TBD |
| Power | Own battery, pogo-pin dock | TBD |

The phone is a data pipe only (USB tether for internet and GPS). It never powers the device.

---

## 08 APP

One Flutter application (iOS first, Android in scope). Two modes.

**User mode.** Pair the device by QR code or USB claim. Settings. Beta opt-in. Feedback. Per-companion permission grants to exactly who you choose: friends, family, certified medical professionals.

**Companion mode.** See the user's location (retained 30 days) and make a voice call, WhatsApp style. No live camera feed. No stored photos or video.

---

## 09 INFRASTRUCTURE

- **Fleet gateway (Go).** Device registry. End-to-end encrypted channels. Remote commands exist for the development bench only. Shipped devices are provisionable and updatable but never remotely breakable.
- **OTA with update rings.** ALPHA (dev team) to BETA (opt-in users) to STABLE. Signed artifacts, staged rollout, rollback. Updates cover the compute module and the glasses MCU, delivered through the app.
- **Web dashboard.** Fleet view, update rings, feedback tab.
- **Feedback** from every ring, in the app and on the dashboard. Text plus trimmed logs.

---

## 10 PRIVACY

| Data | Policy |
|:---|:---|
| Images and video | Never stored. Zero retention, including on our own infrastructure |
| Location | Retained 30 days, shared per companion with your consent |
| Calls, transit data, activity logs | Stored |
| Companion access | Location and calls only. No live feed, ever |

Encryption end to end on every device, app and infrastructure path.

---

## 11 NUMBERS

| Metric | Value |
|:---|---:|
| Safety latency, on-device | Under 100 ms (80.7 ms average measured) |
| Intent routing accuracy | 97.7 percent across 14 intents |
| V3 prototype BOM | About USD 156 |
| Commercial AI glasses | USD 2,500 to 3,000 |
| V4 glasses sensor BOM | About S$59 |
| Community trials | Singapore Association for the Visually Handicapped |

---

## 12 ROADMAP

| Stage | Scope | Status |
|:---|:---|:---|
| **V3, the proof** | Raspberry Pi 5 prototype, five-layer brain, cane-aware safety, live agent harness, community trials | Complete. YIA 2026 finalist |
| **V4 Alpha, the ecosystem** | Custom glasses, Dragon Q8B, companion app, Go infrastructure. Lab first, field tested only once lab-proven | In progress |
| **V4 Final, the product** | Custom SoM and carrier board. Manufacturing through the NTU partnership (injection molding, 3D printing). Grant funded | Planned |
| **Horizon** | In-house sub-1B non-transformer scene model. Scene understanding small enough to run locally, accurate enough to lead | Research |

---

## 13 REPO

```
ProjectCortex/
├── apps/
│   ├── cortex/              Device CLI and Textual TUI (python -m apps.cortex)
│   └── laptop_dashboard/    Deprecated V3 dashboard, being replaced
├── core/                    The five-layer brain, being refactored for V4
│   ├── system.py            CortexSystem orchestrator
│   ├── layer0_guardian/ .. layer4_memory/
│   ├── safety_monitor.py    Tiered hazard fusion
│   └── config/config.yaml
├── device/                  Cameras, sensors, GPS, power (RPi-specific today)
├── infra/                   Protocol and schema seeds, Go gateway lives here
├── tools/                   Sync, converters, setup, training
├── docs/architecture/       V4-ECOSYSTEM.md, start here
├── media/  archive/         Assets, presentations, V1-V3 history
└── tests/
```

This repository still contains deprecated V2 and V3 systems being refactored out. `docs/architecture/V4-ECOSYSTEM.md` is the reference for what comes next.

---

## 14 SETUP

```bash
git clone https://github.com/Asirive/Asirive-Cortex.git
cd Asirive-Cortex
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Full system with Textual TUI
python -m apps.cortex all

# Subsystem checks
python -m apps.cortex test-live    # minimal Gemini Live probe
python -m apps.cortex status       # env, config, layer availability
```

`.env` (gitignored): GEMINI_API_KEY, GOOGLE_MAPS_API_KEY, LTA_API_KEY, CARTESIA_API_KEY, SUPABASE_URL, SUPABASE_KEY. A key-rotation pool is supported (GEMINI_API_KEY_2 through _10).

Note: `numpy<2.0` is pinned for HailoRT 4.20 compatibility.

---

## 15 ABOUT

Asirive Cortex is built by **Asirive**: Haziq Shah (lead engineering), Muhammad Irfan Nuafal and Eryna Natasha. Finalists at the Tan Kah Kee Young Inventors' Award 2026. Designed with and for the visually impaired community in Singapore.

*Asir* (Arabic: difficult) plus *-ive*. Making the difficult navigable. Cortex is the system that connects cane, camera, microphone and cloud into one companion.

[asirive.com/cortex](https://www.asirive.com/cortex) | [github.com/Asirive](https://github.com/Asirive)

---

<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=rect&color=000000&height=80&section=footer&text=DOOR%20TO%20DOOR.%20ON%20YOUR%20OWN.&fontSize=22&fontColor=FFD700" width="100%" />

  <br/>

  <img src="https://img.shields.io/badge/LICENSE-GPLv3-FFD700?style=for-the-badge&labelColor=000000" />
</div>
