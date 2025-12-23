# 🗺️ SLAM/VIO Navigation System Research & Planning
**Project-Cortex v2.0 - Layer 3 (Guide) Enhancement**  
**Research Date:** December 21, 2025  
**Status:** 🔬 Research Phase (No Implementation Yet)

---

## 📋 EXECUTIVE SUMMARY

This document outlines a comprehensive plan to enhance **Layer 3 (The Guide)** with a SLAM-like navigation system integrating:
- **VIO (Visual-Inertial Odometry)** for ego-motion tracking
- **IMU (9-DOF Inertial Measurement Unit)** for orientation and acceleration
- **GPS Module** for outdoor absolute positioning
- **Loop Closure** for drift correction

**Goal:** Enable Project-Cortex to navigate indoor/outdoor environments with spatial memory, building a persistent map of the world while localizing the user in real-time.

---

## 🎯 PROBLEM STATEMENT

### Current Layer 3 Limitations:
1. **No Spatial Memory:** System cannot remember physical locations beyond detected objects
2. **No Ego-Motion Tracking:** Cannot estimate user's movement direction/speed
3. **Outdoor Navigation Gap:** GPS integration pending
4. **No Map Building:** Cannot create a persistent 3D map of environments
5. **Drift in Dead Reckoning:** Pure IMU integration would accumulate error over time

### Proposed Solution:
A **hybrid VIO + GPS + IMU fusion system** that:
- Uses **IMX415 camera** for visual feature tracking
- Integrates **9-DOF IMU** for inertial measurements (accel + gyro + magnetometer)
- Fuses **GPS** for outdoor absolute positioning
- Implements **loop closure** to correct accumulated drift
- Builds a **persistent occupancy grid map** for navigation

---

## 🔬 RESEARCH FINDINGS

### 1. SLAM/VIO Framework Comparison

| Framework | Type | Sensors | Raspberry Pi 5 | Pros | Cons | Recommendation |
|-----------|------|---------|----------------|------|------|----------------|
| **OpenVINS** | VIO (Filter-based) | Mono/Stereo + IMU | ⚠️ Requires ROS | • Open-source (GPL)<br>• 1004 code snippets<br>• Excellent docs<br>• Allan variance calibration | • ROS dependency<br>• C++ only (no Python)<br>• High computational cost | ⭐ **BEST** if ROS is acceptable |
| **VINS-Fusion** | VIO (Optimization) | Mono/Stereo + IMU | ⚠️ Requires ROS | • Stereo + mono support<br>• Loop closure<br>• GPU acceleration option | • ROS dependency<br>• C++ only<br>• Complex tuning | ⭐ **Runner-up** (more features) |
| **RTAB-Map** | RGB-D SLAM | RGB-D/Stereo + IMU | ✅ ROS optional | • **No depth camera needed** (works with stereo)<br>• Loop closure<br>• Memory-efficient<br>• Graph optimization | • Requires stereo camera (we have mono)<br>• Lower accuracy vs. VIO | ❌ **Not suitable** (requires stereo) |
| **ORB-SLAM3** | Visual SLAM | Mono/Stereo/RGB-D | ✅ No ROS | • State-of-the-art<br>• Multi-map system<br>• Loop closure | • C++ only<br>• No official IMU fusion<br>• High compute | ❌ **Too heavy** for RPi 5 |

**Winner:** **OpenVINS** (if we adopt ROS) or **Custom Lightweight VIO** (if staying ROS-free)

---

### 2. Hardware Requirements (Updated: User's Confirmed Hardware)

**✅ USER'S ACTUAL HARDWARE:**
- **Camera:** Raspberry Pi Camera Module 3 Wide (120° FOV)
- **IMU:** Adafruit BNO055 (9-DOF with built-in fusion)
- **GPS:** u-blox NEO-8M (UART)

---

#### A. IMU Sensor (9-DOF: Accelerometer + Gyroscope + Magnetometer)

| Sensor | Interface | Python Support | Accuracy | Cost (Est.) | Adafruit CircuitPython | Recommendation |
|--------|-----------|----------------|----------|-------------|------------------------|----------------|
| **BNO055** | I2C/UART | ✅ Excellent (`adafruit_bno055`) | **Best** (built-in sensor fusion) | ~$30 | ✅ 692 weekly downloads | ⭐⭐⭐ **BEST CHOICE** |
| **ICM-20948** | I2C/SPI | ✅ Good (`adafruit_icm20x`) | High (9-axis) | ~$15 | ✅ 454 weekly downloads | ⭐⭐ **Budget alternative** |
| **LSM9DS1** | I2C/SPI | ✅ Good (`adafruit_lsm9ds1`) | Moderate | ~$10 | ✅ 493 weekly downloads | ⭐ **Cheapest option** |
| **MPU-9250** | I2C/SPI | ⚠️ Limited (deprecated chip) | Moderate | ~$8 | ❌ No official driver | ❌ **Not recommended** |

