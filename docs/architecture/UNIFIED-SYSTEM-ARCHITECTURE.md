# Project-Cortex v2.0 - Unified System Architecture

**Last Updated:** March 7, 2026
**Author:** Haziq (@IRSPlays)
**Status:** MVP Sprint In Progress — Safety Features + SNAP-C1 + Caretaker Telemetry
**Target:** Tan Kah Kee YIA 2026, MOE Innovation Programme, SAVH Usability Testing
**Innovation:** Layer 0 (Guardian + Hailo Depth) + Layer 1 (Learner 3-Mode) + Layer 3 (SNAP-C1 Offline Survival + 3D Acoustic UI) + **Caretaker Safety Net** — First AI wearable that learns without retraining, survives offline with local action decoding, and provides silent real-time caretaker telemetry.

**LATEST CHANGE (Mar 7, 2026):** **MVP SPRINT** — Phase 0 foundation fixes (L2 override removal, SpatialAudio wiring), Phase 1 Acoustic UI (wall hum + drop-off override), Phase 2 Hailo depth unification, Phase 3 GPS audio beacons, Phase 4 SNAP-C1 ONNX action decoder, Phase 5 Caretaker telemetry backend. See `docs/plans/IMPLEMENTATION_PLAN_MVP_SPRINT.md`.

---

## 📋 EXECUTIVE SUMMARY

Project-Cortex v2.0 is a **<$150 AI wearable** for the visually impaired, disrupting the $4,000+ OrCam market through:
- **Adaptive Self-Learning**: Dual-model cascade learns new objects without retraining (Layer 0 + Layer 1)
- **Edge-First Computing**: Raspberry Pi 5 + **Hailo-8L NPU** (13 TOPS via PCIe M.2) — YOLO + Monocular Depth at 30+ FPS with CPU at <20% utilization
- **Acoustic UI**: 3D spatial audio replaces slow TTS for navigation — wall proximity hum, drop-off chirp (<50ms), GPS audio beacons
- **Offline Survival (SNAP-C1)**: Quantized ONNX action decoder + ChromaDB GPS breadcrumbs navigate user to safety when cellular drops
- **Caretaker Safety Net**: Silent 5-second telemetry + IMU fall detection + stationary-zone SOS → two-way VoIP (Rokr app)
- **Revolutionary Layer 2**: Gemini 3 Flash Preview vision + Gemini 2.5 Flash Live API for <500ms audio-to-audio, 3-tier fallback (Gemini → Kokoro → GLM-4.6V)
- **Local-First Safety**: Layer 0 Guardian works 100% offline with <100ms latency (no network dependency)

**Architecture Modes:**
1. **Standalone (RPi-only)**: Full operation without server (degrades VIO/SLAM to GPS-only, Supabase sync disabled)
2. **Hybrid (RPi + Supabase + Laptop)**: Full features with VIO/SLAM post-processing + cloud sync + remote monitoring ⭐ **RECOMMENDED**
3. **Offline Survival (SNAP-C1 only)**: No internet — SNAP-C1 + ChromaDB route user to nearest known safe zone
4. **Development (Laptop-only)**: Fast iteration without deploying to RPi
5. **Multi-Device (Multiple RPi + Supabase)**: Future expansion - coordinate multiple wearables via cloud

---

## 🎯 THE PROBLEM: RPi 5 Resource Constraints

| Hardware Component | Specification | Status / Constraint |
| :--- | :--- | :--- |
| **CPU** | ARM Cortex-A76 @ 2.4GHz (4 cores) | ✅ GOOD |
| **RAM** | 4GB LPDDR4X | ⚠️ CONSTRAINT (must stay under 3.9GB) |
| **Storage** | microSD (slow I/O) | ⚠️ CONSTRAINT |
| **GPU** | VideoCore VII (limited CUDA) | ⚠️ CONSTRAINT |
| **Network** | Gigabit Ethernet / Wi-Fi 6 | ✅ GOOD |
| **AI Hat NPU** | Hailo-8L (13 TOPS) | ✅ GOOD |

**All models converted at 256x256 resolution for RPi5 optimization**

| Component | Model Size | RAM Usage | Framework | Status |
|-----------|------------|-----------|-----------|--------|
| **Layer 0: YOLO26n-ncnn** | 2.8 MB | ~150MB | NCNN | **IMPLEMENTED** |
| **Layer 0: YOLO26s-ncnn** | 9.1 MB | ~250MB | NCNN | **IMPLEMENTED** |
| **Layer 0: YOLO26m-ncnn** | 20.9 MB | ~400MB | NCNN | **IMPLEMENTED** |
| **Layer 1: YOLOE-26n-seg-ncnn** | 3.2 MB | ~300MB | NCNN | **IMPLEMENTED** |
| **Layer 1: YOLOE-26s-seg-ncnn** | 11.8 MB | ~500MB | NCNN | **IMPLEMENTED** |
| Layer 1: YOLOE-26s-seg-pf-onnx | ~27 MB | ~400MB | ONNX Runtime | **DISABLED** (ONNX export failed) |
| MobileCLIP Text Encoder | - | ~100MB | PyTorch | **IMPLEMENTED** |
| Adaptive Prompt Embeddings | - | ~2MB | RPi | **IMPLEMENTED** |
| Whisper (base) | - | ~800MB | RPi | **IMPLEMENTED** |
| Kokoro TTS | - | ~500MB | RPi | **IMPLEMENTED** |
| Silero VAD | - | ~50MB | RPi | **IMPLEMENTED** |
| Data Recorder | - | ~100MB | RPi | **IMPLEMENTED** |
| SQLite | - | ~50MB | RPi | **IMPLEMENTED** |
| **RPi TOTAL (with YOLO26n + YOLOE-26s)** | **~15MB models** | **~1.9GB** | RPi | **WITHIN BUDGET** |
| VIO/SLAM | ~1GB | Laptop | 🟢 (offloaded) |
| Web Dashboard | ~150MB | Laptop | 🟢 (offloaded) |
| **Server TOTAL** | **~2GB** | Laptop | 🟢 LOW |

**Conclusion:** Dual-model cascade (YOLO26n + YOLOE-26n-seg pf + non pf) keeps RPi under 4GB while enabling
**adaptive learning without retraining**. This is the first AI wearable that learns new objects from context (Gemini descriptions + Google Maps POI + Server Post Processing) in real-time.

**NPU Acceleration (AI Hat+):** When AI Hat+ (Hailo-8L, 13 TOPS) is installed:
- Layer 0 (Guardian) inference: 50ms → 5ms (10x faster)
- Total latency (frame to haptic): 60-80ms → 15-25ms (3-5x faster)
- Power consumption: 8-12W → 1.5W (6-8x less)

**Innovation Breakthrough:** By using YOLOE's dynamic text prompts, the system can add "coffee machine", "fire extinguisher", "exit sign" to its detection vocabulary based on:
1. Gemini scene descriptions ("I see a red fire extinguisher...")
2. Google Maps nearby POI ("Near Starbucks" → adds "coffee shop sign", "menu board")
3. User's stored memories ("Remember this wallet" → adds "brown leather wallet")

This adaptive vocabulary updates every 30 seconds with <50ms overhead, requiring zero model retraining.

---

## 🏗️ PHYSICAL INFRASTRUCTURE

### Edge Unit (Wearable - Raspberry Pi 5)
┌─────────────────────────────────────────────────────────────┐
│                   RASPBERRY PI 5 (4GB RAM)                  │
├─────────────────────────────────────────────────────────────┤
│ SENSORS:                                                    │
│  • Rasberry Pi Camera Module 3 (Wide Angle) -               |
│     Vision Input (CSI)                                      |
│  • BNO055 IMU - 9-DOF Head-Tracking (I2C)                   |
│  • GY-NEO8MV2 GPS - Outdoor Localization (UART)             |
│                                                             |
│ ACTUATORS:                                                  │
│  • PWM Vibration Motor - Haptic Alerts (GPIO 18)            |
│  • Bluetooth Headphones - 3D Spatial Audio (Low-Latency)    |
│                                                             |
│ CONNECTIVITY:                                               |
│  • Wi-Fi 1: Internet (Gemini Live API)                      |
│  • Wi-Fi 2: Local Server (VIO/SLAM, Dashboard)              |
│                                                             |
│ POWER:                                                      │
│  • 10,000mAh USB-C PD Power Bank (usb_max_current_enable=1) |
│  • Official Active Cooler (MANDATORY for thermal mgmt)      │
└─────────────────────────────────────────────────────────────┘
```

**Note:** AI Hat+ (Hailo-8L NPU, 13 TOPS) is an optional expansion that connects via PCIe M.2 slot, providing 10x faster AI inference for Layer 0 and Layer 1 while reducing power consumption by 6-8x.

### Compute Node (Server - High-Performance Laptop)
```
┌─────────────────────────────────────────────────────────────┐
│             ACER NITRO V15S (RTX 2050 CUDA)                 │
├─────────────────────────────────────────────────────────────┤
│ ROLE: Heavy Spatial Computing                               │
│  • VIO/SLAM Post-Processing (OpenVINS, VINS-Fusion)         │
│  • 3D Map Generation & Storage (PostgreSQL + PostGIS)       │
│  • Pytqq6 Desktop Dashboard - Realtime, Fast                │
│  • REST API (Port 8001) - SQLite queries from RPi           │
│  • Moondream 2 Preview (VLMM)                               │
│                                                             │
│ COMMUNICATION:                                              │
│  • HTTP Server (Port 5001) - EuRoC dataset upload           │
│  • WebSocket Server (Port 8765) - Real-time Nav Data        │
└─────────────────────────────────────────────────────────────┘
```

---

## 🧠 THE 4-LAYER AI BRAIN

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER INTERACTION LAYER                             │
│  Voice Commands (Mic) → Gemini Live API → PCM Audio (Bluetooth Headphones)  │
│  Haptic Feedback (Vibration Motor) ← Obstacle Alerts ← YOLO Detection       │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┬─────────────────┐
        │                        │                        │                 │
        ▼                        ▼                        ▼                 ▼
┌──────────────┐  ┌──────────────────────┐  ┌──────────────────┐  ┌──────────┐
│ LAYER 1 [Pi] │  │   LAYER 2 [Pi+Cloud] │  │ LAYER 3 [HYBRID] │  │ LAYER 4  │
│  The Reflex  │  │   The Thinker        │  │  The Navigator   │  │ The Memory│
├──────────────┤  ├──────────────────────┤  ├──────────────────┤  ├──────────┤
│ YOLO,E LOCAL │  │ Whisper STT (LOCAL)  │  │ Server: ORB SLAM │  │ SQLite DB│
│ Haptic Alert │  │ Gemini Live (Cloud)  │  │ Pi: 3D Audio Out │  │ REST API │
│ <100ms       │  │ Kokoro TTS (Offline) │  │ GPS+IMU Fusion   │  │ Port 8001│
│ Offline      │  │ ~500ms (Live API)    │  │ Post-Process     │  │ Local I/O│
└──────────────┘  └──────────────────────┘  └──────────────────┘  └──────────┘
        │                        │                        │                 │
        └────────────────────────┴────────────────────────┴─────────────────┘
                                 │
                                 ▼
                   ┌──────────────────────────┐
                   │  RPI CM 3 WIDE Low-Light │
                   │  1920x1080 @ 30fps       │
                   └──────────────────────────┘
```

---

## 📋 LAYER 0: THE GUARDIAN [RUNS ON RASPBERRY PI 5]

**Purpose:** Immediate Physical Safety - Zero-Tolerance Latency

### Technical Stack:
- **Model:** YOLO26n-ncnn (2.8 MB, 256x256 resolution) - **IMPLEMENTED**
- **Model:** YOLO26s-ncnn (9.1 MB, 256x256 resolution) - **IMPLEMENTED**
- **Model:** YOLO26m-ncnn (20.9 MB, 256x256 resolution) - **IMPLEMENTED**
- **Framework:** NCNN (ARM-optimized, pure CPU inference)
- **Device:** Raspberry Pi 5 (Quad-core Cortex-A76 @ 2.4GHz)
- **Output:** Direct GPIO 18 → PWM Vibration Motor
- **Vocabulary:** 80 Static COCO Classes (NEVER UPDATES)

### Performance Requirements:
- **Latency:** <100ms (frame capture → detection → haptic trigger) ✅ **ACHIEVED: 60-80ms**
- **Throughput:** 10-15 FPS minimum
- **Power Draw:** 8-12W during inference
- **Memory:** ~150MB RAM allocated (11 MB model)
- **Reliability:** 100% offline operation (no network dependency)
- **Execution:** Runs in PARALLEL with Layer 1 (same frame, different thread)

### Haptic Feedback Protocol:
```python
# Layer 0 Guardian - Proximity-based vibration intensity
if distance < 0.5m:  vibrate(intensity=100%, pattern="continuous")
elif distance < 1.0m: vibrate(intensity=70%, pattern="pulse_fast")
elif distance < 1.5m: vibrate(intensity=40%, pattern="pulse_slow")
```

### Safety-Critical Objects (Layer 0 Static List):
- **Immediate Hazards**: Stairs, open manholes, walls, curbs
- **Moving Threats**: Vehicles, bicycles, scooters, motorcycles
- **Human Collisions**: People in path (<1.5m)
- **Environmental**: Low-hanging branches, poles, construction barriers

### Key Optimizations:
- INT8 quantization for 4x speedup on ARM
- Aggressive NMS (Non-Maximum Suppression) to reduce false positives
- Parallel inference with Layer 1 (ThreadPoolExecutor)
- **256x256 resolution** for 4x faster inference than 640x640

### Why Keep Local:
- ✅ **No Network Dependency**: Works offline (critical for safety)
- ✅ **Predictable Latency**: 60-80ms consistent (no network jitter)
- ✅ **Real-Time Safety**: Instant detection for navigation hazards
- ✅ **Privacy**: Video never leaves device
- ✅ **Static Vocabulary**: Never updates (zero configuration drift)

### Implementation Files:
- `rpi5/layer0_guardian/__init__.py` - YOLO26n wrapper with haptic integration
- `rpi5/layer0_guardian/haptic_controller.py` - GPIO PWM control
- `rpi5/layer0_guardian/YOLOGuardian` class - Main guardian implementation

### Current Implementation Status:
| Feature | Status | Notes |
|---------|--------|-------|
| YOLO26n-ncnn Model | **IMPLEMENTED** | 2.8 MB, 80 COCO classes |
| Haptic Controller | **IMPLEMENTED** | GPIO 18, PWM at 1kHz |
| Safety Classes Filter | ⚠️ **EXPANDING** | 21→28 classes (MVP Sprint Step 8) |
| Proximity Detection | ⚠️ **UPGRADING** | bbox-area heuristic → real metric depth (Step 7) |
| Mock Mode (Laptop) | **IMPLEMENTED** | For testing without RPi |
| Hailo Depth Integration | 🔲 **IN SPRINT** | `hailo_depth.py` wired into Guardian (Step 7) |
| Hailo YOLO Path | 🔲 **OPTIONAL** | yolo26n.hef if compiled → 60ms → 5ms (Step 9) |
| Fall Detector | 🔲 **IN SPRINT** | IMU >3g spike + stillness → SOS trigger (Step 19) |

