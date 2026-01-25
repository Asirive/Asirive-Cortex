# 🎯 Project Cortex - Detailed TODO List

**Created:** January 2, 2026
**Last Updated:** January 25, 2026
**Status:** AI Hat+ Hardware Acceleration Implementation
**Priority Legend:** 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low

---

## Phase 1: Multi-Process Parallel Inference 🔴 ✅ MOSTLY COMPLETE

### 1.1 Core Infrastructure

- [x] **Create `src/process_manager.py`** 🔴 ✅
  - Singleton class managing all worker processes
  - Handles process lifecycle (start, stop, restart)
  - Coordinates SharedMemory allocation
  - Implements process watchdog
  - **Status:** COMPLETE
  - **Files Created:** `src/process_manager.py`

- [x] **Create `src/frame_queue.py`** 🔴 ✅
  - Lock-free ring buffer implementation
  - Uses `multiprocessing.shared_memory.SharedMemory`
  - 3 frame slots (640x480x3 bytes each = ~900KB per slot)
  - Automatic frame dropping when queue is full
  - Timestamp-based frame ordering
  - **Status:** COMPLETE
  - **Files Created:** `src/frame_queue.py`

### 1.2 Worker Processes

- [x] **Create `src/workers/__init__.py`** 🔴 ✅
  - Package initialization with BaseWorker class
  - CPU pinning support
  - Signal handling
  - Health monitoring
  - **Status:** COMPLETE

- [x] **Create `src/workers/guardian_worker.py`** 🔴 ✅
  - Dedicated process for YOLO11n
  - CPU affinity: Core 1 (`os.sched_setaffinity(0, {1})`)
  - Loads model on startup (in process memory)
  - Hazard detection with distance estimation
  - PWM vibration motor control via GPIO 18
  - **Status:** COMPLETE
  - **Files Created:** `src/workers/guardian_worker.py`

- [x] **Create `src/workers/learner_worker.py`** 🔴 ✅
  - Dedicated process for YOLOE-11s
  - CPU affinity: Core 2 (`os.sched_setaffinity(0, {2})`)
  - Object learning capability (tracks common objects)
  - Segmentation support when available
  - **Status:** COMPLETE
  - **Files Created:** `src/workers/learner_worker.py`

- [x] **Create `src/workers/camera_worker.py`** 🔴 ✅
  - Dedicated process for Picamera2
  - CPU affinity: Core 3 (`os.sched_setaffinity(0, {3})`)
  - Captures frames at configurable FPS
  - Motion detection for adaptive encoding
  - OpenCV fallback for testing
  - **Status:** COMPLETE
  - **Files Created:** `src/workers/camera_worker.py`

### 1.3 Integration

- [ ] **Modify `src/cortex_dashboard.py`** 🔴 ⏳ IN PROGRESS
  - Replace `_inference_loop()` with process-based pipeline
  - Create ProcessManager on startup
  - Start all worker processes
  - Implement result polling from queues
  - Handle graceful shutdown (cleanup processes)
  - **Key Changes:**
    - Remove `ThreadPoolExecutor` usage
    - Add `ProcessManager` initialization
    - Modify `update_tick()` to read from result queues
  - **Estimated Time:** 2 hours
  - **Files to Modify:** `src/cortex_dashboard.py`
  - **Dependencies:** All workers

---

## Phase 2: Frame Transmission Optimization 🟠 ✅ COMPLETE

### 2.1 FPS Improvements

- [x] **Increase TARGET_ENCODE_FPS** 🟠 ✅
  - **Status:** COMPLETE
  - Changed `TARGET_ENCODE_FPS = 12` → `TARGET_ENCODE_FPS = 24`
  - Impact: 2x smoother video display

- [x] **Implement Motion-Adaptive JPEG Quality** 🟠 ✅
  - **Status:** COMPLETE
  - High motion: quality=50 (faster encode)
  - Low motion: quality=75 (clearer image)
  - Implemented in both thread and multiprocess loops

### 2.2 Encoding Optimization

- [ ] **Move Encoding to Camera Worker** 🟡
  - JPEG encoding happens in camera process (Core 3)
  - Send base64 string via queue (not raw frame)
  - Reduces main process CPU load
  - **Estimated Time:** 1 hour
  - **Files to Modify:** `src/workers/camera_worker.py`

- [ ] **Consider Turbo-JPEG** 🟢
  - Install: `pip install PyTurboJPEG`
  - 2-6x faster JPEG encoding on ARM
  - **Estimated Time:** 30 minutes
  - **Optional:** Only if needed

---

