# ProjectCortex: MVP Sprint Implementation Plan
**Target Deployments:** Tan Kah Kee YIA 2026, MOE Innovation Programme, SAVH Usability Testing
**Last Updated:** March 7, 2026
**Author:** Haziq (@IRSPlays)

---

## Gap Analysis Summary (as of March 7, 2026)

| Area | Status | Key Gap |
|------|--------|---------|
| Layer 0 Guardian (YOLO NCNN + Haptic) | ✅ | Safety class filter only passes 21 classes |
| Layer 0 Hailo NPU integration | ❌ | Hailo is separate module, not in Guardian |
| Layer 0 Drop-off detection | ⚠️ | Exists in `hailo_depth.py`, not in Guardian |
| Layer 2 GeminiTTS (vision HTTP) | ✅ | Production-ready with key rotation |
| Layer 2 GeminiLive (WebSocket) | ⚠️ | Implemented, not connected to voice pipeline |
| Layer 2 Cartesia TTS | ✅ | Fully implemented |
| Layer 3 IntentRouter (fuzzy) | ✅ | Active but overridden by L2 force in main.py |
| Layer 3 Spatial Audio module | ⚠️ | Code complete, not wired into CortexSystem |
| Layer 3 "Wall force-field hum" | ❌ | Not implemented anywhere |
| Layer 3 GPS/Navigation | ❌ | TODO stubs only |
| SNAP-C1 / ChromaDB | ❌ | Zero lines of code |
| Hailo Depth (fast_depth.hef) | ⚠️ | Code complete, config-gated OFF |
| Hailo OCR (PaddleOCR + HEF) | ⚠️ | Code complete, config-gated OFF |
| Caretaker Telemetry / SOS / VoIP | ❌ | Not started |
| L2 force-override in main.py | ⚠️ | **Active debug override routing ALL queries → L2** |

**Decisions recorded:**
- Hailo HEFs confirmed ready → Hailo depth enabled in Phase 2
- SNAP-C1 = minimal MLP→ONNX approach, IntentRouter as teacher + fallback
- Caretaker app UI = Rokr (separate agent) — this plan builds only the Supabase backend

---

## Sprint Order

| Week | Phases | Deliverable |
|------|--------|-------------|
| Week 1 | Phase 0 + Phase 1 | Routing fixed, spatial audio live, drop-off chirp working |
| Week 2 | Phase 2 + Phase 3 | Hailo depth enriching haptic, GPS beacon navigation |
| Week 3 | Phase 4 | SNAP-C1 ONNX classifier + FastBrain offline mode |
| Week 4 | Phase 5 | Supabase caretaker schema + both SOS triggers |
| Backlog | Phase 6 | SLAM pipeline on Wi-Fi restore |

---

## Phase 0 — Foundation Fixes (Unblock Everything)
**Estimated time:** ~1 day
**Priority:** CRITICAL — must be done before anything else

### Step 1 — Remove the L2 Force Override in `rpi5/main.py`
**File:** `rpi5/main.py` (~line 1468)

The block `if target_layer != "layer2": target_layer = "layer2"` is live in production,
silently routing every voice command to Gemini and hiding all other layer functionality.
Remove it so `IntentRouter` output is respected.

```python
# REMOVE THIS BLOCK:
if target_layer != "layer2":
    logger.info(f"⚡ OVERRIDE: Forcing {target_layer} -> layer2 (temporary)")
    target_layer = "layer2"
```

**Verification:** `pytest tests/test_router_fix.py tests/test_router_priority_fix.py -v`

---

### Step 2 — Wire `GeminiLiveHandler` into the voice pipeline
**File:** `rpi5/main.py` → `handle_voice_command()`

`GeminiLiveManager` is instantiated at `self.layer2` but `handle_voice_command()` calls
`GeminiTTS` (HTTP) instead. Fix routing:
- `GeminiLiveHandler` = primary path for real-time audio-to-audio conversation
- `GeminiTTS` (HTTP) = fallback for vision-query requests (single image + prompt)

---

### Step 3 — Instantiate `SpatialAudioManager` in `CortexSystem.__init__()`
**Files:** `rpi5/main.py`, `rpi5/layer3_guide/spatial_audio/manager.py`