**Winner:** **Adafruit BNO055** (built-in quaternion fusion offloads CPU, I2C plug-and-play)

**Technical Specs (BNO055):**
- **Built-in ARM Cortex-M0** sensor fusion processor (offloads RPi 5 CPU!)
- **Absolute orientation:** Quaternion, Euler angles, rotation matrix
- **Calibration:** Self-calibrating (saves to EEPROM)
- **Update Rate:** 100Hz (IMU data), 100Hz (absolute orientation)
- **Interface:** I2C (0x28/0x29) or UART
- **Power:** 3.3V, 12.3mA (typical)
- **Python Library:** `adafruit-circuitpython-bno055` (692 weekly downloads)

---

#### B. GPS Module (Outdoor Absolute Positioning)

| Module | Chipset | Accuracy | Update Rate | Power | Cost (Est.) | Recommendation |
|--------|---------|----------|-------------|-------|-------------|----------------|
| **NEO-9N** | u-blox 9 | 2.0m (standalone) | 25Hz | 23mA | ~$40 | ⭐⭐⭐ **BEST** (newest) |
| **NEO-8M** | u-blox 8 | 2.5m | 10Hz | 27mA | ~$20 | ⭐⭐ **Good balance** |
| **NEO-7M** | u-blox 7 | 2.5m | 10Hz | 45mA | ~$12 | ⭐ **Budget** |
| **NEO-6M** | u-blox 6 | 2.5m | 5Hz | 45mA | ~$8 | ❌ **Outdated** |

**Winner:** **NEO-8M** (balance of cost/performance) or **NEO-9N** (if budget allows)

**Technical Specs (NEO-8M):**
- **Horizontal Accuracy:** 2.5m CEP
- **Cold Start:** 26s, Hot Start: 1s
- **Update Rate:** 10Hz (configurable to 18Hz)
- **Interface:** UART (9600 baud default), I2C optional
- **Output:** NMEA 0183 protocol
- **Python Library:** `adafruit-circuitpython-gps` (939 weekly downloads)
- **Power:** 3.3V, 27mA @ continuous tracking

---

#### C. Raspberry Pi Camera Module 3 Wide (120° FOV)

**✅ USER'S ACTUAL CAMERA:**
- **Sensor:** Sony IMX708 (12MP)
- **Field of View:** 102° horizontal / 67° vertical (marketed as "120° diagonal FOV")
- **Interface:** CSI-2 MIPI (15-pin ribbon cable to RPi 5)
- **Supported Resolutions:**
  - **2304x1296 @ 56fps** (optimal balance)
  - **1536x864 @ 120fps** (high speed, lower res)
  - **2304x1296 @ 30fps with HDR**
  - Still photos: 11.9MP

**Why Wide-Angle is EXCELLENT for VIO:**
- ✅ **Larger FOV = More Features:** Tracks 2-3x more features vs. standard lens
- ✅ **Better Motion Estimation:** Wide FOV captures more scene context
- ✅ **Reduced Motion Blur:** Features stay in frame longer during fast motion
- ⚠️ **Challenge: Fisheye Distortion** (see calibration section below)

**SLAM/VIO Recommendations:**
- **Optimal Resolution:** **1536x864 @ 120fps** (lowest latency, best for tracking)
- **Alternative:** **2304x1296 @ 56fps** (higher quality, still real-time)
- **Grayscale Mode:** Extract from RGB for VIO (YOLO uses RGB)
- **Synchronized Capture:** RPi 5 supports software camera sync (no hardware needed)
- **Frame Timing:** `rpicam-apps` provides precise timestamps for IMU-camera fusion

**Configuration Tweaks for High Frame Rate (from Raspberry Pi docs):**
```bash
# In /boot/firmware/config.txt
force_turbo=1  # Prevent CPU throttling
dtoverlay=imx708  # Enable Camera Module 3 (wide)

# rpicam-apps settings for VIO (recommended)
rpicam-vid --width 1536 --height 864 --framerate 120 --denoise cdn_off --nopreview --level 4.2

# Alternative: Higher resolution for better feature quality
rpicam-vid --width 2304 --height 1296 --framerate 56 --denoise cdn_off --nopreview --level 4.2
```

**CRITICAL: Fisheye Distortion Calibration Required!**
The wide-angle lens introduces **significant barrel distortion** that MUST be corrected before VIO:
- **Distortion Model:** Equidistant (fisheye) projection (NOT standard radtan)
- **Calibration Method:** OpenCV `fisheye` module or Kalibr with `pinhole-equi` model
- **Distortion Parameters:** 4 coefficients (k1, k2, k3, k4) for fisheye model
- **Impact if Uncorrected:** Feature tracking errors up to 50% in corners, VIO drift

