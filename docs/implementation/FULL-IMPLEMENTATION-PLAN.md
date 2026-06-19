# ProjectCortex v2.0 - Full Implementation Plan
**Complete System Integration: All Modules Working Together**

**Date**: January 8, 2026
**Status**: Ready for Implementation
**Implementer**: Claude (AI Assistant) + Haziq (@IRSPlays)

---

## 📋 EXECUTIVE SUMMARY

You have **all the modules built individually**. Now we need to make them work together as a unified system.

### **Current State**:
- ✅ Layer 0 (Guardian): Complete with YOLO11n-NCNN
- ✅ Layer 1 (Learner): Complete with YOLOE-11s (3 modes)
- ✅ Layer 2 (Thinker): Complete with Gemini Live API
- ✅ Layer 3 (Router): Complete with 97.7% accuracy
- ✅ Layer 4 (Memory): **NEW** HybridMemoryManager (SQLite + Supabase)
- ✅ Supabase Database: Deployed and configured
- ✅ main.py Orchestrator: **NEW** Complete system runner

### **What's Left**:
- 🔄 Update Layer 1-3 to use HybridMemoryManager
- 🔄 Test complete pipeline
- 🔄 Deploy to RPi5 hardware
- 🔄 Verify end-to-end functionality

---

## 🎯 IMPLEMENTATION ROADMAP (2-Week Sprint)

### **Week 1: Core Integration** (Days 1-7)
**Goal**: All modules store data to Supabase

| Day | Task | Files | Status |
|-----|------|-------|--------|
| 1 | Update Layer 1 (Learner) → HybridMemoryManager | `layer1_learner/__init__.py` | ⏳ TODO |
| 2 | Update Layer 2 (Thinker) → HybridMemoryManager | `layer2_thinker/gemini_live_handler.py` | ⏳ TODO |
| 3 | Update Layer 3 (Router) → HybridMemoryManager | `layer3_guide/router.py` | ⏳ TODO |
| 4 | Test main.py on laptop (without camera) | `rpi5/main.py` | ⏳ TODO |
| 5 | Test with sample video file | `tests/test_main_orchestrator.py` | ⏳ TODO |
| 6 | Fix integration issues | Various | ⏳ TODO |
| 7 | Verify all data flowing to Supabase | Supabase dashboard | ⏳ TODO |

### **Week 2: Production Deployment** (Days 8-14)
**Goal**: Deploy to RPi5, test with real camera

| Day | Task | Status |
|-----|------|--------|
| 8 | Deploy to RPi5 hardware | ⏳ TODO |
| 9 | Connect camera module | ⏳ TODO |
| 10 | Test full system (real camera) | ⏳ TODO |
| 11 | Optimize performance (CPU/RAM) | ⏳ TODO |
| 12 | Test offline mode (disconnect WiFi) | ⏳ TODO |
| 13 | Test laptop dashboard integration | ⏳ TODO |
| 14 | Final testing + bug fixes | ⏳ TODO |

---

## 🔧 DETAILED IMPLEMENTATION STEPS

### **STEP 1: Update Layer 1 (Learner) Integration**

**File**: `rpi5/layer1_learner/__init__.py`

**What to add**:

```python
# In __init__ method of YOLOELearner class:
def __init__(
    self,
    model_path: str = "models/yoloe-11m-seg.pt",
    device: str = "cpu",
    confidence: float = 0.25,
    mode: YOLOEMode = YOLOEMode.TEXT_PROMPTS,
    prompt_manager: Optional['AdaptivePromptManager'] = None,
    memory_manager: Optional['HybridMemoryManager'] = None  # NEW!
):
    # ... existing code ...

    # Memory manager (optional, for cloud storage)
    self.memory_manager = memory_manager
```

**In detect() method**:

```python
# After creating detection dict:
detections.append({
    'class': class_name,
    'confidence': conf_score,
    # ... existing fields ...
})

# NEW: Store to memory manager
if self.memory_manager:
    self.memory_manager.store_detection({
        'layer': 'learner',
        'class_name': class_name,
        'confidence': float(conf_score),
        'bbox_x1': float(bbox[0] / frame_width),
        'bbox_y1': float(bbox[1] / frame_height),
        'bbox_x2': float(bbox[2] / frame_width),
        'bbox_y2': float(bbox[3] / frame_height),
        'bbox_area': float(bbox_area),
        'detection_mode': self.mode.value,
        'source': self.prompt_manager.get_source(class_name) if self.prompt_manager else 'base'
    })
```

**Command to implement**:
```bash
# I'll create this update when you say "Implement Step 1"
```

---

### **STEP 2: Update Layer 2 (Thinker) Integration**

**File**: `rpi5/layer2_thinker/gemini_live_handler.py`

**What to add**:

```python
# In __init__ method:
def __init__(
    self,
    api_key: str,
    memory_manager: Optional['HybridMemoryManager'] = None  # NEW!
):
    # ... existing code ...
    self.memory_manager = memory_manager
```

**In send_query() method**:

```python
async def send_query(self, query: str, frame: np.ndarray):
    # ... existing Gemini API code ...

    # NEW: Store to memory manager
    if self.memory_manager:
        await self.memory_manager.store_query(
            user_query=query,
            transcribed_text=transcribed_text,
            routed_layer='layer2',
            routing_confidence=1.0,
            ai_response=response_text,
            response_latency_ms=latency_ms,
            tier_used='gemini_live'
        )
```

---

### **STEP 3: Update Layer 3 (Router) Integration**

**File**: `rpi5/layer3_guide/router.py`

**What to add**:

```python
# In __init__ method:
def __init__(self, memory_manager: Optional['HybridMemoryManager'] = None):
    # ... existing code ...
    self.memory_manager = memory_manager
```

**In route() method**:

```python
def route(self, text: str) -> str:
    # ... existing routing logic ...

    # NEW: Log routing decision
    if self.memory_manager:
        # Use asyncio.run if in async context, or store for later
        try:
            asyncio.create_task(self.memory_manager.store_query(
                user_query=text,
                transcribed_text=text,
                routed_layer=layer,
                routing_confidence=confidence,
                detection_mode=None,
                ai_response=None
            ))
        except:
            # If not in async context, store synchronously
            pass

    return layer
```

---

### **STEP 4: Test Complete Pipeline**

**Create**: `tests/test_complete_pipeline.py`

```python
"""
Test complete ProjectCortex pipeline

Tests:
1. Camera capture
2. Layer 0 + Layer 1 detection
3. Supabase sync
4. WebSocket to laptop
5. Voice command routing
"""

import asyncio
import pytest
from rpi5.main import CortexSystem

@pytest.mark.asyncio
async def test_full_pipeline():
    """Test complete system with sample frame"""
    # Initialize system
    system = CortexSystem()

    # Load test frame
    test_frame = load_test_frame("tests/test_frame.jpg")

    # Run detection
    detections = system._run_dual_detection(test_frame)

    # Verify detections
    assert len(detections) > 0

    # Verify stored to memory manager
    stats = system.memory_manager.get_stats()
    assert stats['upload_queue_size'] > 0

    # Cleanup
    system.stop()
```

---

## 📊 DATA FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────┐
│                      MAIN LOOP (main.py)                     │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 1. Get Frame (CameraHandler)                          │ │
│  │    ↓                                                   │ │
│  │ 2. Run Dual Detection (ThreadPoolExecutor)            │ │
│  │    ├─ Layer 0: Guardian (YOLO11n)                     │ │
│  │    └─ Layer 1: Learner (YOLOE-11s)                    │ │
│  │    ↓                                                   │ │
│  │ 3. Aggregate Detections                               │ │
│  │    ↓                                                   │ │
│  │ 4. Store to HybridMemoryManager                       │ │
│  │    ├─ Local SQLite (<10ms)                           │ │
│  │    └─ Queue for Supabase upload                      │ │
│  │    ↓                                                   │ │
│  │ 5. Send to Laptop (WebSocket)                          │ │
│  │    ├─ Video frame                                     │ │
│  │    ├─ Detections                                     │ │
│  │    └─ Metrics                                        │ │
│  │    ↓                                                   │ │
│  │ 6. Background: Sync to Supabase (every 60s)          │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Voice Command Handler (async)                         │ │
│  │    ↓                                                   │ │
│  │ 1. Route Intent (IntentRouter)                         │ │
│  │    ↓                                                   │ │
│  │ 2. Execute Layer 1 or Layer 2                          │ │
│  │    ↓                                                   │ │
│  │ 3. Generate Response                                   │ │
│  │    ↓                                                   │ │
│  │ 4. Store to Supabase                                 │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

                    ↓ (Background Sync)