The entire spatial audio module (HRTF, beacons, proximity alerts, 7 sub-modules) is
unreachable because `CortexSystem` never creates an instance.

```python
# Add to CortexSystem.__init__():
from rpi5.layer3_guide.spatial_audio.manager import SpatialAudioManager
self.spatial_audio = SpatialAudioManager()
self.spatial_audio.start()
```

Route L0/L1 detection results into `manager.update_detections()` on every frame.
This unblocks all acoustic UI work in Phase 1.

---

## Phase 1 — Acoustic UI (Safety: Spatial Sound)
**Estimated time:** ~3–4 days
**Prerequisites:** Phase 0 complete

### Step 4 — Wall Force-Field Hum
**Files:** `rpi5/layer3_guide/spatial_audio/manager.py`, `rpi5/layer3_guide/spatial_audio/sound_generator.py`

Replace discrete threshold-triggered alert clips with a **continuous looping tone** per
close wall whose `AL_PITCH` and `AL_GAIN` are updated every frame from depth data.

Implementation:
- Use `sound_generator._generate_sine_wave()` to create an 80–200Hz tone buffer
- Read leftmost and rightmost columns of the depth matrix (from `HailoDepthEstimator`)
- Map 0–2m range → pitch 0.5–2.0, gain scales proportionally
- Update the left/right OpenAL mono source (mono = HRTF-processed, stereo bypasses HRTF)
- New method: `SpatialAudioManager.update_wall_hum(left_depth_m, right_depth_m)`

Result: Wall on the right → low hum in right ear that rises as user approaches.

---

### Step 5 — Drop-Off Audio Override
**Files:** `rpi5/layer3_guide/spatial_audio/manager.py`, `rpi5/layer3_guide/spatial_audio/sound_generator.py`

New method: `SpatialAudioManager.trigger_dropoff_override()`

Sequence when `HailoDepthEstimator.detect_hazards()` returns `DROPOFF` or `STAIRS_DOWN`
with severity `CRITICAL`/`HIGH`:
1. Immediately call `AL_STOP` on ALL active sources + hum loop
2. Play sharp dual-ear chirp (1kHz `_generate_chirp()`, both channels simultaneously
   to bypass HRTF directionality → user hears it centered/everywhere)
3. Hold audio silent for 500ms (force freeze)
4. Resume normal proximity hum

**Target latency:** <50ms from hazard detection to chirp onset
**Verification:** `pytest tests/test_spatial_audio.py -v` (add timing assertions)

---

### Step 6 — Enable Hailo Depth in Production Config
**File:** `rpi5/config/config.yaml`

Change `hailo.enabled: false` → `hailo.enabled: true`

Both `.hef` files confirmed present in `models/hailo/`. Extend existing hazard detection
integration path (currently → `AudioAlertManager` WAV clips) to also call
`trigger_dropoff_override()` on the `SpatialAudioManager`.

**Verification:** Run main loop, confirm `HailoDepthEstimator.estimate()` returns real
depth matrices (not zeros/None). Check logs for `[Hailo] Depth estimation active`.

---

## Phase 2 — Layer 0: Guardian + Hailo Unification
**Estimated time:** ~2–3 days
**Prerequisites:** Phase 1 complete

### Step 7 — Integrate `HailoDepthEstimator` into `YOLOGuardian`
**Files:** `rpi5/layer0_guardian/__init__.py`, `rpi5/hailo_depth.py`

Currently depth is a separate system called from `CortexSystem._run_dual_detection()`.
Merge depth context into the Guardian's output:

```python
# YOLOGuardian.detect(frame, depth_matrix=None) -> List[Detection]
# When depth_matrix provided:
#   enrich each Detection with real distance via hailo_depth.enrich_detections_with_distance()
#   replace bbox-area-fraction proximity tiers with metric thresholds
```

Updated `HapticController` proximity tiers (real metres):
- `<0.5m` → intensity 100%, continuous
- `<1.0m` → intensity 70%, fast pulse
- `<2.0m` → intensity 40%, slow pulse

**Verification:** `pytest tests/test_dual_yolo.py -v` — Layer 0 must remain <100ms with
depth enrichment added.

