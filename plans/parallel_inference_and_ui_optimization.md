# 🧠 Project Cortex - Parallel Inference & UI Optimization Plan

**Date:** January 2, 2026  
**Version:** 2.1  
**Author:** Haziq + Claude (CTO)  
**Target:** YIA 2026 Competition

---

## 📊 Executive Summary

This plan addresses three critical optimization areas:
1. **Multi-Core Parallel YOLO Inference** (3 cores for YOLO, 1 for system)
2. **UI Enhancement** (Match reference biotech design from code.html)
3. **Frame Transmission Optimization** (Increase dashboard FPS from 12 to 24+)

---

## 🔬 Research Summary

### Multi-Threading Research (from context7/deepwiki)

#### Key Findings from Ultralytics Documentation:
1. **Thread-Safe YOLO Inference**: Each thread must instantiate its own model instance to avoid race conditions
2. **Python GIL Limitation**: Threads share the GIL, but YOLO's C/C++ inference code releases GIL during computation
3. **Multiprocessing Recommended**: For true parallelism, use separate processes with their own memory space
4. **CPU Pinning (mpire)**: Can pin worker processes to specific CPU cores for optimal performance

#### Best Practice for Parallel YOLO:
```python
# Each worker has its own model instance
def worker_init(worker_state):
    worker_state['model'] = YOLO("yolo11n_ncnn_model")

# Use mpire with CPU pinning for RPi 5 (4 cores)
with WorkerPool(n_jobs=3, cpu_ids=[1, 2, 3]) as pool:
    results = pool.map(inference_task, frames, worker_init=worker_init)
```

#### RPi 5 CPU Core Allocation:
| Core | Assignment | Priority |
|------|------------|----------|
| Core 0 | System/UI/NiceGUI | Normal |
| Core 1 | YOLO Guardian (Layer 0) | High |
| Core 2 | YOLOE Learner (Layer 1) | High |
| Core 3 | Camera/Encoding/I/O | Normal |

---

## 🏗️ Architecture Changes

### Current Architecture (Single-Thread Sequential)
```
[Main Thread] → Camera → YOLO Guardian → YOLOE Learner → Encode → Display
                 ↑                                           ↓
                 └───── 12 FPS limit, blocking inference ────┘
```

### Target Architecture (Multi-Process Parallel)
```
[Process 0 - Core 0] NiceGUI Dashboard + UI Updates
        ↓ (shared memory queue)
[Process 1 - Core 1] YOLO Guardian (dedicated, ~100ms)
        ↓ (shared memory queue)
[Process 2 - Core 2] YOLOE Learner (dedicated, ~200ms)
        ↓ (shared memory queue)
[Process 3 - Core 3] Camera Capture + JPEG Encoding + Transmission
```

### Key Design Decisions:
1. **multiprocessing.Queue** for inter-process communication (IPC)
2. **SharedMemory** for frame buffer (zero-copy optimization)
3. **CPU affinity** via `os.sched_setaffinity()` for core pinning
4. **Separate model instances** per process (memory isolation)

---

## 📋 Detailed TODO List

### Phase 1: Multi-Process Inference Pipeline (Priority: HIGH)

#### Task 1.1: Create ProcessManager Class
- **File:** `src/process_manager.py` (NEW)
- **Description:** Singleton class managing all worker processes
- **Components:**
  - `GuardianProcess` (Core 1): YOLO11n-NCNN inference only
  - `LearnerProcess` (Core 2): YOLOE-11s inference only
  - `CameraProcess` (Core 3): Picamera2 capture + encoding
  - `SharedFrameBuffer`: Shared memory for frame data
- **RAM Budget:** ~2.5GB (Guardian) + ~1GB (Learner) + ~500MB (Camera) = 4GB ✅

#### Task 1.2: Implement Frame Queue System
- **File:** `src/frame_queue.py` (NEW)
- **Description:** Lock-free frame queue using SharedMemory
- **Features:**
  - Ring buffer with 3 frame slots
  - Automatic frame dropping when backpressured
  - Timestamp-based frame ordering
  - Zero-copy frame passing between processes

#### Task 1.3: Create Worker Process Classes
- **File:** `src/workers/guardian_worker.py` (NEW)
- **File:** `src/workers/learner_worker.py` (NEW)
- **File:** `src/workers/camera_worker.py` (NEW)
- **Description:** Dedicated process for each task with CPU pinning
- **Implementation:**
```python
class GuardianWorker(Process):
    def __init__(self, frame_queue, result_queue):
        super().__init__()
        self.frame_queue = frame_queue
        self.result_queue = result_queue
    
    def run(self):
        # Pin to Core 1
        os.sched_setaffinity(0, {1})
        # Load model in this process
        self.model = YOLO("models/yolo11n_ncnn_model")
        while True:
            frame = self.frame_queue.get()
            results = self.model(frame)
            self.result_queue.put(results)
```

