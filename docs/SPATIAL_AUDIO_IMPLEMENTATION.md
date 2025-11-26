# Project-Cortex v2.0 - 3D Spatial Audio Navigation System

**Implementation Plan**  
**Last Updated:** November 26, 2025  
**Author:** Haziq (@IRSPlays)  
**Status:** ✅ Implemented with Procedural Sounds

---

## ⚠️ CRITICAL: BODY-RELATIVE NAVIGATION ⚠️

```
╔══════════════════════════════════════════════════════════════════╗
║  ⚠️  BODY-RELATIVE NAVIGATION  ⚠️                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  This device uses Body-Relative Navigation.                      ║
║  You must TURN YOUR TORSO to center the sound,                  ║
║  not just your head.                                             ║
║                                                                  ║
║  The camera is mounted on your chest/torso, so sounds           ║
║  are positioned relative to where your body is facing.          ║
╚══════════════════════════════════════════════════════════════════╝
```

**When demonstrating to YIA Judges:**
> "This device uses Body-Relative Navigation. You must turn your torso to center the sound, not just your head."

**Why Body-Relative?**
- The IMX415 camera is mounted on the user's chest/torso
- Sound positions are calculated from the camera's perspective
- We do NOT use head tracking (no IMU/gyroscope on headphones)
- This is simpler, more reliable, and works with any Bluetooth headphones

---

## 🎯 Executive Summary

This document outlines the complete implementation plan for the **3D Spatial Audio Navigation System** - a core feature of Project-Cortex designed to help visually impaired users navigate their environment using binaural audio cues.