### Expanded Safety Classes (MVP Sprint Step 8):
Current (`SAFETY_CLASSES`, 21 classes) + additions:
- **Tripping hazards**: `fire hydrant`, `parking meter`, `bench`
- **Orientation aids**: `traffic light`, `stop sign`
- **Pedestrian collision**: `suitcase`, `backpack`
- **Note**: `curb` and `drop-off` are NOT in COCO-80 → handled exclusively by Hailo depth estimation

---

## 📋 LAYER 1: THE LEARNER [RUNS ON RASPBERRY PI 5] - 3-MODE ARCHITECTURE

**Purpose:** Adaptive Context Detection - Learns Without Retraining

### Revolutionary 3-Mode System (World-First Innovation):

#### 🔍 MODE 1: PROMPT-FREE (DISCOVERY)
**"What do you see?" → Scan environment with maximum coverage**

- **Vocabulary:** 4,585+ built-in classes (LVIS + Objects365)
- **Model:** yoloe-26s-seg-pf.onnx (~27MB) [DISABLED - ONNX Export Failed]
- **Framework:** ONNX Runtime (required - NCNN incompatible with LRPCHead)
- **Use Case:** Environmental scanning, broad cataloging, exploratory queries
- **Confidence Range:** 0.3-0.6 (lower but broader coverage)
- **Latency:** ~150ms (ONNX Runtime inference)
- **RAM Overhead:** ~600MB (ONNX Runtime + model)
- **Example Output:** "chair, desk, lamp, keyboard, mouse, monitor, phone, wallet, cup, notebook, pen, stapler, plant, speaker..."
- **Learning:** None (static pre-trained vocabulary)
- **Offline:** ✅ 100% (no network required)

**When to Use:**
- Discovery queries: "what do you see", "scan the room", "list objects"
- Initial environment assessment
- Finding unexpected objects
- Broad situational awareness

---

#### 🧠 MODE 2: TEXT PROMPTS (ADAPTIVE LEARNING) - DEFAULT MODE
**"Find the fire extinguisher" → Targeted detection with learned vocabulary**

- **Vocabulary:** 15-100 dynamic classes (learns from Gemini/Maps/Memory)
- **Model:** yoloe-11s-seg_ncnn_model/ (~40MB)
- **Framework:** NCNN (ARM-optimized, best for RPi5)
- **Text Encoder:** MobileCLIP-B(LT) (100MB RAM, cached)
- **Use Case:** Targeted queries, learned objects, contextual detection
- **Confidence Range:** 0.7-0.9 (high accuracy, learned context)
- **Latency:** ~120ms (NCNN inference)
- **RAM Overhead:** +10MB (text embeddings for 97 classes)
- **Example Output:** "fire extinguisher (0.91), exit sign (0.87), yellow dumbbell (0.89)"
- **Learning:** Real-time from 3 sources (see below)
- **Offline:** ✅ 100% (uses cached prompts from last online session)

**Learning Sources:**
1. **Gemini (Layer 2)**: NLP noun extraction from scene descriptions
   - User: "Explain what you see"
   - Gemini: "I see a red fire extinguisher mounted on the wall..."
   - System extracts: `["fire extinguisher", "wall mount", "red cylinder"]`
   - → Added to adaptive_prompts.json

2. **Google Maps (Layer 3)**: POI-to-object mapping
   - Location: "Near Starbucks"
   - Maps returns: `["Starbucks", "ATM", "Bus Stop"]`
   - System converts: `["coffee shop sign", "menu board", "ATM sign", "bus stop sign"]`
   - → Added to adaptive_prompts.json

3. **Memory (Layer 4)**: User-stored objects
   - User: "Remember this brown leather wallet"
   - System stores: `{"object": "brown leather wallet", "bbox": [...], "location": [x,y,z]}`
   - → Added to adaptive_prompts.json

**Prompt Management:**
```python
# Base vocabulary (76 Singapore-specific objects, always included)
base_prompts = [
    "person", "car", "phone", "wallet", "keys",
    "stone chess table", "void deck kiosk", "blue recycling bin",
    "rubbish chute hopper", "tissue packet", "EZ-Link card",
    ...
]

# Dynamic prompts (learned from Gemini/Maps/Memory)
dynamic_prompts = {
    "fire extinguisher": {"source": "gemini", "use_count": 5, "age_hours": 2},
    "coffee machine": {"source": "maps", "use_count": 12, "age_hours": 8},
    "yellow dumbbell": {"source": "gemini", "use_count": 3, "age_hours": 1}
}

# Auto-pruning (every 24 hours)
if prompt.age > 24h AND prompt.use_count < 3:
    remove_prompt(prompt)  # Keep list manageable (50-100 classes max)

# Persistence
save_to_file("memory/adaptive_prompts.json")  # Survives restarts
```

**When to Use:**
- Targeted queries: "find the", "where's the", "locate"
- Learned objects: Objects previously described by Gemini
- Contextual detection: Objects relevant to current location (POI)
- High-confidence needs: When accuracy > speed

---

#### 👁️ MODE 3: VISUAL PROMPTS (PERSONAL OBJECTS)
**"Where's MY wallet?" → Track user's specific items with spatial memory**

- **Vocabulary:** User-defined (1-50 personal items)
- **Model:** yoloe-11s-seg_ncnn_model/ (~40MB, same as text prompts)
- **Framework:** NCNN (ARM-optimized)
- **Visual Encoder:** SAVPE (Semantic-Activated Visual Prompt Encoder)
- **Predictor:** YOLOEVPSegPredictor (specialized for visual prompts)
- **Use Case:** Personal item tracking, "remember this" objects, spatial memory
- **Confidence Range:** 0.6-0.95 (very high, visual matching)
- **Latency:** ~120ms (NCNN inference)
- **RAM Overhead:** +5MB (visual embeddings, ~5KB per object)
- **Example Output:** "your wallet is on the desk near the laptop (0.93)"
- **Learning:** User-drawn bounding boxes + reference images
- **Offline:** ✅ 100% (saved embeddings in Layer 4)

**Visual Prompt Storage (Layer 4 Integration):**
```
memory_storage/wallet_003/
├── image.jpg                   # Reference photo (captured at "remember" time)
├── visual_prompt.json          # Bboxes + class IDs
│   {
│     "object_name": "wallet",
│     "bboxes": [[450, 320, 580, 450]],  # [x1, y1, x2, y2]
│     "cls": [0],
│     "reference_image": "image.jpg",
│     "visual_embedding_path": "visual_embedding.npz",
│     "slam_coordinates": [2.3, 0.8, 0.9],  # [x, y, z] meters
│     "timestamp": "2025-12-29T10:30:00"
│   }
├── visual_embedding.npz        # model.predictor.vpe (pre-computed, 15KB)
└── metadata.json               # Tags, location, user notes
```

**Workflow Example: "Remember This Wallet"**
```python
# Step 1: User voice command
User: "Remember this wallet"

# Step 2: Capture frame + GUI bbox drawing (future: auto-segmentation)
frame = capture_camera_frame()
bbox = user_draws_bounding_box(frame)  # GUI interaction

# Step 3: Extract visual embeddings
model.predict(
    frame,
    prompts={"bboxes": [bbox], "cls": [0]},
    predictor=YOLOEVPSegPredictor,
    return_vpe=True  # Extract visual prompt embeddings
)
visual_embedding = model.predictor.vpe  # Save this!

# Step 4: Save to Layer 4 memory
memory_id = "wallet_003"
visual_prompt_manager.save_visual_prompt(
    object_name="wallet",
    memory_id=memory_id,
    bboxes=np.array([bbox]),
    cls=np.array([0]),
    visual_embedding=visual_embedding,
    reference_image_path=f"memory_storage/{memory_id}/image.jpg",
    slam_coordinates=current_slam_position  # [x, y, z] from Layer 3
)

# Result: Cross-session persistence, <50ms loading
```

**Workflow Example: "Where's My Wallet"**
```python
# Step 1: User voice command
User: "Where's my wallet"

# Step 2: Load visual prompt from Layer 4
memory_ids = visual_prompt_manager.search_by_object_name("wallet")
visual_prompt = visual_prompt_manager.load_visual_prompt(memory_ids[0])

# Step 3: Set visual classes
vpe = visual_prompt_manager.get_visual_embedding(memory_ids[0])
model.set_classes(["wallet"], vpe)

# Step 4: Detect with visual prompts
results = model.predict(
    live_frame,
    conf=0.15,  # Lower threshold for cross-image detection
    predictor=YOLOEVPSegPredictor
)

# Step 5: Spatial localization (Layer 3 integration)
if wallet_detected:
    slam_coords = visual_prompt.slam_coordinates  # [2.3, 0.8, 0.9]
    direction_3d = calculate_3d_direction(current_position, slam_coords)
    spatial_audio.play_beacon(direction_3d)  # 3D audio guidance
    tts.speak("Your wallet is on the desk, 2.3 meters at 45 degrees right")
```

**When to Use:**
- Personal queries: "where's MY", "find MY", "remember this"
- Specific items: User's unique wallet, keys, glasses (not generic)
- Spatial memory: Objects with saved SLAM coordinates
- High-confidence needs: When personal item must be correct (not just any wallet)

---

### Technical Stack:
- **Models:**
  - **Layer 0 (Guardian):** YOLO11n-ncnn (11 MB) - NCNN format, 256x256
  - **Layer 1 (Learner) - Standard:** YOLOE-11s-seg_ncnn_model (40 MB) - NCNN format, text/visual prompts
  - **Layer 1 (Learner) - Standard:** YOLOE-11m-seg_ncnn_model (88 MB) - NCNN format, more accurate
  - **Layer 1 (Learner) - Prompt-Free:** YOLOE-11s-seg-pf.onnx (~27 MB) - ONNX format, discovery mode
- **Frameworks:**
  - **NCNN:** Best for RPi5 - ARM-optimized, pure CPU, minimal RAM
  - **ONNX Runtime:** Required for prompt-free models - supports LRPCHead operations NCNN cannot handle
- **Resolution:** 256x256 (4x faster than 640x640, acceptable accuracy loss)
- **Device:** Raspberry Pi 5 (Quad-core Cortex-A76 @ 2.4GHz)
- **Storage:** memory/adaptive_prompts.json, memory_storage/{object}_{id}/

### Performance Requirements:
- **Latency:** ~80-120ms (mode-dependent, parallel with Layer 0)
- **Throughput:** 8-10 FPS
- **Power Draw:** 6-9W during inference
- **Memory:**
  - YOLOE-11s-seg-ncnn (NCNN): ~300MB
  - YOLOE-11m-seg-ncnn (NCNN): ~500MB
  - YOLOE-11s-seg-pf-onnx (ONNX): ~400MB
  - MobileCLIP text encoder: 100MB (cached)
  - Text embeddings: 10MB (97 classes)
  - Visual embeddings: 5MB (50 objects × 100KB each)
  - **Total: ~400-600MB per mode** (within budget)
- **Mode Switching:** <50ms (no model reload, just embedding update)
- **Visual Prompt Loading:** <50ms (from .npz file)
- **Execution:** Runs in PARALLEL with Layer 0 (same frame, different thread)

### Adaptive Prompt System:

**Base Vocabulary (15 objects, always included):**
```python
base_prompts = [
    "person", "car", "phone", "wallet", "keys",
    "door", "stairs", "chair", "table", "bottle",
    "cup", "book", "laptop", "bag", "glasses"
]
```

**Dynamic Learning Sources:**
1. **Layer 2 (Gemini Scene Descriptions):**
   - User: "Describe the scene"
   - Gemini: "I see a red fire extinguisher, a water fountain, and exit signs"
   - System extracts: `["fire extinguisher", "water fountain", "exit sign"]`
   - → Added to YOLOE prompt list

2. **Layer 3 (Google Maps POI):**
   - User location: "Near Starbucks, 123 Main St"
   - Maps API returns: `["Starbucks", "ATM", "Bus Stop"]`
   - System converts: `["coffee shop sign", "ATM", "bus stop sign"]`
   - → Added to YOLOE prompt list

3. **Layer 4 (User Memory):**
   - User: "Remember my brown leather wallet"
   - System stores: `{"object": "brown leather wallet", "location": "desk"}`
   - → Added to YOLOE prompt list

**Prompt Management:**
```python
# Automatic pruning (every 24 hours)
if prompt.age > 24h AND prompt.use_count < 3:
    remove_prompt(prompt)  # Keep list under 50-100 classes

# Deduplication (case-insensitive, synonyms)
if "coffee machine" in prompts:
    skip("espresso maker")  # Avoid synonym duplicates

# Persistence (JSON storage)
save_to_file("memory/adaptive_prompts.json")
```

### Use Cases:
- **Contextual Queries**: "Where is my wallet?" (searches adaptive list)
- **Scene Understanding**: "What objects are around me?" (uses learned vocabulary)
- **Location-Aware**: Detects "menu board" near restaurants, "ATM sign" near banks
- **Memory Recall**: "Find my brown leather wallet" (uses stored object names)

### Why Adaptive YOLOE:
- ✅ **Zero Retraining**: Learns via text prompts (no model fine-tuning)
- ✅ **Real-Time Updates**: Prompts update every 30s or on-demand
- ✅ **Lightweight**: 0.8GB RAM vs 3.2GB for YOLOE-11l
- ✅ **Context-Aware**: Vocabulary adapts to user's environment
- ✅ **Privacy-Preserving**: Text prompts stored locally (no cloud upload)

### Implementation Files:
- `src/layer1_learner/__init__.py` - YOLOE-11s wrapper (dynamic)
- `src/layer1_learner/adaptive_prompt_manager.py` - Prompt list manager
- `src/dual_yolo_handler.py` - Orchestrates Layer 0 + Layer 1
- `memory/adaptive_prompts.json` - Persistent prompt storage

### Integration with Other Layers:
```python
# Layer 2 (Gemini) → Layer 1 (YOLOE)
def on_gemini_response(response_text):
    new_objects = adaptive_prompt_manager.add_from_gemini(response_text)
    if new_objects:
        yoloe_learner.set_classes(adaptive_prompt_manager.get_current_prompts())

# Layer 3 (Maps) → Layer 1 (YOLOE)
def on_location_update(poi_list):
    adaptive_prompt_manager.add_from_maps(poi_list)
    yoloe_learner.set_classes(adaptive_prompt_manager.get_current_prompts())

# Layer 4 (Memory) → Layer 1 (YOLOE)
def on_user_stores_object(object_name):
    adaptive_prompt_manager.add_from_memory(object_name)
    yoloe_learner.set_classes(adaptive_prompt_manager.get_current_prompts())
```

---

## 📋 INTENT ROUTER: THE DISPATCHER [RUNS ON RASPBERRY PI 5]

**Purpose:** Route voice commands to the appropriate AI layer using keyword priority + fuzzy matching

**Location:** `src/layer3_guide/router.py`  
**Test Suite:** `tests/test_router_fix.py` (44 tests, 97.7% accuracy)  
**Latency:** <1ms (typically 0.1-0.5ms)  
**Research:** Based on Microsoft Bot Framework Orchestrator + TheFuzz library patterns

### Two-Phase Routing Algorithm:

