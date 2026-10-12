<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=000000&height=260&section=header&text=ASIRIVE%20CORTEX&fontSize=84&fontColor=EAFF00&animation=fadeIn&fontAlignY=35&desc=INDEPENDENT%20NAVIGATION%20FOR%20THE%20VISUALLY%20IMPAIRED&descAlignY=56&descSize=16" width="100%" />

  <br/>

  <img src="miscellaneous/IVP_Slides/Pictures/asirive%20logo.svg" width="56" alt="Asirive logo" />

  <br/>

  <img src="https://img.shields.io/badge/STATUS-V4%20ALPHA-EAFF00?style=for-the-badge&labelColor=000000" alt="Status: V4 Alpha" />
  <img src="https://img.shields.io/badge/COMPUTE-QUALCOMM%20SNAPDRAGON-EAFF00?style=for-the-badge&labelColor=000000" alt="Compute: Qualcomm Snapdragon" />
  <img src="https://img.shields.io/badge/SAFETY-%3C100%20MS-EAFF00?style=for-the-badge&labelColor=000000" alt="Safety latency under 100 ms" />
  <img src="https://img.shields.io/badge/GLASSES%20BOM-~S%2459-EAFF00?style=for-the-badge&labelColor=000000" alt="Glasses bill of materials about S$59" />
  <img src="https://img.shields.io/badge/iOS-ANDROID-EAFF00?style=for-the-badge&labelColor=000000" alt="iOS and Android" />
  <img src="https://img.shields.io/badge/LICENSE-GPLv3-EAFF00?style=for-the-badge&labelColor=000000" alt="License: GPL v3" />

  <br/>
  <br/>

  <b>DOOR TO DOOR. ON YOUR OWN.</b>
</div>

<img src="miscellaneous/IVP_Slides/Pictures/Asirive%20Cortex%20Standalone.png" width="720" alt="Asirive Cortex glasses and compute module connected by USB-C" />

---