---

### Step 8 — Expand `SAFETY_CLASSES` Filter
**File:** `rpi5/layer0_guardian/__init__.py`

Current 21-class hard-coded list silently drops many hazards. Additions:
- `fire hydrant`, `parking meter`, `bench` (tripping hazards)
- `traffic light`, `stop sign` (orientation aids)
- `suitcase`, `backpack` (pedestrian collision)
- Document clearly: `curb` and `drop-off` are NOT in COCO-80 → handled by depth estimation

---

### Step 9 — Hailo YOLO Path (Optional / Best-Effort)
**Files:** `rpi5/layer0_guardian/__init__.py`, `rpi5/hailo_depth.py`

If a compiled `yolo26n.hef` is available: add as second network group on the existing
`HailoVDevice` (already uses `ROUND_ROBIN` scheduler). This drops Guardian inference
from ~60ms → ~5ms. Skip if HEF not compiled — add as V2 upgrade task.

---

## Phase 3 — Layer 3 Navigation: GPS Audio Beacons
**Estimated time:** ~2–3 days
**Prerequisites:** Phase 0 + Phase 1 complete

### Step 10 — Wire GPS Routing into `AudioBeacon`
**Files:** `rpi5/main.py`, `rpi5/layer3_guide/spatial_audio/audio_beacon.py`

The `audio_beacon.py` module is fully implemented (distance-based ping rate, arrival
chime) but navigation in `handle_voice_command()` is a `# TODO` stub.

Implementation:
1. When `IntentRouter` returns `use_spatial_audio=True` or `query_type="navigate"`
2. Parse destination from Gemini's response (Gemini handles POI lookup)
3. Compute azimuth from current GPS heading to destination
4. Call `AudioBeacon.start(target_position)` — beacon accelerates from 1Hz (far) to 8Hz (near)

---

### Step 11 — IMU Heading → Listener Orientation
**Files:** `rpi5/main.py`, `rpi5/layer3_guide/spatial_audio/manager.py`

Each GPS fix and IMU compass heading should update OpenAL listener orientation:

```python
# Add to SpatialAudioManager:
def update_heading(self, heading_degrees: float):
    """Update listener orientation so objects stay body-relative as user turns."""
    ...

# In CortexSystem main loop (IMU data already read):
self.spatial_audio.update_heading(imu_data.heading_degrees)
```

**Verification:** Manual GPS navigation test — walk to nearby POI, confirm beacon
direction is correct and chirps on arrival.

---

## Phase 4 — SNAP-C1: Minimal ONNX Action Decoder
**Estimated time:** ~4–5 days
**Prerequisites:** Phase 0 complete (needs correct routing baseline)
**Approach:** Minimal MLP → ONNX (IntentRouter as teacher + fallback)

### Step 12 — Define Action Token Vocabulary
**New file:** `rpi5/layer3_guide/snap_c1/action_tokens.py`

~25 action tokens covering all routing outcomes:
```python
ACTION_TOKENS = [
    "NAVIGATE_LEFT", "NAVIGATE_RIGHT", "NAVIGATE_FORWARD", "NAVIGATE_STOP",
    "IDENTIFY_OBJECT", "READ_TEXT", "DESCRIBE_SCENE", "COUNT_OBJECTS",
    "STORE_MEMORY", "RECALL_MEMORY", "LIST_MEMORIES",
    "EMERGENCY_STOP", "CALL_CARETAKER",
    "REPEAT_LAST", "INCREASE_VOLUME", "DECREASE_VOLUME",
    "FILLER_IGNORE", "UNKNOWN",
    # Layer routing tokens
    "ROUTE_LAYER0", "ROUTE_LAYER1", "ROUTE_LAYER2", "ROUTE_LAYER3",
]
```

---

### Step 13 — Build Training Data from `IntentRouter`
**New file:** `rpi5/layer3_guide/snap_c1/build_dataset.py`

- Run every keyword/phrase from `IntentRouter` keyword lists through the router
- Collect `(text → action_token)` pairs
- Augment with rule-based paraphrasing (add filler words, rearrange, add "please", etc.)
- Target: ~5,000–10,000 labelled examples
- Save as `data/snap_c1_training.json`