---

### 3. VIO Algorithm Architecture

#### Option A: OpenVINS (ROS-based, C++)
**Architecture:**
- **Frontend:** Feature detection (FAST/ORB) + KLT tracker
- **Backend:** Multi-State Constraint Kalman Filter (MSCKF)
- **IMU Preintegration:** Between visual measurements
- **Loop Closure:** Optional (BoW-based)

**Pros:**
- ✅ Battle-tested on real robots (DARPA SubT Challenge)
- ✅ Extensive documentation (1004 code snippets)
- ✅ Allan variance IMU calibration tools
- ✅ Kalibr integration for camera-IMU extrinsic calibration

**Cons:**
- ❌ **Requires ROS2** (Humble/Jazzy)
- ❌ C++ only (Python bindings would need custom work)
- ❌ ~500-800ms latency on RPi 5 (estimated)

**Integration Strategy:**
1. Install ROS2 Humble on Raspberry Pi OS
2. Create ROS2 node publishing IMX415 frames + BNO055 IMU data
3. Launch OpenVINS node subscribing to these topics
4. Publish odometry to `/odom` topic
5. Bridge ROS2 → Python via `rclpy` for Layer 3 integration

---

#### Option B: Custom Lightweight VIO (Python, ROS-free)
**Architecture:**
- **Feature Tracking:** OpenCV optical flow (Lucas-Kanade)
- **IMU Fusion:** Madgwick/Mahony filter (BNO055 handles this internally)
- **Scale Estimation:** Dead reckoning from IMU velocity integration
- **Loop Closure:** Visual bag-of-words (ORBSLAM2 vocabulary)

**Pros:**
- ✅ **No ROS dependency** (pure Python)
- ✅ Integrates directly with existing `cortex_gui.py`
- ✅ Lightweight (200-300ms latency target on RPi 5)
- ✅ Can leverage BNO055's built-in quaternion fusion

**Cons:**
- ❌ Lower accuracy vs. OpenVINS (no MSCKF, simple fusion)
- ❌ More manual tuning required
- ❌ No loop closure (unless implemented)

**Integration Strategy:**
1. Create `layer3_guide/vio/` module
2. Extract grayscale from IMX415 frames (from existing YOLO pipeline)
3. Track FAST features with OpenCV KLT tracker
4. Read BNO055 quaternion + linear acceleration via I2C
5. Fuse visual velocity + IMU velocity → ego-motion estimate
6. Publish pose to Layer 3 spatial audio + memory system

---

### 4. IMU-Camera Calibration Requirements

**CRITICAL: Wide-Angle Fisheye Calibration Required First!**

#### A. **Fisheye Camera Intrinsic Calibration** (NEW - Required for Wide-Angle Lens)

**⚠️ HIGHEST PRIORITY:** The Raspberry Pi Camera Module 3 Wide uses a **fisheye lens** (102° FOV) that introduces significant barrel distortion. This MUST be calibrated BEFORE VIO will work accurately.

**Fisheye vs. Standard Lens:**
| Property | Standard Lens (Pinhole) | Wide-Angle Fisheye (Your Camera) |
|----------|------------------------|----------------------------------|
| **Distortion Model** | Radial-tangential (radtan) | Equidistant (fisheye) |
| **Distortion Parameters** | 5 coefficients (k1, k2, p1, p2, k3) | 4 coefficients (k1, k2, k3, k4) |
| **OpenCV Module** | `cv2.calibrateCamera()` | `cv2.fisheye.calibrate()` |
| **Kalibr Model** | `pinhole-radtan` | `pinhole-equi` |
| **Distortion Severity** | Low (corners slightly curved) | **High (straight lines heavily curved)** |

**Fisheye Distortion Formula (Equidistant Model):**
```
θ_d = θ * (1 + k1*θ² + k2*θ⁴ + k3*θ⁶ + k4*θ⁸)
x_distorted = (x_n / r) * θ_d
y_distorted = (y_n / r) * θ_d

where:
  r = sqrt(x_n² + y_n²)  # Radial distance from center
  θ = atan(r)             # Angle from optical axis
  (x_n, y_n) = normalized coordinates
```