#### Task 1.4: Modify CortexHardwareManager
- **File:** `src/cortex_dashboard.py`
- **Changes:**
  - Replace `_inference_loop()` with process-based pipeline
  - Create process manager on startup
  - Handle graceful shutdown of all processes
  - Update state from result queues

#### Task 1.5: Performance Benchmarking
- **File:** `tests/benchmark_multiprocess.py` (NEW)
- **Metrics:**
  - Per-core CPU utilization
  - End-to-end inference latency
  - Frame throughput (FPS)
  - Memory usage per process
  - IPC overhead measurement

---

### Phase 2: Frame Transmission Optimization (Priority: HIGH)

#### Task 2.1: Increase Target FPS
- **File:** `src/cortex_dashboard.py`
- **Change:** `TARGET_ENCODE_FPS = 12` → `TARGET_ENCODE_FPS = 24`
- **Rationale:** Smoother video, better user experience

#### Task 2.2: Optimize JPEG Encoding
- **Current:** `cv2.IMWRITE_JPEG_QUALITY = 65`
- **Target:** Dynamic quality based on motion
- **Implementation:**
```python
# Motion-adaptive JPEG quality
if frame_diff > motion_threshold:
    quality = 50  # Lower quality during motion (faster encode)
else:
    quality = 75  # Higher quality when static (clearer image)
```

#### Task 2.3: Implement Delta Frame Encoding
- **Description:** Only transmit changed regions of frame
- **Approach:**
  1. Compute frame difference mask
  2. If >80% unchanged, send delta patch only
  3. Fallback to full frame every 30 frames

#### Task 2.4: Use WebSocket for Streaming
- **Current:** Base64 via HTTP polling
- **Target:** MJPEG via WebSocket (lower latency)
- **NiceGUI Support:** `ui.image()` with `source` update
- **Alternative:** Custom endpoint `/api/video_feed`

#### Task 2.5: Move Encoding to Dedicated Process
- **File:** `src/workers/camera_worker.py`
- **Description:** Encoding happens on Core 3, not blocking UI
- **Pipeline:**
```
[Core 3] Picamera2 → Resize (640x480) → JPEG Encode → Queue → [Core 0] Dashboard
```

---

### Phase 3: UI Enhancement (Priority: MEDIUM)

#### Task 3.1: Match Reference Design Layout
- **Reference:** `code.html`
- **Current Issues:**
  1. Grid layout not matching (3-col: 3/7/2 ratio)
  2. Memory Recalls section too wide
  3. Missing organic border-radius variations
  4. Layer cards missing hover glow effects

#### Task 3.2: Fix Grid Column Ratios
- **Current:** `w-1/4` | `w-1/2` | `w-1/4`
- **Target:** `col-span-3` | `col-span-7` | `col-span-2` (12-col grid)
- **Implementation:**
```python
# Change from row-based to grid-based layout
with ui.element('main').classes('flex-1 grid grid-cols-12 gap-6 p-8'):
    with ui.column().classes('col-span-3 ...'):  # Left sidebar
    with ui.column().classes('col-span-7 ...'):  # Center video
    with ui.column().classes('col-span-2 ...'):  # Right sidebar
```

#### Task 3.3: Add Missing Visual Effects
- **Breathing glow animation:** Already implemented ✅
- **Scanline animation:** Already implemented ✅
- **Corner decorations:** Already implemented ✅
- **Missing:** 
  - `animate-spin-slow` for settings icon
  - Organic border radius variations (`rounded-tr-sm`, `rounded-bl-sm`)
  - Gradient progress bars (not solid colors)

#### Task 3.4: Improve Progress Bar Styling
- **Current:** Solid color NiceGUI progress bars
- **Target:** Gradient with glow shadow (like reference)
- **Implementation:** Custom CSS classes
```python
ui.add_head_html('''
<style>
.gradient-progress-teal .q-linear-progress__track {
    background: linear-gradient(to right, #0f766e, #2dd4bf) !important;
    box-shadow: 0 0 10px rgba(45, 212, 191, 0.4);
}
</style>
''')
```

