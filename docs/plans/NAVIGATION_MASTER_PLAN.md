# PROJECT CORTEX — Navigation Independence Master Plan

**Author:** Haziq (@IRSPlays)  
**Date:** March 10, 2026  
**Status:** REVISED — Grounded in what's built, honest about gaps  
**Source:** SAVH advocate meeting + 5-round architecture review + fatal flaw analysis + code audit  

---

## Table of Contents

1. [Mission & Priority Ranking](#1-mission--priority-ranking)
2. [Hard Safety Rules (Non-Negotiable)](#2-hard-safety-rules-non-negotiable)
3. [Audio Architecture (The Sacred Sound Space)](#3-audio-architecture-the-sacred-sound-space)
4. [The 3D Audio Beam — Engineering Detail](#4-the-3d-audio-beam--engineering-detail)
5. [Hardware Decisions (Final)](#5-hardware-decisions-final)
6. [Autonomous Gemini — The Proactive AI Companion](#6-autonomous-gemini--the-proactive-ai-companion)
7. [Compute Budget — What RPi5 Can Actually Run](#7-compute-budget--what-rpi5-can-actually-run)
8. [Navigation Modes (Auto-Switching)](#8-navigation-modes-auto-switching)
9. [Bus Detection Pipeline](#9-bus-detection-pipeline)
10. [Outdoor GPS Navigation](#10-outdoor-gps-navigation)
11. [Indoor Navigation (Gemini-Guided + Depth)](#11-indoor-navigation-gemini-guided--depth)
12. [Transit Navigation (Bus + MRT)](#12-transit-navigation-bus--mrt)
13. [The Research Agent](#13-the-research-agent)
14. [Connectivity & Offline Resilience](#14-connectivity--offline-resilience)
15. [Failure Scenarios — Exhaustive](#15-failure-scenarios--exhaustive)
16. [Privacy & PDPA Compliance](#16-privacy--pdpa-compliance)
17. [Real-World Scenarios — Full Walkthrough](#17-real-world-scenarios--full-walkthrough)
18. [Phase Roadmap (V1.0 → V3.0)](#18-phase-roadmap-v10--v30)
19. [SAVH Demo Scope](#19-savh-demo-scope)
20. [Sprint Plan](#20-sprint-plan)
21. [Testing Methodology](#21-testing-methodology)
22. [BOM & Cost Target](#22-bom--cost-target)

---

## 1. Mission & Priority Ranking

From SAVH advocate meeting — priority order based on real user needs:

| Priority | Feature | Advocate's Words |
|----------|---------|-----------------|
| **#1** | **Bus number detection + boarding** | "The biggest daily challenge" |
| **#2** | **Safety alerts** (curbs, stairs, bicycle racks, overhead) | "Bicycle racks are particularly dangerous" |
| **#3** | **Basic outdoor navigation** (3D beam to destination) | "Independence in navigation" |
| **#4** | **Responsiveness + offline resilience** | "Lack of responsiveness... dependency on data plan" = why devices fail |
| **#5** | **Simplicity for aging users** | "Senior citizens who lose their sight struggle with technology" |
| **#6** | Indoor/mall/food court navigation | Important but secondary |
| **#7** | MRT navigation | Secondary |
| **#8** | Scene description, menus, etc. | "Be My AI already does this" — NOT our differentiator |

**Our differentiator = 3D audio beam navigation + safety. NOT AI scene description.**

### Key Insights From The Meeting

1. **The white cane stays.** We complement the cane, not replace it. Cane = ground level. Cortex = overhead, far-away, reasoning.
2. **Aging population = dead simple UI.** Turn on → it works. Say where → it navigates. Say nothing → it keeps you safe.
3. **The tray problem.** Food court: user has food tray + cane. NO free hands. System must be 100% autonomous after "find me a seat."
4. **Mandarin + English.** Gemini handles both. Kokoro TTS supports both. Hailo OCR reads Chinese.
5. **$300 price target.** Non-negotiable for adoption.
6. **Waterproof.** IP-rated enclosure required.
7. **Continuous testing with SAVH.** Don't develop in isolation.

---

## 2. Hard Safety Rules (Non-Negotiable)

These are hardcoded into the system. Violating any of these is a showstopper.

### RULE 1: NEVER GUIDE TOWARD MOVING OBJECTS

```
if target.velocity > 0:
    beam.lock_on(fixed_reference)  # bus stop pole, railing, etc.
    DO NOT shift beam to moving target
```

At bus stops: beam stays on pole. Voice announces bus numbers. Only when bus velocity = 0 AND doors detected (YOLO) does beam shift to door.

### RULE 2: NO IN-EAR TIPS. EVER.

Blind person's ears = primary survival sensor. Silicone tips block natural spatial hearing and mask quiet EVs approaching from behind. Use bone conduction (Shokz) or open-ear (Sony LinkBuds) ONLY.

### RULE 3: PHYSICAL PRIVACY SHUTTER

3D-printed sliding shutter over camera lens. GPIO reed switch detects shutter position. Shutter closed = `camera.release()` at hardware level. No frames captured, buffered, or sent. Visible to public = social proof.

### RULE 4: ESCALATOR = VOICE + CANE (NOT RHYTHMIC HAPTIC)

Gemini detects escalator from distance (voice: "Escalator ahead, hold the railing"). At the edge, voice says: "Step on when ready." User uses cane + railing to time their step — this is how blind people already use escalators. ~~Rhythmic haptic matching step frequency~~ was removed: the timing window is ~300ms, a single vibration motor provides too crude a signal, and this has never been validated with a real user. Risk of causing falls outweighs benefit.

### RULE 5: SAFETY NEVER DEPENDS ON CLOUD

All safety alerts (wall, stair, curb, overhead, drop-off) run on Hailo NPU locally. Zero network dependency. Even with no internet, no GPS, no Gemini — safety works.

### RULE 6: GYRO-PRIMARY INDOORS (BNO055 HEADING ONLY)

Indoor metal structures distort BNO055 magnetometer by 20-30°. Switch BNO055 to gyro-only mode indoors (for chest heading / audio beam direction). Correct gyro drift with OCR sign readings (visual odometry using text landmarks). Positioning is handled by NEO-M8U UDR — no BNO055 step counting needed.

### RULE 7: MULTI-SOURCE VERIFICATION FOR CRITICAL DECISIONS

Never cross a road, change direction, or board transport based on ONE source. Cross-reference GPS + OCR + Gemini + depth. Conflict = pause, re-check, ask user.

---

## 3. Audio Architecture (The Sacred Sound Space)

The user has ONE pair of ears. Every sound competes with the real world they NEED to hear (cars, people, MRT announcements).

### ONLY 2 AUDIO CHANNELS. EVER.

**CHANNEL 1 — THE BEAM** (3D HRTF spatialized, one source)
- ONE continuous directional sound
- Direction = where to walk next (adjusted for obstacles)
- Pitch rises = getting closer
- Ping rate increases = almost there
- That's it. No multiple obstacle pings. No layered warning sounds.

**CHANNEL 2 — THE VOICE** (Gemini Live OR cached TTS, centered)
- Speaks naturally in English (or Mandarin)
- Handles ALL warnings: "Table on your left, go around it"
- Handles ALL status: "You're almost there"
- Conversational, calm, human-like
- Gemini Live online / Kokoro TTS offline

**NO obstacle ping sounds. NO ambient hums. NO chirps.** Voice handles all warnings. Beam handles all direction.

### Sound Feedback (Replace Distance With Feeling)

| Instead of this | Do this |
|----------------|---------|
| "3 meters away" | Beam volume: louder = closer |
| "Turn left 45°" | Beam plays from left → just follow |
| "You're on track" | Beam stays centered, constant gentle pulse |
| "Getting close" | Ping rate increases (like metal detector) |
| "Obstacle ahead" | Voice: "Table on your left" |
| "You arrived" | Distinct chime + voice confirmation |

---

## 4. The 3D Audio Beam — Engineering Detail

### Two Dedicated Movement Systems

```
NEO-M8U (BODY POSITION — where am I in the world?):
├─ GNSS satellite fix outdoors (standard GPS)
├─ Untethered Dead Reckoning (UDR) when GNSS degrades:
│   ├─ Internal 3D accelerometer + gyroscope on the chip
│   ├─ Continues outputting valid NMEA coordinates at 30Hz
│   ├─ Works under HDB blocks, MRT bridges, urban canyons
│   ├─ Works in malls and indoor spaces (drift-limited)
│   └─ No custom IMU fusion code needed — hardware handles it
├─ Seamless transition: outdoor GPS → indoor UDR → back to GPS
└─ Output: standard NMEA lat/lon/alt — same interface regardless of mode

BNO055 (HEAD/CHEST ORIENTATION — which way am I facing?):
├─ Euler angles: heading, roll, pitch
├─ Used ONLY for 3D audio beam direction
│   (beam must track where user's head/chest points)
├─ Outdoor: NDOF mode (magnetometer + gyro)
├─ Indoor: IMU mode (gyro-only, avoids magnetic interference)
└─ Still needs OCR sign readings for gyro drift correction indoors
```

### How The Beam Moves (25Hz loop on RPi5)

```python
while navigating:
    # 1. HEADING — from BNO055 IMU (which way is user facing)
    heading = imu.get_euler().heading  # 0-360°

    # 2. POSITION — from NEO-M8U (where is user, GPS or UDR)
    my_position = gps.get_position()  # always valid, even indoors

    # 3. TARGET BEARING — simple geometry, works everywhere
    target_bearing = geo_bearing(my_position, next_waypoint)

    # 4. RELATIVE TO USER'S HEAD
    relative_angle = target_bearing - heading  # -180 to +180°

    # 5. SET BEAM POSITION (OpenAL HRTF)
    rad = math.radians(relative_angle)
    beam_source.set_position(math.sin(rad), 0, -math.cos(rad))

    # 6. DISTANCE FEEDBACK (pitch + ping rate)
    dist = distance_to_target()
    if dist > 20:   beam.set_pitch(0.8);  beam.set_interval(2.0)
    elif dist > 5:  beam.set_pitch(1.0);  beam.set_interval(1.0)
    elif dist > 2:  beam.set_pitch(1.2);  beam.set_interval(0.5)
    else:           play_arrival_chime()
```

### Obstacle Avoidance — Phased Approach

```
PHASE 1 (Sprint — what we build first):
├─ Beam points DIRECTLY at next waypoint (no obstacle adjustment)
├─ Safety system (already built) warns about obstacles via voice:
│   "Wall ahead" / "Table on your left" / "Stairs going down"
├─ User navigates around obstacles using cane + voice warnings
├─ This is how blind people already navigate — cane + audio cues
└─ Beam re-centers once user passes the obstacle

WHY THIS IS OK:
├─ Safety system has sub-100ms alerts (already production-ready)
├─ User has a white cane (ground-level obstacle detection)
├─ Gemini provides voice context ("table on your left, go around")
└─ Beam gives DIRECTION, safety gives WARNINGS — they complement

PHASE 2 (after demo, with real user data):
├─ Build 2D occupancy grid from accumulated depth frames
├─ A* or wavefront path planning on occupancy grid
├─ Beam follows planned clear path, not straight line to target
├─ Requires: persistent map, odometry, proper SLAM-lite
└─ Only worth building after Phase 1 proves beam navigation works
```

**User experience:** A gentle pulse in 3D space. Turn until it centers. Walk forward. It stays centered = on track. It shifts right = there's a table, curve right. Instinctive. No thinking required.

### The Beam Follows Waypoints, Safety Handles Obstacles

```
PHASE 1:
  Beam points at next GPS waypoint.
  Safety system warns about obstacles.
  User navigates around with cane + voice.
  
PHASE 2:
  Beam follows computed clear path (occupancy grid + pathfinding).
  User flows around obstacles following the beam.
```

---

## 5. Hardware Decisions (Final)

| Component | Choice | Cost |
|-----------|--------|------|
| Compute | RPi5 4GB | ~$80 |
| Camera | Camera Module 3 Wide (130° FOV, IMX708) | ~$35 |
| AI Accelerator | Hailo-8L NPU | ~$70 |
| IMU | BNO055 (I2C 0x29, 25Hz) | ~$30 |
| GPS + UDR | NEO-M8U (UART, Untethered Dead Reckoning, 30Hz) | ~$25 |
| Haptic | Vibration motor (GPIO 18) | ~$2 |
| Audio | Open-ear headphones (bone conduction or open driver) | ~$30 |
| Privacy | 3D-printed camera shutter + reed switch | ~$1 |
| Power | Battery + USB-C power management | ~$20 |
| Enclosure | IP-rated case (waterproof) | ~$15 |
| Misc | Wires, PCB, connectors | ~$10 |
| **TOTAL** | | **~$318** |

### Audio Hardware: Open-Ear (Non-Negotiable)

Options:
- **Shokz OpenRun** — bone conduction, proven HRTF compatibility
- **Sony LinkBuds** — ring driver, fully open
- **Generic open-ear clips** — cheapest option for $300 target

HRTF works on all of these: brain processes L/R phase delay identically regardless of transducer type.

### Calibration At Setup

- Step length: "Walk 10 steps in a straight line" → GPS measures actual distance → calibrate
- Audio beam: "I'll play a sound to your right, nod if you hear it there" → verify HRTF
- IMU: auto-calibrates on BNO055 (NDOF mode, figure-8 motion)

---

## 6. Autonomous Gemini — The Proactive AI Companion

### The Problem With Current Gemini

The current `gemini_live_handler.py` treats Gemini as a **chatbot**: it waits for the user to ask a question, then responds. This is wrong for a wearable companion. A visually impaired user shouldn't have to constantly ask "what's in front of me?" — the system should **proactively narrate** what matters.

### Architecture: Two Parallel AI Streams

```
┌──────────────────────────────────────────────────────────┐
│                    RPi5 MAIN LOOP                        │
│                                                          │
│  STREAM 1: SAFETY (local, always-on, <100ms)             │
│  ├─ YOLO 11n → 80 classes, 80ms                          │
│  ├─ Hailo depth → 6 hazard types, 3ms                    │
│  ├─ SafetyMonitor → tier-based fusion                    │
│  └─ Voice alert: "Wall ahead!" (interrupts everything)   │
│                                                          │
│  STREAM 2: GEMINI (cloud, proactive, ~500ms)             │
│  ├─ Video frames → Gemini Live WebSocket (1-2 FPS)       │
│  ├─ Scene change detector triggers narration              │
│  ├─ Sensor context injected into conversation             │
│  └─ Speaks when something is WORTH saying                 │
│                                                          │
│  PRIORITY: Safety stream ALWAYS interrupts Gemini         │
└──────────────────────────────────────────────────────────┘
```

### System Prompt (The Core Change)

```
OLD PROMPT (chatbot):
  "You are a helpful assistant. Answer the user's questions about what you see."

NEW PROMPT (autonomous companion):
  "You are the eyes of a visually impaired person wearing you as glasses.
   You see through their camera. You hear through their microphone.
   
   SPEAK when:
   - Something new or important appears (person approaching, door, sign)
   - The scene changes significantly (entered a building, reached a road)
   - Something could be dangerous that the safety system didn't catch
   - The user seems lost or confused
   
   STAY SILENT when:
   - Nothing has changed (walking down a clear corridor)
   - The safety system already warned about it
   - The user is in a conversation with someone
   
   Be CONCISE. Never say more than 2 sentences unprompted.
   Speak naturally, like a trusted friend walking beside them.
   
   You also receive sensor context:
   - GPS: current location, distance to waypoint
   - Safety: recent hazard alerts
   - Navigation: current mode (outdoor/indoor/bus stop)
   Use this to give relevant, contextual guidance."
```

### Scene Change Detector

Triggers Gemini narration when the world changes meaningfully:

```python
# Pseudocode — actual implementation in rpi5/layer2_thinker/
class SceneChangeDetector:
    """Decides when Gemini should speak unprompted."""
    
    def should_narrate(self, current_frame, detections, context):
        # 1. New object class appeared (not seen in last 5 seconds)
        new_classes = current_classes - self.recent_classes
        if new_classes: return True
        
        # 2. Significant depth change (entered a room, reached a wall)
        if abs(avg_depth - self.last_depth) > DEPTH_THRESHOLD: return True
        
        # 3. Navigation event (reached waypoint, mode changed)
        if context.nav_event: return True
        
        # 4. Time-based: haven't spoken in 30+ seconds on a route
        if context.navigating and self.silence_duration > 30: return True
        
        return False
```

### Context Injection

Every Gemini video frame includes sensor context as metadata:

```
[CONTEXT] Location: 1.3521°N, 103.8198°E | Mode: OUTDOOR_NAV
[CONTEXT] Waypoint: 45m ahead, bearing 035° | Next turn: right in 20m
[CONTEXT] Safety: clear | Battery: 78% | Signal: strong
[CONTEXT] Recent: user asked about bus 23 (2 min ago)
```

This gives Gemini the **full picture** without it needing to infer everything from video alone.

---

## 7. Compute Budget — What RPi5 Can Actually Run

### Simultaneous Processes on RPi5 4GB

| Process | CPU | RAM | Accelerator | Latency | Status |
|---------|-----|-----|-------------|---------|--------|
| YOLO 11n (NCNN) | ~50% 1 core | ~200MB | CPU (NEON) | 80ms | ✅ Built |
| Hailo depth | ~5% | ~50MB | Hailo-8L NPU | 3ms | ✅ Built |
| Kokoro TTS | ~80% 1 core | ~150MB | CPU | <500ms | ✅ Built |
| Whisper STT | ~90% 1 core | ~100MB | CPU | <1s | ✅ Built |
| Silero VAD | ~10% | ~20MB | CPU | <10ms | ✅ Built |
| OpenAL HRTF | ~5% | ~10MB | CPU | <1ms | ✅ Built |
| Gemini WebSocket | ~5% | ~30MB | Network | ~500ms | ✅ Built |
| GPS/IMU polling | ~2% | ~5MB | UART/I2C | <1ms | ✅ Built |
| Navigation loop | ~5% | ~20MB | CPU | 40ms | ⬜ Sprint |
| Safety monitor | ~5% | ~10MB | CPU | <1ms | ✅ Built |
| **Total peak** | **~3 cores** | **~595MB** | | | |

**Available:** 4 cores, ~3.5GB usable RAM (OS takes ~500MB). **Fits comfortably.**

### Hailo-8L Scheduling (Critical Constraint)

The Hailo-8L can only run **ONE model at a time**. Currently only fast_depth runs on it.

```
Current: Hailo runs fast_depth continuously (3ms per frame)
Future possibility: Time-slice between depth + another model

Strategy for Phase 1:
  - Hailo = depth ONLY (always-on, safety-critical)
  - YOLO = CPU NCNN (80ms, acceptable)
  
Strategy for Phase 2 (if needed):
  - Frame N: Hailo depth (3ms)
  - Frame N+1: Hailo YOLO (if YOLO-Hailo conversion works)
  - Alternating at 15 FPS each = 30 FPS total Hailo utilization
```

### What CANNOT Run on RPi5

| Model | Why Not |
|-------|---------|
| YOLOE (PyTorch) | 5 FPS, 2GB+ RAM, no NCNN conversion |
| SmolVLM-256M | ~3-5s/frame, blocks safety pipeline |
| Qwen2.5-VL-3B | 8GB+ RAM, won't even load |
| Any LLM >1B | Too slow for real-time, RAM constrained |

### Profiling Test Plan

Before SAVH demo, run this 5-minute stress test:
```bash
# Monitor during full pipeline operation
htop                          # CPU per core
free -h                       # RAM usage
hailortcli monitor            # NPU utilization
vcgencmd measure_temp         # CPU temperature (throttles at 85°C)
```

Target: CPU <80% sustained, RAM <3GB, temp <75°C.

---

## 8. Navigation Modes (Auto-Switching)
<!-- Section 8 -->

```
┌─────────────────────────────────────────────────┐
│              NAVIGATION AGENT (Layer 3)          │
│                                                  │
│  Modes (auto-switching, user never selects):     │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │ FREE ROAM│ │NAVIGATION│ │  BUS STOP     │    │
│  │(default) │ │(GPS beam │ │ (LTA API     │    │
│  │safety    │ │+ voice   │ │  + YOLO bus) │    │
│  │only      │ │guidance) │ │              │    │
│  └──────────┘ └──────────┘ └──────────────┘    │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │ TRANSIT  │ │ INDOOR   │ │  PRIVACY     │    │
│  │(on bus/  │ │(Gemini   │ │ (camera off, │    │
│  │MRT, stop │ │guide +   │ │  IMU only)   │    │
│  │counting) │ │depth)    │ │              │    │
│  └──────────┘ └──────────┘ └──────────────┘    │
│                                                  │
│  Always running underneath ALL modes:            │
│  ├─ Safety alerts (depth, obstacles) [LOCAL]     │
│  ├─ Autonomous Gemini (proactive voice) [CLOUD]  │
│  ├─ Connectivity monitor [LOCAL]                 │
│  └─ System heartbeat [LOCAL]                     │
└─────────────────────────────────────────────────┘
```

**Mode transitions are AUTOMATIC:**
- GPS quality degrades → INDOOR
- At bus stop + waiting → BUS STOP
- On bus/MRT (velocity detected, no walking) → TRANSIT
- GPS returns → NAVIGATION (outdoor)
- No destination → FREE ROAM
- Privacy shutter closed → PRIVACY

---

## 9. Bus Detection Pipeline
<!-- Section 9 -->

**THE LED MATRIX TRAP:** Singapore buses use LED matrix displays. PWM + RPi Camera rolling shutter = text flickers/disappears in 40-60% of frames. Single-frame OCR will produce gibberish.

### Architecture: LTA API Primary, Camera Secondary

```
PHASE 1 (Sprint):

PRIMARY: LTA DataMall API (online, responsive)
├─ GET /BusArrivalv2?BusStopCode=XXXXX
├─ Returns: which bus numbers arriving, estimated time
├─ GPS → find nearest bus stop code → query arrivals
├─ Voice: "Bus 23 arriving in about 2 minutes"
├─ Refresh every 15-30 seconds
└─ Offline fallback: voice asks user to ask driver

SECONDARY: Camera (YOLO bus detection only)
├─ YOLO detects "bus" objects in frame
├─ Track bus velocity: moving vs stopped
│   velocity > 0 → "Bus approaching, stay still"
│   velocity = 0 → "A bus has stopped"
├─ LTA API confirms WHICH bus it is
└─ Voice: "Bus 23 has stopped. It should be in front of you."

NOT IN PHASE 1 (deferred to Phase 2):
├─ Door detection (YOLO's 80 classes don't include "bus door")
├─ Beam shift to door (unreliable without door detection)
├─ Bus queue handling (LTA GPS correlation with YOLO = research problem)
├─ Temporal voting OCR (LED matrix PWM anti-flicker)
└─ Beam-on-pole (YOLO doesn't detect "bus stop pole" specifically)
```

### Phase 1 Bus Stop Protocol

```
1. Navigation brings user to bus stop area (GPS)
2. Voice: "You're at the bus stop. Bus 23 should arrive in about 3 minutes."
3. System watches: LTA API for arrival + camera for YOLO bus detection

4. Bus approaching:
   LTA API: bus 23 is nearby
   Voice: "Bus 23 is coming. Stay where you are."
   Camera: YOLO detects bus, tracks velocity
   
5. Bus stops:
   YOLO: bus velocity = 0
   LTA API: confirms it's bus 23
   Voice: "Bus 23 has stopped. Walk forward to board."
   User approaches with cane (user already knows how to board buses)

6. User boards:
   Mode switches to TRANSIT
   
FAILURE: LTA API down
   Voice: "I can't confirm the bus number right now. 
   A bus has stopped. You can ask the driver 'Is this bus 23?'"

FAILURE: Multiple buses
   LTA API tells which buses are here right now
   Voice: "Two buses here. Bus 23 is one of them."
   (Without door detection, guide user to the front bus —
    if wrong, user asks driver and waits for next)
```

### Phase 2 Additions (After Demo)

```
├─ Door detection via Gemini (send frame, ask "where is the bus door?")
├─ Bus queue handling (LTA GPS + YOLO position correlation)
├─ Temporal voting OCR (buffer 10 frames, consensus vote for LED text)
├─ Beam-on-pole using Gemini object identification
└─ Beam shift to door once door detection is reliable
```

---

## 10. Outdoor GPS Navigation

### Route Planning

```
User: "Take me to Tampines MRT"

1. Google Maps Directions API (walking mode)
   → Waypoints: [(lat1,lon1,"Walk north on Tampines St 81"), 
                  (lat2,lon2,"Turn right onto Tampines Ave 4"), ...]

2. Cache entire route to SQLite (works offline after this point)

3. Navigation loop:
   ├─ GPS: current position
   ├─ Next waypoint: bearing + distance
   ├─ IMU: current heading
   ├─ Depth: obstacle scan
   ├─ Beam: points at clear path toward waypoint
   ├─ Voice: turn-by-turn instructions at waypoints
   │   "Keep going straight... Turn right ahead... 
   │    You're on Tampines Avenue 4."
   └─ Arrival at each waypoint → advance to next

4. At destination:
   Arrival chime + "You've arrived at Tampines MRT station."
```

### Road Crossings

```
DETECTION: depth sees curb drop + camera sees road markings

ALWAYS (online or offline):
  Voice: "Road crossing detected. Please check it's safe before crossing."
  Beam: PAUSES (does NOT guide across)
  System waits for user to say "cross now" or start crossing (GPS detects movement)
  
  WHY NOT "AI judges traffic":
  ├─ Gemini has 500ms+ latency. Cars at 50km/h cover 7m in 500ms.
  ├─ Single frame cannot assess traffic FLOW.
  ├─ Giving false confidence to cross is the worst possible failure.
  ├─ Blind people already have road-crossing skills (listen, cane, timing).
  └─ System helps DETECT the crossing, user DECIDES when to cross.

DURING CROSSING:
  GPS tracks progress across the road.
  Voice: "Keep straight. Almost across. Back on the footpath."
  
POST-CROSS:
  GPS confirms user is on the other side → resume beam
```

### Orientation Recovery

```
"I'M LOST" PROTOCOL:

Voice (calm): "Don't worry. Let me work out where you are."

1. GPS: reverse geocode → "You're on Tampines Street 81, near Block 831"
2. Camera → Gemini: "I can see a coffee shop and a playground"
3. OCR: reads signs → "Block 831A"
4. "I can take you back to where you started, or to the nearest MRT. 
    What do you prefer?"
5. If no response capability: follow breadcrumb trail back (autonomous)
```

---

## 11. Indoor Navigation (Gemini-Guided + Depth)

### Architecture: Gemini Voice Guidance + Depth Safety

```
HONEST ASSESSMENT OF INDOOR POSITIONING:
├─ NEO-M8U UDR was designed for AUTOMOTIVE (wheel tick + gyro)
├─ Pedestrian UDR (no wheel ticks) drifts 5-10% of distance walked
├─ After 5 min walking in a mall: 20-50m position error
├─ Indoor beam pointing at specific coordinates WILL be wrong
└─ ACCEPT THIS LIMITATION. Don't pretend GPS works indoors.

WHAT ACTUALLY WORKS INDOORS (already built):
├─ Safety system: depth + YOLO → walls, stairs, obstacles (local, 100ms)
├─ Gemini voice: sees camera → describes what's ahead proactively
├─ OCR: reads signs, stall numbers, floor indicators (Hailo, local)
├─ Ask the AI: user asks → Gemini answers from camera view
└─ These are ALL local perception — no positioning needed

INDOOR NAVIGATION STRATEGY (Phase 1):
├─ NO indoor beam navigation (position too unreliable)
├─ Instead: "Gemini Guide Mode"
│   ├─ Gemini watches camera continuously (autonomous companion)
│   ├─ Proactively narrates: "escalator ahead" "exit sign to your right"
│   ├─ User asks: "where's the chicken rice?" → Gemini scans stalls
│   ├─ Depth keeps user safe from walls/obstacles
│   └─ This is how a sighted guide ACTUALLY helps indoors
├─ Beam stays OFF indoors (avoids pointing user in wrong direction)
├─ Beam resumes when GPS re-locks outdoors
└─ Safety system runs continuously regardless

INDOOR NAVIGATION STRATEGY (Phase 2 — after demo):
├─ WiFi fingerprinting (free, most SG malls have WiFi, ~3-5m accuracy)
├─ Or BLE beacon integration (if SAVH building installs them)
├─ Or visual SLAM-lite (YOLO landmark matching across frames)
└─ Only then: indoor beam with real position data
```

### ORIENTATION (BNO055 — which way is chest facing)

```
├─ Indoor: gyro-only mode (no magnetometer — metal interference)
├─ Still useful for: Gemini knowing which way user is facing
├─ Drift correction: OCR sign readings can help if known landmarks exist
└─ NOT used for navigation positioning — only for orientation context
```

### Floor Changes

```
├─ Escalator: Gemini detects → voice: "Escalator ahead, hold the railing"
├─ Elevator: Gemini reads buttons → "Press the fourth from bottom"
├─ OCR: read floor indicator → confirm correct floor
└─ Depth: detects stairs → safety alert "stairs going up/down"
```

### The Food Court Micro-Navigation

```
1. ENTER food court (GPS degrades / Gemini sees open space)
   Voice: "You're in the food court. Looking for chicken rice."

2. LOCATE target stall
   ├─ Pre-cached from research agent: "Stall 8, far right side"
   ├─ Gemini scans visible stalls: "I can see Stall 6... Stall 7... 
   │   keep going, two more"
   └─ OCR reads stall signs → match against target

3. NAVIGATE through tables
   Depth map → obstacle grid → beam follows clear path
   Voice handles warnings: "Table on your left, go around it"
   Beam smoothly weaves user through gaps (25Hz updates)
   Not a straight line — a flowing path following clearances

4. AT the stall
   Voice: "You're at the chicken rice stall. Counter in front of you."
   Queue: Gemini sees line → "About 5 people. End of queue on your left."
   Beam guides to queue end

5. ORDERING (social mode)
   System goes QUIET. Only speaks if asked.
   Monitors for when to step forward (queue gap detection)

6. FIND SEAT / RETURN
   Voice: "Got your food? Want a seat or heading back?"
   Seat: Gemini finds empty table → beam guides there
   Return: breadcrumb trail OR Google Maps reverse route
```

---

## 12. Transit Navigation (Bus + MRT)

### On The Bus

```
MONITORING (3 methods simultaneously):
├─ GPS tracking vs expected route stops
├─ Accelerometer stop detection (deceleration → door → acceleration)  
├─ LTA API: real-time bus position / next stop

Voice: "We're on bus 23. I'll tell you when to get off."
  "3 more stops... 2 more... next one is yours."
  "This is your stop. Press the bell now."
  "Doors are on your left."

WRONG BUS DETECTION:
  GPS route diverges from expected after 1-2 stops
  "This doesn't seem like the right route. Are you on bus 23?"
  If wrong: "Alight at the next stop, I'll reroute."

MISSED STOP:
  GPS passes destination
  "I think we passed your stop. Get off at the next one."
```

### MRT Ride

```
PRE-CACHE before entering station:
├─ Full route: which line, which direction, how many stops
├─ Transfer instructions (if line change needed)
├─ Exit number at destination
├─ All stored locally — works underground

RIDING:
├─ Stop counting (accelerometer + door detection)
├─ Announcement listening (mic picks up "Next station: Bugis")
├─ OCR through window (if platform name visible)
├─ All 3 methods vote → consensus

TRANSFER:
  Pre-cached: "Exit, follow blue line markers, down one level"
  OCR reads colored line indicators
  Beam guides through corridors
  Voice: step-by-step from cached instructions

EXIT:
  Back outside → GPS locks → confirms position → resume outdoor nav
```

---

## 13. The Research Agent

### Runs On Laptop Server (Heavy Processing)

```
PRE-TRIP RESEARCH (when user sets destination):

1. ROUTE IMAGES
   ├─ Google Street View API: image every 50m along route
   ├─ Resize to 160x120 (~10KB each, ~20 per route = 200KB)
   ├─ Store with: GPS coords, expected heading, text description
   └─ Gemini describes each: "Blue overhead bridge, 7-Eleven sign visible"

2. DESTINATION INFO
   ├─ Google Places API: photos, reviews, hours
   ├─ POI data: stall names, floor levels, entrance descriptions
   ├─ Gemini search: "Northpoint food court stall layout"
   └─ Operating hours: warn if destination closing soon

3. LANDMARK DATABASE (per route, stored in SQLite)
   ├─ image_thumbnail: 160x120 jpg
   ├─ gps: (lat, lon)
   ├─ description: "Blue bridge with metal railings"
   ├─ type: CHECKPOINT / TURN_POINT / DESTINATION / HAZARD
   ├─ expected_heading: 045° NE
   └─ features: ["7-Eleven sign", "overhead bridge", "red pillar"]

4. TRANSIT DATA
   ├─ LTA DataMall: bus routes, stops, timings
   ├─ MRT: line info, transfer instructions, exit data
   └─ Disruptions: service alerts, construction
```

### Continuous Discovery (During Journey, GPS-Triggered)

```
Every ~200m or new area:
├─ "What's notable near this GPS position?"
├─ POI search: shops, food, services within 200m
├─ Store to local DB for instant recall
├─ Available when user asks: "What's nearby?" → instant answer from cache
```

### Live Image Capture & Learning

```
During navigation:
├─ System captures frame when landmark matches expectations
├─ "Matched the overhead bridge — saving my own photo"
├─ Next visit: use OWN images (more relevant than Street View)
├─ Personal landmark database grows over time

ON-DEVICE MATCHING (works offline):
├─ NOT pixel comparison (too heavy)
├─ YOLO detects objects + OCR reads text
├─ Compare against landmark descriptions:
│   Expected: "7-Eleven sign" → OCR reads "7-Eleven" → MATCH
│   Expected: "overhead bridge" → YOLO detects bridge → MATCH
├─ 3/4 features match → "On track"
└─ 0/4 features match → "Off track, recalculating"
```

---

## 14. Connectivity & Offline Resilience

### Actual Detection (Never Guess From Location)

```python
class ConnectivityMonitor:
    """Check REAL connectivity. Never infer from location."""
    
    async def check_loop(self):
        while True:
            # Test 1: Laptop server reachable?
            laptop_ok, latency = await ping_websocket()
            
            # Test 2: Gemini Live connected?
            gemini_ok = gemini_live.is_connected()
            
            # Determine level from MEASUREMENTS, not assumptions
            if gemini_ok and latency < 0.2:
                self.level = 4  # FULL
            elif laptop_ok and latency < 1.0:
                self.level = 3  # DEGRADED
            elif laptop_ok:
                self.level = 2  # INTERMITTENT
            else:
                self.level = 1  # OFFLINE
            
            await asyncio.sleep(3)
```

MRT stations might have WiFi. Basements might have 4G. Open fields might have dead zones. **Never assume — always measure.**

### Graceful Degradation

```
LEVEL 4 → LEVEL 1 transition:

1. Gemini disconnects
2. Cache Gemini's last context
3. Voice: Gemini Live → Kokoro TTS (local)
4. "I've lost connection. Don't worry, I'm still guiding you."
5. Beam CONTINUES (fully local: IMU + GPS/dead-reckoning + depth)
6. Safety CONTINUES (fully local)
7. Route: follow cached waypoints
8. OCR: continues on Hailo (fully local)
9. When connection returns:
   Gemini reconnects, syncs position
   "I'm back online. Let me look around... yes, you're on track."
```

### What Always Works Offline

| Component | Online | Offline |
|-----------|--------|---------|
| 3D audio beam | ✅ | ✅ (GPS/IMU/depth = all local) |
| Safety alerts | ✅ | ✅ (Hailo depth, fully local) |
| Object detection | ✅ | ✅ (YOLO on Hailo, fully local) |
| OCR sign reading | ✅ | ✅ (Hailo PaddleOCR, fully local) |
| Voice instructions | Gemini Live | Kokoro TTS + cached text |
| Route following | Live + cached | Cached waypoints only |
| New route planning | ✅ | ❌ (needs API) |
| Bus arrivals | ✅ (LTA API) | ❌ (temporal voting OCR fallback) |
| Scene reasoning | ✅ (Gemini) | ❌ (YOLO + OCR + rules only) |
| Breadcrumb trail | ✅ | ✅ (fully local GPS/IMU log) |

---

## 15. Failure Scenarios — Exhaustive

### Connection Lost Mid-Navigation
- Beam continues from cached route + local sensors
- Voice switches to Kokoro TTS
- Safety 100% unaffected
- "I've lost connection. Following saved route."

### Microphone Not Working / Too Noisy
- System detects: no voice input for extended period in noisy environment
- "I'm having trouble hearing you. Switching to automatic mode."
- Makes all decisions autonomously (pick nearest option)
- Gesture fallback: nod = yes, head shake = no (camera detection)
- Navigation NEVER stops because mic failed

### Headphone Disconnects (Bluetooth)
- Haptic motor takes over for all warnings (vibration patterns)
- Try reconnect every 10 seconds
- If RPi5 has speaker: mono voice output (no HRTF, but audible)
- "Headphones disconnected. Using vibration alerts."

### Camera Blocked / Dirty / Wet
- Detect: all-dark or blurry frames for >3 seconds
- "My camera's blocked. Can you check it?"
- GPS + IMU navigation continues (no vision)
- Safety: "I can't see obstacles. Please use your cane."

### Low Battery
- 20%: "Battery low. Want me to guide you home?"
- 10%: "Battery at 10%. Reduced processing. Navigation still active."
- 5%: "Critical battery. Saving your location. Notifying [contact]."
- Shutdown: save GPS + route state → resume on next boot

### Rain
- Increase audio volume
- Haptic more prominent (rain doesn't affect vibration)
- "Ground may be slippery, be careful."
- Camera wet → warn user, rely more on GPS/IMU
- Suggest sheltered routes if re-routing

### GPS Drift (Wrong Side of Road)
- Gemini sees camera → corrects via visual context
- "You seem to be on the road, move left toward the sidewalk"

### Wrong Bus Boarded
- GPS route diverges after 1-2 stops
- "This doesn't seem like the right route. Alight at next stop."

### Missed MRT Stop
- Stop count exceeds expected → "I think we passed your stop."

### Stall Closed
- Gemini sees shutters → "This stall looks closed."
- Auto-find alternative → "Another chicken rice two stalls down."

### Elevator Floor Detection
- IMU detects vertical motion + count door events
- OCR reads floor indicator
- Camera + Gemini reads buttons: "Press the fourth from bottom"

### Someone Talks To The User (Social Mode)
- Detect: conversation happening (speaker diarization)
- System goes QUIET. Beam continues at very low volume.
- After 5s silence: "Ready to keep going?"

### Complete Confusion / Panic
- "Don't worry. Let me figure out where you are."
- GPS + camera + OCR → describe location
- Breadcrumb trail → "I can guide you back the way you came."
- Emergency: "Shall I call [contact]?"

### Multiple Food Courts Found
- Pick nearest (user said "nearest")
- If ambiguous: "I found 3 options. Northpoint is 300m. Kopitiam is 500m. Which?"
- Learn preference over time

### Infrastructure Changes (New Construction)
- Gemini sees camera → "Construction barrier ahead, looking for a way around"
- Re-query Google Maps for updated route
- If offline: "Path seems blocked. Let me find another way." (depth-guided detour)

### System Crash / Freeze
- Audio stops → user notices immediately
- Auto-restart within 5 seconds (systemd watchdog)
- "Sorry, had to restart. Let me get my bearings."
- Load saved state → resume navigation

---

## 16. Privacy & PDPA Compliance

### Physical Privacy Shutter
- 3D-printed sliding cover over camera lens
- GPIO reed switch detects open/closed
- Closed: `camera.release()` — no frames captured period
- Visible to public: camera is physically covered

### Software Privacy Mode
- Voice command: "Privacy mode"
- Camera feed killed, Gemini video stopped
- Navigation continues on IMU + GPS only
- "Camera off. Using sensors only. Say 'camera on' to re-enable."

### Data Policy
- Camera NEVER stores video by default (process frame, discard)
- Landmark images: descriptions only, not photos of people
- Gemini Live: no server-side frame storage (Google Gemini API policy)
- User can opt into landmark photo saving (of buildings, not people)

### Restroom Scenario
- User approaches restroom → system prompts: "Want me to turn off the camera?"
- Privacy shutter: physically close
- OR voice command: "Privacy mode"
- Re-enable: open shutter or "camera on"

---

## 17. Real-World Scenarios — Full Walkthrough

### Scenario: Home → Northpoint Food Court → Chicken Rice → Home

```
HOME:
  System boots → chime → "Good morning. System ready. GPS locked. Battery 85%."
  User: "Take me to Northpoint food court for chicken rice."
  
RESEARCH (3-5 seconds):
  Laptop research agent:
  ├─ Google Maps: walking route, 15 min, 1.2km
  ├─ Northpoint food court: Level 4, chicken rice at Stall 8
  ├─ Operating hours: 10am-9pm (OK)
  ├─ Route landmarks: overhead bridge at 400m, cross Tampines Ave at 600m
  ├─ LTA API: any bus option? (walking is fastest)
  └─ All cached to SQLite

  Voice: "Northpoint City is about a 15 minute walk. 
  There's a chicken rice stall on Level 4. I'll guide you there."
  
  Beam: activates, pointing northeast (first waypoint direction)
  
WALKING (outdoor navigation):
  Beam: continuous 3D pulse, adjusts for heading changes
  Voice: "Keep going straight on this path."
  
  400m in: "The overhead bridge is coming up. Stairs ahead."
  Depth detects stairs → voice: "Stairs going up, about 15 steps."
  Safety: monitors each step via depth
  
  600m in: "Road crossing ahead."
  Voice: "Road crossing detected. Check it's safe before crossing."
  Beam: pauses. User crosses using their normal method.
  GPS confirms user is on the other side → beam resumes.
  
  1km in: "Northpoint City is ahead on your right."
  GPS accuracy starts degrading → system prepares for indoor mode

ENTERING MALL:
  Gemini: "I can see the entrance. Glass doors ahead."
  Beam: guides to entrance, then turns OFF indoors
  "You're inside. I'll guide you with my voice from here."
  Mode: switches to INDOOR (Gemini Guide Mode)
  
FINDING ESCALATOR:
  Voice: "Food court is on Level 4. Looking for the escalator."
  Gemini sees escalator → "Escalator ahead, about 15 meters. Going up."
  Safety: depth warns about obstacles along the way
  
  At escalator edge:
  Voice: "Step on when ready. Hold the railing."
  User steps on using cane + railing (their normal method)
  
  Level 2... 3... 4:
  OCR reads floor sign: "L4"
  Voice: "Level 4. Step off. Food court is to your right."
  
IN FOOD COURT:
  Voice: "Looking for the chicken rice stall."
  Gemini scans: "I can see Japanese on the left... Western... 
  Keep going, Tian Tian Chicken Rice is ahead!"
  
  Safety: depth warns about tables/obstacles
  Voice: "Table on your right, go around. Straight now. Almost there."
  "You're at the chicken rice stall."
  
ORDERING:
  "Counter is right in front of you."
  Gemini sees queue: "About 4 people in line. End is to your left."
  Beam: guides to queue end
  System goes quiet during wait (monitors queue movement)
  At counter: available if called. "The menu shows $4.50 for chicken rice."
  
AFTER ORDERING:
  Voice: "Got your food? Want to find a seat or head back?"
  User: "Find a seat"
  Gemini: "Empty table to your right, about 4 meters."
  Voice guides to table. "Chair is in front of you."
  
EATING (system on standby, safety only)

RETURN:
  User: "Let's go back"
  Voice: "Heading home. Let me find the down escalator."
  
  Down escalator: Gemini finds it
    Voice: "Escalator going down. Hold the railing."
  
  Exit mall → GPS locks → beam resumes → outdoor navigation
  Reverse route to home
  Arrival chime: "You're home."
```

---

## 18. Phase Roadmap (V1.0 → V3.0)

### PHASE 1 — "THE DAILY WIN" (For SAVH Demo)

```
ALREADY BUILT (production-ready):
├─ Safety: walls, stairs, curbs, overhead, approaching objects ✅
├─ Depth: Hailo monocular 224×224 @ 3ms, 6 hazard types ✅
├─ YOLO: 11n-NCNN, 80 classes, 80ms ✅
├─ Spatial audio: OpenAL HRTF, body-relative, comfort presets ✅
├─ Gemini Live: audio-to-audio WebSocket, video streaming ✅
├─ TTS: Kokoro local + Gemini cloud, smart routing ✅
├─ VAD + Whisper STT ✅
├─ Privacy shutter: GPIO reed switch ✅
├─ Haptic: PWM vibration, 3 patterns ✅

SPRINT BUILDS (new code for demo):
├─ Google Maps Directions API → waypoint list (~150 LOC)
├─ Navigation loop: waypoint follower + beam driver (~250 LOC)
├─ LTA DataMall API: bus arrival announcements (~150 LOC)
├─ Bus stop nearest lookup + SQLite cache (~100 LOC)
├─ Bus stop mode: YOLO bus tracking + LTA voice (~200 LOC)
├─ Voice turn announcements at waypoints (~80 LOC)
├─ Autonomous Gemini prompt (proactive companion) (~50 LOC)
├─ Scene change detector for Gemini trigger (~150 LOC)
├─ Total new code: ~1,130 lines
```

### PHASE 2 — "FULL JOURNEY"

```
├─ Indoor beam navigation (WiFi fingerprinting or BLE beacons)
├─ Occupancy grid + A* pathfinding for obstacle avoidance
├─ Door detection (bus, building) via YOLO fine-tuning
├─ Temporal voting OCR for bus number LED panels
├─ End-to-end transit: walk + bus + MRT + walk
├─ Offline resilience (pre-cache, graceful degradation)
├─ Research agent (pre-trip landmarks, Street View images)
├─ SmolVLM-256M as offline Gemini fallback
├─ Mandarin support
├─ Return trip planning (breadcrumbs + reverse routes)
├─ Rain mode, crowd mode
├─ Emergency protocol ("I'm lost", fall detection)
```

### PHASE 3 — "ECOSYSTEM"

```
├─ Crowdsourced mapping (Supabase sync between users)
├─ Route learning (saved routes, familiarity-based verbosity)
├─ Multi-destination trips
├─ OTA update system
├─ Companion phone app (backup input, emergency contacts)
├─ Manufacturing preparation
```

---

## 19. SAVH Demo Scope

### What We're Demonstrating

A controlled demo at the SAVH building + nearby outdoor route. NOT a "full journey" demo. 
The goal: prove the wearable provides **meaningful independence gain** for daily tasks.

### 4-Station Demo Protocol

| Station | Location | What We Show | Success Metric |
|---------|----------|-------------|----------------|
| 1. Indoor Safety | SAVH building corridors + stairs | Wall/stair/obstacle detection + voice alerts | 100% of walls/stairs detected, 0 false negatives |
| 2. Ask AI | SAVH building interior | "What's in front of me?" → Gemini describes scene | Accurate scene description within 2 seconds |
| 3. Outdoor Nav Beam | Sidewalk near SAVH | 3D audio beam guides to a waypoint ~200m away | User follows beam to destination without wrong turns |
| 4. Bus Arrival | Nearest bus stop | LTA API announces next bus arrivals by voice | Correct bus number + accurate ETA announced |

### Safety Requirements

- **Human safety supervisor** walks alongside user at ALL times
- Supervisor has kill-switch (voice command: "Cortex stop")
- Demo route pre-walked by team, hazards noted
- First run: sighted team member wears device, eyes open
- Second run: sighted team member, eyes closed (simulated)
- Third run: SAVH tester (with supervisor)

### Pre-Visit Checklist

```
□ LTA DataMall API key approved and tested
□ Google Maps API key active with billing
□ Battery fully charged (target: 2+ hour runtime)
□ Demo route cached offline (in case of connection loss)
□ Spare battery pack
□ Laptop running dashboard for monitoring (optional)
□ Shokz/open-ear headphones charged
□ Privacy shutter tested (open/close)
□ 5-minute stress test passed (CPU <80%, temp <75°C)
□ Audio levels calibrated for outdoor noise
```

### What We Explicitly DO NOT Demo

- Indoor beam navigation (GPS drift too high indoors)
- Bus door detection (unreliable, Phase 2)
- Bus boarding guidance (safety risk without more testing)
- End-to-end transit journey (bus + MRT + walk)
- Rain/crowd modes (not built)

---

## 20. Sprint Plan

### Prerequisites (Do These BEFORE Day 1)

```
□ Register for LTA DataMall API key (1-3 business days approval)
□ Set up Google Maps Directions API + billing account
□ Verify NEO-M8U GPS is receiving fixes on RPi5
□ Run htop/free stress test on RPi5 with current full pipeline
```

### DAY 1: Google Maps API + Waypoint Engine

The foundation — outdoor navigation starts here.

```
rpi5/layer3_guide/navigation_engine.py (NEW, ~250 LOC):
├─ google_maps_route(origin, destination) → List[Waypoint]
│   ├─ HTTP request to Directions API (walking mode)
│   ├─ Parse polyline → lat/lng waypoints every ~20m
│   ├─ Extract turn-by-turn instructions
│   └─ Cache route to SQLite for offline use
├─ WaypointFollower class:
│   ├─ get_bearing_to_next(current_pos) → degrees
│   ├─ get_distance_to_next(current_pos) → meters
│   ├─ check_arrival(current_pos, threshold=10m) → bool
│   └─ advance_waypoint() → next waypoint + voice announcement
└─ Integration with existing GPS handler (gps_handler.py)

Test: API returns valid route, waypoints parse correctly
```

### DAY 2: Navigation Beam + Voice Turns

Wire waypoints into the existing spatial audio system.

```
rpi5/layer3_guide/navigation_engine.py (extend):
├─ Navigation main loop (async, 25Hz):
│   ├─ Read M8U position
│   ├─ Calculate bearing to next waypoint
│   ├─ Read BNO055 heading → relative angle
│   ├─ Update beam position via OpenAL HRTF
│   └─ Adjust pitch + ping rate by distance
├─ Voice turn announcements:
│   ├─ "Turn right in 15 meters"
│   ├─ "You've arrived at your destination"
│   └─ Use Kokoro TTS (local, no latency)
├─ Beam behavior:
│   ├─ Points directly at waypoint (Phase 1 — no obstacle avoidance)
│   ├─ Safety system handles obstacle warnings separately
│   └─ Beam pauses at road crossings

Test: Walk a 200m outdoor route with beam guidance
```

### DAY 3: LTA Bus API + Bus Stop Mode

```
rpi5/layer3_guide/bus_handler.py (NEW, ~250 LOC):
├─ LTA DataMall integration:
│   ├─ find_nearest_bus_stop(lat, lng) → BusStop
│   │   (pre-loaded SQLite table of all SG bus stop codes + coords)
│   ├─ get_bus_arrivals(stop_code) → List[BusArrival]
│   │   (GET /BusArrivalv2, refresh every 30s)
│   └─ Format arrival as voice: "Bus 23, arriving in 3 minutes"
├─ Bus stop mode:
│   ├─ Triggered when GPS within 30m of known bus stop
│   ├─ Voice announces: "You're near bus stop 12345"
│   ├─ Periodic arrival announcements (every 60s or on change)
│   ├─ YOLO detects "bus" class → voice: "A bus is approaching"
│   └─ Fallback if API down: "I can't check arrivals. Ask the driver."

Test: Query real bus stop, verify arrival data matches app
```

### DAY 4: Autonomous Gemini + Indoor Tuning

```
Autonomous Gemini (~200 LOC):
├─ Update system prompt in gemini_live_handler.py
│   (chatbot → proactive companion, as specified in §6)
├─ SceneChangeDetector class:
│   ├─ Track recent YOLO classes (5-second window)
│   ├─ Track average depth changes
│   ├─ Trigger narration on significant change
│   └─ Cooldown: min 5 seconds between unprompted speech
├─ Context injection:
│   ├─ Append sensor state to each video frame metadata
│   └─ GPS, nav mode, recent safety alerts, battery

Indoor tuning for SAVH building:
├─ Adjust safety thresholds for indoor corridors
│   (walls closer, lower ceilings, glass doors)
├─ Test stair detection on SAVH staircase
├─ Test Gemini Guide Mode: walk SAVH corridors, verify narration
├─ Calibrate voice volume for indoor echoes

Test: Walk SAVH hallways, Gemini narrates meaningfully
```

### DAY 5: Integration + Stress Test

```
Full pipeline integration:
├─ All systems running simultaneously:
│   YOLO + Hailo depth + safety + nav beam + Gemini + TTS
├─ Mode auto-switching:
│   ├─ GPS quality → outdoor/indoor mode switch
│   ├─ Bus stop proximity → bus stop mode
│   └─ Voice command: "navigate to [place]" starts route
├─ Connection loss handling:
│   ├─ Gemini drops → Kokoro TTS announces "offline mode"
│   ├─ Cached route continues with beam
│   └─ Safety pipeline unaffected (fully local)

Stress test (5 minutes continuous):
├─ htop: verify CPU <80% sustained
├─ free -h: verify RAM <3GB
├─ vcgencmd measure_temp: verify <75°C
├─ hailortcli monitor: verify NPU responsive
├─ Fix any bottlenecks found

Test: Run full pipeline for 10 minutes, no crashes
```

### DAY 6-7: Real-World Testing

```
Day 6 — Outdoor route test:
├─ Walk a ~500m route near SAVH building
├─ Verify: beam guides correctly, turns announced, arrival detected
├─ Verify: safety alerts during walk (walls, curbs, obstacles)
├─ Verify: road crossing detection + "check it's safe" warning
├─ Test: connection loss midway → verify graceful degradation
├─ Fix any issues found

Day 7 — Bus stop + integration test:
├─ Go to nearest bus stop
├─ Verify: LTA arrivals announced correctly
├─ Verify: YOLO detects approaching bus
├─ Full scenario: navigate to bus stop → wait → hear arrivals
├─ Run the 4-station demo protocol (§19) end-to-end
├─ Fix any issues found
```

### DAY 8: Demo Prep + Buffer

```
├─ Run 4-station demo protocol twice (full rehearsal)
├─ Record demo video for backup
├─ Charge all batteries
├─ Prepare: spare headphones, spare battery, offline route cache
├─ Contingency: if anything broke on Day 6-7, fix here
├─ Print simple user instruction card for SAVH tester
```

### Schedule Risk

This plan is tight but achievable because ~70% of the system is already built and tested. The sprint builds ~1,130 lines of new code. The biggest risks are:
1. **LTA API key not approved in time** → fallback: demo without bus station (3 stations instead of 4)
2. **M8U GPS not locked at SAVH location** → test location beforehand, have backup coords
3. **Hailo scheduling conflict** → unlikely (depth-only in Phase 1), but profile on Day 5

---

## 21. Testing Methodology

### 5-Level Testing Progression

Each level gates the next. Do NOT advance until the current level passes.

#### Level 0: Desk Tests (No Hardware)
```
├─ Unit tests: pytest tests/ -v
├─ API tests: Google Maps returns valid route, LTA returns bus data
├─ Navigation math: bearing calculation, distance formula, waypoint arrival
├─ SceneChangeDetector: mock frames, verify trigger logic
├─ Can run on laptop (no RPi5 needed)
├─ Gate: all tests pass, no crashes
```

#### Level 1: Bench Tests (RPi5 on Desk)
```
├─ Full pipeline boot: power on → "System ready" (no movement)
├─ Camera: frames flowing to YOLO + Hailo + Gemini
├─ Safety: hold objects in front of camera → verify detection
├─ Audio: beam sound plays, voice alerts play
├─ GPS: verify M8U gets fix (window/outdoor antenna)
├─ Stress test: 5 min continuous, check CPU/RAM/temp
├─ Gate: all sensors reading, no crashes, metrics in budget
```

#### Level 2: Controlled Outdoor Walk (Sighted, Eyes Open)
```
├─ Team member wears device, walks pre-planned 200m route
├─ Verify: beam points toward destination
├─ Verify: turns announced at correct locations
├─ Verify: safety alerts for real obstacles (poles, walls, curbs)
├─ Verify: arrival detection at destination
├─ Log: latency measurements, false positive count
├─ Gate: beam direction correct >90%, safety alerts >95%, no false negatives
```

#### Level 3: Simulated Blind Test (Sighted, Eyes Closed)
```
├─ Same team member, same route, eyes closed
├─ Safety supervisor walking alongside (arms-length distance)
├─ Can the user follow the beam to the destination?
├─ Does safety warn about all obstacles before contact?
├─ Are voice announcements timely and clear?
├─ Gate: user reaches destination without supervisor intervention
```

#### Level 4: SAVH User Test
```
├─ Run 4-station demo protocol from §19
├─ SAVH tester + safety supervisor
├─ Collect feedback:
│   ├─ Was the beam intuitive to follow?
│   ├─ Were voice alerts helpful or annoying?
│   ├─ Audio volume OK for environment?
│   ├─ Would they use this daily?
│   └─ What would they change?
├─ Gate: user completes at least 3/4 stations successfully
```

### Latency Targets (Measure at Each Level)

| Component | Target | Method |
|-----------|--------|--------|
| Safety alert | <100ms from detection | Timestamp logging |
| Beam update | <40ms (IMU cycle) | HRTF position update rate |
| Voice response | <1s (Gemini Live) | End-to-end from query |
| Turn announcement | <2s before turn point | GPS distance calc |
| Bus arrival query | <3s (LTA API) | API response time |

---

## 22. BOM & Cost Target

| Component | Model | Est. Cost |
|-----------|-------|-----------|
| Compute | RPi5 4GB | $80 |
| Camera | Camera Module 3 Wide (IMX708, 130° FOV) | $35 |
| AI Accelerator | Hailo-8L M.2 NPU (13 TOPS) | $70 |
| IMU | BNO055 9-axis (I2C 0x29) | $30 |
| GPS + UDR | NEO-M8U (UART, Untethered Dead Reckoning) | $25 |
| Haptic | Vibration motor (GPIO 18) | $2 |
| Audio | Open-ear headphones | $30 |
| Privacy | 3D-printed shutter + reed switch | $1 |
| Power | 5V 3A battery + USB-C PD | $20 |
| Enclosure | IP-rated case | $15 |
| Misc | Wires, PCB, connectors | $10 |
| **TOTAL** | | **~$318** |

---

## Appendix: Design Philosophy

> "The product must be responsive, waterproof, and easy to use for the aging population." — SAVH Advocate

> "Independence in navigation and bus number detection is the priority." — SAVH Advocate

> "Visually impaired people will always carry a white cane as safeguard." — SAVH Advocate

We build the **intelligent layer** the cane cannot provide: what's far away, what's overhead, what needs reasoning. We guide with **one sound and one voice**. We work when the internet dies. We never put silicone in their ears. We never point them at moving traffic. We never film them in a restroom.

**Simplicity is the feature.**
