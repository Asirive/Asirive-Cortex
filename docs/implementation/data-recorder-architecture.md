# 📊 Data Recorder Architecture (EuRoC MAV Format)
**Project-Cortex v2.0 - Development Infrastructure**

---

## 🎯 PURPOSE

This document defines the **Data Recording Pipeline** for Project-Cortex, solving the critical "Laptop vs. RPi Reality Gap" problem identified in peer review.

### The Problem: Simulation Gap
Developing VIO algorithms on a **laptop webcam** (narrow FOV, low distortion) will fail catastrophically on the **RPi Camera Wide** (120° FOV, massive fisheye distortion).

### The Solution: Data-Driven Development
1. **Record sensor data** in industry-standard **EuRoC MAV dataset format**
2. **Develop algorithms** on laptop using recorded data (or simulated dummy data)
3. **Deploy on RPi 5** without changing a single line of VIO code (just swap data source)

---

## 📋 EuRoC MAV Dataset Format

### Industry Standard Structure
```
/data_session_001/                  # Recording session directory
├── cam0/                           # Camera 0 data
│   ├── data.csv                    # Timestamp index
│   └── data/                       # Image files
│       ├── 1520532096118336678.png
│       ├── 1520532096168337822.png
│       └── ...
├── imu0/                           # IMU data
│   └── data.csv                    # IMU measurements
├── gps0/                           # GPS data (Project-Cortex extension)
│   └── data.csv                    # GPS NMEA sentences
└── sensor.yaml                     # Sensor calibration metadata
```

### CSV File Formats

#### cam0/data.csv (Camera Timestamps)
```csv
#timestamp [ns],filename
1520532096118336678,1520532096118336678.png
1520532096168337822,1520532096168337822.png
1520532096218339682,1520532096218339682.png
...
```

#### imu0/data.csv (IMU Measurements)
```csv
#timestamp [ns],omega_x [rad/s],omega_y [rad/s],omega_z [rad/s],alpha_x [m/s^2],alpha_y [m/s^2],alpha_z [m/s^2]
1520532096118336678,-0.006604425,0.027463167,-0.219075842,-9.377390629,-2.509590162,1.803427934
1520532096119000000,-0.006288854,0.034143698,-0.192908493,-9.396187268,-2.561453858,1.801144085
1520532096120000000,-0.003507960,0.041634469,-0.169406436,-9.413662963,-2.611338997,1.794072908
...
```

#### gps0/data.csv (GPS Data - Custom Extension)
```csv
#timestamp [ns],latitude [deg],longitude [deg],altitude [m],fix_quality,satellites,hdop
1520532096118336678,37.421998333,-122.084000000,15.2,3,8,1.2
1520532096218336678,37.422001234,-122.084002345,15.3,3,8,1.2
1520532096318336678,37.422004567,-122.084005678,15.4,3,9,1.1
...
```