#### Task 3.5: Fix Neural Stream Chat Styling
- **Issues:**
  - Chat messages not matching reference bubbles
  - Missing avatar circles
  - Input field styling differs

#### Task 3.6: Memory Recalls Card Refinement
- **Issues:**
  - Cards too uniform in height
  - Missing staggered organic borders
  - Hover effects not smooth

---

### Phase 4: Integration & Testing (Priority: HIGH)

#### Task 4.1: Integration Test Suite
- **File:** `tests/test_multiprocess_integration.py` (NEW)
- **Tests:**
  - Process startup/shutdown
  - Frame queue throughput
  - Graceful degradation on process crash
  - Memory leak detection

#### Task 4.2: Performance Regression Tests
- **File:** `tests/benchmark_regression.py` (NEW)
- **Baseline Metrics:**
  - Current: ~12 FPS display, ~500ms latency
  - Target: ~24 FPS display, ~150ms latency

#### Task 4.3: Error Handling
- **Implement:**
  - Process watchdog (restart crashed workers)
  - Queue overflow protection
  - Graceful fallback to single-process mode

---

## 📊 Expected Performance Gains

| Metric | Current | Target | Improvement |
|--------|---------|--------|-------------|
| Display FPS | 12 | 24+ | 2x |
| Inference Latency | 500-800ms | 150-200ms | 3x |
| CPU Utilization | 100% (1 core) | 75% (4 cores) | Balanced |
| Frame Drop Rate | High | <5% | Stable |

---

## ⚠️ Risk Assessment

### Risk 1: Memory Exhaustion
- **Probability:** Medium
- **Impact:** High (system crash)
- **Mitigation:** 
  - Use SharedMemory for frames (no copying)
  - Limit queue sizes (max 3 frames)
  - Monitor with psutil

### Risk 2: Process Communication Overhead
- **Probability:** Low
- **Impact:** Medium (latency increase)
- **Mitigation:**
  - SharedMemory for large data (frames)
  - Queue for small data (results)
  - Batch result updates

### Risk 3: Camera Contention
- **Probability:** Low
- **Impact:** High (no video)
- **Mitigation:**
  - Single camera process owns Picamera2
  - No concurrent camera access

---

## 🗓️ Implementation Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1 (Multi-Process) | 4-6 hours | None |
| Phase 2 (Frame Optimization) | 2-3 hours | Phase 1 |
| Phase 3 (UI Enhancement) | 2-3 hours | None (parallel) |
| Phase 4 (Integration) | 2-3 hours | Phase 1+2 |
| **Total** | **10-15 hours** | |

---

## 📝 Implementation Notes

### Python Multiprocessing on RPi 5
```python
import multiprocessing as mp
import os

# Use 'spawn' start method for clean process isolation
mp.set_start_method('spawn')

# CPU affinity (Linux only)
os.sched_setaffinity(0, {core_id})
```

### SharedMemory for Frame Buffer
```python
from multiprocessing import shared_memory

# Create shared buffer for 640x480 RGB frame
shm = shared_memory.SharedMemory(create=True, size=640*480*3)
frame_buffer = np.ndarray((480, 640, 3), dtype=np.uint8, buffer=shm.buf)

# In worker process
existing_shm = shared_memory.SharedMemory(name=shm.name)
frame = np.ndarray((480, 640, 3), dtype=np.uint8, buffer=existing_shm.buf)
```

### NiceGUI Frame Update Pattern
```python
# Efficient image update (no re-render)
self.image_view.set_source(f'data:image/jpeg;base64,{b64}')

# For even faster updates, consider:
# 1. WebSocket endpoint with binary JPEG
# 2. MJPEG stream via FastAPI
```

---

## ✅ Success Criteria

1. **Multi-Process:** All 4 cores utilized, no single-thread bottleneck
2. **Latency:** End-to-end inference <200ms
3. **FPS:** Dashboard displays 24+ FPS smoothly
4. **UI:** Matches reference design (code.html) at 95% fidelity
5. **Stability:** No crashes during 1-hour continuous operation
6. **Memory:** Total RAM usage <3.9GB

---

## 📚 References

- [Ultralytics Thread Safety](https://docs.ultralytics.com/guides/yolo-thread-safe-inference/)
- [mpire CPU Pinning](https://github.com/sybrenjansen/mpire)
- [Python multiprocessing](https://docs.python.org/3/library/multiprocessing.html)
- [NiceGUI Image Streaming](https://github.com/zauberzeug/nicegui/wiki/ROS2-image-display)
- [SharedMemory](https://docs.python.org/3/library/multiprocessing.shared_memory.html)