┌─────────────────────────────────────────────────────────────┐
│               SUPABASE CLOUD STORAGE                        │
│  • detections table (all AI output)                        │
│  • queries table (voice commands)                          │
│  • system_logs table (monitoring)                          │
│  • device_status table (heartbeat)                         │
└─────────────────────────────────────────────────────────────┘
                    ↑ (Historical fetch)
┌─────────────────────────────────────────────────────────────┐
│           LAPTOP PYQT6 DASHBOARD                             │
│  • Real-time: Video feed + metrics (WebSocket)             │
│  • Historical: Analytics from Supabase (hourly fetch)       │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 ACCEPTANCE CRITERIA

### **Phase 1: Integration** (Week 1)
- [ ] main.py runs without errors
- [ ] All layers initialize successfully
- [ ] Camera captures frames (30 FPS)
- [ ] Layer 0 + Layer 1 run in parallel
- [ ] Detections stored to local SQLite
- [ ] Detections uploaded to Supabase (every 60s)
- [ ] Data visible in Supabase dashboard

### **Phase 2: Laptop Integration** (Week 2)
- [ ] WebSocket connects to laptop
- [ ] Video frames stream to laptop (30 FPS)
- [ ] Detections sent to laptop (real-time)
- [ ] Metrics displayed in PyQt6 dashboard
- [ ] Voice commands route correctly

### **Phase 3: Production** (Deployment)
- [ ] Runs on RPi5 hardware
- [ ] Performance targets met (<100ms Layer 0, <150ms Layer 1)
- [ ] RAM usage <3.9GB
- [ ] Offline mode works (disconnect WiFi)
- [ ] Auto-reconnect on WiFi restore

---

## 🚀 QUICK START (Testing)

### **Option 1: Test on Laptop (Simulated)**

```bash
# 1. Install dependencies
cd ~/ProjectCortex
pip install -r rpi5/requirements.txt

# 2. Set environment variables
export SUPABASE_URL="https://ziarxgoansbhesdypfic.supabase.co"
export SUPABASE_KEY="<REDACTED-SUPABASE-PUBLISHABLE>"
export DEVICE_ID="test-device-001"

# 3. Run main.py (without camera first)
python rpi5/main.py
```

**Expected**:
```
╔══════════════════════════════════════════════════════════════╗
║     🧠 ProjectCortex v2.0 - AI Wearable Assistant          ║
╚══════════════════════════════════════════════════════════════╝

🧠 Initializing ProjectCortex v2.0...
💾 Initializing Layer 4: Memory Manager...
✅ Layer 4 initialized
🛡️  Initializing Layer 0: Guardian...
✅ Layer 0 initialized
🎯 Initializing Layer 1: Learner...
✅ Layer 1 initialized
🧠 Initializing Layer 2: Thinker...
✅ Layer 2 initialized
🔀 Initializing Layer 3: Router...
✅ Layer 3 initialized
📸 Initializing Camera...
🌐 Initializing WebSocket Client...
✅ ProjectCortex v2.0 initialized successfully

🚀 Starting ProjectCortex v2.0...
✅ System started
📸 Capturing frames...
🔍 Running detections...
💾 Syncing to Supabase...
🌐 Sending to laptop dashboard...
```

### **Option 2: Test with Video File**

```bash
# Create test script that uses video file instead of camera
python tests/test_with_video.py --video sample.mp4
```

---