---

### Step 14 — Train and Export ONNX
**New file:** `rpi5/layer3_guide/snap_c1/train.py`

Architecture: TF-IDF features → 3-layer MLP → softmax over action tokens
- Train on CPU (~10 minutes)
- Export via `torch.onnx.export()` or `sklearn-onnx`
- INT8 quantization for RPi5 (<5ms inference target)
- Save as `models/snap_c1_action_decoder.onnx`

---

### Step 15 — Wire SNAP-C1 into `CortexSystem`
**New file:** `rpi5/layer3_guide/snap_c1/decoder.py` — `SnapC1Decoder` class
**Modified file:** `rpi5/main.py`

```python
# In handle_voice_command():
action, confidence = snap_c1.decode(text)
if confidence < 0.7:
    action = intent_router.route(text)  # fallback

# Offline survival mode:
if self.is_offline:
    action = snap_c1.decode_offline(text, yolo_threat_level, last_gps_fix)
    # No Gemini fallback — direct action token only
```

---

### Step 16 — ChromaDB Fast Brain for GPS Breadcrumbs
**New file:** `rpi5/layer3_guide/snap_c1/fast_brain.py` — `FastBrain` class

```python
# Store GPS safe zones as user moves through known areas
fast_brain.store_location(gps_coords, description="home entrance")

# On offline activation:
nearest_safe_zone = fast_brain.find_nearest_safe_zone(current_gps)
AudioBeacon.start(nearest_safe_zone.bearing)
```

Uses local ChromaDB collection (no server needed). Add `chromadb` to `requirements.txt`.

**Verification:** `pytest tests/test_router_fix.py tests/test_router_priority_fix.py -v`
— SNAP-C1 must match IntentRouter accuracy on curated test set (target ≥97%).

---

## Phase 5 — Caretaker Telemetry Backend
**Estimated time:** ~2–3 days
**Note:** Roku app UI built by separate agent — this phase builds only the Supabase
backend that the app reads from.

### Step 17 — Supabase Schema Design

```sql
-- State vector pushed every 5 seconds
CREATE TABLE device_telemetry (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    device_id text NOT NULL,
    timestamp timestamptz DEFAULT now(),
    gps_lat float,
    gps_lon float,
    battery_pct float,
    threat_level int CHECK (threat_level BETWEEN 0 AND 4),
    -- 0=clear, 1=notice, 2=warning, 3=danger, 4=critical
    is_offline boolean DEFAULT false,
    snap_c1_last_action text,
    created_at timestamptz DEFAULT now()
);

-- SOS events
CREATE TABLE sos_events (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    device_id text NOT NULL,
    trigger_type text CHECK (trigger_type IN ('fall', 'stationary')),
    timestamp timestamptz DEFAULT now(),
    gps_lat float,
    gps_lon float,
    resolved_at timestamptz,
    caretaker_notified boolean DEFAULT false
);

-- Caretaker-device relationships
CREATE TABLE caretaker_pairs (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    caretaker_user_id text NOT NULL,
    device_id text NOT NULL,
    permissions jsonb DEFAULT '{"can_view_location": true, "can_initiate_call": true}'
);
```

---

### Step 18 — Add Telemetry Thread to `CortexSystem`
**Files:** `rpi5/layer4_memory/hybrid_memory_manager.py`, `rpi5/main.py`

Add to `HybridMemoryManager`:
```python
def push_caretaker_state(self, gps, battery_pct, threat_level, is_offline, last_action):
    """Batch-insert caretaker state vector into device_telemetry every 5s."""
    ...
```

Wire in `CortexSystem` background thread:
- Current GPS fix + battery reading + current max `threat_level` from L0
- Push every 5 seconds via existing Supabase sync worker

---

### Step 19 — Implement SOS Triggers
**New file:** `rpi5/layer0_guardian/fall_detector.py` — `ImuFallDetector` class
**Modified file:** `rpi5/main.py`, `rpi5/layer4_memory/hybrid_memory_manager.py`