**Calibration Procedure (OpenCV Fisheye Method):**
1. **Print Checkerboard Pattern:** 9x6 or 10x7 squares, ~25mm square size
2. **Capture 20-30 Images:** Move checkerboard to cover entire FOV (especially corners!)
3. **Run OpenCV Fisheye Calibration:**
   ```python
   import cv2
   import numpy as np
   
   # Detect checkerboard corners in all images
   objpoints = []  # 3D points in real world space
   imgpoints = []  # 2D points in image plane
   
   for image_file in calibration_images:
       img = cv2.imread(image_file)
       gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
       ret, corners = cv2.findChessboardCorners(gray, (9, 6), None)
       if ret:
           objpoints.append(objp)  # 3D coordinates
           imgpoints.append(corners)
   
   # CRITICAL: Use fisheye calibration (NOT standard calibrateCamera!)
   K = np.zeros((3, 3))  # Camera intrinsic matrix
   D = np.zeros((4, 1))  # Fisheye distortion coefficients
   rvecs = []  # Rotation vectors
   tvecs = []  # Translation vectors
   
   calibration_flags = (cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC +
                        cv2.fisheye.CALIB_CHECK_COND +
                        cv2.fisheye.CALIB_FIX_SKEW)
   
   rms, K, D, rvecs, tvecs = cv2.fisheye.calibrate(
       objpoints, imgpoints, gray.shape[::-1],
       K, D, rvecs, tvecs, calibration_flags,
       (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)
   )
   
   print(f"RMS Reprojection Error: {rms}")
   print(f"Camera Matrix K:\n{K}")
   print(f"Distortion Coefficients D:\n{D}")
   
   # Save calibration to YAML
   np.save('camera_intrinsics.npy', {'K': K, 'D': D})
   ```

4. **Undistort Images for VIO:**
   ```python
   # Load calibration
   calib = np.load('camera_intrinsics.npy', allow_pickle=True).item()
   K = calib['K']
   D = calib['D']
   
   # Undistort image (fast method using precomputed maps)
   h, w = img.shape[:2]
   new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
       K, D, (w, h), np.eye(3), balance=0.0
   )
   map1, map2 = cv2.fisheye.initUndistortRectifyMap(
       K, D, np.eye(3), new_K, (w, h), cv2.CV_16SC2
   )
   undistorted_img = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
   ```

**Expected Results:**
- **RMS Error:** <0.5 pixels (good), <0.3 pixels (excellent)
- **Focal Length (fx, fy):** ~1400-1600 pixels (for IMX708 @ 2304x1296)
- **Principal Point (cx, cy):** Close to image center (1152, 648)
- **Distortion k1:** Large negative value (~-0.2 to -0.4) for barrel distortion

**Alternative: Kalibr (ROS-based, more automated):**
```bash
# Use pinhole-equi model for fisheye lenses
kalibr_calibrate_cameras \
  --target april_6x6.yaml \
  --bag calibration_data.bag \
  --models pinhole-equi \
  --topics /camera/image_raw
```