## Phase 3: UI Enhancement 🟡 ✅ MOSTLY COMPLETE

### 3.1 Layout Fixes

- [x] **Fix Grid Column Ratios** 🟡 ✅
  - **Status:** COMPLETE
  - Changed to 12-column grid with col-span-3, col-span-7, col-span-2

### 3.2 Visual Effects

- [x] **Add Gradient Progress Bars** 🟡 ✅
  - **Status:** COMPLETE
  - Added gradient CSS with glow shadows for teal, amber, indigo, rose

- [x] **Fix Layer Card Hover Effects** 🟡 ✅
  - **Status:** COMPLETE
  - Added `layer-card` CSS class with hover effects
  - Ensure smooth transitions (300ms)
  - **Reference:** `code.html` lines 168-210
  - **Estimated Time:** 20 minutes

- [ ] **Add animate-spin-slow** 🟢
  - Settings icon should spin slowly (10s per rotation)
  - **CSS Addition:**
    ```css
    @keyframes spin-slow {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
    .animate-spin-slow {
        animation: spin-slow 10s linear infinite;
    }
    ```
  - **Estimated Time:** 10 minutes

### 3.3 Chat Styling

- [ ] **Improve Neural Stream Chat Bubbles** 🟡
  - Add avatar circles with letters ("C" for Cortex, "U" for User)
  - Fix bubble border-radius (`rounded-r-xl rounded-bl-xl`)
  - Match reference colors and spacing
  - **Reference:** `code.html` lines 277-295
  - **Estimated Time:** 30 minutes

### 3.4 Memory Recalls

- [ ] **Fix Memory Recalls Card Heights** 🟡
  - Staggered heights: 40, 48, 36, 44, 32 (in Tailwind units)
  - Matches reference organic feel
  - **Estimated Time:** 15 minutes

- [ ] **Add Organic Border Variations** 🟡
  - Alternate corner radius styles:
    - `rounded-tr-sm` (first card)
    - `rounded-bl-sm` (second card)
    - `rounded-tl-sm` (third card)
    - `rounded-br-sm` (fourth card)
  - **Reference:** `code.html` lines 315-380
  - **Estimated Time:** 20 minutes

---

## Phase 4: Testing & Validation 🟠

### 4.1 Unit Tests

- [ ] **Create `tests/test_frame_queue.py`** 🟠
  - Test queue put/get operations
  - Test backpressure handling
  - Test SharedMemory cleanup
  - **Estimated Time:** 1 hour

- [ ] **Create `tests/test_workers.py`** 🟠
  - Test worker startup/shutdown
  - Test CPU affinity assignment
  - Test error handling
  - **Estimated Time:** 1 hour

### 4.2 Integration Tests

- [ ] **Create `tests/test_multiprocess_integration.py`** 🟠
  - Full pipeline test with mock camera
  - Test process communication
  - Test graceful degradation
  - **Estimated Time:** 1.5 hours

### 4.3 Benchmarks

- [ ] **Create `tests/benchmark_multiprocess.py`** 🟠
  - Measure per-core CPU utilization
  - Measure end-to-end latency
  - Measure FPS
  - Measure memory per process
  - Measure IPC overhead
  - **Metrics Table:**
    | Metric | Baseline | Target |
    |--------|----------|--------|
    | FPS | 12 | 24+ |
    | Latency | 500ms | <200ms |
    | CPU (total) | 100% | 75% |
    | RAM | 3.5GB | <3.9GB |
  - **Estimated Time:** 1 hour

### 4.4 Stability Testing

- [ ] **Run 1-Hour Endurance Test** 🟠
  - All processes running
  - No crashes or memory leaks
  - Stable FPS throughout
  - **Estimated Time:** 1 hour (runtime)

---

## Summary

| Phase | Tasks | Time Estimate |
|-------|-------|---------------|
| Phase 1 | 8 tasks | 8-10 hours |
| Phase 2 | 4 tasks | 2-3 hours |
| Phase 3 | 8 tasks | 2-3 hours |
| Phase 4 | 5 tasks | 4-5 hours |
| **Total** | **25 tasks** | **16-21 hours** |

---

## Quick Start (First 3 Tasks)

1. **Create `src/frame_queue.py`** - Core infrastructure for all workers
2. **Create `src/workers/guardian_worker.py`** - First worker to test pattern
3. **Modify `src/cortex_dashboard.py`** - Increase FPS to 24 (quick win)

---

## Notes

- Always test on RPi 5 (not development laptop)
- Keep RAM under 3.9GB at all times
- Graceful degradation is key for demo reliability
- Prioritize stability over speed for competition