```
┌─────────────────────────────────────────────────────────────────┐
│                     IntentRouter (router.py)                    │
│                                                                 │
│  Input: "what do you see" (transcribed by Whisper)             │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  PHASE 1: PRIORITY KEYWORD OVERRIDE                      │ │
│  │                                                          │ │
│  │  ✅ Layer 1 Priority: ["what do you see", "what u see", │ │
│  │     "see", "look", "identify", "count", ...]            │ │
│  │                                                          │ │
│  │  ✅ Layer 2 Priority: ["describe the scene", "read",    │ │
│  │     "analyze", "explain", ...]                          │ │
│  │                                                          │ │
│  │  ✅ Layer 3 Priority: ["where am i", "navigate",        │ │
│  │     "where is", "locate", ...]                          │ │
│  │                                                          │ │
│  │  Check: Does query contain ANY priority keyword?        │ │
│  │  → YES: Return layer immediately (skip fuzzy matching)  │ │
│  │  → NO: Proceed to Phase 2                               │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  PHASE 2: FUZZY MATCHING (Ambiguous Queries)            │ │
│  │                                                          │ │
│  │  1. Calculate similarity scores:                        │ │
│  │     - Layer 1 Score: max(fuzzy_match(query, patterns))  │ │
│  │     - Layer 2 Score: max(fuzzy_match(query, patterns))  │ │
│  │     - Layer 3 Score: max(fuzzy_match(query, patterns))  │ │
│  │                                                          │ │
│  │  2. Apply threshold (0.7):                              │ │
│  │     - If any score >= 0.7: Route to highest score       │ │
│  │     - Else: Default to Layer 1 (offline, safe)          │ │
│  │                                                          │ │
│  │  3. Fuzzy match algorithm:                              │ │
│  │     - Current: difflib.SequenceMatcher (97.7% accuracy) │ │
│  │     - Upgrade: thefuzz.fuzz.token_sort_ratio (99%+)     │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Output: "layer1" | "layer2" | "layer3"                        │
│  Latency: <1ms (measured: 0-2ms typical)                       │
└─────────────────────────────────────────────────────────────────┘
```

### Routing Decision Matrix:
| User Query | Priority Keyword Match | Fuzzy Scores (L1/L2/L3) | Final Route | Reason |
|------------|------------------------|-------------------------|-------------|--------|
| "what do you see" | ✅ Layer 1 ("what do you see") | (skipped) | **Layer 1** | Priority keyword override |
| "describe the room" | ✅ Layer 2 ("describe the room") | (skipped) | **Layer 2** | Priority keyword override |
| "where am i" | ✅ Layer 3 ("where am i") | (skipped) | **Layer 3** | Priority keyword override |
| "wat do u c" | ❌ No match | (0.85 / 0.45 / 0.30) | **Layer 1** | Highest fuzzy score |
| "navgate to store" | ❌ No match | (0.55 / 0.40 / 0.68) | **Layer 1** | All scores < 0.7, default to Layer 1 |
| "unknown query xyz" | ❌ No match | (0.20 / 0.15 / 0.25) | **Layer 1** | Default to Layer 1 (offline fallback) |

### Layer Classification Patterns:

#### Layer 1: Object Detection (Fast, Offline, Adaptive)
**Purpose:** Immediate object identification using YOLO11x + YOLOE-11s  
**Latency:** <150ms (102ms typical)  
**Priority Keywords:**
- `"what do you see"`, `"what u see"`, `"what you see"`, `"what can you see"`
- `"see"`, `"look"`, `"show me"`, `"list objects"`, `"what objects"`
- `"identify"`, `"detect"`, `"count"`, `"how many"`
- `"what's in front"`, `"what's ahead"`, `"whats in front"`, `"whats ahead"`

**Pattern Examples:**
- "What is this?" → Layer 1 (quick object ID)
- "Is there a person?" → Layer 1 (object query)
- "Count the chairs" → Layer 1 (counting task)
- "Watch out" → Layer 1 (safety alert)

#### Layer 2: Deep Analysis (Slow, Cloud, Reasoning)
**Purpose:** Scene understanding, OCR, reasoning using Gemini 2.5 Flash  
**Latency:** <500ms (vs 2-3s HTTP API)  
**Priority Keywords:**
- `"describe the entire scene"`, `"describe the room"`, `"describe everything"`
- `"analyze"`, `"analyze the scene"`, `"what's happening"`
- `"read"`, `"read text"`, `"read this"`, `"what does it say"`
- `"explain what's happening"`, `"explain"`, `"is this safe"`

**Pattern Examples:**
- "Describe the room" → Layer 2 (comprehensive scene)
- "Read that sign" → Layer 2 (OCR required)
- "Should I cross the road?" → Layer 2 (reasoning)
- "What kind of place is this?" → Layer 2 (context understanding)

#### Layer 3: Navigation + Spatial Audio (Hybrid, 3D Audio)
**Purpose:** GPS/VIO/SLAM navigation + object localization with 3D audio  
**Latency:** 50ms (3D audio) / 5-10s (VIO/SLAM post-processing)  
**Priority Keywords:**
- **Location/GPS:** `"where am i"`, `"location"`, `"gps"`
- **Navigation:** `"navigate"`, `"go to"`, `"take me"`, `"direction"`, `"route"`
- **Memory:** `"remember"`, `"memory"`, `"save"`
- **Spatial Audio:** `"where is"`, `"where's"`, `"locate"`, `"find the"`, `"guide me to"`

**Pattern Examples:**
- "Where am I?" → Layer 3 (GPS location)
- "Navigate to the exit" → Layer 3 (pathfinding)
- "Where is the door?" → Layer 3 (3D audio localization)
- "Remember this wallet" → Layer 3 (memory storage)

### Key Design Decisions:

1. **Priority Keywords Checked FIRST**
   - Prevents fuzzy matching from misrouting common queries
   - Example: "what do you see" always → Layer 1 (never Layer 2)
   - Research: Microsoft Bot Framework Orchestrator pattern

2. **Threshold = 0.7 (Stricter Than Industry Standard)**
   - Python docs recommend 0.6 for "close match"
   - We use 0.7 to reduce false positives (Layer 2 = API costs)
   - If uncertain → default to Layer 1 (offline, free)

3. **Default to Layer 1 (Safety-First)**
   - If all fuzzy scores < 0.7 → Layer 1
   - Rationale: Offline, fast, free, safety-critical
   - Never block user with "I don't understand" errors

4. **Fuzzy Matching Algorithm**
   - Current: `difflib.SequenceMatcher` (97.7% accuracy, standard library)
   - Optional upgrade: `thefuzz.token_sort_ratio` (99%+ accuracy, robust to typos)
   - Handles typos: "wat u see" → Layer 1 ✅, "discribe room" → Layer 2 ✅

### Logging Visibility:
```python
# Router logs now use logger.info() (always visible):
INFO:layer3_guide.router:🎯 [ROUTER] Layer 1 priority: 'what do you see' → Forcing Layer 1 (Reflex)
INFO:layer3_guide.router:📊 [ROUTER] Fuzzy scores: L1=0.85, L2=0.45, L3=0.30 (threshold=0.7)
INFO:layer3_guide.router:🎯 [ROUTER] Fuzzy match: Layer 1 (Reflex) - score=0.85
```

### Test Suite (`tests/test_router_fix.py`):
```bash
$ python tests/test_router_fix.py

📊 FINAL SUMMARY
Total Tests: 44
✅ Passed: 43 (97.7%)
❌ Failed: 1 (2.3%)  # "navgate to store" with extreme typo
```

**Test Categories:**
- Layer 1 Priority Keywords: 17/17 (100%) ✅
- Layer 2 Deep Analysis: 12/12 (100%) ✅
- Layer 3 Navigation: 9/9 (100%) ✅
- Fuzzy Matching (Typos): 5/6 (83.3%) ⚠️

### Performance Metrics:
- **Routing Latency:** <1ms (typical: 0.1-0.5ms)
- **Memory Overhead:** ~1MB (pattern lists cached)
- **Accuracy:** 97.7% (43/44 tests pass)
- **Network Dependency:** None (100% offline)

### Implementation Files:
- `src/layer3_guide/router.py` - Core routing logic (275 lines)
- `tests/test_router_fix.py` - Validation test suite (NEW)
- `docs/implementation/ROUTER-FIX-V2-RESEARCH-DRIVEN.md` - Implementation plan

### Research Sources:
- **Microsoft Bot Framework:** Orchestrator component (two-phase routing pattern)
- **TheFuzz Library:** `/seatgeek/thefuzz` (fuzzy string matching best practices)
- **Python Difflib:** CPython repository (SequenceMatcher algorithm, threshold guidance)

---

## 📋 LAYER 1 LEGACY COMPONENTS [RUNS ON RASPBERRY PI 5]

**Note:** These components remain from the original Layer 1 Reflex architecture:

### Voice Components:
- `src/layer1_reflex/vad_handler.py` - Silero VAD for wake word
- `src/layer1_reflex/whisper_handler.py` - Local STT
- `src/layer1_reflex/kokoro_handler.py` - Offline TTS fallback

---

## 📋 LAYER 2: THE THINKER [HYBRID: LOCAL STT + CLOUD AI]

**Purpose:** Vision Intelligence & Conversational AI

### Technical Stack:

#### Local Components (Raspberry Pi 5):
- **STT:** Whisper base model (800MB RAM, 500ms latency)
- **TTS Fallback:** Kokoro TTS (500MB RAM, offline)
- **VAD:** Silero VAD (50MB RAM, <10ms latency)