**⚠️ WARNING:** Skipping fisheye calibration will cause:
- Feature tracking to fail in corners (50% of FOV unusable)
- VIO scale estimation errors (2-5x position drift)
- Loop closure failures (distorted features don't match)

---

#### B. IMU Noise Calibration (Allan Variance Method)
- **Purpose:** Measure gyro/accel noise, random walk, bias stability
- **Data Collection:** 20 hours of stationary IMU data
- **Tool:** `allan_variance_ros` (if using ROS) or `imu_utils` (ROS-free)
- **Output:** YAML file with noise parameters:
  ```yaml
  imu:
    sigma_a_cdot: 0.0001  # Accelerometer noise density
    sigma_g_cdot: 0.00001  # Gyroscope noise density
    sigma_a_cdot_cdot: 0.00001  # Accel random walk
    sigma_g_cdot_cdot: 0.000001  # Gyro random walk
  ```

#### C. Camera-IMU Extrinsic Calibration (Spatial Transform)
- **Purpose:** Determine 6-DOF transform (rotation + translation) from IMU to camera frame
- **Tool:** Kalibr (ROS-based) or `camera_imu_calib` (Python)
- **Data Collection:** Checkerboard pattern video while moving IMU+camera rig
- **Output:** 4x4 transformation matrix T_cam_imu

**Note:** BNO055 has built-in sensor fusion, so we may **skip Allan variance** and use manufacturer calibration. **Fisheye camera intrinsic calibration is mandatory. Camera-IMU extrinsic calibration is also required.**

---

### 5. GPS Integration Strategy

**Outdoor Navigation Enhancement:**

#### A. Sensor Fusion (GPS + VIO + IMU)
**Problem:** GPS has 2.5m accuracy, VIO drifts over time, IMU drifts rapidly  
**Solution:** Extended Kalman Filter (EKF) fusion

**Fusion Architecture:**
```
State Vector: [x, y, z, vx, vy, vz, qw, qx, qy, qz]
           (position, velocity, orientation quaternion)

Prediction (IMU @ 100Hz):
- Integrate IMU acceleration → velocity → position
- Update orientation from gyroscope

Correction (GPS @ 10Hz):
- Absolute position measurement (x, y, z) from GPS
- Update position + velocity

Correction (VIO @ 30Hz):
- Relative motion estimate from visual odometry
- Update velocity + orientation
```

**Libraries:**
- **Python EKF:** `filterpy` (Kalman filters in Python)
- **ROS Alternative:** `robot_localization` (ROS2 EKF node)

#### B. Indoor/Outdoor Transition Handling
**Challenge:** GPS signal lost indoors  
**Solution:**
1. **Outdoor (GPS available):** Use GPS as ground truth, VIO for smooth interpolation
2. **Transition (GPS signal degrading):** Gradually increase VIO weight in EKF
3. **Indoor (No GPS):** Pure VIO + IMU, rely on loop closure for drift correction

---

## 🏗️ PROPOSED ARCHITECTURE

### Layer 3 (Guide) - Enhanced Navigation Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 3: THE GUIDE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │   IMX415      │  │   BNO055      │  │   NEO-8M      │       │
│  │   Camera      │  │   9-DOF IMU   │  │   GPS         │       │
│  │   (Visual)    │  │   (Inertial)  │  │   (Global)    │       │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘       │
│          │                  │                  │                 │
│          v                  v                  v                 │
│  ┌──────────────────────────────────────────────────┐           │
│  │         VIO (Visual-Inertial Odometry)           │           │
│  │  • Feature tracking (OpenCV KLT)                 │           │
│  │  • IMU preintegration                            │           │
│  │  • Scale estimation                              │           │
│  └──────────────────────┬───────────────────────────┘           │
│                         │                                        │
│                         v                                        │
│  ┌──────────────────────────────────────────────────┐           │
│  │      Sensor Fusion (Extended Kalman Filter)      │           │
│  │  • State: [x, y, z, vx, vy, vz, qw, qx, qy, qz] │           │
│  │  • Prediction: IMU integration (100Hz)           │           │
│  │  • Correction: VIO (30Hz) + GPS (10Hz)          │           │
│  └──────────────────────┬───────────────────────────┘           │
│                         │                                        │
│                         v                                        │
│  ┌──────────────────────────────────────────────────┐           │
│  │            Localization & Mapping                 │           │
│  │  • Current pose: (x, y, θ) + GPS coords          │           │
│  │  • Occupancy grid map (2D/3D)                    │           │
│  │  • Loop closure (prevent drift)                  │           │
│  └──────────────────────┬───────────────────────────┘           │
│                         │                                        │
│          ┌──────────────┴──────────────┐                        │
│          v                              v                        │
│  ┌──────────────┐              ┌──────────────┐                │
│  │ Spatial      │              │ Memory       │                │
│  │ Audio        │              │ System       │                │
│  │ (3D Nav)     │              │ (Layer 4)    │                │
│  └──────────────┘              └──────────────┘                │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 💰 HARDWARE COST BREAKDOWN

| Component | Model | Quantity | Unit Cost | Total | Notes |
|-----------|-------|----------|-----------|-------|-------|
| **Camera** | ✅ RPi Camera Module 3 Wide | 1 | $35 | **$35** | Already owned (IMX708, 102° FOV) |
| **IMU** | ✅ Adafruit BNO055 | 1 | $30 | **$30** | Already owned (I2C, built-in fusion) |
| **GPS** | ✅ u-blox NEO-8M | 1 | $20 | **$20** | Already owned (UART, 10Hz) |
| **Connector Cables** | Qwiic I2C cables | 2 | $2 | **$4** | For BNO055 I2C connection |
| **GPS Antenna** | Active ceramic patch | 1 | $10 | **$10** | Included with NEO-8M usually |
| **Checkerboard Print** | 9x6 pattern | 1 | $5 | **$5** | For fisheye calibration |
| **Enclosure Mounting** | 3D printed brackets | - | $5 | **$5** | For IMU/GPS mounting |
| | | | **TOTAL:** | **$109** | **$85 already owned!** Only $24 for accessories |

**Updated BOM Total:** $135 (v2.0 base) + $24 (Navigation accessories) = **$159** ✅
- **User already owns:** RPi Camera Wide ($35), BNO055 ($30), NEO-8M ($20) = $85
- **Still needed:** Cables, mounting, calibration materials = $24
- **Total project cost: $159** (Still **96% cheaper** than $4,000 OrCam!)

---

## 📊 PERFORMANCE ESTIMATES

### VIO Latency Budget (Raspberry Pi 5)

| Component | Frequency | Latency (ms) | CPU Load |
|-----------|-----------|--------------|----------|
| **RPi Camera Wide Capture** | 56-120 fps | 8-18 ms | ~5% (libcamera) |
| **Fisheye Undistortion** | 56 fps | 15-20 ms | ~10% (cv2.remap) |
| **YOLO Detection** | 60 fps | 60-80 ms | ~60% (1 core) |
| **Feature Tracking (OpenCV KLT)** | 30 fps | 20-30 ms | ~15% (1 core) |
| **IMU Reading (BNO055)** | 100 Hz | 1 ms | ~2% (I2C) |
| **EKF Fusion** | 100 Hz | 5 ms | ~10% |
| **GPS Parsing (NEO-8M)** | 10 Hz | 10 ms | ~1% |
| **Total VIO Pipeline** | 30 fps | **~120 ms** | ~100% (multi-core) |

**Verdict:** ✅ **Real-time feasible** on Raspberry Pi 5 (4 cores @ 2.4GHz)

**Note:** Fisheye undistortion adds ~15-20ms latency, but can be optimized:
- Use precomputed remap maps (faster than `cv2.fisheye.undistortImage()`)
- Consider GPU acceleration with OpenCL (RPi 5 has VideoCore VII GPU)
- Alternative: Use undistorted coordinates in feature tracker (skip full image undistortion)

---

## 🚧 IMPLEMENTATION PHASES (When We Start Coding)

### Phase 1: Hardware Setup & Calibration (Week 1-2)
- [ ] ✅ **Hardware already acquired:** RPi Camera Wide, BNO055, NEO-8M
- [ ] Wire I2C (BNO055) and UART (NEO-8M) to RPi 5 GPIO
- [ ] Test raw sensor readings (Python test scripts)
- [ ] **CRITICAL:** Perform fisheye camera intrinsic calibration (20-30 checkerboard images)
  - [ ] Print 9x6 checkerboard pattern
  - [ ] Capture calibration images covering full FOV
  - [ ] Run `cv2.fisheye.calibrate()`
  - [ ] Validate RMS error <0.5 pixels
  - [ ] Save K matrix + D coefficients to YAML
- [ ] Test fisheye undistortion (verify straight lines are straight)
- [ ] Perform camera-IMU extrinsic calibration (T_cam_imu transform)
- [ ] (Optional) Collect 20-hour stationary IMU data for Allan variance (BNO055 may not need this)

### Phase 2: VIO Prototype (Week 3-4)
**Option A (ROS2):**
- [ ] Install ROS2 Humble on RPi 5
- [ ] Create ROS2 camera publisher (RPi Camera Wide → undistorted `/camera/image_raw`)
- [ ] Create ROS2 IMU publisher (BNO055 → `/imu/data`)
- [ ] Configure OpenVINS with fisheye distortion model (`pinhole-equi`)
- [ ] Launch OpenVINS node
- [ ] Visualize trajectory in RViz

**Option B (Python ROS-free) - RECOMMENDED:**
- [ ] Create `layer3_guide/vio/fisheye_undistort.py` (load K/D, precompute remap maps)
- [ ] Create `layer3_guide/vio/feature_tracker.py` (OpenCV FAST + KLT on undistorted frames)
- [ ] Create `layer3_guide/vio/imu_reader.py` (BNO055 I2C, quaternion + accel)
- [ ] Create `layer3_guide/vio/vio_estimator.py` (simple fusion)
- [ ] Test trajectory accuracy (walk 10m straight, compare GPS ground truth)
- [ ] Validate: Straight line should be straight (not curved from distortion)

### Phase 3: GPS Integration (Week 5)
- [ ] Create `layer3_guide/gps/gps_reader.py` (NMEA parser)
- [ ] Implement EKF fusion (VIO + GPS + IMU)
- [ ] Test indoor→outdoor transition (start indoors, walk outside)
- [ ] Validate accuracy (compare GPS coords to Google Maps)

### Phase 4: Integration with Existing Layer 3 (Week 6)
- [ ] Connect VIO pose to Spatial Audio Manager (3D audio follows heading)
- [ ] Store GPS waypoints in Layer 4 Memory ("remember this coffee shop")
- [ ] Add voice commands:
  - "Where am I?" → Read GPS coordinates + street address (Gemini TTS)
  - "Navigate to Starbucks" → GPS routing + audio beacons
  - "How far have I walked?" → Distance traveled from VIO

### Phase 5: Loop Closure & Map Building (Week 7-8)
- [ ] Implement visual bag-of-words (ORB vocabulary)
- [ ] Detect loop closures (revisiting same location)
- [ ] Perform pose graph optimization (g2o library)
- [ ] Build 2D occupancy grid map
- [ ] Store map in Layer 4 Memory (persistent across sessions)

---

## 🔍 KEY TECHNICAL DECISIONS

### Decision 1: ROS2 vs. ROS-free?
**Recommendation:** **Start ROS-free** (Option B - Custom Python VIO)

**Rationale:**
- ✅ Faster prototyping (no ROS learning curve)
- ✅ Direct integration with existing `cortex_gui.py` (no IPC overhead)
- ✅ Lighter weight (no ROS2 daemon, no XML configs)
- ❌ Lower accuracy (but acceptable for YIA 2026 demo)
- 🔄 **If needed:** Can migrate to OpenVINS later for production

---

### Decision 2: Stereo vs. Monocular?
**Current Setup:** **Monocular (IMX415)**  
**Recommendation:** **Keep monocular + IMU** (VIO handles scale)

**Rationale:**
- ✅ Already have IMX415 (no new hardware cost)
- ✅ VIO (mono + IMU) solves scale ambiguity problem
- ✅ Lower bandwidth (1 camera vs. 2)
- ❌ Stereo would give better accuracy (but requires 2nd camera + sync)

**If budget allows:** Consider **Raspberry Pi Stereo Camera Module** ($60) for Phase 2 upgrade

---

### Decision 3: Built-in Sensor Fusion (BNO055) vs. Raw IMU?
**Recommendation:** **Use BNO055's built-in fusion** (quaternion output)

**Rationale:**
- ✅ **Offloads CPU:** BNO055's ARM Cortex-M0 handles Madgwick filter internally
- ✅ **Self-calibrating:** Saves calibration data to EEPROM
- ✅ **Plug-and-play:** Read quaternion directly via I2C
- ✅ **100Hz orientation:** Perfect for VIO heading correction
- ❌ Less flexibility (can't tune filter parameters)

**Alternative:** If we need raw data (for OpenVINS), BNO055 can output raw accel/gyro too

---

## 🎓 LEARNING RESOURCES

### Recommended Papers (For Understanding):
1. **OpenVINS Paper:** "MARS: An Open-Source Platform for Autonomous Navigation Research" (2022)
2. **VINS-Fusion Paper:** "VINS-Fusion: A Robust and Versatile Multi-Sensor Visual-Inertial State Estimator" (2019)
3. **MSCKF Primer:** "A Multi-State Constraint Kalman Filter for Vision-aided IMU" (Mourikis, 2007)

### Hands-on Tutorials:
1. **Adafruit BNO055 Guide:** https://learn.adafruit.com/adafruit-bno055-absolute-orientation-sensor
2. **OpenVINS Getting Started:** https://docs.openvins.com/gs-tutorial.html
3. **Kalman Filtering in Python:** `filterpy` library documentation

---

## ⚠️ RISKS & MITIGATION

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **IMU-Camera time sync issues** | High drift | Medium | Use hardware timestamps, implement time offset calibration |
| **GPS signal loss indoors** | No absolute position | High | Rely on VIO + loop closure, graceful degradation |
| **VIO scale drift** | Position error accumulates | Medium | Fuse with GPS outdoors, reset with visual loop closure |
| **RPi 5 computational limits** | Latency >200ms | Medium | Optimize feature tracking (reduce # features), use grayscale |
| **Calibration complexity** | Poor VIO accuracy | High | Use BNO055's built-in fusion (skip manual calibration) |

---

## 📈 SUCCESS METRICS (For YIA 2026 Demo)

### Minimum Viable Demo:
- [ ] **Indoor Navigation:** Walk 20m indoors, VIO tracks trajectory within 5% error
- [ ] **Outdoor Navigation:** Walk 50m outdoors, GPS + VIO within 3m accuracy
- [ ] **Memory Integration:** "Remember this coffee shop" → Store GPS waypoint
- [ ] **Voice Navigation:** "Where am I?" → Read GPS coords + street address
- [ ] **3D Audio Heading:** Spatial audio follows user's heading (IMU orientation)

### Stretch Goals:
- [ ] **Loop Closure Demo:** Walk a square loop, system recognizes return to start
- [ ] **Map Visualization:** Display 2D occupancy grid on laptop GUI
- [ ] **Multi-session Memory:** Return to location from previous day, system remembers

---

## 🏁 NEXT STEPS (Action Items)

### Immediate (This Week):
1. ✅ **Research complete** (this document)
2. ⏳ **Order hardware:** Adafruit BNO055, u-blox NEO-8M GPS
3. ⏳ **Review with Haziq:** Confirm ROS-free approach

### Near-term (Next 2 Weeks):
4. ⏳ Test BNO055 I2C communication (read quaternion)
5. ⏳ Test NEO-8M UART (parse NMEA sentences)
6. ⏳ Prototype simple dead reckoning (IMU velocity integration)

### Mid-term (Before YIA 2026):
7. ⏳ Implement lightweight VIO (OpenCV feature tracking)
8. ⏳ Fuse VIO + GPS + IMU (EKF)
9. ⏳ Integrate with Layer 3 spatial audio
10. ⏳ Add voice commands for navigation

---

## 📚 REFERENCES

### Technical Documentation:
- OpenVINS Docs: https://docs.openvins.com/
- VINS-Fusion GitHub: https://github.com/HKUST-Aerial-Robotics/VINS-Fusion
- RTAB-Map Docs: https://introlab.github.io/rtabmap/
- Raspberry Pi Camera Docs: https://www.raspberrypi.com/documentation/computers/camera_software.html

### Hardware Datasheets:
- BNO055 Datasheet: https://cdn-learn.adafruit.com/downloads/pdf/adafruit-bno055-absolute-orientation-sensor.pdf
- NEO-8M Datasheet: https://www.u-blox.com/en/product/neo-m8-series
- IMX415 Specs: Sony official specs (8MP, 1/2.8" sensor, MIPI CSI-2)

### Python Libraries:
- `adafruit-circuitpython-bno055`: https://pypi.org/project/adafruit-circuitpython-bno055/
- `adafruit-circuitpython-gps`: https://pypi.org/project/adafruit-circuitpython-gps/
- `filterpy`: https://filterpy.readthedocs.io/ (Kalman filters)
- `opencv-python`: Feature tracking (FAST, KLT optical flow)

---

## 💬 NOTES FROM RESEARCH SESSION

### Key Insights:
1. **BNO055 is a game-changer:** Built-in sensor fusion offloads CPU, perfect for RPi 5
2. **Monocular + IMU is sufficient:** No need for expensive stereo camera
3. **ROS-free is viable:** Custom Python VIO achievable in 2-4 weeks
4. **GPS fusion is straightforward:** EKF with 3 measurement sources (VIO, GPS, IMU)
5. **Raspberry Pi 5 is powerful enough:** 2.4GHz ARM Cortex-A76, 4 cores → can handle VIO

### Concerns:
1. **Calibration complexity:** Camera-IMU extrinsic calibration requires careful data collection
2. **Time synchronization:** Must timestamp IMU and camera with <10ms accuracy
3. **Testing environment:** Need large open space for GPS + VIO validation

### Questions for Haziq:
- [ ] Budget approval for BNO055 ($30) + NEO-8M ($20) = **$50 total**?
- [ ] Preference: ROS2 (higher accuracy, steeper learning curve) vs. ROS-free (faster, lower accuracy)?
- [ ] Timeline: 2-week prototype or 8-week full implementation?

---

## 10. DEVELOPMENT WORKFLOW: Laptop ↔ RPi Pipeline

**THE PROBLEM (Peer Review Feedback):**
Developing VIO on laptop webcam (narrow FOV, no distortion) will **fail catastrophically** on RPi 5 fisheye camera (120° FOV, massive distortion). We need to develop algorithms using **real RPi data** without physically working on the RPi.

**THE SOLUTION: Record → Develop → Deploy Workflow**
```
┌─────────────────────────────────────────────────────────┐
│ Phase 1: RPi Data Recording (5 minutes, one-time)      │
├─────────────────────────────────────────────────────────┤
│ • Record EuRoC MAV dataset on RPi 5                     │
│   - Camera: 30fps fisheye images                        │
│   - IMU: 100Hz BNO055 (gyro + accel)                    │
│   - GPS: 10Hz NEO-8M (lat/lon/alt)                      │
│ • Output: /data_session_001/ (500MB - 2GB)             │
│   cam0/data.csv, imu0/data.csv, cam0/data/*.png         │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Phase 2: Laptop Algorithm Development (weeks)          │
├─────────────────────────────────────────────────────────┤
│ • Load EuRoC dataset on laptop (evo library)            │
│ • Develop VIO using REAL fisheye images                 │
│ • Iterate quickly (no RPi recompile/reboot needed)      │
│ • Debug with matplotlib (visualize keyframes)           │
│ • Validate with evo (compare trajectories)              │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Phase 3: RPi Deployment (swap data source)             │
├─────────────────────────────────────────────────────────┤
│ • Change 1 line: cv2.VideoCapture(0) (live mode)        │
│ • VIO algorithm unchanged (same distortion, same FOV)   │
│ • Real-time navigation now works on RPi                 │
└─────────────────────────────────────────────────────────┘
```

**WHY THIS WORKS:**
1. **EuRoC format is device-agnostic**: RPi records data, laptop consumes it
2. **Same fisheye distortion**: Algorithms trained on RPi images work on RPi camera
3. **Fast iteration**: No RPi reboots, no SSH delays, full debug tools (matplotlib, pdb)
4. **Reproducibility**: Same dataset validates VIO changes

**IMPLEMENTATION:**
- **Data Recorder**: See [data-recorder-architecture.md](../implementation/data-recorder-architecture.md)
- **Python Library**: `pip install evo` (loads EuRoC datasets)
- **RPi Recording**: 5 minutes = 9,000 images + 30,000 IMU samples (~500MB)

---

**End of Research Document**  
*Next Step: Hardware procurement + Data recorder implementation* 🚀
