# Project Cortex v2.0 - RPi 5 Dashboard Implementation Plan

**Author:** GitHub Copilot (CTO)  
**Date:** December 31, 2025  
**Status:** READY FOR APPROVAL  
**Priority:** 🔥 CRITICAL PATH TO YIA 2026

---

## 🎯 EXECUTIVE SUMMARY

**Goal:** Integrate NiceGUI web dashboard (`cortex_dashboard.py`) with RPi 5 Lite OS (headless) and implement comprehensive model benchmarking system.

**Current State:**
- ✅ `cortex_gui.py`: Tkinter GUI for laptop development (2683 lines, feature-complete)
- ✅ `cortex_dashboard.py`: NiceGUI web dashboard (746 lines, partially complete)
- ❌ **Gap:** Dashboard not integrated with RPi 5 headless environment
- ❌ **Gap:** No model benchmarking system

**Target Outcome:**
1. **Web dashboard accessible at `http://<RPi_IP>:5000`** from any device (laptop, phone, tablet)
2. **Headless RPi 5 operation** (no monitor/keyboard needed)
3. **Real-time video streaming** with <500ms latency
4. **Model benchmarking suite** for NCNN/ONNX/PyTorch comparison
5. **3-tier selection UI** for Gemini Live API / Gemini TTS / GLM-4.6V

---

## 🏗️ ARCHITECTURE ANALYSIS

### Current Implementation Comparison

| Feature | cortex_gui.py (Tkinter) | cortex_dashboard.py (NiceGUI) | Gap |
|---------|-------------------------|-------------------------------|-----|
| **Video Feed** | Tkinter Canvas (local) | Base64 JPEG streaming | ✅ Ready |
| **AI Handlers** | All 5 layers initialized | All 5 layers initialized | ✅ Ready |
| **Voice Commands** | PyAudio + Gradio STT | Browser WebAudio API | ⚠️ Need testing |
| **Layer Status** | Tkinter indicators | Glassmorphism cards | ✅ Ready |
| **Model Switching** | Dropdown menus | Dropdown menus | ✅ Ready |
| **YOLOE Modes** | 3 modes (PF/TP/VP) | Not implemented | ❌ **Need to add** |
| **Memory System** | Full integration | Partial (recall only) | ⚠️ **Need to complete** |
| **Spatial Audio** | Toggle + indicators | Not implemented | ❌ **Need to add** |
| **Benchmarking** | None | None | ❌ **Need to create** |
| **RPi 5 Headless** | Not designed for | Partially ready | ⚠️ **Need to complete** |

---

## 📋 IMPLEMENTATION PLAN

### Phase 1: Complete NiceGUI Dashboard (Priority: HIGH)
**Goal:** Feature parity with cortex_gui.py + RPi 5 optimization  
**Duration:** 4-6 hours  
**Owner:** Haziq + Copilot

#### Task 1.1: Add Missing Features to Dashboard
**Files to Modify:**
- `src/cortex_dashboard.py`

**Changes Required:**
1. **YOLOE 3-Mode Selector** (Line ~400)
   ```python
   # Add mode selector dropdown
   mode_selector = ui.select(
       options=["Prompt-Free", "Text Prompts", "Visual Prompts"],
       value="Text Prompts",
       on_change=lambda e: self.on_yoloe_mode_changed(e.value)
   ).props('dense')
   ```

2. **Spatial Audio Toggle** (Line ~420)
   ```python
   # Add 3D audio toggle
   ui.switch('3D Spatial Audio', on_change=self.toggle_spatial_audio)
   ```

3. **Complete Memory Storage** (Line ~350-400)
   - Currently only has `_execute_memory_recall`
   - Need to add `_execute_memory_store` with bounding box UI
   - Integration with visual prompts mode

4. **VAD (Voice Activity Detection) Integration** (Line ~250)
   - Browser microphone access (already has AudioBridge)
   - VAD state indicator
   - Interrupt TTS feature

5. **Performance Metrics Display** (NEW section)
   - Add real-time FPS counter
   - Inference latency graph (Chart.js or Plotly)
   - RAM usage monitor

#### Task 1.2: Optimize for RPi 5 Headless
**Files to Modify:**
- `src/cortex_dashboard.py`
- `src/main.py` (add dashboard launch option)