**CONTENTS**
[01 JOURNEY](#01-journey) | [02 SYSTEM](#02-system) | [03 SAFETY](#03-safety) | [04 VOICE](#04-voice) | [05 NAVIGATION](#05-navigation) | [06 HARDWARE](#06-hardware) | [07 APP](#07-app) | [08 INFRASTRUCTURE](#08-infrastructure) | [09 PRIVACY](#09-privacy) | [10 NUMBERS](#10-numbers) | [11 ROADMAP](#11-roadmap) | [12 REPO](#12-repo) | [13 SETUP](#13-setup) | [14 ABOUT](#14-about)

---

## 01 JOURNEY

One journey is the product: origin to destination, alone. Outdoor walking, indoor space, trains and buses.

```mermaid
flowchart LR
  A["House"] -->|"turn by turn"| B["Bus stop"]
  B -->|"bus 161, 3 minutes"| C["On board"]
  C -->|"2 stops left"| D["MRT"]
  D -->|"sign reading"| E["Mall"]
  E -->|"escalator ahead, left"| F["Destination"]
```

---

## 02 SYSTEM

Five layers. Safety stays local. Reasoning can go to the cloud. The device never depends on the network to keep you safe.

```mermaid
flowchart LR
  subgraph GL["GLASSES"]
    direction LR
    TOF["ToF VL53L7CX"] --> BR["ESP32-S3 bridge"]
    CAM["Camera OV5640 AF"] --> BR
    MIC["2x mic, open-ear speakers"] --- BR
  end
  subgraph CM["COMPUTE MODULE"]
    direction LR
    SAFE["L0 safety, under 100 ms"]
    AGENT["Agent harness, one toolset"]
    LOCAL["Local sub-1B brain"]
  end
  subgraph PH["PHONE"]
    APP["Companion app"]
  end
  subgraph CL["CLOUD"]
    GEM["Gemini Live brain"]
    GW["Fleet gateway, OTA"]
  end
  BR -->|"USB-C: frames, ToF, audio"| SAFE
  SAFE --- AGENT
  AGENT <--> LOCAL
  AGENT <-->|"when online"| GEM
  CM <-->|"USB tether, data + GPS"| APP
  APP <-->|"end-to-end encrypted"| GW
```

| Layer | Name | Role | Where it runs |
|:---:|:---|:---|:---|
| **L0** | Guardian | Hazard detection, haptic and voice alerts | Device, offline, **under 100 ms** |
| **L1** | Learner | Open-vocabulary detection (YOLO-World on NPU) | Device |
| **L2** | Thinker | Scene understanding, conversation, function calling | Gemini Live and local sub-1B model |
| **L3** | Guide | Intent routing, navigation, transit, indoor guidance | Device with phone relay |
| **L4** | Memory | Recall, history, telemetry | Local first, retention-aware sync |

One agent toolset. Two interchangeable brains. Connected, Gemini leads on malls, interchanges and signage. Offline, the local model keeps you moving.

---

## 03 SAFETY

> **The cane handles the ground. Cortex handles head-height and beyond.**

| Hazard | Cane covers | Cortex alerts |
|:---|:---:|:---:|
| Walls, benches, curbs, stairs down | Yes | No, indoors |
| Overhead obstacles, signs, branches | No | Yes |
| Stairs going up | No | Yes |
| Fast-approaching vehicles and e-scooters | No | Yes |
| Text, bus numbers, prices, faces | No | Yes |

Alerts are hard-coded and model-independent. No AI sits between a hazard and its warning. They fire with no phone, no cloud and no internet.

---

## 04 VOICE

- Microphones and open-ear speakers built into the glasses. Ears stay open for traffic.
- Wake word "Hey Cortex". A voice command mutes the mic, confirmed by haptic.
- Two voices: conversation and safety never sound alike, so a warning is recognized before it is parsed.
- Cloud voices when connected, local speech synthesis offline. Speak over Cortex and it stops talking.

---

## 05 NAVIGATION

| Mode | Trigger | Behavior |
|:---|:---|:---|
| IDLE | Default | Silent unless a hazard fires |
| OUTDOOR_NAV | GPS fix, active route | Turn by turn, reads landmarks and signs |
| INDOOR_NAV | GPS lost | Visual guidance: "door left", "escalator ahead" |
| BUS_STOP | Near a stop | LTA arrivals, on-device bus number reading |
| TRANSIT | On bus or MRT | Stop counting, overhead sign reading |

Fourteen agent functions: search_places, get_directions, guide_indoor, get_bus_arrival, zoom_in, search_memory, report_obstacle. Multi-leg routes supported.

---

## 06 HARDWARE

### Glasses

| Part | Role |
|:---|:---|
| **VL53L7CX** 8x8 ToF, 90 degree field of view, 3.5 m | Overhead and ground hazard ranging |
| **OV5640** 5 MP 120 degree autofocus camera | Scene stream, close-up reading of signs and prices |
| **ESP32-S3** N16R8 | I/O bridge: camera, ToF and audio over one USB-C |
| 2x **MP34DT01** PDM MEMS microphones | Voice and ambient capture |
| **MAX98357A** amp, 2x **1511** open-ear speakers | Voice output without blocking hearing |
| Haptic motor | Microphone state, device status |

Rules: no folding frame (the ribbon must never flex at a hinge). Sensors stay on the brow line. The lower visual field stays clear, because partially-sighted users keep their remaining sight.

### Compute module

| | Alpha | V4 Final |
|:---|:---|:---|
| Board | Radxa Dragon Q8B | Custom SoM, custom carrier |
| Silicon | Snapdragon 8cx Gen 3, 29+ TOPS AI Engine | Smaller, faster, production |
| Memory | 8 GB, quantized sub-1B models | TBD |
| Power | Own battery, pogo-pin dock | TBD |

The phone is a data pipe only. It never powers the device.

---

## 07 APP

One Flutter application (iOS first, Android in scope). Two modes.

**User mode.** Pair the device, settings, beta opt-in, feedback, and per-companion permission grants to friends, family or certified medical professionals.

**Companion mode.** See the user's location and make a voice call. No live camera feed. No stored photos or video.

---

## 08 INFRASTRUCTURE

```mermaid
flowchart LR
  A["ALPHA<br/>dev team decides"] --> B["BETA<br/>opt-in users"] --> C["STABLE<br/>everyone"]
```

- **Go fleet gateway.** Device registry, end-to-end encrypted channels. Shipped devices are provisionable and updatable, never remotely breakable.
- **OTA with rings.** Signed artifacts, staged rollout, rollback. Updates reach the compute module and the glasses MCU through the app.
- **Web dashboard.** Fleet, rings, feedback tab. Feedback from every ring lands here.

---

## 09 PRIVACY

| Data | Policy |
|:---|:---|
| Images and video | Never stored. Zero retention, including on our own infrastructure |
| Location | Retained 30 days, shared per companion with your consent |
| Calls, transit data, activity logs | Stored |
| Companion access | Location and calls only. No live feed, ever |

---

## 10 NUMBERS

<div align="center">
  <img src="https://img.shields.io/badge/SAFETY_LATENCY-%3C100%20MS-EAFF00?style=for-the-badge&labelColor=000000" alt="Safety latency under 100 milliseconds" />
  <img src="https://img.shields.io/badge/INTENT_ROUTING-97.7%25-EAFF00?style=for-the-badge&labelColor=000000" alt="Intent routing accuracy 97.7 percent" />
  <img src="https://img.shields.io/badge/PROTOTYPE_BOM-~USD%20156-EAFF00?style=for-the-badge&labelColor=000000" alt="Prototype bill of materials about 156 US dollars" />
  <img src="https://img.shields.io/badge/GLASSES_SENSORS-~S%2459-EAFF00?style=for-the-badge&labelColor=000000" alt="Glasses sensor bill of materials about 59 Singapore dollars" />
  <img src="https://img.shields.io/badge/COMMERCIAL_ALTERNATIVES-USD%202500%2B-EAFF00?style=for-the-badge&labelColor=000000" alt="Commercial alternatives 2500 US dollars and up" />
</div>

Measured on V3 hardware. Community trials with the Singapore Association for the Visually Handicapped.

---

## 11 ROADMAP

<div align="center">
  <img src="https://img.shields.io/badge/V3-PROOF%20COMPLETE-EAFF00?style=for-the-badge&labelColor=000000" alt="V3: proof complete" />
  <img src="https://img.shields.io/badge/V4_ALPHA-IN%20PROGRESS-EAFF00?style=for-the-badge&labelColor=000000" alt="V4 Alpha: in progress" />
  <img src="https://img.shields.io/badge/V4_FINAL-PLANNED-EAFF00?style=for-the-badge&labelColor=000000" alt="V4 Final: planned" />
  <img src="https://img.shields.io/badge/SUB-1B%20MODEL-RESEARCH-EAFF00?style=for-the-badge&labelColor=000000" alt="Sub-1B model: research" />
</div>

| Stage | Scope |
|:---|:---|
| **V3, the proof** | Raspberry Pi prototype, five-layer brain, cane-aware safety, community trials. YIA 2026 finalist |
| **V4 Alpha, the ecosystem** | Custom glasses, Dragon Q8B, companion app, Go infrastructure. Lab first, field tested once lab-proven |
| **V4 Final, the product** | Custom SoM and carrier board. Manufacturing through the NTU partnership. Grant funded |
| **Horizon** | In-house sub-1B non-transformer scene model, run locally, accurate enough to lead |

---

## 12 REPO

```
ProjectCortex/
├── core/           The five-layer brain, being refactored for V4
│   └── device/     Cameras, sensors, GPS, power
├── infra/          Protocol seeds, Go fleet gateway lives here
├── apps/           Device CLI and companion surfaces
├── docs/           architecture/V4-ECOSYSTEM.md, start here
└── miscellaneous/  Models, media, archive, tools, tests, legacy deploy
```

Deprecated V2 and V3 systems still ship in this repository while they are refactored out. Each of core/, infra/ and apps/ carries an AGENTS.md that must be updated with every change in that domain.

---

## 13 SETUP

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

`.env` (gitignored): GEMINI_API_KEY, GOOGLE_MAPS_API_KEY, LTA_API_KEY, CARTESIA_API_KEY, SUPABASE_URL, SUPABASE_KEY. Key-rotation pool supported.

---

## 14 ABOUT

<div align="center">
  <img src="miscellaneous/IVP_Slides/Pictures/Irfan%20Wearing%20Cortex%20V3.png" width="380" alt="Cortex worn during field testing" />
</div>

Asirive Cortex is built by **Asirive**: Haziq Shah (lead engineering), Muhammad Irfan Nuafal and Eryna Natasha. Finalists at the Tan Kah Kee Young Inventors' Award 2026. Designed with and for the visually impaired community in Singapore.

*Asir* (Arabic: difficult) plus *-ive*. Making the difficult navigable.

[asirive.com/cortex](https://www.asirive.com/cortex) | [github.com/Asirive](https://github.com/Asirive)

---

<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=rect&color=000000&height=80&section=footer&text=DOOR%20TO%20DOOR.%20ON%20YOUR%20OWN.&fontSize=22&fontColor=EAFF00" width="100%" />

  <br/>

  <img src="miscellaneous/IVP_Slides/Pictures/asirive%20logo.svg" width="48" alt="Asirive logo" />
</div>