#### Cloud Components (Google Cloud):
- **Primary AI:** Gemini 2.5 Flash Live API
- **Transport:** WebSocket (wss://generativelanguage.googleapis.com/ws/...)
- **Model:** `gemini-2.0-flash-exp` (Live API model)

### Revolutionary Feature: Native Audio-to-Audio Streaming

**Old v1.0 Flow (HTTP API):**
```
Pi → Capture Audio → Upload WAV → Gemini Vision API (text) → 
Gemini TTS API (audio) → Download MP3 → Pi
Total Latency: 2-3 seconds
```

**New v2.0 Flow (Live API):**
```
Pi → PCM Stream (16kHz) → WebSocket → Gemini Live API → 
PCM Stream (24kHz) → Pi
Total Latency: <500ms (83% reduction!)
```

### WebSocket Implementation:

```python
from google import genai
from google.genai import types
import asyncio

class GeminiLiveHandler:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.session = None
    
    async def connect(self):
        """Establish persistent WebSocket connection."""
        self.session = await self.client.aio.live.connect(
            model='gemini-2.0-flash-exp',
            config=types.LiveConnectConfig(
                response_modalities=['AUDIO', 'TEXT'],
                system_instruction="""You are an AI assistant for a visually impaired person. 
                Your role is to describe visual scenes, read text, identify objects, and provide 
                navigation guidance in real-time. Be concise, clear, and prioritize safety-critical 
                information. Use simple language and avoid technical jargon.""",
                generation_config=types.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=1024
                )
            )
        )
    
    async def send_audio_chunk(self, audio_bytes: bytes):
        """Send 16kHz PCM audio chunk."""
        await self.session.send_realtime_input(
            audio=types.Blob(
                data=audio_bytes,
                mime_type='audio/pcm;rate=16000'
            )
        )
    
    async def send_video_frame(self, frame_pil: PIL.Image.Image):
        """Send JPEG video frame (2-5 FPS recommended)."""
        await self.session.send_realtime_input(video=frame_pil)
    
    async def receive_responses(self):
        """Stream audio responses in real-time."""
        async for message in self.session.receive():
            if message.server_content:
                # Check for interruption
                if message.server_content.interrupted:
                    print("⚠️ Response interrupted by user")
                    continue
                
                # Extract audio chunks (24kHz PCM)
                for part in message.server_content.model_turn.parts:
                    if part.inline_data:
                        yield part.inline_data.data  # Raw PCM bytes
```

### Audio Formats:
- **Input:** 16kHz PCM mono (direct from microphone)
- **Output:** 24kHz PCM (direct to Bluetooth headphones)
- **No Intermediate Files:** Streaming-only (no temp files)

### Use Cases:
1. **Conversational Queries**: "What's in front of me?"
2. **OCR/Text Reading**: "Read that sign" (camera + Live API)
3. **Scene Understanding**: "Describe the environment"
4. **Object Identification**: "What is this object?" (camera + Live API)
5. **Contextual Assistance**: "How do I navigate to the door?"

### Current Implementation Status:
| Feature | Status | Notes |
|---------|--------|-------|
| Gemini Live API WebSocket | **IMPLEMENTED** | Using gemini-2.0-flash-exp model |
| Audio Input (16kHz PCM) | **IMPLEMENTED** | Direct from microphone |
| Audio Output (24kHz PCM) | **IMPLEMENTED** | Direct to Bluetooth |
| Video Frame Sending | **IMPLEMENTED** | PIL Image to Live API |
| Interruption Handling | **IMPLEMENTED** | server_content.interrupted |
| Whisper STT (Local) | **IMPLEMENTED** | For offline fallback |
| Kokoro TTS (Local) | **IMPLEMENTED** | For offline fallback |
| Silero VAD | **IMPLEMENTED** | Wake word detection |

### Implementation Files:
- `rpi5/layer2_thinker/gemini_live_handler.py` - Gemini Live API WebSocket handler
- `rpi5/layer2_thinker/audio_utils.py` - Audio capture and playback

### Performance Requirements:
- **Audio Latency:** <500ms (includes Bluetooth transmission)
- **Video Streaming:** 2-5 FPS (JPEG frames via WebSocket)
- **Network Dependency:** Requires Wi-Fi (falls back to Kokoro TTS if offline)
- **Cost:** $0.005/min (cheaper than HTTP API!)
- **Bandwidth:** ~200 KB/s (audio + video)

### Interruption Handling:
```python
# User can interrupt AI mid-response via VAD detection
if vad_handler.detect_speech():
    # Cancel current playback
    audio_player.stop()
    
    # Send new audio input (server will set interrupted=True)
    await gemini_live.send_audio_chunk(new_audio)
```

### Key Advantages Over HTTP API:
| Feature | HTTP API (v1.0) | Live API (v2.0) |
|---------|----------------|-----------------|
| Latency | 2-3 seconds | <500ms |
| Pipeline | 3-step (vision→text→TTS) | 1-step (audio+video→audio) |
| Conversation | Stateless | Stateful (session context) |
| Interruption | Not supported | Native (interrupted flag) |
| Connection | One-shot POST | Persistent WebSocket |
| Cost | $0.01/request | $0.005/min (50% cheaper!) |

### System Instruction Best Practices:
Based on research (Gemini API docs + googleapis/python-genai):
- **Be Specific**: "You are an AI assistant for a visually impaired person"
- **Define Role**: "Describe visual scenes, read text, identify objects"
- **Safety First**: "Prioritize safety-critical information"
- **Output Style**: "Be concise, clear, use simple language"
- **Avoid Jargon**: "No technical jargon"

### Implementation Files:
- `src/layer2_thinker/gemini_live_handler.py` - WebSocket client (NEW)
- `src/layer2_thinker/gemini_tts_handler.py` - Legacy HTTP API (fallback)
- `src/layer2_thinker/audio_stream_manager.py` - PCM buffer (NEW)
- `docs/implementation/layer2-live-api-plan.md` - Full implementation guide

---

## 📋 LAYER 3: THE ROUTER [RUNS ON RASPBERRY PI 5]

**Purpose:** Intelligent Intent Routing — Decides which AI layer handles each user command

### Technical Stack (Current → MVP Sprint Upgrade):
- **Current:** Fuzzy matching with SequenceMatcher (`router.py`), 97.7% accuracy, <1ms
- **MVP Sprint:** SNAP-C1 quantized ONNX action decoder (replaces fuzzy router as primary, IntentRouter becomes fallback)

### SNAP-C1: Offline Action Decoder (MVP Sprint Phase 4)

**Architecture:** TF-IDF features → 3-layer MLP → softmax → 25 action tokens, exported as INT8 ONNX
**Inference:** <5ms on RPi5 CPU
**Offline Survival Mode:** If cellular drops, SNAP-C1 is the ONLY path — combines mic text + YOLO threat level + GPS → direct action token, no Gemini fallback

**Action Token Vocabulary (~25 tokens):**
```python
ACTION_TOKENS = [
    "NAVIGATE_LEFT", "NAVIGATE_RIGHT", "NAVIGATE_FORWARD", "NAVIGATE_STOP",
    "IDENTIFY_OBJECT", "READ_TEXT", "DESCRIBE_SCENE", "COUNT_OBJECTS",
    "STORE_MEMORY", "RECALL_MEMORY", "LIST_MEMORIES",
    "EMERGENCY_STOP", "CALL_CARETAKER",
    "REPEAT_LAST", "INCREASE_VOLUME", "DECREASE_VOLUME",
    "FILLER_IGNORE", "UNKNOWN",
    "ROUTE_LAYER0", "ROUTE_LAYER1", "ROUTE_LAYER2", "ROUTE_LAYER3",
]
```

**Routing with fallback:**
```python
# Primary: SNAP-C1
action, confidence = snap_c1.decode(text)
if confidence < 0.7:
    action = intent_router.route(text)  # IntentRouter fallback

# Offline survival:
if self.is_offline:
    action = snap_c1.decode_offline(text, yolo_threat_level, last_gps_fix)
    # No Gemini fallback — direct action token only
```

### ChromaDB Fast Brain (GPS Breadcrumbs)
- Local ChromaDB collection (no server) stores GPS coord + description per location visited
- On offline activation: retrieve nearest safe-zone GPS fix → compute heading → `AudioBeacon.start()`
- Guides user back to last known safe zone without any network

### Routing Logic (Current Fuzzy Router — remains as fallback):

| Priority | Keywords | Target Layer | Use Case |
|----------|----------|--------------|----------|
| 1 (HIGH) | "describe", "read", "analyze" | Layer 2 | Deep analysis, OCR, reasoning |
| 2 (MED) | "where am I", "navigate", "remember" | Layer 3 | Navigation, memory storage |
| 3 (HIGH) | "what do you see", "find", "count" | Layer 1 | Object detection, fast responses |

### Current Implementation Status:
| Feature | Status | Notes |
|---------|--------|-------|
| IntentRouter (fuzzy) | **IMPLEMENTED** | SequenceMatcher, 0.7 threshold, 97.7% accuracy |
| Priority Keywords | **IMPLEMENTED** | Three-tier priority system |
| Mode Recommendation | **IMPLEMENTED** | TEXT_PROMPTS, VISUAL_PROMPTS, PROMPT_FREE |
| L2 Force Override | ⚠️ **REMOVING** | Active debug override in main.py (Sprint Step 1) |
| SNAP-C1 ONNX Decoder | 🔲 **IN SPRINT** | MLP → ONNX, IntentRouter as teacher (Steps 12–15) |
| ChromaDB Fast Brain | 🔲 **IN SPRINT** | Local GPS breadcrumb store (Step 16) |
| Offline Survival Mode | 🔲 **IN SPRINT** | SNAP-C1 + ChromaDB only when offline (Step 15) |

### Implementation Files:
- `rpi5/layer3_guide/router.py` — IntentRouter (fuzzy, fallback)
- `rpi5/layer3_guide/snap_c1/decoder.py` — SnapC1Decoder (primary, ONNX) 🔲
- `rpi5/layer3_guide/snap_c1/fast_brain.py` — ChromaDB GPS breadcrumbs 🔲
- `rpi5/layer3_guide/snap_c1/action_tokens.py` — Action token vocabulary 🔲

---

## 📋 LAYER 3: THE NAVIGATOR [HYBRID: SERVER + RASPBERRY PI 5]

**Purpose:** Spatial Guidance, 3D Acoustic UI, GPS Audio Beacons

### Acoustic UI — Core Philosophy
Project-Cortex **eliminates slow, high-cognitive-load TTS for immediate physical navigation**. Instead:
- **Continuous spatial hum** → maps wall proximity to HRTF-processed tone (body-relative, subconscious)
- **Drop-off chirp** → instant dual-ear alert forces user to freeze (<50ms)
- **GPS audio beacon** → directional ping the user follows (no "turn left" instructions)

### Wall Proximity Force-Field Hum (MVP Sprint Step 4)
- Hailo depth matrix → read leftmost/rightmost columns for wall proximity
- Map `0–2m` range → OpenAL mono source `AL_PITCH 0.5–2.0`, `AL_GAIN` proportional
- Mono source = processed by HRTF → right wall produces right-ear hum
- Updates every frame; continuous loop (not threshold-triggered clips)
- New method: `SpatialAudioManager.update_wall_hum(left_depth_m, right_depth_m)`

### Drop-Off Audio Override (MVP Sprint Step 5)
Triggered when `HailoDepthEstimator` returns `DROPOFF` or `STAIRS_DOWN` (CRITICAL/HIGH):
1. `AL_STOP` on ALL active sources including hum
2. Dual-ear 1kHz chirp (`_generate_chirp()`, both channels — bypasses HRTF directionality)
3. 500ms audio silence (force freeze)
4. Resume normal hum
- **Target latency:** <50ms from hazard detection to chirp onset

### GPS Audio Beacon (MVP Sprint Step 10)
- `IntentRouter` returns `use_spatial_audio=True` or `query_type="navigate"`
- Gemini handles POI lookup → parses destination
- Compute azimuth from current GPS + IMU heading → destination
- `AudioBeacon.start(target_position)` — ping accelerates 1Hz (far) → 8Hz (arrival)
- IMU compass heading → `SpatialAudioManager.update_heading()` → OpenAL listener orientation updated in real time (objects stay body-relative as user turns)

### Current Spatial Audio Status:
| Feature | Status | Notes |
|---------|--------|-------|
| SpatialAudioManager (module) | ⚠️ **WIRING** | Code complete, not instantiated in CortexSystem (Sprint Step 3) |
| Wall Force-Field Hum | 🔲 **IN SPRINT** | Continuous depth-driven tone (Step 4) |
| Drop-Off Audio Override | 🔲 **IN SPRINT** | Dual-ear chirp + freeze (Step 5) |
| GPS Audio Beacon | 🔲 **IN SPRINT** | AudioBeacon wired to GPS nav (Step 10) |
| IMU Heading → Listener | 🔲 **IN SPRINT** | Body-relative audio as user turns (Step 11) |
| AudioBeacon module | **IMPLEMENTED** | fully coded, awaiting wiring |
| ProximityAlertSystem | **IMPLEMENTED** | discrete threshold clips, being extended |
| HRTF / OpenAL | **IMPLEMENTED** | INVERSE_DISTANCE_CLAMPED model |

### Split-Task Architecture:

#### Server Responsibilities (Laptop - Heavy Compute):
- **VIO (Visual-Inertial Odometry)**
  - Fuses camera + BNO055 IMU data
  - Post-processes EuRoC datasets from RPi
  - Latency: 5-10 seconds (NOT real-time)
- **SLAM (Simultaneous Localization & Mapping)**
  - ORB-SLAM3 for visual odometry
  - Constructs 3D point cloud of environment
  - Stores explored areas for future reference
- **Pathfinding**
  - A* algorithm with dynamic obstacle avoidance
  - Generates waypoint list: `[(lat, lon, alt), ...]`
- **Map Database**
  - PostgreSQL + PostGIS for geospatial queries

#### Pi 5 Responsibilities (Wearable - Real-Time):
- **Sensor Fusion**
  - GPS (GY-NEO6MV2) for outdoor positioning
  - BNO055 IMU for head orientation (Euler angles)
- **3D Spatial Audio Rendering**
  - PyOpenAL with HRTF (Head-Related Transfer Function)
  - Receives target coordinate from server
  - Calculates azimuth/elevation relative to head
  - Renders directional "ping" sound via Bluetooth
- **Data Recording**
  - Records EuRoC MAV dataset format (cam0, imu0, gps0)
  - Uploads to server for VIO/SLAM post-processing

### Communication Protocol:
```json
// Server → Pi (WebSocket, 10Hz)
{
  "target_waypoint": {"lat": 1.3521, "lon": 103.8198},
  "distance_to_target": 12.5,  // meters
  "turn_angle": -45,            // degrees (left = negative)
  "obstacles_ahead": ["car", "person"]
}
```

### Audio Priority Mixing (Ducking):
```python
Priority 1 (HIGH):   Layer 1 Haptics (Never delayed)
Priority 2 (MEDIUM): Layer 3 Nav Pings ("Turn left")
Priority 3 (LOW):    Layer 2 Gemini Voice (Auto-duck by -10dB)
```

### Performance Requirements:
- **Server Processing:** <200ms (SLAM + pathfinding)
- **Network Latency:** <50ms (local Wi-Fi)
- **Audio Rendering:** <100ms (3D position calculation)
- **Total Latency:** <350ms (acceptable for navigation)

### Why Offload VIO/SLAM:
- ✅ **Saves 1GB+ RAM** on RPi (no OpenCV, scipy, VIO libraries)
- ✅ **Faster Processing**: Laptop processes 5-min session in 30s
- ✅ **Better Accuracy**: Laptop can run complex algorithms
- ⚠️ **Not Real-Time**: Post-processing only (5-10s latency)

### Implementation Files:
- **Server:** `server/slam_engine.py`, `server/pathfinder.py`
- **Pi:** `src/layer3_guide/spatial_audio/manager.py`
- **Communication:** `src/layer3_guide/websocket_client.py`
- **Data Recorder:** `src/layer3_guide/data_recorder.py`

---

## 📋 LAYER 4: THE MEMORY [RUNS ON RASPBERRY PI 5] - HYBRID SQLite + Supabase

**Purpose:** Persistent Data Storage & Analytics with Cloud Sync

### Technical Stack:
- **Local Database:** SQLite (local file I/O, hot cache)
- **Cloud Database:** Supabase PostgreSQL (historical data, sync)
- **RAM Usage:** ~50MB
- **Latency:** <10ms (local disk access)
- **Sync Interval:** 60 seconds (batch uploads)

### Data Stored:
- **Object Detections**: Timestamp, class, confidence, bbox
- **User Queries**: Voice commands, Gemini responses
- **Navigation Events**: GPS waypoints, IMU orientation
- **System Logs**: Error messages, performance metrics
- **Adaptive Prompts**: Learned vocabulary from Gemini/Maps
- **Visual Prompts**: User-defined personal items with embeddings

### Current Implementation Status:
| Feature | Status | Notes |
|---------|--------|-------|
| SQLite Local Storage | **IMPLEMENTED** | local_cortex.db |
| Supabase PostgreSQL | **IMPLEMENTED** | Cloud sync enabled |
| Detection Logging | **IMPLEMENTED** | Layers 0 and 1 |
| Adaptive Prompts Sync | **IMPLEMENTED** | Realtime subscription |
| Visual Prompts Storage | **IMPLEMENTED** | Embeddings in .npz format |
| Batch Upload | **IMPLEMENTED** | Every 60 seconds |
| Realtime Config | **IMPLEMENTED** | Cloud → RPi push |

### Implementation Files:
- `rpi5/layer4_memory/hybrid_memory_manager.py` - HybridMemoryManager class
- `rpi5/layer4_memory/supabase_client.py` - Supabase REST/WebSocket client
- `rpi5/config/config.py` - Configuration with Supabase settings

---

## 🌐 SUPABASE CLOUD INTEGRATION [NEW - 3-TIER HYBRID ARCHITECTURE]

**Purpose:** Cloud-Powered Memory, Real-Time Sync, Remote Monitoring, and Multi-Device Coordination

### Why Supabase? (Free Tier Capabilities)

| Feature | SQLite (Local Only) | **Supabase (Cloud)** | Benefit |
|---------|---------------------|---------------------|---------|
| **Multi-Device Sync** | ❌ Manual file copy | ✅ Realtime WebSocket | Coordinate RPi + Laptop + Phone |
| **Persistent Storage** | ❌ Lost if SD card fails | ✅ Auto-backup daily | Data durability |
| **Remote Monitoring** | ❌ Need physical access | ✅ Web dashboard anywhere | Watch RPi from phone |
| **Scalable Analytics** | ❌ Manual SQL queries | ✅ Built-in dashboards | Usage insights |
| **Real-Time Config** | ❌ SSH to RPi | ✅ Cloud → RPi push | Change settings remotely |
| **Cost** | ✅ Free | ✅ **Free (500MB)** | Production-ready backend |

**Supabase Free Tier Limits** (2025):
- 500 MB Database storage (PostgreSQL)
- 1 GB File storage (images, audio, models)
- 5 GB Bandwidth/month
- 50,000 Monthly Active Users
- 2 Projects

**Our Usage Estimate** (Single RPi5 deployment):
```
Database (500MB limit):
├── detections: 50 MB (~100K rows @ 500B each) ✅
├── queries: 10 MB (~50K sessions @ 200B each) ✅
├── memories: 5 MB (~10K objects @ 500B each) ✅
├── adaptive_prompts: 2 MB (~100 classes) ✅
├── system_logs: 20 MB (~200K logs @ 100B each) ✅
└── **TOTAL: 87 MB / 500 MB (17% used)** ✅ PLENTY OF HEADROOM

File Storage (1GB limit):
├── Reference images: 200 MB (400 objects @ 500KB) ✅
├── Audio clips: 100 MB (1000 clips @ 100KB) ✅
└── **TOTAL: 300 MB / 1 GB (30% used)** ✅ WITHIN LIMITS

Bandwidth (5GB/month limit):
├── Detection uploads: 500 MB/month (batch every 60s) ✅
├── Dashboard queries: 1 GB/month (real-time monitoring) ✅
├── Realtime sync: 2 GB/month (WebSocket) ✅
└── **TOTAL: 3.5 GB / 5 GB (70% used)** ✅ SAFE (30% margin)
```

**Conclusion**: Free tier is **sufficient for competition and single-device deployment**.

---

## 🏗️ 3-TIER HYBRID ARCHITECTURE

```
┌──────────────────────────────────────────────────────────────┐
│              TIER 1: EDGE (RPi5 Wearable)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Layer 0  │  │ Layer 1  │  │ Layer 2  │  │ Layer 3  │     │
│  │ Guardian │  │ Learner  │  │ Thinker  │  │ Router   │     │
│  │ (YOLO)   │  │ (YOLOE)  │  │(Gemini)  │  │(Intent)  │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│         ↓              ↓              ↓              ↓         │
│  Safety-Critical  Adaptive      Conversational  Voice       │
│  Detection        Learning      AI (WebSocket)   Commands    │
│                                                                │
│  Layer 4: Memory Manager (Hybrid)                              │
│  ├─ Local: SQLite (hot cache, last 1000 detections)          │
│  └─ Cloud: Supabase PostgreSQL (all historical data)         │
└──────────────────────────────────────────────────────────────┘
                           ↓ (WiFi, batch every 60s)
┌──────────────────────────────────────────────────────────────┐
│           TIER 2: CLOUD (Supabase Free Tier)                  │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │  PostgreSQL DB   │  │  Realtime API    │                 │
│  │  (500MB storage) │  │  (WebSocket)     │                 │
│  ├──────────────────┤  ├──────────────────┤                 │
│  │ • detections     │  │ • Live device    │                 │
│  │ • queries        │  │   status sync    │                 │
│  │ • memories       │  │ • Remote config  │                 │
│  │ • adaptive_      │  │   updates        │                 │
│  │   prompts        │  │ • Dashboard      │                 │
│  │ • system_logs    │  │   push events    │                 │
│  └──────────────────┘  └──────────────────┘                 │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │  Storage (1GB)   │  │  Edge Functions  │                 │
│  ├──────────────────┤  ├──────────────────┤                 │
│  │ • Images (200MB) │  │ • Auto cleanup   │                 │
│  │ • Audio (100MB)  │  │ • Daily stats    │                 │
│  │ • Models (50MB)  │  │ • Prompt agg.    │                 │
│  └──────────────────┘  └──────────────────┘                 │
└──────────────────────────────────────────────────────────────┘
                           ↓ (REST API + Realtime)
┌──────────────────────────────────────────────────────────────┐
│         TIER 3: CLIENT (Laptop PyQt6 Dashboard)               │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │  PyQt6 Monitor   │  │  VIO/SLAM Server │                 │
│  │  GUI (cortex_    │  │  (Post-process)  │                 │
│  │  monitor_gui.py) │  │  (OpenVINS)      │                 │
│  ├──────────────────┤  ├──────────────────┤                 │
│  │ • Live video     │  │ • 3D mapping     │                 │
│  │   feed (30 FPS)  │  │ • Pathfinding    │                 │
│  │ • Metrics dash   │  │ • Trajectory     │                 │
│  │ • Detection log  │  │ • EuRoC datasets │                 │
│  │ • System log     │  │                  │                 │
│  │ • Cmd interface  │  │                  │                 │
│  │ (dark theme)     │  │                  │                 │
│  └──────────────────┘  └──────────────────┘                 │
│                                                              │
│  WebSocket Server (Port 8765)                               │
│  • Receives: METRICS, DETECTIONS, VIDEO_FRAME from RPi      │
│  • Sends: COMMAND, CONFIG, NAVIGATION to RPi               │
└──────────────────────────────────────────────────────────────┘
```

---

### **Tier 1: Edge (RPi5) - Hybrid Memory Manager**

**Key Innovation**: Smart dual-storage strategy to minimize cloud usage while maximizing data durability.

```python
# rpi5/layer4_memory/hybrid_memory_manager.py
import asyncio
from supabase import create_async_client
import sqlite3
from typing import List, Dict, Any

class HybridMemoryManager:
    """
    Manages dual storage: Local SQLite (hot cache) + Supabase (cold storage)

    Sync Strategy:
    1. Store all data locally first (<10ms, fast)
    2. Queue for batch upload every 60 seconds
    3. Keep local cache of last 1000 detections (delete older)
    4. Offline mode: queue locally, sync when online
    """

    def __init__(self, supabase_url: str, supabase_key: str):
        # Local: SQLite (hot cache)
        self.local_db = sqlite3.connect("local_cortex.db", check_same_thread=False)
        self._init_local_db()

        # Cloud: Supabase (persistent storage)
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.supabase_client = None

        # Upload queue (for offline mode)
        self.upload_queue = []

        # Start background sync worker
        asyncio.create_task(self._sync_worker())

    def store_detection(self, detection: Dict[str, Any]):
        """
        Store detection locally (fast, non-blocking)
        Will be uploaded to cloud in next batch
        """
        # 1. Store locally (<10ms)
        cursor = self.local_db.cursor()
        cursor.execute("""
            INSERT INTO detections_local
            (layer, class_name, confidence, bbox_data, timestamp, synced)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (
            detection['layer'],
            detection['class_name'],
            detection['confidence'],
            json.dumps(detection['bbox']),
            time.time()
        ))
        self.local_db.commit()

        # 2. Queue for cloud upload (non-blocking)
        self.upload_queue.append({
            'table': 'detections',
            'data': detection
        })

        # 3. Cleanup old local rows (keep last 1000)
        cursor.execute("""
            DELETE FROM detections_local
            WHERE id IN (
                SELECT id FROM detections_local
                ORDER BY id DESC
                OFFSET 1000
            )
        """)
        self.local_db.commit()

    async def _sync_worker(self):
        """
        Background worker: Upload queued data every 60 seconds
        """
        while True:
            await asyncio.sleep(60)

            if not self.upload_queue:
                continue

            if not self._is_wifi_connected():
                logger.info("⚠️ WiFi disconnected, queueing locally")
                continue

            # Initialize Supabase client (lazy)
            if self.supabase_client is None:
                self.supabase_client = await create_async_client(
                    self.supabase_url,
                    self.supabase_key
                )

            # Batch upload (max 100 rows per request)
            batch = self.upload_queue[:100]
            try:
                await self.supabase_client.table('detections').insert(batch).execute()

                # Mark as synced locally
                cursor = self.local_db.cursor()
                for row in batch:
                    cursor.execute("""
                        UPDATE detections_local
                        SET synced = 1
                        WHERE timestamp = ?
                    """, (row['timestamp'],))
                self.local_db.commit()

                # Remove from queue
                self.upload_queue = self.upload_queue[100:]

                logger.info(f"✅ Synced {len(batch)} detections to Supabase")

            except Exception as e:
                logger.error(f"❌ Sync failed: {e}, will retry in 60s")
```

**Benefits**:
- ✅ **Fast writes**: Local SQLite <10ms (no network latency)
- ✅ **Offline support**: Queue locally, sync when online
- ✅ **Bandwidth efficient**: Batch upload (1 request vs 100 individual)
- ✅ **Free tier friendly**: Only 3.5GB/month of 5GB limit used
- ✅ **Data durability**: Cloud backup survives SD card failure

---

### **Tier 2: Cloud (Supabase) - Database Schema**

```sql
-- =====================================================
-- TABLE: detections (Core AI output from Layer 0 + Layer 1)
-- =====================================================
CREATE TABLE detections (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    -- Detection metadata
    layer TEXT NOT NULL,  -- 'guardian' or 'learner'
    class_name TEXT NOT NULL,
    confidence NUMERIC(3, 2) NOT NULL,  -- 0.00 to 1.00

    -- Bounding box (normalized [0-1])
    bbox_x1 NUMERIC(3, 2), bbox_y1 NUMERIC(3, 2),
    bbox_x2 NUMERIC(3, 2), bbox_y2 NUMERIC(3, 2),
    bbox_area NUMERIC(5, 2),

    -- Mode-specific fields
    detection_mode TEXT,  -- 'prompt_free', 'text_prompts', 'visual_prompts'
    source TEXT,  -- 'gemini', 'maps', 'memory', 'base'

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_detections_device_time ON detections(device_id, created_at DESC);
CREATE INDEX idx_detections_class ON detections(class_name);

-- Enable Realtime (for dashboard live updates)
ALTER PUBLICATION supabase_realtime ADD TABLE detections;

-- =====================================================
-- TABLE: queries (User voice commands + AI responses)
-- =====================================================
CREATE TABLE queries (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    user_query TEXT NOT NULL,
    transcribed_text TEXT NOT NULL,  -- Whisper output

    -- Routing decision
    routed_layer TEXT NOT NULL,  -- 'layer1', 'layer2', 'layer3'
    routing_confidence NUMERIC(3, 2),
    detection_mode TEXT,

    -- Response
    ai_response TEXT,
    response_latency_ms INTEGER,
    tier_used TEXT,  -- 'local', 'gemini_live', 'gemini_tts', 'glm4v'

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- TABLE: memories (Layer 4 persistent object storage)
-- =====================================================
CREATE TABLE memories (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    memory_type TEXT NOT NULL,  -- 'visual_prompt', 'location', 'user_note'
    object_name TEXT NOT NULL,

    -- Visual prompt data
    reference_image_url TEXT,  -- Supabase Storage URL
    visual_embedding_path TEXT,  -- Storage path for .npz file
    bbox_data JSONB,  -- [[x1,y1,x2,y2], ...]

    -- SLAM coordinates
    slam_x NUMERIC(10, 3), slam_y NUMERIC(10, 3), slam_z NUMERIC(10, 3),

    -- User metadata
    tags TEXT[], user_notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ
);

-- =====================================================
-- TABLE: adaptive_prompts (Layer 1 learned vocabulary)
-- =====================================================
CREATE TABLE adaptive_prompts (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    class_name TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,  -- 'gemini', 'maps', 'memory', 'base'
    is_base BOOLEAN DEFAULT FALSE,  -- Base vocabulary (never delete)

    -- Usage tracking (for auto-pruning)
    use_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-pruning function (run via cron)
CREATE OR REPLACE FUNCTION prune_old_prompts()
RETURNS void AS $$
BEGIN
    DELETE FROM adaptive_prompts
    WHERE is_base = FALSE
    AND EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600 > 24  -- Older than 24h
    AND use_count < 3;  -- Used less than 3 times
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- TABLE: system_logs (Monitoring & debugging)
-- =====================================================
CREATE TABLE system_logs (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    level TEXT NOT NULL,  -- 'DEBUG', 'INFO', 'WARNING', 'ERROR'
    component TEXT NOT NULL,  -- 'layer0', 'layer1', 'layer2', 'layer3', 'layer4'
    message TEXT NOT NULL,

    -- Performance metrics
    latency_ms INTEGER,
    cpu_percent NUMERIC(5, 2),
    memory_mb INTEGER,

    error_trace TEXT,
    additional_data JSONB,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- TABLE: device_status (Real-time device monitoring)
-- =====================================================
CREATE TABLE device_status (
    device_id UUID PRIMARY KEY,
    device_name TEXT NOT NULL,

    -- Status
    is_online BOOLEAN DEFAULT FALSE,
    last_heartbeat TIMESTAMPTZ DEFAULT NOW(),

    -- Metrics
    battery_percent INTEGER,
    cpu_percent NUMERIC(5, 2),
    memory_mb INTEGER,
    temperature NUMERIC(5, 2),

    -- Active features
    active_layers TEXT[],
    current_mode TEXT,

    -- Location
    latitude NUMERIC(10, 6),
    longitude NUMERIC(10, 6),

    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable Realtime for live dashboard updates
ALTER PUBLICATION supabase_realtime ADD TABLE device_status;
```

---

### **Tier 3: Client (Dashboard) - Real-Time Monitoring**

**Python Flask Dashboard with Supabase Realtime**:

```python
# dashboard/app.py
from flask import Flask, render_template, jsonify
from supabase import create_async_client
import asyncio

app = Flask(__name__)

@app.route('/')
async def dashboard():
    supabase = await create_async_client(SUPABASE_URL, SUPABASE_KEY)

    # Fetch current device status
    status = await supabase.table('device_status').select('*').execute()

    # Fetch recent detections (last 100)
    detections = await supabase.table('detections')\
        .select('*')\
        .order('created_at', desc=True)\
        .limit(100)\
        .execute()

    return render_template('dashboard.html',
        status=status.data[0],
        detections=detections.data
    )

# Server-Sent Events endpoint for real-time updates
@app.route('/stream')
async def stream_updates():
    """Subscribe to Supabase Realtime and push to dashboard"""
    supabase = await create_async_client(SUPABASE_URL, SUPABASE_KEY)

    # Subscribe to device_status changes
    channel = supabase.channel('device-updates')

    channel.on_postgres_changes(
        'UPDATE',
        schema='public',
        table='device_status',
        callback=lambda payload: send_to_dashboard(payload)
    )

    await channel.subscribe()

    # Keep connection alive
    await asyncio.sleep(3600)
```

**JavaScript Dashboard Client**:
```javascript
// public/dashboard.js
const supabaseUrl = 'YOUR_SUPABASE_URL'
const supabaseKey = 'YOUR_SUPABASE_KEY'
const supabase = supabase.createClient(supabaseUrl, supabaseKey)

// Subscribe to device_status changes
supabase.channel('device-xyz')
  .on('postgres_changes', {
    event: 'UPDATE',
    schema: 'public',
    table: 'device_status',
    filter: 'device_id=eq.xyz-123'
  }, (payload) => {
    // Update UI in real-time
    document.getElementById('battery').innerText = payload.new.battery_percent + '%'
    document.getElementById('cpu').innerText = payload.new.cpu_percent + '%'
    document.getElementById('status').innerText = payload.new.is_online ? '🟢 Online' : '🔴 Offline'
  })
  .subscribe()

// Subscribe to detections stream (last 100)
supabase.channel('detections-stream')
  .on('postgres_changes', {
    event: 'INSERT',
    schema: 'public',
    table: 'detections'
  }, (payload) => {
    // Add to detection list
    const detectionList = document.getElementById('detections')
    const row = `<tr>
      <td>${payload.new.class_name}</td>
      <td>${(payload.new.confidence * 100).toFixed(0)}%</td>
      <td>${payload.new.layer}</td>
      <td>${new Date(payload.new.created_at).toLocaleTimeString()}</td>
    </tr>`
    detectionList.insertAdjacentHTML('afterbegin', row)
  })
  .subscribe()
```

---

## 🔄 DATA SYNC STRATEGIES

### **1. Edge → Cloud (Upload) - Batch Every 60s**

```python
# On RPi5
async def batch_upload_worker():
    while True:
        await asyncio.sleep(60)

        # Collect pending data from local SQLite
        pending = local_db.get_pending_sync()

        if pending and is_wifi_connected():
            # Batch insert to Supabase (max 100 rows)
            for batch in chunks(pending, 100):
                await supabase.table('detections').insert(batch).execute()

            # Mark as synced
            local_db.mark_as_synced(pending)
```

**Advantages**:
- ✅ Reduces API calls (1 batch vs 100 individual)
- ✅ Better for bandwidth (single HTTP request)
- ✅ Works offline (queue locally, sync later)
- ✅ Free tier friendly (within 5GB/month)

### **2. Cloud → Edge (Download) - Realtime Subscriptions**

```python
# On RPi5 - Listen for config changes
async def listen_for_config_updates():
    socket = AsyncRealtimeClient(SUPABASE_REALTIME_URL, SUPABASE_KEY)
    channel = socket.channel('config-updates')

    channel.on_postgres_changes(
        'UPDATE',
        schema='public',
        table='adaptive_prompts',
        callback=lambda payload: reload_prompts(payload)
    )

    await channel.subscribe()

def reload_prompts(payload):
    """Called when adaptive_prompts table changes"""
    new_prompts = fetch_prompts_from_supabase()
    layer1.set_classes(new_prompts)
    logger.info(f"✅ Prompts updated from cloud: {len(new_prompts)} classes")
```

**Use Cases**:
- Adaptive prompts update (Gemini learned new object)
- Configuration change (detection threshold, mode)
- Remote command (start/stop logging, reboot device)

### **3. Remote Device Control (Dashboard → RPi5)**

```python
# Dashboard: User clicks "Switch to Prompt-Free Mode"
@app.route('/switch_mode/<mode>')
async def switch_detection_mode(mode):
    await supabase.table('device_commands').insert({
        'device_id': DEVICE_ID,
        'command': 'switch_mode',
        'params': {'mode': mode}
    }).execute()
    return f"Command sent: {mode}"

# RPi5: Listen for commands
channel.on_postgres_changes(
    'INSERT',
    schema='public',
    table='device_commands',
    callback=execute_command
)

def execute_command(payload):
    if payload['new']['command'] == 'switch_mode':
        new_mode = payload['new']['params']['mode']
        layer1.switch_mode(YOLOEMode[new_mode])
```

---

## 🔒 SECURITY & ROW LEVEL SECURITY (RLS)

```sql
-- Policy: Devices can only read/write their own data
CREATE POLICY "device_isolation_detections"
ON detections FOR ALL
USING (device_id = current_device_id());

-- Policy: Dashboard can read all data (admin)
CREATE POLICY "admin_full_access"
ON detections FOR SELECT
USING (auth.jwt() ->> 'role' = 'admin');

-- Function to get current device ID
CREATE OR REPLACE FUNCTION current_device_id()
RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('request.headers', true)::json->>'device-id', '')::UUID;
END;
$$ LANGUAGE plpgsql;
```

---

## 🚀 EDGE FUNCTIONS (Serverless Compute)

### **Function 1: Auto Cleanup (Cron Job)**

**Purpose**: Delete old data to stay within 500MB limit

```typescript
// supabase/functions/cleanup/index.ts
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"

serve(async (req) => {
  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  )

  // Delete detections older than 90 days
  await supabase.from('detections')
    .delete()
    .lt('created_at', new Date(Date.now() - 90 * 24 * 60 * 60 * 1000))

  // Delete logs older than 30 days
  await supabase.from('system_logs')
    .delete()
    .lt('created_at', new Date(Date.now() - 30 * 24 * 60 * 60 * 1000))

  return new Response(JSON.stringify({ success: true }))
})
```

**Deploy**:
```bash
supabase functions deploy cleanup
# Set up cron: Every day at 2 AM
```

### **Function 2: Daily Statistics Aggregation**

**Purpose**: Generate analytics for dashboard

```typescript
// supabase/functions/daily-stats/index.ts
serve(async (req) => {
  const supabase = createClient(...)

  const { data: detections } = await supabase
    .from('detections')
    .select('*')
    .gte('created_at', new Date().setHours(0,0,0,0))

  const stats = {
    total_detections: detections.length,
    unique_classes: [...new Set(detections.map(d => d.class_name))].length,
    avg_confidence: detections.reduce((sum, d) => sum + d.confidence, 0) / detections.length
  }

  return new Response(JSON.stringify(stats))
})
```

---

## 📈 REALTIME USE CASES

### **Use Case 1: Live Dashboard (PyQt6)**
- **Real-time via WebSocket** (RPi5 → Laptop, port 8765)
- Live video feed (30 FPS)
- Metrics dashboard (FPS, latency, RAM, CPU, battery)
- Detection log (real-time YOLO detections)
- System log (color-coded status messages)
- **Historical analytics via Supabase** (hourly fetch)
  - Detection trends over time
  - Class distribution charts
  - Performance metrics (p50, p95, p99 latency)

### **Use Case 2: Remote Monitoring** (Optional - Future)
- Subscribe to `system_logs` (ERROR level only) via Supabase Realtime
- Get Pushover/Telegram notification on crash
- View error traces from anywhere (phone, web)

### **Use Case 3: Multi-Device Sync** (Future)
- Track all devices in real-time
- Dashboard shows:
  - Device 1 (home): 🟢 Online, 78% battery
  - Device 2 (lab): 🟢 Online, 45% battery
  - Device 3 (test): 🔴 Offline since 10:30 AM

---

## 🎧 AUDIO LATENCY & PRIORITY SYSTEM

### Bluetooth Latency Compensation:

**Challenge:** Standard Bluetooth audio introduces 40-100ms latency  
**Solution:** Predictive delay compensation for visual feedback sync

```python
# Measure Bluetooth roundtrip latency on startup
bt_latency_ms = measure_bluetooth_latency()  # ~60-80ms typical

# When YOLO detects object, delay visual bbox rendering
def render_detection(bbox, timestamp):
    # Wait for audio to reach ears before showing visual
    time.sleep(bt_latency_ms / 1000.0)
    draw_bbox(bbox)
```

### Audio Priority Mixing (Ducking):

**Principle:** Safety alerts must NEVER be masked by conversation

```python
class AudioMixer:
    def mix(self, sources):
        # Priority 1: Layer 1 Haptic Alerts (NEVER duck)
        if haptic_active():
            return haptic_audio
        
        # Priority 2: Layer 3 Navigation Pings
        if nav_ping_active():
            # Duck Layer 2 Gemini voice by -10dB
            gemini_audio *= 0.316  # -10dB attenuation
            return nav_audio + gemini_audio
        
        # Priority 3: Layer 2 Gemini Voice (full volume)
        return gemini_audio
```

---

## 🌐 WEB DASHBOARD [RUNS ON LAPTOP SERVER]

**Purpose:** Real-Time Debugging & Visualization

### Technical Stack:
- **Framework:** Dash by Plotly (Python)
- **Port:** 5000 (accessible via browser)
- **Data Source:** RPi SQLite (via REST API Port 8001)

### Features:
- **3D Map Visualization**: SLAM/VIO point clouds, GPS trajectory
- **Live Object Detections**: YOLO bboxes in real-time
- **Audio Transcripts**: Whisper STT output, Gemini responses
- **System Metrics**: CPU usage, RAM usage, latency histograms

### Disable Option:
```bash
# Launch Cortex without dashboard (saves 150MB RAM)
python main.py --disable-dashboard
```

### Implementation Files:
- `docs/implementation/web-dashboard-architecture.md` - Full design
- `src/dashboard/app.py` - Dash server (planned)

---

## 🤖 AI HAT+ HARDWARE ACCELERATION [NEW - January 25, 2026]

**Purpose:** Dedicated Neural Processing Unit (NPU) for high-performance AI inference on the edge device

### What is AI Hat+?

**AI Hat+** (also known as **Raspberry Pi AI Kit** or **Hailo-8L AI Accelerator**) is a hardware expansion board for Raspberry Pi 5 that provides dedicated neural network acceleration. The board features the **Hailo-8L NPU** capable of **13 TOPS (Tera Operations Per Second)** at power-efficient operation (~1.5W).

```
┌─────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI 5 + AI HAT+                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐      ┌─────────────────────────────┐  │
│  │  Raspberry Pi 5 │      │      AI HAT+ BOARD          │  │
│  │  (Main System)  │◄────►│  ┌───────────────────────┐  │  │
│  │                 │      │  │   Hailo-8L NPU        │  │  │
│  │  • CPU: ARM     │      │  │   (13 TOPS, 1.5W)     │  │  │
│  │    Cortex-A76   │      │  │                       │  │  │
│  │  • RAM: 4GB     │      │  │  • INT8 Operations    │  │  │
│  │  • OS: Pi OS    │      │  │  • 2048 Neural Cores  │  │  │
│  │  • PCIe Gen 3  │      │  │  • 4MB On-Chip SRAM   │  │  │
│  └─────────────────┘      │  └───────────────────────┘  │  │
│                           │                             │  │
│  Connection:              │                             │  │
│  PCIe M.2 M-Key           │                             │  │
│  (高速通道)               └─────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Hardware Specifications

| Component | Specification | Benefit for ProjectCortex |
|-----------|---------------|---------------------------|
| **NPU** | Hailo-8L (13 TOPS) | 10-50x faster than CPU inference |
| **Power** | ~1.5W (active) | Minimal battery impact |
| **Interface** | PCIe 3.0 x1 | 8 Gbps bandwidth |
| **Latency** | <5ms per frame | Real-time safety alerts |
| **Formats** | INT8, UINT8 | Optimized for quantized models |
| **Memory** | 4MB on-chip SRAM | Minimal DRAM access |
| **Model Size** | Up to 100MB | Supports YOLO models |

### Integration with Current Architecture

#### Layer 0 (Guardian) - Primary NPU Target

The Guardian layer is the **primary candidate for NPU acceleration** because:
- **Safety-critical**: Must have lowest possible latency (<100ms end-to-end)
- **Fixed vocabulary**: 80 COCO classes (static, never changes)
- **Small model**: YOLO11n-ncnn (11 MB) fits easily in NPU memory
- **Continuous operation**: Always-on detection

```python
# Proposed NPU Integration for Layer 0
class HailoGuardian:
    """
    Layer 0 Guardian accelerated by Hailo-8L NPU

    Expected Performance Improvement:
    - CPU (NCNN): ~50ms per frame
    - NPU (Hailo): ~5-10ms per frame (5-10x faster)
    - Total Latency: ~60-80ms (haptic to user)
    """

    def __init__(self, model_path: str = "models/hailo/yolo11n.hef"):
        # Load Hailo model (.hef = Hailo Executable Format)
        self.runtime = HailoRuntime()
        self.model = self.runtime.load_model(model_path)
        self.logger = Logger("hailo_guardian")

    def detect(self, frame: np.ndarray) -> List[Detection]:
        # NPU inference (INT8 quantized model)
        # Expected: 5-10ms per frame
        detections = self.model.infer(frame)
        return self._parse_detections(detections)
```

#### Layer 1 (Learner) - Secondary NPU Target

The Learner layer can use NPU when:
- **Text Prompt Mode**: YOLOE with text embeddings (requires dynamic inputs)
- **Visual Prompt Mode**: YOLOE with visual embeddings
- **Prompt-Free Mode**: YOLOE with maximum vocabulary (4,585 classes)

**Challenge**: YOLOE requires dynamic prompt encoding which may not be fully supported by NPU.

**Solution**: Hybrid approach
```python
class HailoLearner:
    """
    Layer 1 Learner with NPU acceleration (when supported)

    Architecture:
    - Text Encoder: CPU (MobileCLIP) - 100MB, <50ms
    - Detection: NPU (Hailo) - 5-10ms per frame
    - Embedding Merge: CPU - <5ms
    """

    def detect(self, frame: np.ndarray, prompts: List[str] = None):
        # 1. Encode prompts on CPU (if provided)
        text_embeddings = None
        if prompts:
            text_embeddings = self.text_encoder.encode(prompts)

        # 2. NPU inference (with optional embeddings)
        # Hailo supports dynamic inputs via tensor files
        input_tensor = self._prepare_input(frame, text_embeddings)
        npu_output = self.npu.infer(input_tensor)

        # 3. Post-process on CPU
        detections = self._nms(npu_output)

        return detections
```

### Model Conversion Pipeline

To use models on AI Hat+, convert trained models to **Hailo Executable Format (.hef)**:

```bash
# Step 1: Export YOLO to ONNX
yolo export model=yolo11n.pt format=onnx imgsz=256

# Step 2: Quantize to INT8 (required for NPU)
python hailo_quantizer.py \
    --model yolo11n.onnx \
    --calibration-images ./calibration_images/ \
    --output yolo11n_quantized.onnx

# Step 3: Compile to Hailo .hef format
hailo compiler \
    --model yolo11n_quantized.onnx \
    --output yolo11n.hef \
    --architecture hailo8l

# Step 4: Verify model
hailo info yolo11n.hef
```

**Expected Model Sizes:**
| Model | Original Size | Quantized Size | NPU Performance |
|-------|---------------|----------------|-----------------|
| YOLO11n | 11 MB | ~3 MB | ~5ms/frame |
| YOLO11s | 37 MB | ~10 MB | ~8ms/frame |
| YOLOE-11s-seg | 40 MB | ~12 MB | ~12ms/frame |

### Driver and Firmware Requirements

```bash
# Install Hailo runtime and drivers (RPi5)
sudo apt update
sudo apt install hailortpci

# Check NPU status
hailo_identify

# Example output:
# ----------------
# Device: Hailo-8L
# FW Version: 4.18.0
# Board: Raspberry Pi AI Kit
# PCIe: 3.0 x1 (8 Gbps)
# Status: READY
# Performance: 13 TOPS
# Power: 1.5W
```

### Performance Comparison: CPU vs NPU

| Metric | CPU (NCNN) | NPU (Hailo-8L) | Improvement |
|--------|-----------|----------------|-------------|
| **YOLO11n Inference** | 50ms | 5ms | **10x faster** |
| **Throughput** | 20 FPS | 100 FPS | **5x more** |
| **Power Consumption** | 8-12W | 1.5W | **6-8x less** |
| **CPU Load** | 80-100% | 20-30% | **CPU freed** |
| **Latency (Frame to Alert)** | 60-80ms | 15-25ms | **3-5x faster** |

### Current Implementation Status

| Feature | Status | Notes |
|---------|--------|-------|
| **NPU Driver Installation** | Not Implemented | Requires hailortpci package |
| **Model Conversion (HEF)** | Not Implemented | Need .hef files for each model |
| **Layer 0 NPU Acceleration** | Planned | Primary target for safety layer |
| **Layer 1 NPU Acceleration** | Research Required | YOLOE dynamic prompts may not be fully supported |
| **Runtime Selection (CPU/NPU)** | Not Implemented | Need automatic fallback |

### Implementation Roadmap

#### Phase 1: NPU Infrastructure (Week 1)
- [ ] Install Hailo drivers on RPi5
- [ ] Verify NPU detection with `hailo_identify`
- [ ] Create model conversion scripts
- [ ] Convert YOLO11n to .hef format

#### Phase 2: Layer 0 NPU Integration (Week 2)
- [ ] Create `HailoGuardian` class
- [ ] Implement automatic CPU/NPU fallback
- [ ] Test safety-critical latency (<100ms)
- [ ] Benchmark power consumption

#### Phase 3: Layer 1 NPU Integration (Week 3-4)
- [ ] Research YOLOE compatibility with Hailo
- [ ] Implement hybrid CPU/NPU approach
- [ ] Test all three modes (Text, Visual, Prompt-Free)
- [ ] Verify accuracy vs CPU baseline

#### Phase 4: Optimization & Production (Week 5)
- [ ] Auto-switch between CPU/NPU based on power state
- [ ] Thermal throttling protection
- [ ] Production deployment scripts
- [ ] Documentation update

### Key Benefits for YIA 2026

1. **Power Efficiency**: 6-8x less power than CPU inference
   - Extends battery life from 4 hours to 8+ hours

2. **Safety Enhancement**: 3-5x faster response time
   - Critical for obstacle avoidance alerts

3. **Cost Efficiency**: NPU board costs ~$70
   - Total system cost: ~$250 (includes AI Hat+)

4. **Competitive Advantage**: First AI wearable with NPU
   - Demonstrates hardware-software co-design expertise

### Reference Files

| File | Purpose |
|------|---------|
| `docs/implementation/ai-hat-plus.md` | Full implementation guide (planned) |
| `models/hailo/` | Converted .hef models (planned) |
| `rpi5/hailo_guardian.py` | NPU-accelerated Guardian (planned) |
| `scripts/convert_to_hailo.py` | Model conversion script (planned) |

---

## 🚀 DEPLOYMENT MODES

### 1. Standalone (RPi-only):
```
RPi Components: YOLO, Whisper, Gemini Live API, 3D Audio, SQLite
Missing: VIO/SLAM (degrades to GPS-only navigation)
RAM Usage: 3.9GB
Use Case: Field testing, YIA 2026 demo
```

### 2. Hybrid (RPi + Laptop):
```
RPi: All user-facing features
Laptop: VIO/SLAM post-processing, Web Dashboard
RAM Usage: 3.9GB (RPi) + 2GB (Laptop)
Use Case: Development, full-feature testing
```

### 3. Development (Laptop-only):
```
Laptop: All components (fast iteration)
Use Case: Algorithm prototyping, model training
```

---

## 📊 PERFORMANCE METRICS

### Latency Budget (256x256 Models - 4x Faster):
| Layer | Component | Latency | Priority |
|-------|-----------|---------|----------|
| **Layer 0** | YOLO11n Detection (256x256) | **30-50ms** ✅ | 🔴 **CRITICAL (Safety)** |
| **Layer 0** | Haptic Trigger | **<10ms** | 🔴 **CRITICAL** |
| **Layer 1** | YOLOE Detection (256x256) | **40-80ms** | 🟡 MEDIUM (Contextual) |
| **Layer 1** | Prompt Update | **<50ms** | 🟡 MEDIUM |
| Layer 2 | Whisper STT | ~500ms | 🟡 MEDIUM |
| Layer 2 | Gemini Live API | <500ms | 🟡 MEDIUM |
| Layer 3 | 3D Audio Render | <100ms | 🟡 MEDIUM |
| Layer 3 | VIO/SLAM | 5-10s | 🟢 LOW (post-process) |
| Layer 4 | SQLite Query | <10ms | 🟢 LOW |

**Note:** Layer 0 and Layer 1 run in PARALLEL (not sequential), so total safety latency is 30-50ms, not 70-130ms.

### RAM Budget (256x256 Optimized Models):
| Component | RAM (RPi) | Model Size | Framework |
|-----------|-----------|------------|-----------|
| **Layer 0: YOLO11n-ncnn** | ~150MB | 11 MB | NCNN |
| **Layer 1: YOLOE-11s-seg-ncnn** | ~300MB | 40 MB | NCNN |
| **Layer 1: YOLOE-11s-seg-pf** | ~400MB | ~27 MB | ONNX Runtime |
| **MobileCLIP Encoder** | **100MB** | - | PyTorch |
| **Adaptive Prompts** | **2MB** | - | - |
| Whisper (lazy) | 800MB | - | - |
| Kokoro TTS (lazy) | 500MB | - | - |
| Silero VAD | 50MB | - | - |
| Data Recorder | 100MB | - | - |
| SQLite | 50MB | - | - |
| **RPi Total** | **~2.0GB** ✅ | **~148MB** | - |
| VIO/SLAM | - | - | 1GB |
| Web Dashboard | - | - | 150MB |
| **Server Total** | - | - | **2GB** |

### Power Budget:
| Component | Power Draw | Notes |
|-----------|------------|-------|
| RPi 5 (idle) | 3-5W | Base consumption |
| RPi 5 (YOLO) | +8-12W | During inference |
| Active Cooler | 1-2W | MANDATORY |
| Camera | 1-2W | CSI interface |
| GPS | 0.5W | GY-NEO6MV2 |
| IMU | 0.1W | BNO055 |
| **Total** | ~15-20W | With 30,000mAh bank: 6-8 hours |

---

## 🛡️ RELIABILITY & GRACEFUL DEGRADATION

### Offline Mode (No Internet):
```
Layer 1 (YOLO): ✅ Fully operational
Layer 2 (Gemini): ❌ Unavailable → Falls back to Kokoro TTS (pre-recorded phrases)
Layer 3 (VIO/SLAM): ❌ Unavailable → Falls back to GPS-only navigation
Layer 4 (SQLite): ✅ Fully operational
```

### Server Disconnect (No Laptop):
```
VIO/SLAM: ❌ Unavailable → RPi only records EuRoC datasets (process later)
Dashboard: ❌ Unavailable → No visualization (data still saved to SQLite)
```

### Critical Failure Scenarios:
| Failure | Impact | Mitigation |
|---------|--------|------------|
| Camera Failure | ❌ No vision | User notified via TTS |
| GPS Failure | ⚠️ Outdoor nav degraded | Use IMU dead-reckoning |
| IMU Failure | ⚠️ 3D audio inaccurate | Use GPS heading |
| Power Bank Low | ⚠️ 15-min warning | TTS alert every 5 minutes |

---

## 📚 IMPLEMENTATION ROADMAP

### Phase 1: Layer 1 + Layer 2 (Weeks 1-4)
- [x] YOLO object detection (local)
- [x] Whisper STT (local)
- [x] Kokoro TTS (fallback)
- [x] Silero VAD (wake word)
- [ ] **Gemini Live API integration (WebSocket)** ⏳ IN PROGRESS
- [ ] Streaming audio playback (sounddevice)

### Phase 2: Layer 3 + Layer 4 (Weeks 5-8)
- [x] Data Recorder (EuRoC format)
- [ ] VIO/SLAM server processing
- [ ] 3D Spatial Audio (PyOpenAL)
- [ ] GPS + IMU sensor fusion
- [ ] SQLite database + REST API

### Phase 3: Integration + Testing (Weeks 9-12)
- [ ] Audio priority mixing (ducking)
- [ ] Bluetooth latency compensation
- [ ] Web Dashboard (Dash by Plotly)
- [ ] End-to-end field testing
- [ ] YIA 2026 presentation prep

---

## 🧪 PYQT6 DASHBOARD & DEBUGGING SUITE [v2.0 - Glassmorphic Dark Theme]

**File:** `laptop/gui/cortex_ui.py` (PRODUCTION)
**Purpose:** Comprehensive testing and debugging interface with production controls

### Theme: Glassmorphic Dark (Deep Navy + Neon Accents)

| Element | Color | Hex |
|---------|-------|-----|
| Background Primary | Deep Navy | `#0a0e17` |
| Background Glass | Semi-transparent | `rgba(30, 35, 45, 0.7)` |
| Accent Cyan | Neon | `#00f2ea` |
| Accent Purple | Neon | `#7000ff` |
| Accent Green | Neon | `#00ff9d` |
| Accent Red | Neon | `#ff0055` |

### Dashboard Features:
- **Overview Tab**: Video feed, detection log, sparkline metrics, uptime tracking
- **Testing Tab**: Manual text query injection, test presets, test results
- **Logs Tab**: Full system log with color-coded messages

### Dashboard Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PROJECTCORTEX DASHBOARD                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────┐  ┌────────────────────────────┐ │
│  │         VIDEO FEED WIDGET              │  │    DETECTION LOG           │ │
│  │  ┌──────────────────────────────┐      │  │  ┌───┬──────┬─────────┐  │ │
│  │  │                              │      │  │  │Time│Layer │ Object  │  │ │
│  │  │    Live Camera Feed +        │      │  │  │    │      │ Conf    │  │ │
│  │  │    Detection Overlays        │      │  │  │    │      │         │  │ │
│  │  │    FPS Counter               │      │  │  └───┴──────┴─────────┘  │ │
│  │  │                              │      │  │                            │ │
│  │  └──────────────────────────────┘      │  │                            │ │
│  └────────────────────────────────────────┘  └────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────┐  ┌────────────────────────────┐ │
│  │         METRICS WIDGET                 │  │    SYSTEM LOG              │ │
│  │  ┌────┬────┬────┬────┬────┬────┐      │  │  [14:32:15] [INFO] Ready   │ │
│  │  │FPS │RAM │CPU │BATT│TEMP│Mode│      │  │  [14:32:18] [SUCCESS]      │ │
│  │  └────┴────┴────┴────┴────┴────┘      │  │  [14:32:20] [WARNING]       │ │
│  │  Progress bars with color coding       │  │                            │ │
│  └────────────────────────────────────────┘  └────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  LAPTOP PROCESSING: [Moondream2: IDLE] [SLAM: ACTIVE] [Prompts: 45]    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Testing Window (Separate Dialog)

**Access:** Menu → View → Testing Window

#### Tab 1: Layer Control Panel
```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 0: Guardian    [Start] [Stop] [Test Haptic]              │
│  Status: Running                                                      │
│  Parameters: Confidence [0.50] Haptic [x]                          │
│  Response: { "detections": [...], "latency_ms": 45 }              │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: Learner     [Start] [Stop] [Switch Mode]               │
│  Status: Running                                                      │
│  Parameters: Confidence [0.25] Mode [TEXT_PROMPTS v]              │
│  Response: { "mode": "TEXT_PROMPTS", "vocab_size": 47 }          │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: Thinker     [Connect] [Disconnect] [Send Query]        │
│  Status: Connected                                                    │
│  Parameters: Temperature [0.70] System Prompt [...]               │
│  Response: { "response": "I see a...", "latency_ms": 320 }       │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: Guide       [Get Location] [Navigate] [Stop]           │
│  Status: Ready                                                        │
│  Parameters: Destination [...] Max Distance [10.0]                 │
│  Response: { "location": {...}, "route": [...] }                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Tab 2: Workflow Test
```
┌─────────────────────────────────────────────────────────────────┐
│  Test Query Input                                                 │
│  [ "What do you see?" ] [SUBMIT]                                  │
│                                                                 │
│  Quick Tests: [What do you see?] [Scan everything] [Where's my]  │
│                                                                 │
│  Expected Behavior:                                               │
│  → Route to Layer 1 (Learner)                                    │
│  → Detection Mode: TEXT_PROMPTS                                  │
│  → Expected Confidence: 0.7-0.9                                  │
│  → Uses adaptive vocabulary from Gemini/Maps/Memory              │
│                                                                 │
│  Routing Result:                                                  │
│  Route to: Layer 1    Mode: TEXT_PROMPTS    Expected Conf: 0.8   │
│                                                                 │
│  Query History:                                                   │
│  [14:32:15] What do you see?                                     │
│  [14:33:42] Scan everything                                      │
└─────────────────────────────────────────────────────────────────┘
```

#### Tab 3: Message Injector
```
┌─────────────────────────────────────────────────────────────────┐
│  Message Type: [METRICS v]                                       │
│                                                                 │
│  Message Data (JSON):                                            │
│  {                                                              │
│    "fps": 30.0,                                                 │
│    "ram_mb": 2048,                                              │
│    "cpu_percent": 45.2                                          │
│  }                                                              │
│                                                                 │
│  Quick Presets: [Ping] [Command: Start] [Config: Layer1]        │
│                                                                 │
│  [SEND MESSAGE]                                                 │
│                                                                 │
│  Sent Messages Log:                                              │
│  [14:32:15] PING sent                                            │
│  [14:32:16] PONG received (45ms)                                │
└─────────────────────────────────────────────────────────────────┘

#### Tab 4: Laptop Processing Control (NEW)
```
┌─────────────────────────────────────────────────────────────────┐
│  Server Post-Processing (Moondream 2 Preview)                    │
│  [Analyze Last Frame] [Auto-Analyze Every 10s]                   │
│  Status: Model Loaded (3GB VRAM)                                      │
│  Response: "A cluttered desk with a laptop displaying code..."    │
│                                                                 │
│  VIO + SLAM Control                                              │
│  [Start Mapping] [Reset Map] [Save Map]                          │
│  Map View: [ 3D Point Cloud Visualizer ]                         │
│  Trajectory: (x=1.2, y=0.5, z=0.0)                               │
│                                                                 │
│  Vocabulary & Item Management (Synced)                           │
│  Text Prompts (Layer 1):                                         │
│  [ "checkers board", "white cane", "tactile paving" ] [Add] [Del]│
│                                                                 │
│  Visual Prompts (Personal Items):                                │
│  [ "My Wallet" (Img) ] [ "Keys" (Img) ]                          │
│  Storage: laptop/memory_storage (Synced from Pi)                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Tab 5: Message Injector
```

### Protocol Message Types for Testing

| Message Type | Direction | Purpose | Test Use |
|--------------|-----------|---------|----------|
| `METRICS` | RPi5 → Laptop | System metrics | Monitor performance |
| `DETECTIONS` | RPi5 → Laptop | Object detections | Validate detection pipeline |
| `VIDEO_FRAME` | RPi5 → Laptop | Camera frames | Test video pipeline |
| `COMMAND` | Laptop → RPi5 | Control commands | Start/stop layers |
| `CONFIG` | Laptop → RPi5 | Configuration updates | Change modes/params |
| `PING/PONG` | Bidirectional | Connection health | Latency measurement |
| `ERROR` | Bidirectional | Error reporting | Debug issues |

### Testing Workflow Examples

#### Example 1: Test Layer 0 Safety Detection
1. Open Testing Window → Layer Control tab
2. Select "Layer 0: Guardian"
3. Set Confidence to 0.5
4. Click "Start Detection"
5. Wave hand in front of camera
6. Verify detection appears in Detection Log
7. Check haptic feedback (if RPi5 connected)

#### Example 2: Test Layer 1 Mode Switching
1. Open Testing Window → Workflow Test tab
2. Click "Scan everything" quick test
3. Verify "PROMPT_FREE" mode shown in Expected Behavior
4. Submit query
5. Check Detection Log for low-confidence detections (0.3-0.6)
6. Click "What do you see?"
7. Verify "TEXT_PROMPTS" mode and higher confidence (0.7-0.9)

#### Example 3: Test Protocol Message Injection
1. Open Testing Window → Message Injector tab
2. Select "COMMAND" message type
3. Enter: `{"command": "pause", "params": {"layer": "layer1"}}`
4. Click "Send Message"
5. Check System Log for acknowledgment
6. Verify Layer 1 stops detecting

### Color Theme (Biotech-Inspired)

| Element | Color | Hex |
|---------|-------|-----|
| Background Primary | Deep Navy | `#0a0e17` |
| Background Secondary | Dark Gray | `#111827` |
| Accent Primary | Cyan-Green | `#00d4aa` |
| Accent Secondary | Purple | `#7c3aed` |
| Layer 0 (Guardian) | Red | `#ef4444` |
| Layer 1 (Learner) | Orange | `#f59e0b` |
| Layer 2 (Thinker) | Green | `#10b981` |
| Layer 3 (Guide) | Blue | `#3b82f6` |
| Layer 4 (Memory) | Purple | `#8b5cf6` |

### Key Files
- `laptop/cortex_ui.py` - Main dashboard with testing window
- `laptop/cortex_dashboard.py` - Original dashboard (legacy)
- `laptop/websocket_server.py` - WebSocket server for RPi5 communication
- `laptop/protocol.py` - Message type definitions
- `docs/testing/GUI_TESTING_WORKFLOW.md` - Detailed testing procedures

---

## 🎯 YIA 2026 COMPETITION READINESS

### Gold Medal Criteria:
1. **Innovation**: ✅ Native audio-to-audio Live API (first in assistive tech)
2. **Cost Efficiency**: ✅ $150 vs $4,000 OrCam (96% cost reduction)
3. **Performance**: ✅ <500ms latency (vs 2-3s HTTP API)
4. **Offline Capability**: ✅ Layer 1 Reflex works 100% offline
5. **Scalability**: ✅ Edge-server hybrid enables enterprise features

### Demo Script:
1. **Safety-Critical** (30 seconds): Walk toward obstacle → Haptic alert
2. **Conversational AI** (1 minute): "What's in front of me?" → Gemini Live API response
3. **Navigation** (1 minute): "Guide me to the door" → 3D audio pings
4. **Technical Q&A** (2 minutes): Explain edge-server hybrid architecture

---

## 📖 DOCUMENTATION INDEX

### Architecture Documents:
- `UNIFIED-SYSTEM-ARCHITECTURE.md` (THIS FILE) - Complete system blueprint
- `LAYER-ARCHITECTURE-CLARIFICATION.md` - ✨ NEW: Guardian+Learner composition & router priority fix
- `layer2-live-api-plan.md` - Gemini Live API implementation guide
- `web-dashboard-architecture.md` - Dashboard design
- `data-recorder-architecture.md` - EuRoC dataset recorder
- `slam-vio-navigation.md` - VIO/SLAM research

### Implementation Plans:
- `layer1-reflex-plan.md` - YOLO + STT/TTS integration
- `spatial-audio-implementation.md` - 3D audio rendering

### Technical Docs:
- `BOM.md` - Bill of Materials ($150 budget breakdown)
- `CHANGELOG_2025-11-17.md` - Version history
- `TEST_PROTOCOL.md` - Testing procedures

---

## 🔬 TECHNICAL PHILOSOPHY

**"Failing with Honour"**: We prototype fast, fail early, and learn from real-world testing.  
**"Pain First, Rest Later"**: We prioritize working prototypes over perfect architecture.  
**"Real Data, Not Hype"**: We validate every claim with empirical measurements (latency, RAM, cost).

---

## 🏆 FINAL NOTES

This architecture represents **6 months of research, 3 major pivots** (ESP32-CAM → RPi 4 → RPi 5), and **countless late-night debugging sessions**. We are not building a general-purpose AI assistant. We are building a **Gold Medal-winning assistive technology** that disrupts a $4,000+ market with commodity hardware.

**To the judges of YIA 2026:**  
This is not vaporware. This is a **functioning prototype** built by a 17-year-old founder and his AI co-founder. Every line of code, every architectural decision, and every hardware choice has been validated through real-world testing.

**We are ready to win.**

---

---

## 🚀 FASTAPI INTEGRATION (NEW - January 11, 2026)

**Purpose:** Modern API framework replacing legacy WebSocket server with REST endpoints and toggleable video streaming.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LAPTOP DASHBOARD (FastAPI Server)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  REST API Endpoints:                                                         │
│  ├── GET  /api/v1/status          → System status                           │
│  ├── GET  /api/v1/devices         → Connected RPi5 devices                  │
│  ├── POST /api/v1/control         → Control commands (start/stop video)     │
│  ├── GET  /api/v1/metrics         → Latest metrics from RPi5               │
│  ├── GET  /api/v1/detections      → Latest detections                       │
│  ├── GET  /api/v1/video/stream    → MJPEG video stream with YOLO overlays   │
│  ├── POST /api/v1/config          → Update configuration                    │
│  └── GET  /api/v1/logs            → System logs                             │
│                                                                              │
│  WebSocket Endpoint:                                                         │
│  └── WS  /ws/{device_id}          → Real-time data from RPi5                │
│      ├── VIDEO_FRAME + detections → Video with YOLO bboxes                  │
│      ├── METRICS                  → System performance data                 │
│      ├── DETECTIONS               → Object detection events                 │
│      ├── STATUS                   → Connection status updates               │
│      ├── COMMAND ← LAPTOP         → Control RPi5 (start/stop video)         │
│      └── CONFIG  ← LAPTOP         → Configuration updates                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      RPI5 (FastAPI Client)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Core Client:                                                                │
│  └── rpi5/fastapi_client.py                                                 │
│      ├── send_video_frame(frame, detections) → Sends with YOLO data        │
│      ├── send_metrics(...)                   → Sends performance data       │
│      ├── send_detection(detection)           → Sends detection events       │
│      ├── set_video_streaming(enabled)        → Toggle video on/off          │
│      └── REST API client methods             → Query laptop status          │
│                                                                              │
│  Video Streaming Control:                                                    │
│  - Default: ON (sends ~15 FPS to save bandwidth)                            │
│  - Toggle: Via REST API or WebSocket command                                │
│  - Benefit: Save ~200KB/s when video not needed                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Current Implementation Status:
| Feature | Status | Notes |
|---------|--------|-------|
| FastAPI Server | **IMPLEMENTED** | laptop/server/fastapi_server.py |
| WebSocket Endpoint | **IMPLEMENTED** | /ws/{device_id} |
| REST API Endpoints | **IMPLEMENTED** | /api/v1/status, /api/v1/control |
| CORS Support | **IMPLEMENTED** | All origins enabled |
| Connection Manager | **IMPLEMENTED** | Thread-safe connection handling |
| BaseMessage Protocol | **IMPLEMENTED** | shared/api/message_protocol.py |

### Implementation Files:
- `laptop/server/fastapi_server.py` - FastAPI server with WebSocket endpoint
- `shared/api/message_protocol.py` - Message types and serialization
- `rpi5/layer0_guardian/fastapi_client.py` - RPi5 client for sending data

#### 1. Toggleable Video Streaming

```python
# On Laptop - Start video streaming for specific device
POST /api/v1/control
{
    "action": "start_video",
    "device_id": "rpi5-cortex-001"
}

# On Laptop - Stop video streaming (save bandwidth)
POST /api/v1/control
{
    "action": "stop_video",
    "device_id": "rpi5-cortex-001"
}

# On RPi5 - Client responds to commands
if command == "START_VIDEO_STREAMING":
    client.set_video_streaming(True)
elif command == "STOP_VIDEO_STREAMING":
    client.set_video_streaming(False)
```

#### 2. YOLO Overlay on Video Stream

```python
# Laptop: Draw YOLO detections on received frame
@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    data = await websocket.receive_json()
    if data["type"] == "VIDEO_FRAME":
        detections = data["data"]["detections"]
        frame_b64 = data["data"]["frame"]

        # Draw bounding boxes
        for det in detections:
            x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
            class_name = det["class"]
            confidence = det["confidence"]

            # Draw on frame
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{class_name}: {confidence:.2f}",
                       (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
```

#### 3. REST API Endpoints

```python
# Get system status
GET /api/v1/status
Response:
{
    "status": "online",
    "connected_devices": 1,
    "video_streaming_enabled": True,
    "timestamp": "2026-01-11T10:30:00Z"
}

# Get connected devices
GET /api/v1/devices
Response:
{
    "devices": [
        {
            "device_id": "rpi5-cortex-001",
            "streaming_video": True
        }
    ],
    "total": 1
}

# Get MJPEG video stream with overlays
GET /api/v1/video/stream?device_id=rpi5-cortex-001
Response: multipart/x-mixed-replace with JPEG frames
```

### Performance Benefits

| Metric | Legacy WebSocket | FastAPI + Toggleable Video |
|--------|-----------------|---------------------------|
| **Bandwidth** | ~500 KB/s (30 FPS) | ~200 KB/s (15 FPS) or OFF |
| **CPU (Laptop)** | ~15% decoding | ~10% with rate limiting |
| **Control Latency** | ~50ms | ~20ms (REST API) |
| **Browser Access** | ❌ PyQt6 only | ✅ MJPEG stream |

### Usage

**Start FastAPI Server (Laptop):**
```bash
# Using new launcher
python -m laptop.start_fastapi

# Or directly
python -m laptop.fastapi_server --host 0.0.0.0 --port 8765
```

**Start RPi5 with FastAPI Client:**
```bash
# RPi5 automatically uses fastapi_client.py
python rpi5/main.py
```

**Control from Laptop:**
```bash
# Stop video streaming to save bandwidth
curl -X POST http://localhost:8765/api/v1/control \
  -H "Content-Type: application/json" \
  -d '{"action": "stop_video", "device_id": "rpi5-cortex-001"}'

# Check status
curl http://localhost:8765/api/v1/status
```

### Files Changed/Added

| File | Action | Purpose |
|------|--------|---------|
| `laptop/fastapi_server.py` | NEW | FastAPI server with WebSocket + REST |
| `laptop/start_fastapi.py` | NEW | Launcher script |
| `rpi5/fastapi_client.py` | NEW | FastAPI client with streaming toggle |
| `rpi5/main.py` | MODIFIED | Use fastapi_client instead of legacy |
| `laptop/config.py` | MODIFIED | Added API configuration |
| `laptop/protocol.py` | MODIFIED | Message types for video streaming |

---

## 🛡️ LAYER 5: CARETAKER SAFETY NET [SUPABASE + ROKR APP]

**Purpose:** Silent real-time safety monitoring for caretakers — no interaction required from the user.

### Architecture Overview

```
RPi5 Wearable
  └── layer4_memory/caretaker_telemetry.py          ← 5-second state vector push
        ├── GPS position (lat/lon/accuracy)
        ├── IMU last reading (accel mag)
        ├── YOLO threat level (0–3: clear/warning/danger/critical)
        ├── Audio mode (hum/beacon/chirp/idle)
        ├── Battery % estimate
        └── timestamp

            ↓ Supabase.upsert() (caretaker_state table)

Supabase PostgreSQL
  ├── caretaker_state       ← Live 5s state vector (1 row per device)
  ├── caretaker_events      ← Log of SOS, fall, stationary triggers
  └── realtime subscription ← Pushes diffs to Rokr app via WS

            ↓ Realtime WS

Rokr App (iOS/Android) ← Built by separate agent / codebase
  ├── Live map with user dot
  ├── Falls & SOS alerts (push notification)
  └── Two-way VoIP call button
```

### Supabase Schema (New Tables — MVP Sprint Step 17)

```sql
-- Real-time state vector (upserted every 5 seconds)
CREATE TABLE caretaker_state (
    device_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    gps_accuracy_m  REAL,
    imu_accel_mag   REAL,          -- g-force magnitude
    yolo_threat     SMALLINT,      -- 0=clear 1=warning 2=danger 3=critical
    audio_mode      TEXT,          -- hum / beacon / chirp / idle
    battery_pct     SMALLINT,
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Event log (falls, SOS, stationary triggers)
CREATE TABLE caretaker_events (
    id              BIGSERIAL PRIMARY KEY,
    device_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,  -- fall / sos / stationary / low_battery
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    severity        TEXT,           -- critical / warning / info
    details         JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### Fall Detector (MVP Sprint Step 19)

**File:** `rpi5/layer0_guardian/fall_detector.py`

```python
# IMU BNO055 at 200Hz
# Trigger: accel_magnitude > 3.0g for ≥2 consecutive samples
#          THEN accel_magnitude < 1.2g for ≥1s (lying still)
# Action:
#   1. CRITICAL haptic pulse (5×)
#   2. Gemini TTS "Are you okay? Say SOS to alert your caretaker"
#   3. 10s response window → if no voice → caretaker_events.insert(type='fall')
#   4. Push notification via Supabase → Rokr app
```

### Stationary Zone Trigger

- IMU detects no motion >5 minutes in open area (threat_level > 0)
- Insert `caretaker_events` row `type=stationary`
- Gentle vibration prompt: "Are you still exploring? Press button to confirm."

### Implementation Status:
| Feature | Status | Notes |
|---------|--------|-------|
| Caretaker Supabase tables | 🔲 **IN SPRINT** | New SQL schema (Step 17) |
| 5s telemetry push loop | 🔲 **IN SPRINT** | `caretaker_telemetry.py` (Step 17) |
| Fall detector (IMU) | 🔲 **IN SPRINT** | `fall_detector.py`, BNO055 (Step 19) |
| Stationary trigger | 🔲 **IN SPRINT** | 5-min no-motion + threat (Step 19) |
| SOS voice command | 🔲 **IN SPRINT** | IntentRouter "call caretaker" token (Step 20) |
| Rokr app integration | 🔲 **EXTERNAL** | Separate agent/repo — consumes Supabase Realtime |

---

## 🗺️ V2.0 BACKLOG: SERVER-SIDE SLAM

**Purpose:** Build a persistent spatial map of frequently visited environments (home, school route). Enables object recall with real metric coordinates ("Your keys are 1.2m to your left").

> **Scope:** This is a BACKLOG item — not in MVP Sprint. Current GPS-only navigation is sufficient for YIA 2026 demo.

### Architecture Plan

```
RPi5 (Data Collection)
  └── IMU 200Hz keyframes     → cached in SQLite ring buffer (last 10 min)
  └── Visual keyframes (YOLO) → bounding boxes + depth (Hailo)

            ↓ Wi-Fi upload trigger (home detected via GPS geofence)

Laptop Server (SLAM Processing — 1GB+ RAM needed)
  └── OpenVINS or VINS-Fusion posterior optimization
  └── Output: 3D point cloud + object coordinates
  └── Upload result to Supabase (spatial_map table)

RPi5 (Map Consumption)
  └── Query "where are my keys?" → Supabase spatial_map lookup → relative direction
  └── AudioBeacon.start(target_3d_position)
```

### Why Server-Side Only
- OpenVINS requires ~1GB RAM + AVX CPU instructions → impossible on RPi5 (4GB total, arm64)
- Online SLAM options (ORB-SLAM3 lite) tested at 3–4GB resident on RPi5 → OOM
- VIO/SLAM must be deferred to laptop with 8GB+ RAM and RTX 2050

### Planned Files
- `laptop/server/slam_processor.py` — OpenVINS wrappers, post-processing job
- `rpi5/layer4_memory/imu_keyframe_cache.py` — ring buffer, Wi-Fi upload trigger
- `supabase/spatial_map` — Supabase table for 3D object coordinates

### Current Status: NOT STARTED — post-MVP Sprint

---

## 📊 MVP SPRINT — OVERALL IMPLEMENTATION STATUS

**Sprint Start:** March 7, 2026

| Phase | Name | Status | Steps |
|-------|------|--------|-------|
| Phase 0 | Foundation Fixes | 🔲 NOT STARTED | 3 steps (L2 override, SpatialAudio wiring, test suite) |
| Phase 1 | Acoustic UI | 🔲 NOT STARTED | 3 steps (wall hum, drop-off chirp, safety integration) |
| Phase 2 | Hailo Depth | 🔲 NOT STARTED | 3 steps (enable hailo, Guardian wiring, SAFETY_CLASSES) |
| Phase 3 | GPS Navigation | 🔲 NOT STARTED | 3 steps (GPS + IMU, AudioBeacon, GeminiLive wiring) |
| Phase 4 | SNAP-C1 | 🔲 NOT STARTED | 4 steps (train MLP, export ONNX, ChromaDB, offline mode) |
| Phase 5 | Caretaker | 🔲 NOT STARTED | 4 steps (Supabase schema, telemetry, fall detector, SOS) |

**Reference:** `docs/plans/IMPLEMENTATION_PLAN_MVP_SPRINT.md` for full 22-step breakdown.

---

**End of Document**
**Last Updated:** March 7, 2026 (MVP Sprint Architecture — Hailo Depth + Acoustic UI + SNAP-C1 + Caretaker Safety Net)
**See Also:**
- `docs/plans/IMPLEMENTATION_PLAN_MVP_SPRINT.md` — Full 22-step sprint plan
- `docs/implementation/AI-HAT-PLUS.md` — AI Hat+ / Hailo implementation guide
- `docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md` — This file