**Changes Required:**
1. **Network Binding** (Line ~740)
   ```python
   # Change from localhost to 0.0.0.0 for LAN access
   ui.run(
       host='0.0.0.0',  # Allow external connections
       port=5000,
       reload=False,  # Disable auto-reload on RPi
       show=False,  # Don't open browser (headless)
       title='Project Cortex v2.0'
   )
   ```

2. **Camera Source Detection** (Line ~200)
   ```python
   def _init_camera(self):
       # Auto-detect RPi vs Webcam
       if os.path.exists('/dev/video0'):
           self.cap = cv2.VideoCapture(0)
       else:
           try:
               from picamera2 import Picamera2
               self.picamera2 = Picamera2()
               # ... picamera2 setup
           except ImportError:
               logger.error("No camera found")
   ```

3. **Resource Limits** (Line ~180)
   ```python
   # Limit video resolution on RPi
   if platform.machine() == 'aarch64':  # Detect ARM64 (RPi 5)
       FRAME_WIDTH = 640
       FRAME_HEIGHT = 480
       VIDEO_FPS = 15  # Lower FPS to save bandwidth
   else:
       FRAME_WIDTH = 1280
       FRAME_HEIGHT = 720
       VIDEO_FPS = 30
   ```

4. **Graceful Degradation** (Line ~250)
   - If Gemini API fails → Show error in UI (don't crash)
   - If camera fails → Show "No Camera" placeholder
   - If models fail to load → Disable affected layers in UI

#### Task 1.3: Testing & Validation
**Test Cases:**
1. **Laptop Test:** Run dashboard on laptop, access from browser ✅
2. **RPi 5 Test:** Run on RPi 5, access from laptop browser ✅
3. **Mobile Test:** Access dashboard from Android/iOS phone ✅
4. **Network Test:** Test on same LAN vs different networks ✅
5. **Load Test:** Multiple concurrent users (2-3 devices) ✅

**Acceptance Criteria:**
- [ ] Dashboard loads in <3 seconds
- [ ] Video feed has <500ms latency
- [ ] All 4 layers show correct status
- [ ] Voice commands work via browser
- [ ] Mobile layout is responsive

---

### Phase 2: Model Benchmarking System (Priority: CRITICAL)
**Goal:** Validate NCNN 4-5x speedup claim with real data  
**Duration:** 3-4 hours  
**Owner:** Haziq + Copilot

#### Task 2.1: Create Benchmark Framework
**New Files to Create:**
- `tests/benchmark_models.py` - Main benchmarking script
- `tests/benchmark_config.yaml` - Model configurations
- `tests/benchmark_results/` - Directory for results

**Framework Structure:**
```python
# tests/benchmark_models.py
class ModelBenchmark:
    def __init__(self, model_path, format, device='cpu'):
        self.model_path = model_path
        self.format = format  # 'pytorch', 'ncnn', 'onnx', 'openvino'
        self.device = device
        self.model = None
        
    def load_model(self):
        """Load model and measure load time."""
        start = time.time()
        if self.format == 'pytorch':
            self.model = YOLO(self.model_path)
        elif self.format == 'ncnn':
            self.model = YOLO(self.model_path + '_ncnn_model')
        # ... other formats
        load_time = time.time() - start
        return load_time
    
    def benchmark(self, num_frames=100, resolution=(640, 640)):
        """Run inference on dummy frames."""
        results = {
            'load_time_s': 0,
            'avg_inference_ms': 0,
            'min_inference_ms': 0,
            'max_inference_ms': 0,
            'fps': 0,
            'memory_mb': 0
        }
        
        # Load model
        results['load_time_s'] = self.load_model()
        
        # Warm-up
        dummy_frame = np.random.randint(0, 255, (*resolution, 3), dtype=np.uint8)
        for _ in range(10):
            _ = self.model(dummy_frame, verbose=False)
        
        # Benchmark
        latencies = []
        for i in range(num_frames):
            start = time.time()
            _ = self.model(dummy_frame, verbose=False)
            latencies.append((time.time() - start) * 1000)
        
        results['avg_inference_ms'] = np.mean(latencies)
        results['min_inference_ms'] = np.min(latencies)
        results['max_inference_ms'] = np.max(latencies)
        results['fps'] = 1000 / results['avg_inference_ms']
        
        # Memory usage
        import psutil
        process = psutil.Process()
        results['memory_mb'] = process.memory_info().rss / (1024 * 1024)
        
        return results
```

#### Task 2.2: Benchmark Models to Test
**Models:**
1. **YOLO11n** (Guardian candidate - should meet <100ms)
   - PyTorch: `models/yolo11n.pt`
   - NCNN: `models/yolo11n_ncnn_model`
   - ONNX: `models/yolo11n.onnx`
   - OpenVINO: `models/yolo11n_openvino_model`

2. **YOLO11s** (Guardian candidate - balanced)
   - PyTorch: `models/yolo11s.pt`
   - NCNN: `models/yolo11s_ncnn_model`

3. **YOLO11x** (Guardian - current default, probably too slow)
   - PyTorch: `models/yolo11x.pt`
   - NCNN: `models/yolo11x_ncnn_model`

4. **YOLOE-11s-seg** (Learner - text/visual prompts)
   - PyTorch: `models/yoloe-11s-seg.pt`
   - NCNN: `models/yoloe-11s-seg_ncnn_model`

5. **YOLOE-11m-seg** (Learner - larger)
   - PyTorch: `models/yoloe-11m-seg.pt`
   - NCNN: `models/yoloe-11m-seg_ncnn_model`

**Expected Results (RPi 5, 640x640):**
| Model | Format | Expected Latency | Layer | Target |
|-------|--------|------------------|-------|--------|
| YOLO11n | PyTorch | ~388ms | Layer 0 | ❌ Too slow |
| YOLO11n | NCNN | ~94ms | Layer 0 | ✅ **MEETS <100ms!** |
| YOLO11n | OpenVINO | ~85ms | Layer 0 | ✅ **BEST** |
| YOLO11s | PyTorch | ~1085ms | Layer 0 | ❌ Too slow |
| YOLO11s | NCNN | ~222ms | Layer 0 | ⚠️ Close (2.2x over) |
| YOLO11x | PyTorch | ~1200ms | Layer 0 | ❌ Too slow |
| YOLO11x | NCNN | ~280ms | Layer 0 | ⚠️ Close (2.8x over) |
| YOLOE-11s | PyTorch | ~1000ms | Layer 1 | ⚠️ Acceptable |
| YOLOE-11s | NCNN | ~220ms | Layer 1 | ✅ **4.5x faster** |

#### Task 2.3: Automated Benchmark Runner
**CLI Interface:**
```bash
# Run all benchmarks
python3 tests/benchmark_models.py --all

# Run specific model
python3 tests/benchmark_models.py --model yolo11n --format ncnn

# Compare formats
python3 tests/benchmark_models.py --compare yolo11n

# Export results
python3 tests/benchmark_models.py --export results/benchmark_$(date +%Y%m%d).json
```

**Output Format (JSON):**
```json
{
  "timestamp": "2025-12-31T14:30:00Z",
  "platform": {
    "device": "Raspberry Pi 5 Model B",
    "ram": "4GB",
    "cpu": "ARM Cortex-A76 @ 2.4GHz",
    "os": "Raspberry Pi OS Lite (64-bit)"
  },
  "benchmarks": [
    {
      "model": "yolo11n",
      "format": "ncnn",
      "resolution": "640x640",
      "load_time_s": 2.3,
      "avg_inference_ms": 94.2,
      "min_inference_ms": 88.5,
      "max_inference_ms": 102.3,
      "fps": 10.6,
      "memory_mb": 320,
      "meets_target": true,
      "target_ms": 100,
      "speedup_vs_pytorch": 4.1
    }
  ]
}
```

#### Task 2.4: Visual Benchmark Report
**Files to Create:**
- `tests/generate_benchmark_report.py` - Generate HTML report

**Report Features:**
1. **Performance Comparison Chart** (Chart.js)
   - Bar chart: PyTorch vs NCNN vs OpenVINO
   - X-axis: Model names
   - Y-axis: Inference time (ms)
   - Target line at 100ms

2. **Speedup Table**
   | Model | PyTorch | NCNN | Speedup | Target Met |
   |-------|---------|------|---------|------------|
   | YOLO11n | 388ms | 94ms | 4.1x | ✅ |
   | YOLO11s | 1085ms | 222ms | 4.9x | ⚠️ |

3. **Memory Usage Graph**
   - Line chart: Memory over time during inference
   - Show peak RAM usage

4. **Recommendation Summary**
   ```
   🏆 RECOMMENDED FOR LAYER 0 (Guardian):
      Model: YOLO11n-NCNN
      Reason: Meets <100ms target (94ms avg)
      Trade-off: Lower accuracy vs YOLO11s/x (but fast enough)
   
   🏆 RECOMMENDED FOR LAYER 1 (Learner):
      Model: YOLOE-11s-seg-NCNN
      Reason: 4.5x faster than PyTorch (222ms)
      Trade-off: None (acceptable for context detection)
   ```

---

### Phase 3: Dashboard Integration with Benchmarks (Priority: MEDIUM)
**Goal:** Add benchmarking UI to dashboard  
**Duration:** 2-3 hours  
**Owner:** Haziq + Copilot

#### Task 3.1: Add Benchmark Tab to Dashboard
**Files to Modify:**
- `src/cortex_dashboard.py`

**New UI Section:**
```python
with ui.tab_panel('benchmark'):
    ui.label('Model Performance Benchmarking').classes('text-h4')
    
    # Model selector
    benchmark_model = ui.select(
        options=['yolo11n', 'yolo11s', 'yolo11x', 'yoloe-11s-seg'],
        value='yolo11n'
    )
    
    # Format selector
    benchmark_format = ui.select(
        options=['PyTorch', 'NCNN', 'ONNX', 'OpenVINO'],
        value='NCNN'
    )
    
    # Run button
    ui.button('Run Benchmark', on_click=lambda: run_benchmark(
        benchmark_model.value,
        benchmark_format.value
    ))
    
    # Results display
    benchmark_results = ui.chart({
        'title': { 'text': 'Inference Time Comparison' },
        'xAxis': { 'type': 'category', 'data': [] },
        'yAxis': { 'type': 'value', 'name': 'Latency (ms)' },
        'series': [{ 'type': 'bar', 'data': [] }]
    }).classes('w-full h-96')
```

#### Task 3.2: Real-Time Benchmark Monitoring
**Features:**
1. **Live FPS Counter** (top-right corner)
2. **Latency Graph** (last 100 frames)
3. **Model Comparison** (side-by-side)
4. **Export Results** (download JSON/CSV)

---

## 🧪 TESTING STRATEGY

### Test Environment Matrix
| Device | OS | Browser | Camera | Expected Result |
|--------|-----|---------|--------|-----------------|
| RPi 5 | RPi OS Lite | N/A (headless) | IMX415 | ✅ Server runs |
| Laptop | Windows 11 | Chrome | Webcam | ✅ Dashboard access |
| Laptop | Windows 11 | Firefox | Webcam | ✅ Dashboard access |
| Phone | Android | Chrome | N/A | ✅ Dashboard access |
| Tablet | iOS | Safari | N/A | ✅ Dashboard access |

### Performance Benchmarks (Acceptance Criteria)
| Metric | Target | Test Method |
|--------|--------|-------------|
| Dashboard Load Time | <3s | Chrome DevTools |
| Video Latency | <500ms | Stopwatch comparison |
| Inference (YOLO11n-NCNN) | <100ms | Benchmark script |
| RAM Usage (RPi 5) | <3.8GB | `free -h` command |
| Network Bandwidth | <2 Mbps | Video streaming |

---

## 📊 SUCCESS CRITERIA

### Phase 1 Success
- [ ] Dashboard accessible at `http://<RPi_IP>:5000`
- [ ] All 4 layers show correct status (green = active)
- [ ] Video feed updates at 15-30 FPS
- [ ] Voice commands work via browser microphone
- [ ] YOLOE 3-mode selector functional
- [ ] Spatial audio toggle functional
- [ ] Memory store/recall functional

### Phase 2 Success
- [ ] Benchmark script runs without errors
- [ ] Results match Ultralytics official benchmarks (±10%)
- [ ] YOLO11n-NCNN achieves <100ms latency
- [ ] YOLOE-11s-NCNN shows 4-5x speedup
- [ ] HTML report generated with charts
- [ ] JSON export functional

### Phase 3 Success
- [ ] Benchmark tab loads in dashboard
- [ ] Live FPS counter accurate
- [ ] Benchmark results displayed in charts
- [ ] Export functionality works
- [ ] Model switching updates UI

---

## ⚠️ RISK ASSESSMENT

### High Risk
1. **Network Latency on Remote Access**
   - **Impact:** Video streaming lag >1s
   - **Mitigation:** Implement adaptive video quality (JPEG compression)
   - **Fallback:** Static frame updates (1 FPS)

2. **Browser Audio API Compatibility**
   - **Impact:** Voice commands don't work on mobile
   - **Mitigation:** Test on multiple browsers, use WebRTC fallback
   - **Fallback:** Use laptop for voice commands

### Medium Risk
3. **NCNN Conversion Failures**
   - **Impact:** Models don't convert properly
   - **Mitigation:** Test conversion script before benchmarking
   - **Fallback:** Use PyTorch with reduced model size

4. **RPi 5 RAM Exhaustion**
   - **Impact:** System crashes during benchmarking
   - **Mitigation:** Monitor RAM during tests, use swap if needed
   - **Fallback:** Use smaller models (yolo11n instead of yolo11x)

### Low Risk
5. **NiceGUI Performance on RPi 5**
   - **Impact:** Dashboard sluggish
   - **Mitigation:** Optimize refresh rates, disable unnecessary features
   - **Fallback:** Use cortex_gui.py with X11 forwarding

---

## 📅 TIMELINE

### Week 1 (Days 1-3): Phase 1
- Day 1: Add missing features to dashboard (YOLOE modes, spatial audio, memory)
- Day 2: Optimize for RPi 5 headless (network binding, camera detection, resource limits)
- Day 3: Testing & validation (laptop, RPi, mobile)

### Week 1 (Days 4-5): Phase 2
- Day 4: Create benchmark framework + run initial tests
- Day 5: Generate visual reports + validate speedup claims

### Week 2 (Days 6-7): Phase 3
- Day 6: Integrate benchmarks into dashboard UI
- Day 7: Final testing + documentation

**Total Duration:** 7 days (assuming 4-6 hours/day)

---

## 🎯 DELIVERABLES

### Code Deliverables
1. `src/cortex_dashboard.py` - Feature-complete web dashboard
2. `tests/benchmark_models.py` - Automated benchmarking script
3. `tests/benchmark_config.yaml` - Model configurations
4. `tests/generate_benchmark_report.py` - HTML report generator
5. `docs/implementation/DASHBOARD-DEPLOYMENT-GUIDE.md` - Deployment instructions

### Documentation Deliverables
1. **User Guide:** How to access dashboard on RPi 5
2. **Benchmark Report:** PDF with charts + recommendations
3. **API Documentation:** Dashboard endpoints for external integrations

### Demo Deliverables (YIA 2026)
1. **Live Demo Script:** Step-by-step walkthrough
2. **Performance Slides:** Benchmark comparisons vs OrCam
3. **Video Recording:** 5-minute demo showcasing all features

---

## 🚀 NEXT STEPS

**AWAITING YOUR APPROVAL:**
Please review this implementation plan and let me know:

1. **Priority:** Which phase should we start with? (Recommend Phase 2 first for benchmark validation)
2. **Timeline:** Do you need this completed faster? (Can parallelize some tasks)
3. **Scope Changes:** Any features to add/remove?
4. **Hardware Availability:** Do you have RPi 5 ready for testing?

**Once approved, I will:**
1. Create all necessary files
2. Implement code changes systematically
3. Run tests and validate results
4. Generate final reports

**Estimated Total Effort:** 24-30 hours (can be split across multiple sessions)

---

## 📋 CHECKLIST FOR APPROVAL

Review this plan and confirm:
- [ ] I understand the 3-phase approach
- [ ] I approve the timeline (7 days)
- [ ] I have RPi 5 available for testing
- [ ] I approve the model benchmarking scope
- [ ] I want to proceed with implementation

**Ready to start? Just say "Approved, start with Phase [1/2/3]" and I'll begin! 🚀**