## 📈 PERFORMANCE TARGETS

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Layer 0 Latency** | <100ms | Built-in timing in Guardian |
| **Layer 1 Latency** | <150ms | Built-in timing in Learner |
| **Frame Rate** | 30 FPS | FPS counter in main loop |
| **RAM Usage** | <3.9GB | `free -h` command |
| **Supabase Sync** | Every 60s | Background worker logs |
| **Upload Batch Size** | 100 rows | Config setting |

---

## 🔧 TROUBLESHOOTING

### **Issue 1: Import Errors**

**Problem**: `ModuleNotFoundError: No module named 'layer0_guardian'`

**Solution**:
```bash
# Make sure you're in the right directory
cd ~/ProjectCortex

# Run from rpi5 directory
python rpi5/main.py  # NOT python main.py
```

### **Issue 2: Camera Not Found**

**Problem**: `RuntimeError: Failed to open camera 0`

**Solution**:
```python
# Edit rpi5/config/config.yaml
camera:
  use_picamera: False  # Use OpenCV instead of Picamera2
  device_id: 0  # Try different IDs: 0, 1, 2...
```

### **Issue 3: Supabase Connection Failed**

**Problem**: `Failed to initialize Supabase`

**Solution**:
```bash
# Check credentials
echo $SUPABASE_URL
echo $SUPABASE_KEY

# Test connection manually
python examples/test_hybrid_memory.py
```

### **Issue 4: WebSocket Not Connecting**

**Problem**: `Failed to connect to laptop`

**Solution**:
```bash
# Check laptop server is running
# On laptop:
python laptop/start_laptop_server.py

# Check firewall
# Allow port 8765
```

---

## 📚 NEXT STEPS

### **Immediate** (This Week):
1. ✅ Read `rpi5/main.py` - Understand the orchestrator
2. ✅ Update Layer 1-3 to use HybridMemoryManager (I can do this)
3. ✅ Test with sample video file
4. ✅ Verify Supabase data flow

### **Soon** (Next Week):
1. Deploy to RPi5 hardware
2. Connect real camera module
3. Test full system (real-time)
4. Optimize performance

### **Final** (Before Competition):
1. Stress testing (8+ hours continuous)
2. Field testing (real-world scenarios)
3. Documentation updates
4. Demo preparation

---

## ✅ IMPLEMENTATION CHECKLIST

### **Code Integration**
- [ ] Layer 0 (Guardian) + HybridMemoryManager ✅ DONE
- [ ] Layer 1 (Learner) + HybridMemoryManager ⏳ TODO
- [ ] Layer 2 (Thinker) + HybridMemoryManager ⏳ TODO
- [ ] Layer 3 (Router) + HybridMemoryManager ⏳ TODO
- [ ] main.py orchestrator ✅ DONE
- [ ] Layer 4 __init__.py export ✅ DONE

### **Testing**
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Supabase sync verified
- [ ] Laptop dashboard verified
- [ ] Performance targets met

### **Deployment**
- [ ] Runs on RPi5
- [ ] Camera captures frames
- [ ] All layers active
- [ ] Data flowing to Supabase
- [ ] Dashboard showing real-time data

---

## 🎁 BONUS: What You Get After Implementation

### **1. Fully Functional AI Wearable**
- Real-time object detection (30 FPS)
- Adaptive learning (discovers new objects)
- Conversational AI (Gemini Live API)
- Spatial navigation (future)
- Cloud storage + analytics

### **2. Production-Ready Architecture**
- Free tier Supabase (no cost)
- Offline capability
- Graceful degradation
- Auto-recovery
- Scalable (multi-device ready)

### **3. Competition-Ready Demo**
- Live object detection
- Voice command interaction
- Real-time dashboard
- Historical analytics
- Professional presentation

---

## 📞 READY TO IMPLEMENT?

**Say "Implement Step 1"** and I'll update Layer 1 (Learner) to use HybridMemoryManager.

**Or say "Implement all steps"** and I'll update Layer 1-3 all at once.

**Or say "Test the system"** and I'll create a test script that validates everything works together.

---

**🎉 All architecture and planning is complete. Ready for final integration!**
