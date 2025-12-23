# 🧠 Memory + SLAM Navigation Integration
**Project-Cortex v2.0 - Layer 3/4 Enhancement**

---

## 📋 EXECUTIVE SUMMARY

This document outlines the architecture for integrating:
1. **Layer 4 Memory** (SQLite storage) with **VIO/SLAM mapping** (visual odometry)
2. **Object Localization** ("Where did I put my wallet?")
3. **Google Maps API** (outdoor navigation with turn-by-turn directions)
4. **GPS-based waypoint navigation** (NEO-8M GPS @ 10Hz)
5. **3D Spatial Audio guidance** (existing PyOpenAL + HRTF system)

### The Vision: "Find My Wallet with Audio Guidance"

**User Flow:**
```
1. USER: "Remember where I put my wallet"
   → Cortex stores: GPS (if outdoors) + VIO pose (if indoors) + visual anchor

2. USER: "Where is my wallet?"
   → Cortex retrieves: Last known location from memory
   → If OUTDOORS: Use Google Maps Directions API for walking route
   → If INDOORS: Use VIO/SLAM map for relative position
   → 3D Audio Beacon guides user to object location

3. USER follows audio beacon (turns torso, listens to direction)
   → Proximity alerts increase as user approaches
   → "You're 2 meters away... 1 meter... you've arrived!"
```

### Key Capabilities
- **Indoor Positioning**: Store object locations relative to VIO/SLAM map
- **Outdoor Navigation**: Google Maps walking directions with GPS waypoints
- **Hybrid Transitions**: Seamless indoor→outdoor navigation handoff
- **Persistent Memory**: Objects remembered across sessions (SQLite)
- **3D Audio Guidance**: HRTF-based directional audio beacons

---

## 🎯 PROBLEM STATEMENT

### Current System Limitations (Post-Memory Implementation)
✅ **Layer 4 Memory EXISTS** - SQLite database with:
- User conversations (speech recognition logs)
- Detected objects (YOLO classifications with timestamps)
- System states (error logs, performance metrics)

❌ **But NO SPATIAL MEMORY** - Current system cannot:
- Remember WHERE objects are located (no position data)
- Navigate back to remembered locations
- Provide turn-by-turn directions to objects
- Differentiate between indoor/outdoor positioning strategies

### The Gap: Spatial Context
Current memory stores **WHAT** (object classes) and **WHEN** (timestamps).
We need to store **WHERE** (3D positions) and enable navigation.

---

## 🔬 RESEARCH FINDINGS

### 1. Google Maps API (Python Client Library)

**Repository:** `googlemaps/google-maps-services-python`

#### 1A. Directions API

**Functionality:**
- Calculate walking routes between origin and destination
- Turn-by-turn navigation instructions (steps with distances + directions)
- Waypoint optimization (for multi-stop routes)
- Real-time traffic data (DRIVE mode only, not WALK)

**Python Example:**
```python
import googlemaps
from datetime import datetime

gmaps = googlemaps.Client(key='YOUR_API_KEY')

# Walking directions with waypoints
directions = gmaps.directions(
    origin="1600 Amphitheatre Parkway, Mountain View, CA",
    destination="San Francisco, CA",
    mode="walking",  # WALK mode for pedestrians
    waypoints=["Starbucks, Mountain View"],  # Optional intermediate stops
    optimize_waypoints=True,  # Reorder waypoints for shortest route
    departure_time=datetime.now(),
    avoid=["indoor"],  # Prefer outdoor routes
    alternatives=True  # Get multiple route options
)

# Response structure:
# directions[0]['legs'][0]['steps'] = [
#     {
#         'html_instructions': 'Head <b>north</b> on <b>Amphitheatre Pkwy</b>',
#         'distance': {'text': '0.3 mi', 'value': 483},  # meters
#         'duration': {'text': '6 mins', 'value': 360},  # seconds
#         'start_location': {'lat': 37.422, 'lng': -122.084},
#         'end_location': {'lat': 37.427, 'lng': -122.084}
#     },
#     ...
# ]
```