**Trigger 1 — Fall Detection:**
```python
class ImuFallDetector:
    """Detects falls via IMU accelerometer spike + stillness pattern."""
    # Spike threshold: >3g on accelerometer magnitude
    # Followed by: <0.5g (still) for >1s
    # Output: on_fall_detected callback → push_sos_event('fall')
```

**Trigger 2 — Stationary in Unfamiliar Zone:**
```python
# GPS rolling window: if position variance < 5m radius for 180s
# AND location NOT in ChromaDB known-zones collection
# → push_sos_event('stationary')
```

**Verification:** Unit test both triggers with simulated IMU fixtures and GPS mocks.
Confirm Supabase `sos_events` row appears within 5-second window.

---

## Phase 6 — Post-MVP V2.0: Server-Side SLAM (Backlog)
**Estimated time:** ~1–2 weeks
**Prerequisites:** Phase 5 complete, Wi-Fi infrastructure available

### Step 20 — IMU Keyframe Caching (RPi5)
**New file:** `rpi5/layer4_memory/imu_keyframe_recorder.py`

Background thread samples IMU at 200Hz, compresses keyframes (every 5th frame):
```sql
-- Add to SQLite:
CREATE TABLE imu_keyframes (
    id INTEGER PRIMARY KEY,
    timestamp REAL,
    accel_x REAL, accel_y REAL, accel_z REAL,
    gyro_x REAL, gyro_y REAL, gyro_z REAL,
    mag_x REAL, mag_y REAL, mag_z REAL,
    camera_keyframe_id TEXT,
    synced INTEGER DEFAULT 0
);
```

### Step 21 — Wi-Fi Upload Trigger
**File:** `rpi5/layer4_memory/hybrid_memory_manager.py`

When Wi-Fi available (ping to Supabase succeeds), flush `imu_keyframes` table to
Supabase `slam_sessions` bucket as compressed `.npz` package.

### Step 22 — Server-Side SLAM Processing (Laptop)
**New file:** `laptop/server/slam_processor.py`

Polls Supabase for new `slam_sessions`, runs OpenVINS/VINS-Fusion offline, writes
persistent 3D waypoint graphs back to Supabase as:
```json
{
  "device_id": "glasses_001",
  "session_id": "...",
  "waypoint_graph": [
    {"id": 0, "gps_lat": 1.3521, "gps_lon": 103.8198, "label": "home_entrance"},
    {"id": 1, "gps_lat": 1.3523, "gps_lon": 103.8201, "label": "bus_stop_A"}
  ]
}
```

---

## File Creation Checklist

### New files to create:
- [ ] `rpi5/layer3_guide/snap_c1/__init__.py`
- [ ] `rpi5/layer3_guide/snap_c1/action_tokens.py`
- [ ] `rpi5/layer3_guide/snap_c1/build_dataset.py`
- [ ] `rpi5/layer3_guide/snap_c1/train.py`
- [ ] `rpi5/layer3_guide/snap_c1/decoder.py`
- [ ] `rpi5/layer3_guide/snap_c1/fast_brain.py`
- [ ] `rpi5/layer0_guardian/fall_detector.py`
- [ ] `rpi5/layer4_memory/imu_keyframe_recorder.py`
- [ ] `laptop/server/slam_processor.py`
- [ ] `supabase/migrations/001_caretaker_schema.sql`
- [ ] `data/snap_c1_training.json` (generated by build_dataset.py)
- [ ] `models/snap_c1_action_decoder.onnx` (generated by train.py)

### Files to modify:
- [ ] `rpi5/main.py` — remove L2 override, wire SpatialAudio, wire SNAP-C1, wire telemetry
- [ ] `rpi5/config/config.yaml` — `hailo.enabled: true`
- [ ] `rpi5/layer0_guardian/__init__.py` — depth enrichment, expanded SAFETY_CLASSES
- [ ] `rpi5/layer3_guide/spatial_audio/manager.py` — wall hum + drop-off override
- [ ] `rpi5/layer3_guide/spatial_audio/sound_generator.py` — dual-ear chirp + hum tone
- [ ] `rpi5/layer4_memory/hybrid_memory_manager.py` — caretaker state vector push
- [ ] `requirements.txt` — add `chromadb`

---

*End of Implementation Plan — ProjectCortex MVP Sprint*