#### sensor.yaml (Calibration Metadata)
```yaml
cameras:
  - camera:
      intrinsics: [fx, fy, cx, cy]  # From fisheye calibration
      distortion_coefficients: [k1, k2, k3, k4]  # Equidistant model
      distortion_type: equidistant
      resolution: [2304, 1296]
      camera_model: fisheye
      T_BS:  # Camera-to-body transformation (4x4 matrix)
        - [1.0, 0.0, 0.0, 0.0]
        - [0.0, 1.0, 0.0, 0.0]
        - [0.0, 0.0, 1.0, 0.0]
        - [0.0, 0.0, 0.0, 1.0]
      timeshift_cam_imu: 0.0  # From Kalibr calibration

imus:
  - imu:
      T_BS:  # IMU-to-body transformation (4x4 matrix)
        - [1.0, 0.0, 0.0, 0.0]
        - [0.0, 1.0, 0.0, 0.0]
        - [0.0, 0.0, 1.0, 0.0]
        - [0.0, 0.0, 0.0, 1.0]
      accelerometer_noise_density: 0.01
      accelerometer_random_walk: 0.0002
      gyroscope_noise_density: 0.001
      gyroscope_random_walk: 0.00002
      update_rate: 100.0  # Hz

gps:
  - gps:
      update_rate: 10.0  # Hz
      horizontal_accuracy: 2.5  # meters (NEO-8M spec)
      altitude_accuracy: 4.0  # meters

---

## 🏗️ THREADED RECORDER ARCHITECTURE

### The Architecture: Decoupled Producer-Consumer

```
┌────────────────────────────────────────────────────────────┐
│                  PRODUCER THREADS                          │
│                (Fast, Non-blocking)                        │
└────────────┬───────────────┬──────────────┬────────────────┘
             │               │              │
             ▼               ▼              ▼
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │  Camera    │  │    IMU     │  │    GPS     │
    │  Thread    │  │  Thread    │  │  Thread    │
    │            │  │            │  │            │
    │ @30fps     │  │ @100Hz     │  │ @10Hz      │
    └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
          │               │                │
          │ (Push)        │ (Push)         │ (Push)
          ▼               ▼                ▼
    ┌─────────────────────────────────────────────┐
    │            THREAD-SAFE QUEUES               │
    │   Queue(maxsize=100)  Queue(1000)  Queue(100)
    └─────┬──────────────┬──────────────┬─────────┘
          │              │              │
          │ (Pull)       │ (Pull)       │ (Pull)
          ▼              ▼              ▼
    ┌─────────────────────────────────────────────┐
    │            CONSUMER THREAD                  │
    │          (Disk Writer Worker)               │
    │  - Saves images to cam0/data/*.png          │
    │  - Appends to cam0/data.csv                 │
    │  - Appends to imu0/data.csv                 │
    │  - Appends to gps0/data.csv                 │
    └─────────────────────────────────────────────┘
                         │
                         ▼
                  [EuRoC Dataset]
```

### Critical Design Principles

#### 1. Monotonic Timestamps (NOT Wall Clock!)
```python
import time

# ❌ WRONG: time.time() (wall clock - can jump with NTP sync)
timestamp = time.time()

# ✅ CORRECT: time.monotonic_ns() (monotonic - always increases)
timestamp_ns = time.monotonic_ns()
```

**Why This Matters:**
- `time.time()` can jump backward/forward when system time syncs (NTP)
- VIO/SLAM algorithms compute **velocity** from pose differences (Δt must be consistent)
- If timestamps jump, velocity estimates explode → tracking failure

#### 2. Decoupled I/O (Never Block Capture Loop)
```python
# ❌ WRONG: Writing inside capture loop (blocks at ~100ms per save)
while True:
    frame = camera.read()
    cv2.imwrite(f'image_{timestamp}.png', frame)  # <-- BLOCKS FOR 100ms!
    # Result: Dropped frames, inconsistent timestamps

# ✅ CORRECT: Push to queue, separate writer thread
while True:
    frame = camera.read()
    timestamp = time.monotonic_ns()
    queue.put((timestamp, frame), block=False)  # <-- Non-blocking
    # Writer thread handles slow I/O asynchronously
```

#### 3. Dummy Sensors (Laptop Mode)
```python
class DummyIMU:
    """Generates synthetic IMU data for laptop testing"""
    def read(self):
        return {
            'timestamp_ns': time.monotonic_ns(),
            'accel': [0.0, 0.0, 9.81],  # Gravity vector (stationary)
            'gyro': [0.0, 0.0, 0.0]     # No rotation
        }

class DummyGPS:
    """Generates synthetic GPS data for laptop testing"""
    def read(self):
        return {
            'timestamp_ns': time.monotonic_ns(),
            'latitude': 37.4219,  # Fixed location (Google HQ)
            'longitude': -122.0840,
            'altitude': 15.0,
            'fix_quality': 0  # No fix (indoors)
        }
```

**Purpose:** Test pipeline architecture on laptop **without real hardware**.

---

## 💾 PYTHON IMPLEMENTATION

### DataRecorder Class (src/utils/data_recorder.py)

```python
"""
EuRoC MAV Dataset Recorder for Project-Cortex

Records synchronized sensor data (camera, IMU, GPS) in EuRoC format.
Supports both real hardware (RPi 5) and dummy sensors (laptop).
"""

import os
import time
import threading
import queue
import csv
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass
import cv2


@dataclass
class SensorFrame:
    """Single sensor reading with monotonic timestamp"""
    timestamp_ns: int
    data: any  # Frame, IMU dict, GPS dict, etc.


class DataRecorder:
    """
    Multi-threaded sensor data recorder with EuRoC MAV format output.
    
    Architecture:
    - 3 Producer threads (camera, IMU, GPS)
    - 1 Consumer thread (disk writer)
    - Thread-safe queues for decoupling
    """
    
    def __init__(
        self,
        output_dir: str,
        camera_source: any,  # cv2.VideoCapture or DummyCamera
        imu_source: any,     # BNO055 or DummyIMU
        gps_source: any,     # NEO8M or DummyGPS
        use_dummy_sensors: bool = False
    ):
        self.output_dir = Path(output_dir)
        self.camera = camera_source
        self.imu = imu_source
        self.gps = gps_source
        self.use_dummy = use_dummy_sensors
        
        # Thread-safe queues (maxsize prevents memory overflow)
        self.cam_queue = queue.Queue(maxsize=100)
        self.imu_queue = queue.Queue(maxsize=1000)  # Higher freq
        self.gps_queue = queue.Queue(maxsize=100)
        
        # Control flags
        self.recording = False
        self.threads = []
        
        # Create directory structure
        self._create_directories()
        
    def _create_directories(self):
        """Create EuRoC dataset folder structure"""
        (self.output_dir / 'cam0' / 'data').mkdir(parents=True, exist_ok=True)
        (self.output_dir / 'imu0').mkdir(parents=True, exist_ok=True)
        (self.output_dir / 'gps0').mkdir(parents=True, exist_ok=True)
        
    def _camera_thread(self):
        """
        Camera capture thread (30fps target).
        Uses monotonic clock for consistent timestamps.
        """
        csv_path = self.output_dir / 'cam0' / 'data.csv'
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['#timestamp [ns]', 'filename'])
            
            while self.recording:
                ret, frame = self.camera.read()
                if not ret:
                    continue
                    
                timestamp_ns = time.monotonic_ns()
                
                # Non-blocking push to queue
                try:
                    self.cam_queue.put_nowait(SensorFrame(timestamp_ns, frame))
                except queue.Full:
                    print(f"[WARN] Camera queue full, dropping frame")
                
                time.sleep(1/30)  # 30fps
                
    def _imu_thread(self):
        """
        IMU capture thread (100Hz target).
        BNO055 outputs quaternion + linear acceleration.
        """
        csv_path = self.output_dir / 'imu0' / 'data.csv'
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                '#timestamp [ns]',
                'omega_x [rad/s]', 'omega_y [rad/s]', 'omega_z [rad/s]',
                'alpha_x [m/s^2]', 'alpha_y [m/s^2]', 'alpha_z [m/s^2]'
            ])
            
            while self.recording:
                if self.use_dummy:
                    imu_data = {
                        'gyro': [0.0, 0.0, 0.0],
                        'accel': [0.0, 0.0, 9.81]
                    }
                else:
                    imu_data = self.imu.read()  # BNO055 API
                
                timestamp_ns = time.monotonic_ns()
                
                try:
                    self.imu_queue.put_nowait(SensorFrame(timestamp_ns, imu_data))
                except queue.Full:
                    print(f"[WARN] IMU queue full")
                
                time.sleep(1/100)  # 100Hz
                
    def _gps_thread(self):
        """
        GPS capture thread (10Hz target).
        NEO-8M outputs NMEA sentences @ 1Hz-10Hz.
        """
        csv_path = self.output_dir / 'gps0' / 'data.csv'
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                '#timestamp [ns]',
                'latitude [deg]', 'longitude [deg]', 'altitude [m]',
                'fix_quality', 'satellites', 'hdop'
            ])
            
            while self.recording:
                if self.use_dummy:
                    gps_data = {
                        'lat': 37.4219,
                        'lon': -122.0840,
                        'alt': 15.0,
                        'fix': 0,
                        'sats': 0,
                        'hdop': 99.9
                    }
                else:
                    gps_data = self.gps.read()  # NEO-8M API
                
                timestamp_ns = time.monotonic_ns()
                
                try:
                    self.gps_queue.put_nowait(SensorFrame(timestamp_ns, gps_data))
                except queue.Full:
                    print(f"[WARN] GPS queue full")
                
                time.sleep(1/10)  # 10Hz
                
    def _writer_thread(self):
        """
        Consumer thread: Drains queues and writes to disk.
        Handles slow I/O without blocking producers.
        """
        cam_csv = open(self.output_dir / 'cam0' / 'data.csv', 'a', newline='')
        imu_csv = open(self.output_dir / 'imu0' / 'data.csv', 'a', newline='')
        gps_csv = open(self.output_dir / 'gps0' / 'data.csv', 'a', newline='')
        
        cam_writer = csv.writer(cam_csv)
        imu_writer = csv.writer(imu_csv)
        gps_writer = csv.writer(gps_csv)
        
        while self.recording or not (self.cam_queue.empty() and 
                                      self.imu_queue.empty() and 
                                      self.gps_queue.empty()):
            # Write camera frames
            while not self.cam_queue.empty():
                frame_data = self.cam_queue.get()
                filename = f"{frame_data.timestamp_ns}.png"
                cv2.imwrite(
                    str(self.output_dir / 'cam0' / 'data' / filename),
                    frame_data.data
                )
                cam_writer.writerow([frame_data.timestamp_ns, filename])
                
            # Write IMU data
            while not self.imu_queue.empty():
                imu_data = self.imu_queue.get()
                imu_writer.writerow([
                    imu_data.timestamp_ns,
                    *imu_data.data['gyro'],
                    *imu_data.data['accel']
                ])
                
            # Write GPS data
            while not self.gps_queue.empty():
                gps_data = self.gps_queue.get()
                gps_writer.writerow([
                    gps_data.timestamp_ns,
                    gps_data.data['lat'],
                    gps_data.data['lon'],
                    gps_data.data['alt'],
                    gps_data.data['fix'],
                    gps_data.data['sats'],
                    gps_data.data['hdop']
                ])
            
            time.sleep(0.01)  # 100Hz drain rate
        
        cam_csv.close()
        imu_csv.close()
        gps_csv.close()
        
    def start(self):
        """Start all threads"""
        self.recording = True
        
        self.threads = [
            threading.Thread(target=self._camera_thread, name="CameraThread"),
            threading.Thread(target=self._imu_thread, name="IMUThread"),
            threading.Thread(target=self._gps_thread, name="GPSThread"),
            threading.Thread(target=self._writer_thread, name="WriterThread")
        ]
        
        for t in self.threads:
            t.daemon = True
            t.start()
            
        print(f"[INFO] Recording to {self.output_dir}")
        
    def stop(self):
        """Stop all threads gracefully"""
        self.recording = False
        
        for t in self.threads:
            t.join(timeout=5.0)
            
        print(f"[INFO] Recording stopped")


# Usage Example (Laptop Mode)
if __name__ == "__main__":
    import cv2
    
    recorder = DataRecorder(
        output_dir="data/test_session_001",
        camera_source=cv2.VideoCapture(0),  # Laptop webcam
        imu_source=None,  # Dummy IMU
        gps_source=None,  # Dummy GPS
        use_dummy_sensors=True
    )
    
    recorder.start()
    time.sleep(30)  # Record for 30 seconds
    recorder.stop()
```

---

## 🗂️ REVISED DATABASE SCHEMA

### Problem: Coordinate System Confusion

**Original schema** mixed local (VIO meters) and global (GPS degrees) in the same columns.

**Peer Review Feedback:** "Separate Local from Global to prevent logic errors."

### Solution: Strict Coordinate System Separation

```sql
-- ============================================================================
-- COORDINATE SYSTEMS
-- ============================================================================

-- System A: LOCAL (VIO Map Frame)
--   Origin: Where device started
--   Units: Meters
--   Axes: OpenCV convention (X=right, Y=down, Z=forward)
--   Use: Indoor precision navigation

-- System B: GLOBAL (Geodetic Frame)
--   Origin: WGS84 datum
--   Units: Degrees (lat/lon), Meters (alt)
--   Use: Outdoor navigation, Google Maps integration

-- System C: HYBRID (Map Anchors)
--   Links local and global via transformation
--   "At VIO position (x,y,z), GPS was (lat,lon)"


-- ============================================================================
-- TABLE: spatial_objects (Remembered Objects)
-- ============================================================================

CREATE TABLE spatial_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- User-friendly identification
    object_name TEXT NOT NULL,           -- "my wallet", "Starbucks entrance"
    object_class TEXT NOT NULL,          -- YOLO class ("wallet", "door", etc.)
    
    -- LOCAL COORDINATE SYSTEM (VIO/SLAM)
    vio_position_json TEXT,              -- JSON: {"x": 1.2, "y": 0.5, "z": -2.0}
    vio_map_id TEXT,                     -- Which VIO map? "home_2025-12-22"
    vio_keyframe_id INTEGER,             -- Anchor keyframe in VIO map
    
    -- GLOBAL COORDINATE SYSTEM (GPS)
    gps_position_json TEXT,              -- JSON: {"lat": 37.4, "lon": -122.0, "alt": 15}
    gps_address TEXT,                    -- "Starbucks, 123 Main St, ..." (geocoded)
    
    -- QUALITY & METADATA
    quality_flags INTEGER DEFAULT 0,     -- Bitmask (bit 0: VIO valid, bit 1: GPS valid)
    confidence REAL DEFAULT 1.0,         -- 0.0-1.0 (YOLO detection confidence)
    timestamp_ns INTEGER NOT NULL,       -- Monotonic nanoseconds
    created_at TEXT NOT NULL,            -- ISO 8601 human-readable
    
    -- CONSTRAINTS
    FOREIGN KEY(vio_map_id) REFERENCES slam_maps(map_id),
    CHECK(vio_position_json IS NOT NULL OR gps_position_json IS NOT NULL)
);

-- Quality flags bitmask:
-- bit 0 (0x01): VIO position valid
-- bit 1 (0x02): GPS position valid
-- bit 2 (0x04): Object actively tracked (not lost)
-- bit 3 (0x08): High confidence (>0.8)


-- ============================================================================
-- TABLE: slam_maps (VIO/SLAM Maps)
-- ============================================================================

CREATE TABLE slam_maps (
    map_id TEXT PRIMARY KEY,             -- "home_2025-12-22"
    map_file_path TEXT NOT NULL,         -- "maps/home_map.yml" (EuRoC format)
    
    -- MAP METADATA
    creation_time_ns INTEGER NOT NULL,   -- Monotonic timestamp
    creation_time TEXT NOT NULL,         -- ISO 8601
    last_used_ns INTEGER,                -- When last loaded
    num_keyframes INTEGER DEFAULT 0,     -- Map size
    num_landmarks INTEGER DEFAULT 0,     -- 3D points
    
    -- ENVIRONMENT
    location_type TEXT CHECK(location_type IN ('indoor', 'outdoor', 'hybrid')),
    
    -- MAP ORIGIN (If GPS available when map created)
    origin_gps_json TEXT,                -- JSON: {"lat": 37.4, "lon": -122.0}
    origin_address TEXT                  -- "Home, 456 Elm St"
);


-- ============================================================================
-- TABLE: map_anchors (Local ↔ Global Transformations)
-- ============================================================================

CREATE TABLE map_anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- LINK TO MAP
    vio_map_id TEXT NOT NULL,
    
    -- VIO POSITION (Local)
    vio_position_json TEXT NOT NULL,     -- JSON: {"x": 1.2, "y": 0.5, "z": -2.0}
    
    -- GPS POSITION (Global)
    gps_position_json TEXT NOT NULL,     -- JSON: {"lat": 37.4, "lon": -122.0}
    
    -- TIMESTAMP
    timestamp_ns INTEGER NOT NULL,
    
    -- QUALITY
    gps_accuracy_meters REAL,            -- GPS HDOP
    vio_confidence REAL,                 -- Tracking quality
    
    FOREIGN KEY(vio_map_id) REFERENCES slam_maps(map_id)
);

-- Purpose: Align VIO and GPS coordinate systems
-- When VIO says (x,y,z), GPS says (lat,lon) → Store anchor
-- Later: Transform VIO positions to GPS for Google Maps routing


-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- Store object (INDOOR - VIO only)
INSERT INTO spatial_objects (
    object_name, object_class,
    vio_position_json, vio_map_id, vio_keyframe_id,
    quality_flags, confidence,
    timestamp_ns, created_at
) VALUES (
    'my wallet', 'wallet',
    '{"x": 1.2, "y": 0.5, "z": -2.0}', 'home_2025-12-22', 42,
    1, 0.95,  -- bit 0 set (VIO valid)
    1735000000000000000, '2025-12-22T10:30:00Z'
);

-- Store object (OUTDOOR - GPS only)
INSERT INTO spatial_objects (
    object_name, object_class,
    gps_position_json, gps_address,
    quality_flags, confidence,
    timestamp_ns, created_at
) VALUES (
    'Starbucks', 'building',
    '{"lat": 37.4219, "lon": -122.0840, "alt": 15.0}',
    'Starbucks, 123 Main St, Mountain View, CA',
    2, 1.0,  -- bit 1 set (GPS valid)
    1735000100000000000, '2025-12-22T10:32:00Z'
);

-- Find object by name (check both coordinate systems)
SELECT 
    object_name,
    vio_position_json,
    gps_position_json,
    quality_flags,
    CASE 
        WHEN quality_flags & 1 THEN 'VIO'
        WHEN quality_flags & 2 THEN 'GPS'
        ELSE 'NONE'
    END AS coord_system
FROM spatial_objects
WHERE object_name = 'my wallet';

-- List all indoor objects (VIO-based)
SELECT object_name, vio_position_json, vio_map_id
FROM spatial_objects
WHERE quality_flags & 1 = 1;  -- bit 0 set

-- List all outdoor objects (GPS-based)
SELECT object_name, gps_position_json, gps_address
FROM spatial_objects
WHERE quality_flags & 2 = 2;  -- bit 1 set
```

---

## 🎯 DEVELOPMENT WORKFLOW

### Phase 1: Laptop Pipeline Development (Week 1)
**Goal:** Build recording infrastructure **without real hardware**.

**Tasks:**
1. Implement `DataRecorder` class with dummy sensors
2. Record 5-minute laptop webcam session → EuRoC format
3. Validate CSV timestamps (monotonic, no jumps)
4. Test queue overflow handling (drop frames gracefully)

**Success Criteria:**
- ✅ EuRoC dataset structure created
- ✅ CSV files parseable by `evo` library
- ✅ No timestamp inconsistencies

---

### Phase 2: RPi Hardware Integration (Week 2)
**Goal:** Replace dummy sensors with real hardware.

**Tasks:**
1. Wire BNO055 (I2C) and NEO-8M (UART) to RPi 5
2. Test BNO055 quaternion output @ 100Hz
3. Test NEO-8M NMEA parsing @ 10Hz
4. Record 5-minute indoor walk → EuRoC format
5. Record 5-minute outdoor walk → EuRoC format

**Success Criteria:**
- ✅ IMU data shows realistic motion (not [0,0,9.81] static)
- ✅ GPS data shows position changing outdoors
- ✅ Camera fisheye distortion visible in images

---

### Phase 3: Algorithm Development (Laptop) (Week 3-5)
**Goal:** Develop VIO algorithms using **recorded RPi data**.

**Tasks:**
1. Load EuRoC dataset on laptop using `evo` library
2. Implement fisheye undistortion (using calibrated K, D)
3. Implement feature tracking (FAST + KLT)
4. Implement EKF sensor fusion (IMU + VIO)
5. Visualize trajectory vs. GPS groundtruth

**Success Criteria:**
- ✅ Algorithm processes EuRoC data correctly
- ✅ Trajectory matches GPS groundtruth (±5m outdoor)
- ✅ No code changes when switching datasets

---

### Phase 4: VIO/SLAM Server Processing (Laptop) (Week 6)
**Goal:** Process recorded EuRoC datasets on laptop server for map building.

**Tasks:**
1. Upload EuRoC dataset from RPi to laptop (HTTP POST or SCP)
2. Run VIO/SLAM algorithm on laptop (OpenVINS, ORB-SLAM3, etc.)
3. Generate map keyframes and GPS anchors
4. Return processed map to RPi via REST API
5. RPi stores map in SQLite (slam_maps, map_anchors tables)

**Success Criteria:**
- ✅ 5-minute session processes in <1 minute on laptop
- ✅ Map data returned to RPi successfully
- ✅ RPi can query map for spatial memory

**Note:** VIO/SLAM is NOT real-time on RPi. It is post-processing only.

---

## 📚 REFERENCES

### Research Papers
1. **EuRoC MAV Dataset** - ETH Zurich
   - https://projects.asl.ethz.ch/datasets/doku.php?id=kmavvisualinertialdatasets
   - Industry standard format for VIO/SLAM benchmarking

2. **Kalibr Calibration Toolbox** - ETH ASL
   - https://github.com/ethz-asl/kalibr
   - Camera-IMU calibration, EuRoC bag creator

3. **evo Trajectory Evaluation** - Michael Grupp
   - https://github.com/michaelgrupp/evo
   - Python library for reading EuRoC datasets

### Python Libraries
- **evo**: `pip install evo` - Dataset loading and trajectory evaluation
- **opencv-python**: `pip install opencv-python` - Image I/O
- **pyyaml**: `pip install pyyaml` - sensor.yaml parsing

---

**Document Version:** 1.0  
**Last Updated:** 2025-12-22  
**Status:** ✅ PEER REVIEWED & REVISED  
**Next Step:** Implement `DataRecorder` class on laptop