**Key Features:**
- **`mode="walking"`** - Optimized for pedestrians (sidewalks, crosswalks, etc.)
- **`avoid=["indoor"]`** - Prevents indoor mall navigation (matches user's preference)
- **`alternatives=True`** - Multiple route options for user choice
- **Waypoints** - Up to 25 waypoints per request (Free tier: 1 request = $0.005)

#### 1B. Geocoding API

**Functionality:**
- **Forward Geocoding**: Address string → GPS coordinates
- **Reverse Geocoding**: GPS coordinates → Human-readable address

**Python Example:**
```python
# Forward: "Starbucks, Mountain View" → (37.4219, -122.0840)
geocode_result = gmaps.geocode('1600 Amphitheatre Parkway, Mountain View, CA')
lat = geocode_result[0]['geometry']['location']['lat']
lng = geocode_result[0]['geometry']['location']['lng']

# Reverse: (37.4219, -122.0840) → "1600 Amphitheatre Parkway, ..."
reverse_result = gmaps.reverse_geocode((37.4219, -122.0840))
address = reverse_result[0]['formatted_address']
```

**Use Case:** Convert NEO-8M GPS coordinates to street addresses for TTS feedback:
- "You left your wallet at Starbucks, 123 Main Street"

#### 1C. API Rate Limits & Costs

| API | Free Tier | Rate Limit | Cost (Beyond Free) |
|-----|-----------|------------|-------------------|
| Directions API | $200/month credit | - | $0.005 per request |
| Geocoding API | $200/month credit | - | $0.005 per request |

**Estimated Usage for YIA 2026 Demo:**
- 100 navigation sessions/day × 30 days = 3,000 requests = $15/month
- **Free tier covers 40,000 requests/month** - More than enough!

**Critical:** Must enable APIs in Google Cloud Console:
1. Create project: https://console.cloud.google.com/
2. Enable "Directions API" and "Geocoding API"
3. Generate API key with restrictions (HTTP referrer or IP address)
4. Store in `config/.env` file (NEVER commit to GitHub)

---

### 2. SLAM Map Storage & Object Anchoring (OpenCV)

**Repository:** `opencv/opencv`

#### 2A. Map Persistence with FileStorage

OpenCV's `FileStorage` class allows saving/loading structured data (YAML/XML/JSON):

**Saving SLAM Map Data:**
```python
import cv2
import numpy as np

# After VIO/SLAM tracking session:
map_data = {
    'camera_poses': keyframe_poses,  # List of 4x4 transformation matrices
    'landmarks': landmarks_3d,       # Nx3 array of 3D points (world coords)
    'descriptors': descriptors,      # Feature descriptors for each landmark
    'map_id': 'home_2025-12-22',     # Unique identifier
    'timestamp': time.time()
}

# Save to YAML (human-readable)
fs = cv2.FileStorage('maps/home_map.yml', cv2.FileStorage_WRITE)
fs.write('camera_poses', np.array(keyframe_poses))
fs.write('landmarks', landmarks_3d)
fs.write('descriptors', descriptors)
fs.write('map_id', 'home_2025-12-22')
fs.release()
```

**Loading SLAM Map for Re-localization:**
```python
fs = cv2.FileStorage('maps/home_map.yml', cv2.FileStorage_READ)
landmarks_3d = fs.getNode('landmarks').mat()
descriptors = fs.getNode('descriptors').mat()
map_id = fs.getNode('map_id').string()
fs.release()

# Use for re-localization:
# 1. Extract features from current frame
# 2. Match with loaded descriptors (FLANN)
# 3. solvePnPRansac to get camera pose in map coordinate system
```

#### 2B. Object Anchoring Strategy

**Problem:** How do we remember "wallet is on kitchen table" with VIO/SLAM?

**Solution:** Anchor objects to SLAM keyframes with 3D positions.

**Data Structure:**
```python
@dataclass
class SpatialObject:
    """Object location in SLAM map coordinate system"""
    object_name: str              # "wallet", "keys", "phone"
    object_class: str             # YOLO class (e.g., "cell phone")
    position_3d: Tuple[float, float, float]  # (X, Y, Z) in meters (map coords)
    keyframe_id: int              # Which SLAM keyframe was used for anchor
    map_id: str                   # Which map (e.g., "home_2025-12-22")
    confidence: float             # 0.0-1.0 (lower if object detection uncertain)
    timestamp: str                # ISO 8601 format
    gps_coords: Optional[Tuple[float, float]]  # If outdoors (lat, lng)
    address: Optional[str]        # Reverse geocoded address (if outdoors)
```

**Storage in Layer 4 Memory (SQLite):**
```sql
-- ============================================================================
-- REVISED SCHEMA (Peer Review Feedback - Coordinate System Separation)
-- ============================================================================

-- COORDINATE SYSTEMS:
-- A. LOCAL (VIO Map Frame): Origin at device start, Units: Meters, Indoor use
-- B. GLOBAL (Geodetic WGS84): GPS lat/lon/alt, Outdoor use  
-- C. HYBRID (Map Anchors): Links A ↔ B transformations

CREATE TABLE spatial_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- User identification
    object_name TEXT NOT NULL,           -- "my wallet", "Starbucks"
    object_class TEXT NOT NULL,          -- YOLO class ("wallet", "door")
    
    -- LOCAL COORDINATE SYSTEM (VIO/SLAM - Indoor)
    vio_position_json TEXT,              -- JSON: {"x": 1.2, "y": 0.5, "z": -2.0}
    vio_map_id TEXT,                     -- "home_2025-12-22"
    vio_keyframe_id INTEGER,             -- Anchor keyframe ID
    
    -- GLOBAL COORDINATE SYSTEM (GPS - Outdoor)
    gps_position_json TEXT,              -- JSON: {"lat": 37.4, "lon": -122.0, "alt": 15}
    gps_address TEXT,                    -- "Starbucks, 123 Main St" (geocoded)
    
    -- QUALITY & METADATA
    quality_flags INTEGER DEFAULT 0,     -- Bitmask: bit0=VIO valid, bit1=GPS valid
    confidence REAL DEFAULT 1.0,         -- YOLO detection confidence
    timestamp_ns INTEGER NOT NULL,       -- Monotonic nanoseconds (time.monotonic_ns())
    created_at TEXT NOT NULL,            -- ISO 8601 human-readable
    
    FOREIGN KEY(vio_map_id) REFERENCES slam_maps(map_id),
    CHECK(vio_position_json IS NOT NULL OR gps_position_json IS NOT NULL)
);

-- Quality Flags Bitmask:
-- 0x01 (bit 0): VIO position valid
-- 0x02 (bit 1): GPS position valid
-- 0x04 (bit 2): Object actively tracked
-- 0x08 (bit 3): High confidence (>0.8)

CREATE TABLE slam_maps (
    map_id TEXT PRIMARY KEY,             -- "home_2025-12-22"
    map_file_path TEXT NOT NULL,         -- "maps/home_map.yml" (EuRoC format)
    creation_time_ns INTEGER NOT NULL,   -- Monotonic timestamp
    creation_time TEXT NOT NULL,         -- ISO 8601
    last_used_ns INTEGER,
    num_keyframes INTEGER DEFAULT 0,
    num_landmarks INTEGER DEFAULT 0,
    location_type TEXT CHECK(location_type IN ('indoor', 'outdoor', 'hybrid')),
    origin_gps_json TEXT,                -- Map origin GPS (if available)
    origin_address TEXT
);

-- NEW: Map Anchors (Links VIO ↔ GPS coordinate systems)
CREATE TABLE map_anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vio_map_id TEXT NOT NULL,
    vio_position_json TEXT NOT NULL,     -- VIO coords when GPS was recorded
    gps_position_json TEXT NOT NULL,     -- Corresponding GPS coords
    timestamp_ns INTEGER NOT NULL,
    gps_accuracy_meters REAL,            -- GPS HDOP quality
    vio_confidence REAL,                 -- VIO tracking quality
    FOREIGN KEY(vio_map_id) REFERENCES slam_maps(map_id)
);

-- EXAMPLE QUERIES

-- Store indoor object (VIO only)
INSERT INTO spatial_objects (
    object_name, object_class,
    vio_position_json, vio_map_id, vio_keyframe_id,
    quality_flags, confidence, timestamp_ns, created_at
) VALUES (
    'my wallet', 'wallet',
    '{"x": 1.2, "y": 0.5, "z": -2.0}', 'home_2025-12-22', 42,
    1, 0.95, 1735000000000000000, '2025-12-22T10:30:00Z'  -- bit 0 set
);

-- Store outdoor object (GPS only)
INSERT INTO spatial_objects (
    object_name, object_class,
    gps_position_json, gps_address,
    quality_flags, confidence, timestamp_ns, created_at
) VALUES (
    'Starbucks', 'building',
    '{"lat": 37.4219, "lon": -122.0840, "alt": 15.0}',
    'Starbucks, 123 Main St, Mountain View, CA',
    2, 1.0, 1735000100000000000, '2025-12-22T10:32:00Z'  -- bit 1 set
);

-- Find object (check both coordinate systems)
SELECT 
    object_name,
    vio_position_json,
    gps_position_json,
    CASE 
        WHEN quality_flags & 1 THEN 'INDOOR (VIO)'
        WHEN quality_flags & 2 THEN 'OUTDOOR (GPS)'
        WHEN quality_flags & 3 = 3 THEN 'HYBRID (BOTH)'
        ELSE 'UNKNOWN'
    END AS location_type
FROM spatial_objects
WHERE object_name = 'my wallet';
```

**Key Improvements (Peer Review Feedback):**
1. **Separate JSON columns** for VIO vs. GPS (prevents mixing coordinate systems)
2. **Bitmask quality flags** (allows objects with both VIO + GPS)
3. **Map anchors table** (enables VIO→GPS transformation for hybrid navigation)
4. **Monotonic timestamps** (`timestamp_ns`) for sensor fusion accuracy

**How Objects are Anchored:**
1. **User says:** "Remember where I put my wallet"
2. **Cortex detects "wallet"** in current YOLO frame (bounding box)
3. **VIO estimates camera pose** relative to SLAM map (R, t)
4. **Depth estimation** from bbox size or stereo (if available)
5. **Compute 3D position** in map coordinates:
   ```python
   # bbox_center_2d = (x_pixel, y_pixel)
   # depth_estimate = distance_from_bbox_size() or stereo_depth()
   point_3d_camera = pixel_to_3d(bbox_center_2d, depth_estimate, K_camera)
   point_3d_map = T_map_camera @ point_3d_camera  # Transform to map frame
   ```
6. **Store in SQLite** with current VIO keyframe ID and map ID

**Re-localization for "Where is my wallet?":**
1. **Load SLAM map** from `slam_maps.map_file_path`
2. **Current camera pose** estimated via VIO (continuous tracking)
3. **Retrieve wallet's 3D position** from `spatial_objects` table
4. **Compute relative vector**: `vec_wallet = pos_wallet - pos_camera`
5. **Convert to polar coords**: `(distance, azimuth, elevation)`
6. **Generate 3D audio beacon** at `(azimuth, distance)` using spatial_audio manager

---

### 3. RTAB-Map Semantic Labeling (Inspiration)

**Repository:** `introlab/rtabmap`

RTAB-Map (Real-Time Appearance-Based Mapping) is a full SLAM system with:
- **Long-term memory management** (STM → WM → LTM)
- **Semantic labeling** via `Memory::labelSignature()`
- **Label-based querying** via `Memory::getSignatureIdByLabel()`

**How RTAB-Map Stores Semantic Labels:**
```cpp
// C++ API (for reference - we'll use Python equivalent)
rtabmap::Memory memory;
memory.labelSignature(node_id, "kitchen_table");

// Query: "Where is kitchen_table?"
int node_id = memory.getSignatureIdByLabel("kitchen_table");
Transform pose = memory.getSignaturePose(node_id);  // Get 3D pose
```

**Adaptation for Project-Cortex:**
We don't use RTAB-Map (too heavy for RPi 5), but we borrow its semantic labeling concept:
- **VIO keyframes** = RTAB-Map nodes
- **SQLite labels** = RTAB-Map's `Memory::_labels` map
- **Label query** = SQL `SELECT * FROM spatial_objects WHERE object_name = 'wallet'`

---

### 4. 3D Spatial Audio Guidance (Existing System)

**Current Implementation:** `src/layer3_guide/spatial_audio/manager.py`

#### 4A. HRTF-Based Directional Audio

We already have PyOpenAL + HRTF for 3D audio! Key features:
- **OpenAL Coordinate System**:
  - X-axis: Left (-) to Right (+)
  - Y-axis: Down (-) to Up (+)
  - Z-axis: Behind (+) to Front (-), user faces -Z

- **Position Calculator** (`position_calculator.py`):
  - Converts 2D bounding boxes → 3D positions
  - Estimates distance from bbox size + known object dimensions
  - Scales X-axis to 3m wide sound field for perceivable HRTF

- **Audio Beacons** (existing):
  - Interval pings (reduces fatigue vs. continuous tone)
  - Proximity alerts (frequency increases as distance decreases)
  - Start/end melodies for beacon activation

#### 4B. Navigation Audio Beacon Extension

**New Feature: GPS/VIO-based Navigation Beacon**

**Existing Code (for YOLO objects):**
```python
# manager.py - Current implementation
def update_object_positions(self, detections: List[Dict]) -> None:
    """Update 3D audio positions for detected objects"""
    for det in detections:
        pos_3d = self.position_calc.calculate_position(
            bbox=det['bbox'],
            frame_width=det['frame_width'],
            frame_height=det['frame_height']
        )
        # Play sound at pos_3d
```

**NEW: Navigation Beacon (for remembered objects):**
```python
def create_navigation_beacon(
    self, 
    target_position: Tuple[float, float, float],  # (X, Y, Z) in map coords
    current_pose: Tuple[float, float, float],     # Camera pose (from VIO)
    object_name: str = "target"
) -> None:
    """
    Create a persistent audio beacon guiding user to a remembered object.
    
    Args:
        target_position: Object's 3D position in SLAM map coordinates
        current_pose: Current camera pose from VIO (X, Y, Z)
        object_name: User-friendly name ("wallet", "keys", etc.)
    """
    # Compute relative vector
    dx = target_position[0] - current_pose[0]
    dy = target_position[1] - current_pose[1]
    dz = target_position[2] - current_pose[2]
    
    # Convert to polar coordinates for HRTF
    distance = math.sqrt(dx**2 + dy**2 + dz**2)
    azimuth = math.atan2(dx, -dz)  # OpenAL: user faces -Z
    elevation = math.atan2(dy, math.sqrt(dx**2 + dz**2))
    
    # Convert to OpenAL position (in meters for realistic HRTF)
    openal_pos = (
        distance * math.sin(azimuth),  # X
        distance * math.sin(elevation),  # Y
        -distance * math.cos(azimuth)   # Z (negative = in front)
    )
    
    # Activate beacon
    self.audio_beacon.activate(
        position=openal_pos,
        label=object_name,
        beacon_type="navigation",  # vs. "detection" for YOLO
        sound_file="assets/sounds/beacons/gentle_chime.wav",
        interval_ms=2000 if distance > 5 else 1000,  # Faster when close
        volume=self._calculate_proximity_volume(distance)
    )
    
    # TTS feedback
    self.speak(f"Navigating to {object_name}. It's {distance:.1f} meters away.")
```

**Proximity Volume Calculation:**
```python
def _calculate_proximity_volume(self, distance_meters: float) -> float:
    """
    Volume increases as user approaches target.
    Prevents overwhelming audio at large distances.
    """
    if distance_meters > 10:
        return 0.3  # Quiet at long range
    elif distance_meters > 5:
        return 0.5  # Medium at mid-range
    elif distance_meters > 1:
        return 0.7  # Louder when close
    else:
        return 0.9  # Maximum volume when very close
```

#### 4C. Google Maps Turn-by-Turn Audio

**Integration with Directions API:**
```python
def speak_navigation_step(self, step: Dict) -> None:
    """
    Speak a Google Maps navigation instruction with spatial audio.
    
    Args:
        step: Dict from Google Maps Directions API
              {
                'html_instructions': 'Turn <b>left</b> onto Main St',
                'distance': {'text': '0.3 mi', 'value': 483},
                'duration': {'text': '6 mins', 'value': 360},
                'maneuver': 'turn-left'  # Optional
              }
    """
    # Clean HTML tags
    instruction = re.sub(r'<[^>]+>', '', step['html_instructions'])
    distance_text = step['distance']['text']
    
    # Generate TTS
    tts_text = f"{instruction} in {distance_text}"
    self.speak(tts_text)
    
    # Spatial audio cue for turn direction
    if 'maneuver' in step:
        if 'left' in step['maneuver']:
            self._play_turn_cue(azimuth=-90)  # Sound from left
        elif 'right' in step['maneuver']:
            self._play_turn_cue(azimuth=90)   # Sound from right
        elif 'straight' in step['maneuver']:
            self._play_turn_cue(azimuth=0)    # Sound from front
```

**Turn Audio Cue (Earcon):**
```python
def _play_turn_cue(self, azimuth: float) -> None:
    """
    Play a short directional tone to indicate turn direction.
    
    Args:
        azimuth: Angle in degrees (-180 to 180, 0 = front)
    """
    # Convert azimuth to OpenAL position
    azimuth_rad = math.radians(azimuth)
    pos = (
        3.0 * math.sin(azimuth_rad),  # X (3m distance for clarity)
        0.0,                           # Y (ear level)
        -3.0 * math.cos(azimuth_rad)  # Z (in front)
    )
    
    # Play short chime
    self._play_sound_at_position(
        sound_file="assets/sounds/alerts/direction_chime.wav",
        position=pos,
        volume=0.6
    )
```

---

## 🏗️ SYSTEM ARCHITECTURE

### Overall Data Flow

```
┌───────────────────────────────────────────────────────────────┐
│                    USER INTERACTION                           │
│  Voice: "Remember where I put my wallet" / "Where is wallet?" │
└────────────────────┬──────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │   Layer 1 (Reflex)    │
         │  - Whisper STT        │
         │  - YOLO detection     │
         │  - Kokoro TTS         │
         └──────────┬────────────┘
                    │
                    ▼
         ┌──────────────────────────┐
         │  Layer 3 (Router)        │
         │  Determines:             │
         │  - "Remember" → Store    │
         │  - "Where" → Retrieve    │
         └──────────┬───────────────┘
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
┌───────────────┐      ┌─────────────────────┐
│ STORAGE PATH  │      │  RETRIEVAL PATH     │
│ (New System)  │      │  (New System)       │
└───────┬───────┘      └──────────┬──────────┘
        │                         │
        ▼                         ▼
┌──────────────────────────────────────────────┐
│         SPATIAL MEMORY SUBSYSTEM             │
│  ┌──────────────────────────────────────┐  │
│  │  1. VIO/SLAM Pose Estimator          │  │
│  │     - Fisheye camera tracking        │  │
│  │     - BNO055 IMU fusion              │  │
│  │     - Outputs: Camera pose (R, t)    │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │  2. GPS/Geocoding Module             │  │
│  │     - NEO-8M GPS (10Hz)              │  │
│  │     - Google Geocoding API           │  │
│  │     - Outputs: Lat/lng, address      │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │  3. Object Spatial Anchor            │  │
│  │     - 2D bbox → 3D position          │  │
│  │     - Store in SQLite                │  │
│  └──────────────────────────────────────┘  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
      ┌────────────────────────┐
      │  Layer 4 (Memory DB)   │
      │  - spatial_objects     │
      │  - slam_maps           │
      └────────────┬───────────┘
                   │
                   ▼
      ┌────────────────────────┐
      │  NAVIGATION SYSTEM     │
      │  ┌──────────────────┐ │
      │  │ Indoor:          │ │
      │  │ VIO re-localize  │ │
      │  │ 3D audio beacon  │ │
      │  └──────────────────┘ │
      │  ┌──────────────────┐ │
      │  │ Outdoor:         │ │
      │  │ Google Maps API  │ │
      │  │ GPS waypoints    │ │
      │  │ Turn-by-turn TTS │ │
      │  └──────────────────┘ │
      └────────────┬───────────┘
                   │
                   ▼
      ┌────────────────────────┐
      │  Spatial Audio Manager │
      │  - HRTF beacons        │
      │  - Proximity alerts    │
      │  - Turn cues           │
      └────────────────────────┘
                   │
                   ▼
           🎧 USER HEARS GUIDANCE
```

### Module Breakdown

#### Module 1: VIO Pose Estimator (`layer3_guide/vio/`)
**Purpose:** Estimate camera pose in SLAM map coordinates

**Files:**
- `vio_estimator.py` - Main VIO pipeline (feature tracking + IMU fusion)
- `map_manager.py` - Load/save SLAM maps via OpenCV FileStorage
- `relocalization.py` - Match current frame to saved map for pose recovery

**Key Functions:**
```python
class VIOEstimator:
    def get_current_pose(self) -> np.ndarray:
        """Returns 4x4 transformation matrix (camera → map)"""
        
    def save_map(self, map_id: str) -> None:
        """Save current SLAM map to YAML file"""
        
    def load_map(self, map_id: str) -> bool:
        """Load SLAM map for re-localization"""
```

#### Module 2: GPS Geocoding (`layer3_guide/gps/`)
**Purpose:** Interface with NEO-8M GPS + Google Maps API

**Files:**
- `gps_reader.py` - Parse NMEA sentences from NEO-8M (UART)
- `geocoding.py` - Google Maps API wrapper (forward/reverse geocoding)
- `directions.py` - Walking navigation with waypoints

**Key Functions:**
```python
class GPSReader:
    def get_current_position(self) -> Tuple[float, float]:
        """Returns (latitude, longitude) from NEO-8M"""
        
class GoogleMapsClient:
    def geocode_address(self, address: str) -> Tuple[float, float]:
        """Address string → GPS coordinates"""
        
    def reverse_geocode(self, lat: float, lng: float) -> str:
        """GPS coordinates → Human-readable address"""
        
    def get_walking_directions(
        self, origin: Tuple[float, float], 
        destination: Tuple[float, float]
    ) -> List[Dict]:
        """Returns turn-by-turn navigation steps"""
```

#### Module 3: Spatial Memory (`layer4_memory/`)
**Purpose:** Store/retrieve object locations with VIO + GPS data

**Files:**
- `spatial_memory.py` - High-level API for "remember" and "where" commands
- `models.py` - SQLAlchemy models (spatial_objects, slam_maps tables)

**Key Functions:**
```python
class SpatialMemory:
    def remember_object(
        self,
        object_name: str,
        object_class: str,
        bbox: Tuple[int, int, int, int],
        vio_pose: np.ndarray,
        gps_coords: Optional[Tuple[float, float]] = None
    ) -> int:
        """Store object location in memory. Returns object_id."""
        
    def find_object(self, object_name: str) -> Optional[SpatialObject]:
        """Retrieve object location from memory."""
        
    def get_all_remembered_objects(self) -> List[SpatialObject]:
        """List all objects user has remembered."""
```

#### Module 4: Navigation Controller (`layer3_guide/navigation/`)
**Purpose:** Orchestrate indoor/outdoor navigation strategies

**Files:**
- `navigation_controller.py` - Main controller (indoor/outdoor routing logic)
- `indoor_navigator.py` - VIO-based relative positioning + audio beacons
- `outdoor_navigator.py` - Google Maps + GPS waypoint following

**Key Functions:**
```python
class NavigationController:
    def navigate_to_object(self, object_name: str) -> None:
        """
        Main entry point for "Where is my wallet?" command.
        Determines if indoor/outdoor, then delegates to appropriate navigator.
        """
        
    def _determine_location_type(self) -> str:
        """Returns 'indoor', 'outdoor', or 'unknown' based on GPS fix"""
        
class IndoorNavigator:
    def guide_to_position(self, target_pos: np.ndarray) -> None:
        """VIO-based navigation with 3D audio beacon"""
        
class OutdoorNavigator:
    def follow_route(self, route_steps: List[Dict]) -> None:
        """Follow Google Maps turn-by-turn with GPS + audio cues"""
```

---

## 🛠️ IMPLEMENTATION PLAN

### Phase 1: Database Schema Extension (Week 1)
**Goal:** Add spatial memory tables to existing SQLite database

**Tasks:**
- [ ] Create `spatial_objects` table in `layer4_memory/database.py`
- [ ] Create `slam_maps` table
- [ ] SQLAlchemy models (`models.py`)
- [ ] Migration script (upgrade existing DB)
- [ ] Unit tests for CRUD operations

**Success Criteria:**
- Insert object with 3D position → retrieves correctly
- Store multiple objects → query by name

**Estimated Time:** 3-4 days

---

### Phase 2: GPS + Geocoding Integration (Week 1-2)
**Goal:** Interface with NEO-8M GPS + Google Maps API

**Tasks:**
- [ ] **NEO-8M GPS Reader:**
  - UART communication (`/dev/ttyAMA0`, 9600 baud)
  - NMEA sentence parsing (`$GPGGA`, `$GPRMC`)
  - Parse latitude, longitude, altitude, fix quality
  - Test: Print GPS coords every second

- [ ] **Google Maps API Setup:**
  - Create Google Cloud project
  - Enable Directions API + Geocoding API
  - Generate API key with restrictions
  - Store key in `config/.env` (`.gitignore`)

- [ ] **Geocoding Module:**
  - `geocode_address()` - forward geocoding
  - `reverse_geocode()` - lat/lng → address
  - `get_walking_directions()` - turn-by-turn steps
  - Test with hardcoded coordinates

**Success Criteria:**
- NEO-8M outputs GPS coords when outdoors
- Geocoding converts "Starbucks, Mountain View" → (37.4219, -122.0840)
- Directions API returns 5-10 navigation steps

**Estimated Time:** 5-6 days

---

### Phase 3: VIO Pose Integration (Week 2-3)
**Goal:** Use VIO pose for object anchoring (depends on SLAM_VIO_NAVIGATION_RESEARCH.md Phase 1-2)

**Prerequisites:**
- ✅ Fisheye camera calibration complete (from SLAM research Phase 1)
- ✅ VIO prototype functional (from SLAM research Phase 2)

**Tasks:**
- [ ] **Map Manager:**
  - `save_map()` - Export VIO keyframes + landmarks to YAML
  - `load_map()` - Import YAML for re-localization
  - Test: Save map → restart → load map → re-localize

- [ ] **Object Spatial Anchor:**
  - `anchor_object_to_map()` - Convert bbox + depth → 3D position
  - Depth estimation from bbox size (pinhole model)
  - Transform to map coordinates: `T_map_camera @ point_3d_camera`
  - Store in `spatial_objects` table with keyframe ID

**Success Criteria:**
- Walk around room, VIO tracks pose
- Place object (e.g., coffee mug), say "Remember this mug"
- Cortex stores 3D position relative to map origin
- Walk to different location, camera pose updates correctly

**Estimated Time:** 7-10 days

---

### Phase 4: Spatial Memory High-Level API (Week 3)
**Goal:** User-friendly "remember" and "where" commands

**Tasks:**
- [ ] **SpatialMemory Class:**
  - `remember_object()` - Store with VIO + GPS
  - `find_object()` - Retrieve by name
  - `get_all_remembered_objects()` - List all
  - Automatic indoor/outdoor detection (GPS fix quality)

- [ ] **Voice Command Integration:**
  - Update `layer3_guide/router.py` to handle:
    - "Remember where I put my [object]"
    - "Where is my [object]?"
    - "Show me all remembered objects"
  - Call `SpatialMemory` API

**Success Criteria:**
- User: "Remember where I put my wallet"
  - Cortex: "Okay, I'll remember where your wallet is" (stores position)
- User: "Where is my wallet?"
  - Cortex: "Your wallet is 3 meters away, behind you" (retrieves + speaks)

**Estimated Time:** 3-4 days

---

### Phase 5: Indoor Navigation (3D Audio Beacon) (Week 4)
**Goal:** Guide user to remembered object using spatial audio

**Tasks:**
- [ ] **Navigation Beacon:**
  - Extend `spatial_audio/manager.py`:
    - `create_navigation_beacon()` - Persistent audio beacon
    - Update position in real-time as VIO pose changes
  - Proximity alerts (increase frequency as distance decreases)
  - TTS distance updates every 5 seconds

- [ ] **Indoor Navigator:**
  - `IndoorNavigator.guide_to_position()` - Main loop:
    1. Get current VIO pose
    2. Compute relative vector to target
    3. Update beacon position
    4. Check if arrived (distance <0.5m)
  - "You're 5 meters away... 3 meters... 1 meter... you've arrived!"

**Success Criteria:**
- User remembers wallet location (indoors)
- User walks away, asks "Where is my wallet?"
- Cortex activates audio beacon pointing toward wallet
- User turns toward beacon (louder = facing correct direction)
- User walks forward, beacon intensifies, TTS announces distances
- User arrives within 0.5m, beacon stops, TTS says "You've arrived!"

**Estimated Time:** 5-6 days

---

### Phase 6: Outdoor Navigation (Google Maps) (Week 4-5)
**Goal:** Turn-by-turn walking navigation with GPS + audio cues

**Tasks:**
- [ ] **Outdoor Navigator:**
  - `OutdoorNavigator.follow_route()` - Main loop:
    1. Get current GPS position
    2. Find next waypoint from route_steps
    3. Compute bearing to next waypoint
    4. Check if waypoint reached (distance <5m)
    5. Speak next instruction + play turn cue
  - Distance to next turn announced every 50m
  - Reroute if user deviates >20m from path

- [ ] **GPS Waypoint Following:**
  - Compute bearing: `atan2(Δlng, Δlat)`
  - Compute distance: Haversine formula
  - Convert bearing → azimuth for 3D audio turn cue
  - Test with real outdoor walk (5-10 minute route)

- [ ] **Turn Audio Cues:**
  - Left turn: Chime from -90° (left ear)
  - Right turn: Chime from +90° (right ear)
  - Straight: Chime from 0° (front)
  - Integration with TTS: "Turn left in 50 meters" + left chime

**Success Criteria:**
- User remembers wallet location at Starbucks (outdoors)
- User walks to park (500m away), asks "Where is my wallet?"
- Cortex fetches Google Maps walking route
- Cortex speaks: "Your wallet is 500 meters away at Starbucks. Starting navigation."
- TTS announces turns: "In 100 meters, turn right onto Main Street"
- Spatial audio chime plays from right side
- User arrives at Starbucks, TTS says "You've arrived at Starbucks"

**Estimated Time:** 6-7 days

---

### Phase 7: Hybrid Indoor/Outdoor Transitions (Week 5)
**Goal:** Seamless handoff between VIO and GPS navigation

**Tasks:**
- [ ] **Location Type Detection:**
  - GPS fix quality: 3D fix → outdoor, No fix → indoor
  - Transition detection: Indoor → outdoor when GPS acquires fix
  - Transition detection: Outdoor → indoor when GPS loses fix (>10s)

- [ ] **Navigation Strategy Switching:**
  - Start indoors (VIO-based beacon)
  - Walk outdoors → GPS acquires fix → switch to Google Maps
  - Walk back indoors → GPS loses fix → switch to VIO beacon
  - Smooth audio beacon transition (crossfade, not abrupt cutoff)

- [ ] **TTS Transition Announcements:**
  - "GPS signal acquired, switching to outdoor navigation"
  - "GPS signal lost, using indoor positioning"

**Success Criteria:**
- User remembers wallet indoors
- User walks outside → Cortex switches to GPS
- User walks back inside → Cortex switches to VIO
- No crashes or audio glitches during transitions

**Estimated Time:** 4-5 days

---

### Phase 8: Edge Cases & Polish (Week 6)
**Goal:** Handle errors, improve UX, optimize performance

**Tasks:**
- [ ] **Error Handling:**
  - Object not found: "I don't remember seeing your wallet"
  - GPS unavailable: "GPS signal unavailable, using indoor positioning"
  - Google Maps API rate limit: "Navigation temporarily unavailable"
  - VIO tracking lost: "Tracking lost, please look around to re-localize"

- [ ] **User Feedback:**
  - Confirmation after remembering: "Okay, I'll remember where your wallet is"
  - Object list: "You've remembered 3 objects: wallet, keys, phone"
  - Distance estimates: "Your wallet is approximately 10 meters away"

- [ ] **Performance Optimization:**
  - Cache Google Maps routes (avoid redundant API calls)
  - Lazy-load SLAM maps (only when needed)
  - VIO pose updates at 10Hz (not 30fps, save CPU)

- [ ] **Testing:**
  - Indoor navigation: 10 test cases (different rooms, distances)
  - Outdoor navigation: 5 test cases (different routes, 100m-1km)
  - Hybrid transitions: 3 test cases (indoor→outdoor→indoor)

**Success Criteria:**
- No crashes during 20 navigation sessions
- TTS feedback clear and informative
- Audio beacons smooth and non-jarring

**Estimated Time:** 5-6 days

---

## 📊 SYSTEM PERFORMANCE ESTIMATES

### Computational Load (RPi 5, 4 cores)

| Component | Frequency | Latency | CPU Load | Notes |
|-----------|-----------|---------|----------|-------|
| YOLO 11x | 15 fps | 60-80ms | 60% (1 core) | Object detection |
| VIO Pose | 10 Hz | 120ms | 40% (2 cores) | Feature tracking + EKF |
| GPS Parsing | 10 Hz | <5ms | 5% (1 core) | NMEA parsing |
| Spatial Audio | 20 Hz | 10ms | 10% (1 core) | HRTF + OpenAL |
| Google Maps API | On-demand | 200-500ms | <5% (1 core) | Network latency |
| SQLite Queries | On-demand | <10ms | <5% (1 core) | Database I/O |
| **TOTAL** | - | ~200ms | **~100%** (multi-core) | Real-time feasible |

**Notes:**
- **VIO runs at 10Hz** (not 30fps) to save CPU for YOLO + audio
- **Google Maps API cached** to minimize network calls
- **GPS updates 10Hz** but position only queried when needed (1Hz)

### Memory Footprint

| Component | RAM Usage | Notes |
|-----------|-----------|-------|
| YOLO Model | 400-500MB | YOLO 11x weights |
| VIO Map | 50-100MB | Keyframes + landmarks (per map) |
| OpenAL Buffers | 20-30MB | Audio files in memory |
| SQLite DB | 10-50MB | Depends on # of objects |
| GPS + API Client | 5-10MB | Negligible |
| **TOTAL** | **~600MB** | Well within 4GB RAM |

**Optimization:** Load VIO maps on-demand (lazy loading), unload when not needed.

### Network Usage (Google Maps API)

| Operation | Data Transfer | Frequency | Notes |
|-----------|---------------|-----------|-------|
| Geocoding | ~1KB per request | On-demand | Address ↔ GPS |
| Directions | ~5KB per request | Per route | Turn-by-turn steps |
| **TOTAL** | **~10KB per navigation** | Rare | Cacheable |

**Mobile Hotspot Requirement:**
- Use phone's mobile hotspot for outdoor navigation
- Estimated data usage: **1-2MB per day** (20 navigation sessions)
- **YIA 2026 Demo:** Pre-cache routes offline (no internet required during demo)

---

## 💰 COST ANALYSIS

### Hardware Costs (ALREADY OWNED ✅)
| Component | Cost | Status |
|-----------|------|--------|
| Raspberry Pi Camera Module 3 Wide | $35 | ✅ Owned |
| Adafruit BNO055 IMU | $30 | ✅ Owned |
| u-blox NEO-8M GPS | $20 | ✅ Owned |
| **Hardware Total** | **$85** | **All owned** |

### Software Costs (API Usage)
| Service | Free Tier | Demo Usage | Cost |
|---------|-----------|------------|------|
| Google Maps Directions API | $200/month credit | 100 routes/month | **FREE** |
| Google Maps Geocoding API | $200/month credit | 50 requests/month | **FREE** |
| **Software Total** | **$0/month** | - | **FREE** |

**Note:** Free tier covers **40,000 requests/month** - far exceeds YIA demo needs.

### Total Project Cost (Navigation Feature)
- **Hardware:** $0 (already owned)
- **Software:** $0 (free tier)
- **Development Time:** 6 weeks (solo dev)
- **TOTAL: $0** 🎉

---

## 🧪 TESTING PROTOCOL

### Test Case 1: Indoor Object Remembering
**Scenario:** User places wallet on kitchen table, asks Cortex to remember it.

**Steps:**
1. User: "Remember where I put my wallet"
2. Cortex detects "wallet" via YOLO (bounding box)
3. VIO estimates camera pose (R, t) in map coordinates
4. Cortex computes wallet's 3D position
5. Cortex stores in SQLite with map_id, timestamp, GPS (NULL)

**Expected Output:**
- SQLite row: `spatial_objects` table
  - `object_name`: "my wallet"
  - `object_class`: "wallet"
  - `position_x, y, z`: (1.2, 0.5, -2.3) meters
  - `map_id`: "home_2025-12-22"
  - `gps_latitude, gps_longitude`: NULL (indoors)

**Success Criteria:**
- ✅ Object stored in database
- ✅ Position matches expected location (within 0.5m error)
- ✅ TTS confirms: "Okay, I'll remember where your wallet is"

---

### Test Case 2: Indoor Object Retrieval
**Scenario:** User walks to different room, asks "Where is my wallet?"

**Steps:**
1. User: "Where is my wallet?"
2. Cortex queries SQLite: `SELECT * FROM spatial_objects WHERE object_name = 'wallet'`
3. Cortex loads SLAM map via map_id
4. VIO estimates current camera pose
5. Cortex computes relative vector: `vec = pos_wallet - pos_camera`
6. Cortex activates 3D audio beacon at azimuth/distance

**Expected Output:**
- TTS: "Your wallet is 3 meters away, behind you"
- Audio beacon plays from rear (azimuth ~180°)
- User turns around → beacon shifts to front
- User walks forward → beacon gets louder (proximity alert)
- User arrives (distance <0.5m) → TTS: "You've arrived!"

**Success Criteria:**
- ✅ Audio beacon direction matches actual wallet location (±15° error)
- ✅ Distance estimate accurate (±20% error)
- ✅ Proximity alerts trigger correctly

---

### Test Case 3: Outdoor Object Remembering (GPS)
**Scenario:** User leaves wallet at Starbucks, Cortex remembers GPS coordinates.

**Steps:**
1. User stands outside Starbucks (GPS fix acquired)
2. User: "Remember this location as Starbucks"
3. Cortex reads GPS coords: (37.4219, -122.0840)
4. Cortex reverse geocodes: "Starbucks, 123 Main St, Mountain View"
5. Cortex stores in SQLite with GPS + address

**Expected Output:**
- SQLite row: `spatial_objects` table
  - `object_name`: "Starbucks"
  - `gps_latitude`: 37.4219
  - `gps_longitude`: -122.0840
  - `address`: "Starbucks, 123 Main St, Mountain View, CA"
  - `position_x, y, z`: NULL (outdoor, no VIO map)

**Success Criteria:**
- ✅ GPS coordinates stored correctly
- ✅ Address human-readable
- ✅ TTS confirms: "Okay, I'll remember Starbucks"

---

### Test Case 4: Outdoor Navigation (Google Maps)
**Scenario:** User walks 500m away, asks Cortex to navigate back to Starbucks.

**Steps:**
1. User: "Navigate to Starbucks"
2. Cortex queries SQLite for Starbucks GPS coords
3. Cortex gets current GPS position: (37.4250, -122.0850)
4. Cortex calls Google Maps Directions API (walking mode)
5. Cortex receives 10 navigation steps
6. Cortex speaks first step: "Head north on Main St for 100 meters"
7. GPS updates every second → distance to next waypoint decreases
8. At 20m from waypoint → TTS: "Turn right onto Oak Street"
9. Spatial audio chime plays from right side
10. Repeat for all steps
11. Arrival: TTS: "You've arrived at Starbucks"

**Expected Output:**
- Turn-by-turn instructions spoken every 50m
- Turn cues played from correct direction (±45° error)
- Arrival detected within 5m

**Success Criteria:**
- ✅ Route calculated correctly
- ✅ TTS instructions clear and timely
- ✅ Turn cues match turn directions
- ✅ Arrival announced when GPS within 5m

---

### Test Case 5: Hybrid Indoor→Outdoor Transition
**Scenario:** User starts indoors (VIO), walks outside (GPS), navigation switches seamlessly.

**Steps:**
1. User remembers wallet indoors (VIO-based)
2. User walks outside → GPS acquires fix (HDOP <2.0, 3D fix)
3. Cortex detects transition: `gps.has_fix() == True`
4. Cortex speaks: "GPS signal acquired, switching to outdoor navigation"
5. Cortex calls Google Maps API for route
6. Audio beacon transitions from VIO-based to GPS-based (crossfade 1s)

**Expected Output:**
- Smooth audio transition (no abrupt cutoff)
- TTS announces transition
- No tracking loss or crashes

**Success Criteria:**
- ✅ Transition detected within 3 seconds of GPS fix
- ✅ Audio beacon continues without interruption
- ✅ TTS feedback informative

---

## 🚨 EDGE CASES & ERROR HANDLING

### 1. VIO Tracking Lost
**Problem:** Camera moves too fast, features lost, VIO can't estimate pose.

**Detection:**
- `vio_estimator.get_tracking_quality()` returns <0.3 (low confidence)
- `pose_covariance` exceeds threshold

**Handling:**
```python
if vio.get_tracking_quality() < 0.3:
    self.speak("Tracking lost. Please look around slowly to re-localize.")
    self.pause_navigation()  # Stop audio beacon
    self.wait_for_relocalization()  # Wait for VIO to recover
```

---

### 2. GPS Unavailable (Indoors)
**Problem:** User asks for outdoor navigation, but GPS has no fix.

**Detection:**
- `gps.has_fix() == False`
- `gps.fix_quality == 0` (no satellites)

**Handling:**
```python
if not gps.has_fix():
    self.speak("GPS signal unavailable. Using indoor positioning instead.")
    self.fallback_to_vio_navigation()
```

---

### 3. Object Not Found in Memory
**Problem:** User asks "Where is my phone?" but never remembered it.

**Detection:**
- `SpatialMemory.find_object("phone")` returns `None`

**Handling:**
```python
if obj is None:
    self.speak("I don't remember seeing your phone. Would you like me to look for it now?")
    self.trigger_yolo_scan()  # Actively scan for "cell phone" class
```

---

### 4. Google Maps API Rate Limit
**Problem:** Too many requests, API returns 429 error.

**Detection:**
- `googlemaps.exceptions.ApiError: OVER_QUERY_LIMIT`

**Handling:**
```python
try:
    directions = gmaps.directions(origin, destination, mode="walking")
except googlemaps.exceptions.ApiError as e:
    if "OVER_QUERY_LIMIT" in str(e):
        self.speak("Navigation temporarily unavailable. Trying again in 1 minute.")
        self.cache_route()  # Use last known route if available
```

---

### 5. User Deviates from Route (Outdoor)
**Problem:** User walks off-path, GPS position >20m from route polyline.

**Detection:**
- Compute distance from GPS point to nearest route segment
- If distance >20m for >10 seconds → off-route

**Handling:**
```python
if self.is_off_route(current_gps, route_polyline):
    self.speak("You're off the route. Recalculating...")
    new_route = self.recalculate_route(current_gps, destination)
    self.update_navigation_steps(new_route)
```

---

## 🎯 SUCCESS METRICS (YIA 2026 Demo)

### Functionality Targets
- **Indoor Navigation Accuracy:** ±1m position error, ±30° direction error
- **Outdoor Navigation Success Rate:** >90% successful arrivals (within 5m)
- **Audio Beacon Clarity:** Users correctly identify direction in >80% of tests
- **Hybrid Transitions:** <3 second latency for indoor↔outdoor switch

### User Experience
- **TTS Feedback:** Clear, informative, not overwhelming
- **Audio Fatigue:** Users report comfort after 15-minute navigation session
- **Error Recovery:** System recovers gracefully from tracking loss in <10 seconds

### Technical Performance
- **CPU Usage:** <100% multi-core average (no thermal throttling)
- **Battery Life:** >3 hours continuous use (30,000mAh power bank)
- **Memory Usage:** <2GB RAM (50% of available 4GB)
- **Network Data:** <5MB per day (20 navigation sessions)

---

## 📚 REFERENCES

### Research Papers
1. **Microsoft Soundscape** - Open-source spatial audio navigation for blind users
   - https://github.com/microsoft/soundscape
   - Audio beacon design principles

2. **Sonification Handbook** (Hermann et al.) - Academic guidelines for accessible audio
   - http://sonification.de/handbook/
   - HRTF-based navigation research

3. **Google Maps Platform Documentation**
   - https://developers.google.com/maps/documentation/directions/
   - https://developers.google.com/maps/documentation/geocoding/

### Code Libraries
- **googlemaps** (Python client): `pip install googlemaps`
- **adafruit-gps** (NEO-8M driver): `pip install adafruit-circuitpython-gps`
- **PyOpenAL** (3D audio): `pip install PyOpenAL`
- **filterpy** (EKF for sensor fusion): `pip install filterpy`

### Documentation (Already in Project)
- `docs/SLAM_VIO_NAVIGATION_RESEARCH.md` - VIO/SLAM implementation plan
- `docs/SPATIAL_AUDIO_IMPLEMENTATION.md` - 3D audio system design
- `docs/TECHNICAL_STATE_REPORT.md` - Current system architecture (76 pages)

---

## ✅ NEXT STEPS (Awaiting Your Approval)

**We now have TWO comprehensive research documents:**

1. **SLAM_VIO_NAVIGATION_RESEARCH.md** (25 pages)
   - VIO/SLAM framework selection
   - Hardware integration (Camera Wide, BNO055, NEO-8M)
   - Fisheye calibration procedures
   - 8-week implementation roadmap

2. **MEMORY_SLAM_NAVIGATION_INTEGRATION.md** (THIS DOCUMENT)
   - Object localization with VIO + GPS
   - Google Maps API integration
   - 3D audio navigation beacons
   - 6-week implementation plan

**Decision Points:**
1. ✅ **Approve research findings?** (SLAM + Memory + Navigation architecture)
2. ⏳ **Prioritize implementation?**
   - Option A: **SLAM/VIO first** (Weeks 1-8), then Memory+Navigation (Weeks 9-15)
   - Option B: **Memory+Navigation first** (Weeks 1-6), then SLAM/VIO (Weeks 7-14)
   - Option C: **Parallel development** (SLAM + Memory simultaneously, 10-12 weeks)

3. ⏳ **Google Maps API key?**
   - Create Google Cloud project
   - Enable Directions + Geocoding APIs
   - Generate API key (free tier: $200/month credit)
   - Store in `config/.env` (never commit to repo)

4. ⏳ **Hardware testing priority?**
   - GPS outdoor testing (verify NEO-8M accuracy)
   - Fisheye camera calibration (20-30 checkerboard images)
   - IMU sensor fusion (BNO055 quaternion output)

**Ready to code?** Or more research needed? 💚

---

**Document Version:** 1.0  
**Last Updated:** 2025-12-22  
**Status:** ✅ RESEARCH COMPLETE - AWAITING IMPLEMENTATION APPROVAL