### Key Features
- **Audio Beacons** - Continuous directional sounds that guide users to targets
- **Proximity Alerts** - Distance-based warning sounds that intensify as objects approach
- **Object Tracking** - Sound sources that follow detected objects in real-time
- **Obstacle Warnings** - Distinct alert sounds for safety-critical obstacles
- **Distance Estimation** - Calculate real-world distance from YOLO bounding boxes
- **Object-Specific Sounds** - Different audio cues for different object classes

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              USER QUERY / CONTINUOUS MODE                        │
│                    "Guide me to my chair" / Auto-detect obstacles                │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         LAYER 1: YOLO DETECTION OUTPUT                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  Detection {                                                                │ │
│  │    class_name: "chair",                                                     │ │
│  │    confidence: 0.89,                                                        │ │
│  │    bbox: [x1, y1, x2, y2],  // Pixel coordinates                           │ │
│  │    frame_size: [1920, 1080]                                                 │ │
│  │  }                                                                          │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      SPATIAL POSITION CALCULATOR                                  │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  bbox_to_3d_position(bbox, frame_size) → (x, y, z)                          │ │
│  │                                                                              │ │
│  │  x (horizontal): bbox_center_x → [-1.0, +1.0] (left to right)              │ │
│  │  y (vertical):   bbox_center_y → [-1.0, +1.0] (bottom to top)              │ │
│  │  z (depth):      bbox_area     → [-0.5, -10.0] (close to far)              │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         SPATIAL AUDIO MANAGER                                     │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐        │
│  │ Audio Beacon  │ │ Proximity     │ │ Object        │ │ Obstacle      │        │
│  │ System        │ │ Alert System  │ │ Tracker       │ │ Warner        │        │
│  │               │ │               │ │               │ │               │        │
│  │ Continuous    │ │ Distance-     │ │ Per-object    │ │ Safety-       │        │
│  │ guidance      │ │ based alerts  │ │ sounds        │ │ critical      │        │
│  └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘        │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          OPENAL 3D AUDIO ENGINE                                   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  Listener (User's head position + orientation)                              │ │
│  │    └── position: (0, 0, 0)     // User is always at origin                 │ │
│  │    └── orientation: (0, 0, -1) // Facing forward (-Z)                      │ │
│  │                                                                              │ │
│  │  Sources (One per tracked object)                                           │ │
│  │    └── chair_source.set_position(x, y, z)                                  │ │
│  │    └── car_source.set_position(x, y, z)                                    │ │
│  │    └── obstacle_source.set_position(x, y, z)                               │ │
│  │                                                                              │ │
│  │  HRTF Processing → Binaural Stereo Output → Bluetooth Headphones           │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📐 Core Algorithm: YOLO Bbox → 3D Position

### Mathematical Model

```python
def bbox_to_3d_position(bbox, frame_width, frame_height, known_object_sizes=None):
    """
    Convert YOLO bounding box to 3D audio position.
    
    Coordinate System (OpenAL):
    - X-axis: Left (-) to Right (+)
    - Y-axis: Down (-) to Up (+)  
    - Z-axis: Behind (+) to Front (-)  [User faces -Z]
    
    Args:
        bbox: (x1, y1, x2, y2) in pixels or normalized [0-1]
        frame_width, frame_height: Camera frame dimensions
        known_object_sizes: Dict of object_class → real_world_width (meters)
        
    Returns:
        (x, y, z): 3D position in OpenAL coordinate system
        distance_meters: Estimated real-world distance
    """
    # Normalize bbox to [0, 1] if in pixels
    if bbox[2] > 1.0:
        x1 = bbox[0] / frame_width
        y1 = bbox[1] / frame_height
        x2 = bbox[2] / frame_width
        y2 = bbox[3] / frame_height
    else:
        x1, y1, x2, y2 = bbox
    
    # Calculate center point
    center_x = (x1 + x2) / 2  # Range: 0 to 1
    center_y = (y1 + y2) / 2  # Range: 0 to 1
    
    # Calculate bbox area (normalized)
    width = x2 - x1
    height = y2 - y1
    area = width * height  # Range: 0 to 1
    
    # === HORIZONTAL POSITION (X-axis) ===
    # Map [0, 1] → [-1, +1] (left to right)
    x = (center_x - 0.5) * 2.0
    
    # === VERTICAL POSITION (Y-axis) ===
    # Map [0, 1] → [+1, -1] (top of frame = up in 3D)
    y = (0.5 - center_y) * 2.0
    
    # === DEPTH POSITION (Z-axis) ===
    # Larger bbox = closer = smaller |z|
    # Use inverse relationship: z = -k / sqrt(area)
    MIN_DISTANCE = 0.5   # Minimum z (closest)
    MAX_DISTANCE = 10.0  # Maximum z (farthest)
    AREA_CLOSE = 0.4     # Area when object is close
    AREA_FAR = 0.01      # Area when object is far
    
    # Clamp area to valid range
    area_clamped = max(AREA_FAR, min(AREA_CLOSE, area))
    
    # Inverse mapping: larger area → smaller distance
    normalized = (area_clamped - AREA_FAR) / (AREA_CLOSE - AREA_FAR)
    z = -(MIN_DISTANCE + (1 - normalized) * (MAX_DISTANCE - MIN_DISTANCE))
    
    return (x, y, z)
```

### Distance Estimation with Known Object Sizes

For more accurate distance estimation, use pinhole camera model:

```python
# Known object widths (in meters)
KNOWN_OBJECT_SIZES = {
    "person": 0.5,       # Average shoulder width
    "car": 1.8,          # Average car width
    "chair": 0.5,        # Average chair width
    "door": 0.9,         # Standard door width
    "stairs": 1.0,       # Standard staircase width
    "bicycle": 0.6,      # Handlebar width
    "dog": 0.3,          # Average dog body width
}

def estimate_distance_meters(bbox_width_pixels, frame_width, 
                             object_class, focal_length_pixels=1500):
    """
    Estimate real-world distance using pinhole camera model.
    
    Distance = (Known_Width × Focal_Length) / Bbox_Width
    
    Args:
        bbox_width_pixels: Width of bounding box in pixels
        frame_width: Total frame width in pixels
        object_class: Class name for known size lookup
        focal_length_pixels: Camera focal length in pixels (~1500 for IMX415)
    
    Returns:
        Distance in meters (or None if class unknown)
    """
    if object_class not in KNOWN_OBJECT_SIZES:
        return None
    
    known_width = KNOWN_OBJECT_SIZES[object_class]
    
    if bbox_width_pixels <= 0:
        return None
    
    distance = (known_width * focal_length_pixels) / bbox_width_pixels
    
    return max(0.3, min(20.0, distance))  # Clamp to valid range
```

---

## 🔊 Audio System Components

### 1. Audio Beacon System (`audio_beacon.py`)

**Purpose:** Provide continuous directional guidance to a target object.

**Behavior:**
- Emits a rhythmic "ping" sound from the target's 3D position
- Ping frequency increases as user gets closer
- Changes to success chime when target is reached

**Sound Parameters:**
| Distance | Ping Rate | Volume | Pitch |
|----------|-----------|--------|-------|
| > 5m | 1 Hz | 0.3 | Low |
| 2-5m | 2 Hz | 0.5 | Medium |
| 1-2m | 4 Hz | 0.7 | Higher |
| < 1m | 8 Hz | 1.0 | Highest |
| Reached | Chime | 1.0 | Success tone |

### 2. Proximity Alert System (`proximity_alert.py`)

**Purpose:** Warn users of approaching objects/obstacles.

**Behavior:**
- Silent when objects are far (> 3m)
- Warning tone increases in urgency as distance decreases
- Critical alert for imminent collision (< 0.5m)

**Alert Levels:**
| Level | Distance | Sound | Volume |
|-------|----------|-------|--------|
| None | > 3m | Silent | 0.0 |
| Notice | 2-3m | Soft hum | 0.3 |
| Warning | 1-2m | Pulse tone | 0.6 |
| Danger | 0.5-1m | Fast beep | 0.8 |
| Critical | < 0.5m | Alarm | 1.0 |

### 3. Object Sound Mapper (`object_sounds.py`)

**Purpose:** Assign distinct audio signatures to different object classes.

**Sound Mapping:**
| Object Class | Sound Type | Description |
|--------------|------------|-------------|
| person | Soft footsteps | Human presence indicator |
| chair | Wooden tap | Furniture indicator |
| car | Engine hum | Vehicle warning |
| bicycle | Bell ring | Cyclist warning |
| door | Knock sound | Passage indicator |
| stairs | Ascending tones | Level change warning |
| obstacle | Low buzz | Generic obstacle |
| target | Beacon ping | User's target |

### 4. Object Tracker (`object_tracker.py`)

**Purpose:** Maintain audio sources for multiple detected objects.

**Behavior:**
- Create/destroy audio sources as objects enter/exit frame
- Smoothly interpolate positions to avoid audio jumps
- Limit max concurrent audio sources (default: 5)

---

## 🛠️ Implementation Files

### File Structure

```
src/layer3_guide/
├── __init__.py                 # Updated with SpatialAudio integration
├── router.py                   # Existing intent router
├── spatial_audio/
│   ├── __init__.py            # Module exports
│   ├── manager.py             # SpatialAudioManager - main orchestrator
│   ├── position_calculator.py # bbox → 3D position conversion
│   ├── audio_beacon.py        # Directional guidance beacons
│   ├── proximity_alert.py     # Distance-based warnings
│   ├── object_tracker.py      # Multi-object audio source management
│   ├── object_sounds.py       # Object class → sound mapping
│   └── head_tracking.py       # (Future) Headphone gyro integration
└── assets/
    └── sounds/
        ├── beacons/           # Ping, chime, direction sounds
        ├── alerts/            # Warning, danger, critical sounds
        ├── objects/           # Per-object-class sounds
        └── feedback/          # Success, error, notification sounds
```

### Class Hierarchy

```python
# Main orchestrator
class SpatialAudioManager:
    """Central controller for all spatial audio features."""
    
    def __init__(self, config_path: str = "config/spatial_audio.yaml")
    def start(self) -> bool
    def stop(self) -> None
    def update_detections(self, detections: List[Detection]) -> None
    def start_beacon(self, target_class: str) -> bool
    def stop_beacon(self) -> None
    def set_listener_orientation(self, yaw: float, pitch: float, roll: float) -> None
    def get_status(self) -> dict

# Position calculation
class PositionCalculator:
    """Converts 2D bbox to 3D audio position."""
    
    def bbox_to_3d(self, bbox, frame_size) -> Tuple[float, float, float]
    def estimate_distance(self, bbox, object_class) -> Optional[float]
    def smooth_position(self, new_pos, old_pos, alpha=0.3) -> Tuple

# Audio beacon for navigation
class AudioBeacon:
    """Continuous directional guidance sound."""
    
    def __init__(self, sound_file: str)
    def start(self, target_position: Tuple) -> None
    def update_position(self, position: Tuple) -> None
    def update_distance(self, distance_meters: float) -> None
    def stop(self) -> None

# Proximity alert system
class ProximityAlertSystem:
    """Distance-based warning sounds."""
    
    def __init__(self, alert_sounds: dict)
    def update(self, closest_obstacle_distance: float) -> None
    def set_alert_thresholds(self, thresholds: dict) -> None

# Object-specific sounds
class ObjectSoundMapper:
    """Maps object classes to distinct sounds."""
    
    def __init__(self, sound_config: dict)
    def get_sound(self, object_class: str) -> str
    def play_object_sound(self, object_class: str, position: Tuple) -> None

# Multi-object tracking
class ObjectTracker:
    """Manages audio sources for multiple objects."""
    
    def __init__(self, max_sources: int = 5)
    def update(self, detections: List[Detection]) -> None
    def get_active_sources(self) -> List[AudioSource]
```

---

## 📦 Dependencies

### Required Packages

```bash
# Add to requirements.txt
PyOpenAL>=0.7.11a1       # OpenAL bindings for Python
numpy>=1.24.0            # Array operations
PyYAML>=6.0              # Configuration parsing
```

### System Requirements

**Windows:**
```bash
# OpenAL-Soft is bundled with PyOpenAL
pip install PyOpenAL
```

**Raspberry Pi / Linux:**
```bash
# Install OpenAL-Soft system library
sudo apt-get install libopenal-dev libopenal1

# Then install Python bindings
pip install PyOpenAL
```

**Optional (for OGG/FLAC support):**
```bash
pip install PyOgg
```

---

## ⚙️ Configuration

### `config/spatial_audio.yaml`

```yaml
# Spatial Audio Configuration
# Project-Cortex v2.0

audio:
  sample_rate: 44100
  channels: 2
  buffer_size: 4096
  
# Coordinate mapping
position:
  min_distance: 0.5      # meters (closest)
  max_distance: 10.0     # meters (farthest)
  frame_width: 1920
  frame_height: 1080
  focal_length: 1500     # pixels (IMX415 estimate)

# Audio beacon settings
beacon:
  enabled: true
  ping_sound: "assets/sounds/beacons/ping.wav"
  success_sound: "assets/sounds/beacons/success.wav"
  ping_rates:            # Hz at different distances
    far: 1.0
    medium: 2.0
    close: 4.0
    very_close: 8.0
  distance_thresholds:   # meters
    far: 5.0
    medium: 2.0
    close: 1.0

# Proximity alert settings
proximity:
  enabled: true
  sounds:
    notice: "assets/sounds/alerts/notice.wav"
    warning: "assets/sounds/alerts/warning.wav"
    danger: "assets/sounds/alerts/danger.wav"
    critical: "assets/sounds/alerts/critical.wav"
  thresholds:            # meters
    notice: 3.0
    warning: 2.0
    danger: 1.0
    critical: 0.5

# Object sound mapping
objects:
  enabled: true
  max_simultaneous_sources: 5
  sounds:
    person: "assets/sounds/objects/person.wav"
    chair: "assets/sounds/objects/furniture.wav"
    car: "assets/sounds/objects/vehicle.wav"
    bicycle: "assets/sounds/objects/bicycle.wav"
    door: "assets/sounds/objects/door.wav"
    stairs: "assets/sounds/objects/stairs.wav"
    default: "assets/sounds/objects/generic.wav"

# Known object sizes for distance estimation (meters)
object_sizes:
  person: 0.5
  car: 1.8
  chair: 0.5
  door: 0.9
  stairs: 1.0
  bicycle: 0.6
  dog: 0.3
  tv: 1.0
  laptop: 0.35

# Head tracking (future feature)
head_tracking:
  enabled: false
  source: "bluetooth_hid"  # or "imu_sensor"
  update_rate: 30          # Hz
```

---

## 🧪 Testing Plan

### Unit Tests

```python
# tests/test_spatial_audio.py

def test_bbox_to_3d_center():
    """Object in center of frame should have x=0, y=0."""
    bbox = (0.4, 0.4, 0.6, 0.6)  # Center 20% of frame
    pos = bbox_to_3d_position(bbox, 1920, 1080)
    assert abs(pos[0]) < 0.1  # x ≈ 0
    assert abs(pos[1]) < 0.1  # y ≈ 0

def test_bbox_to_3d_left():
    """Object on left side should have negative x."""
    bbox = (0.0, 0.4, 0.2, 0.6)  # Left side
    pos = bbox_to_3d_position(bbox, 1920, 1080)
    assert pos[0] < 0  # x is negative (left)

def test_bbox_to_3d_distance_large_bbox():
    """Large bbox should be closer (smaller |z|)."""
    large_bbox = (0.2, 0.2, 0.8, 0.8)  # Takes up 36% of frame
    small_bbox = (0.45, 0.45, 0.55, 0.55)  # Takes up 1% of frame
    
    pos_large = bbox_to_3d_position(large_bbox, 1920, 1080)
    pos_small = bbox_to_3d_position(small_bbox, 1920, 1080)
    
    assert abs(pos_large[2]) < abs(pos_small[2])  # Large is closer

def test_distance_estimation():
    """Known object size should give accurate distance."""
    # Person at 2 meters with 500px bbox width
    distance = estimate_distance_meters(
        bbox_width_pixels=375,  # 500mm / 2m * 1500 focal length
        frame_width=1920,
        object_class="person",
        focal_length_pixels=1500
    )
    assert 1.5 < distance < 2.5  # Within 0.5m accuracy
```

### Integration Tests

```python
# tests/test_spatial_audio_integration.py

def test_full_pipeline():
    """Test complete YOLO → 3D Audio pipeline."""
    manager = SpatialAudioManager()
    manager.start()
    
    # Simulate YOLO detection
    detection = {
        "class_name": "chair",
        "confidence": 0.9,
        "bbox": [100, 200, 300, 400],  # pixels
        "frame_size": [1920, 1080]
    }
    
    manager.update_detections([detection])
    manager.start_beacon("chair")
    
    # Verify audio source created
    assert manager.get_status()["active_sources"] == 1
    assert manager.get_status()["beacon_active"] == True
    
    manager.stop()
```

---

## 📅 Implementation Timeline

### Week 1: Core Framework
| Day | Task | Deliverable |
|-----|------|-------------|
| 1 | Set up PyOpenAL + test on Windows | Working 3D sound demo |
| 2 | Implement PositionCalculator | bbox_to_3d() function |
| 3 | Implement SpatialAudioManager | Basic orchestrator |
| 4 | Create placeholder sound files | WAV files for testing |
| 5 | Unit tests for position math | 100% test coverage |

### Week 2: Feature Implementation
| Day | Task | Deliverable |
|-----|------|-------------|
| 1 | Implement AudioBeacon | Navigation guidance |
| 2 | Implement ProximityAlertSystem | Distance warnings |
| 3 | Implement ObjectSoundMapper | Per-class sounds |
| 4 | Implement ObjectTracker | Multi-object support |
| 5 | Integration with Layer 1 YOLO | End-to-end test |

### Week 3: Polish & Testing
| Day | Task | Deliverable |
|-----|------|-------------|
| 1 | Fine-tune audio parameters | Optimal UX |
| 2 | Test with real YOLO detections | Real-world validation |
| 3 | Test on Raspberry Pi 5 | Platform validation |
| 4 | Documentation updates | README, API docs |
| 5 | Demo video recording | YIA presentation asset |

---

## 🎯 Success Metrics

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Position Accuracy | ±15° azimuth | A/B test with sighted users |
| Distance Accuracy | ±0.5m at 3m | Compare to tape measure |
| Audio Latency | <100ms | Frame timestamp to audio output |
| CPU Usage | <15% (audio only) | htop monitoring |
| User Comprehension | >80% correct direction | User study |

---

## 🔮 Future Enhancements

### Phase 2 (Post-YIA)
- [ ] Head tracking via Bluetooth HID (AirPods Pro)
- [ ] IMU sensor integration for head orientation
- [ ] HRTF personalization based on ear shape
- [ ] Environmental reverb (indoor vs outdoor)
- [ ] Voice command: "What's to my left?"

### Phase 3 (Long-term)
- [ ] Machine learning for optimal sound design
- [ ] Multi-user support (guide + companion)
- [ ] Integration with Google Maps audio navigation
- [ ] Smartwatch haptic feedback sync

---

## 📚 References

1. **OpenAL Soft Documentation**: https://openal-soft.org/
2. **PyOpenAL GitHub**: https://github.com/Zuzu-Typ/PyOpenAL
3. **Microsoft Soundscape (Research)**: https://github.com/microsoft/soundscape
4. **HRTF Explained**: https://en.wikipedia.org/wiki/Head-related_transfer_function
5. **3D Audio for Accessibility**: IEEE VR 2023 Papers

---

**Document Status:** ✅ Ready for Implementation  
**Next Step:** Create `src/layer3_guide/spatial_audio/manager.py`
