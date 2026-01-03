# Flask Dashboard Architecture - Implementation Plan

**Date:** January 2, 2026  
**Author:** Haziq + GitHub Copilot  
**Status:** Planning Phase  
**Priority:** HIGH - Critical for YIA 2026 Demo  
**⚠️ IMPORTANT:** Based ONLY on proven `cortex_gui.py` architecture (NOT buggy `cortex_dashboard.py`)

---

## 🎯 OBJECTIVE

Restructure the dashboard system from **NiceGUI** to **Flask** with multi-threading, using the **proven architecture from `cortex_gui.py`** which successfully runs all AI layers.

### Why Flask?
1. **Proven Stability:** Flask is battle-tested for production systems (vs NiceGUI's beta status)
2. **Familiar Pattern:** `cortex_gui.py` already uses CustomTkinter with multi-threading (**works reliably**)
3. **Better Control:** Direct control over MJPEG streaming and threading
4. **Lower Overhead:** Flask is lightweight (~100MB RAM vs NiceGUI's ~200MB)
5. **Native MJPEG:** Built-in support for video streaming via generators

### ⚠️ Critical Change
**DO NOT** use code from `cortex_dashboard.py` - it has known threading bugs and unreliable state management. **ONLY** use patterns from `cortex_gui.py` which has been tested and confirmed working for all layers (Guardian, Learner, Whisper, Kokoro, Gemini, VAD, Spatial Audio).

---

## 📊 PROVEN ARCHITECTURE ANALYSIS

### Working System: `cortex_gui.py` (CustomTkinter + Threading)
**Components:**
- `ProjectCortexGUI` class (main application)
- **3 Background Threads:**
  1. `video_capture_thread()` - Camera capture (30 FPS)
  2. `yolo_processing_thread()` - Dual YOLO inference (Layer 0 + Layer 1)
  3. Audio processing threads (VAD, recording)
- **Thread-Safe Queues:**
  - `frame_queue` (Queue maxsize=2) - Raw frames from camera
  - `processed_frame_queue` (Queue maxsize=2) - Annotated frames for UI
  - `status_queue` (Queue) - Status messages
  - `detection_queue` (Queue) - Detection strings
- **Lazy-Loaded AI Handlers:**
  - `dual_yolo` (DualYOLOHandler) - Guardian + Learner
  - `whisper_stt` (WhisperSTT) - Speech-to-text
  - `kokoro_tts` (KokoroTTS) - Text-to-speech
  - `gemini_tts` (GeminiTTS) - Gemini 2.5 Flash Vision
  - `gemini_live` (GeminiLiveHandler) - Live API WebSocket
  - `vad_handler` (VADHandler) - Voice Activity Detection
  - `spatial_audio` (SpatialAudioManager) - 3D Audio Navigation

**Architecture Diagram:**
```
┌──────────────────────────────────────────────────────────┐
│        cortex_gui.py (Tkinter Application)               │
│  ┌────────────────────────────────────────────────────┐  │
│  │  ProjectCortexGUI Class                            │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │  video_capture_thread (30 FPS)               │  │  │
│  │  │  - Picamera2 or OpenCV                       │  │  │
│  │  │  - frame_queue.put(frame)                    │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  │                     ↓                                │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │  yolo_processing_thread                      │  │  │
│  │  │  1. frame_queue.get(timeout=1)               │  │  │
│  │  │  2. dual_yolo.process_frame()                │  │  │
│  │  │     - Guardian (Layer 0): 80 classes [RED]   │  │  │
│  │  │     - Learner (Layer 1): 15-100 classes [GRN]│ │  │
│  │  │  3. Annotate frame with both layers          │  │  │
│  │  │  4. processed_frame_queue.put(annotated)     │  │  │
│  │  │  5. detection_queue.put(detections_str)      │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  │                     ↓                                │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │  update_video() (Main Thread, 15ms timer)    │  │  │
│  │  │  - processed_frame_queue.get_nowait()        │  │  │
│  │  │  - Display on Tkinter Canvas                 │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  │                                                      │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │  update_status() (100ms timer)                │  │  │
│  │  │  - status_queue.get_nowait()                  │  │  │
│  │  │  - Update status label                        │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  │                                                      │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │  update_detections() (100ms timer)            │  │  │
│  │  │  - detection_queue.get_nowait()               │  │  │
│  │  │  - Store self.last_detections                 │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**Key Success Factors:**
- ✅ **Queue-based communication** (thread-safe, no locks needed)
- ✅ **Lazy loading** (models load on first use, not startup)
- ✅ **Non-blocking UI** (queues with `get_nowait()` + `Empty` exception)
- ✅ **Automatic fallback** (Picamera2 → OpenCV, GPU → CPU)
- ✅ **Exception handling** (every thread has try/except + continue)

---

## 🏗️ PROPOSED FLASK ARCHITECTURE

### Design Philosophy
**Replicate `cortex_gui.py` Threading Model in Flask:**
- ✅ Use same 3-thread architecture (Camera → YOLO → Display)
- ✅ Use same Queue-based communication (no locks, no shared state dicts)
- ✅ Use same lazy-loading pattern for AI models
- ✅ Replace Tkinter UI with Flask web endpoints
- ✅ Use MJPEG streaming for video (generator yielding from `processed_frame_queue`)
- ✅ Use Server-Sent Events (SSE) for live metrics (polling `status_queue`)

### System Diagram
```
┌─────────────────────────────────────────────────────────────────┐
│              Flask Web Server (Port 5000)                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │        Application Factory (create_app)                    │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  CortexCore (Replaces ProjectCortexGUI logic)       │  │  │
│  │  │  ┌──────────────────────────────────────────────┐   │  │  │
│  │  │  │  video_capture_thread (30 FPS)               │   │  │  │
│  │  │  │  - Picamera2 / OpenCV auto-detection        │   │  │  │
│  │  │  │  - frame_queue.put(frame)                    │   │  │  │
│  │  │  └──────────────────────────────────────────────┘   │  │  │
│  │  │  ┌──────────────────────────────────────────────┐   │  │  │
│  │  │  │  yolo_processing_thread                      │   │  │  │
│  │  │  │  1. frame = frame_queue.get(timeout=1)       │   │  │  │
│  │  │  │  2. g_res, l_res = dual_yolo.process()       │   │  │  │
│  │  │  │  3. Annotate frame (RED + GREEN boxes)       │   │  │  │
│  │  │  │  4. processed_frame_queue.put(annotated)     │   │  │  │
│  │  │  │  5. detection_queue.put(detections_str)      │   │  │  │
│  │  │  │  6. metrics_queue.put(fps, latency, etc.)    │   │  │  │
│  │  │  └──────────────────────────────────────────────┘   │  │  │
│  │  │  ┌──────────────────────────────────────────────┐   │  │  │
│  │  │  │  Queues (Thread-Safe)                        │   │  │  │
│  │  │  │  - frame_queue (maxsize=2)                   │   │  │  │
│  │  │  │  - processed_frame_queue (maxsize=2)         │   │  │  │
│  │  │  │  - status_queue (unbounded)                  │   │  │  │
│  │  │  │  - detection_queue (unbounded)               │   │  │  │
│  │  │  │  - metrics_queue (unbounded)                 │   │  │  │
│  │  │  └──────────────────────────────────────────────┘   │  │  │
│  │  │  ┌──────────────────────────────────────────────┐   │  │  │
│  │  │  │  AI Handlers (Lazy-Loaded)                   │   │  │  │
│  │  │  │  - dual_yolo: DualYOLOHandler (on demand)    │   │  │  │
│  │  │  │  - whisper_stt: WhisperSTT (first use)       │   │  │  │
│  │  │  │  - kokoro_tts: KokoroTTS (first TTS)         │   │  │  │
│  │  │  │  - gemini_tts: GeminiTTS (first query)       │   │  │  │
│  │  │  │  - vad_handler: VADHandler (voice activation)│   │  │  │
│  │  │  │  - spatial_audio: SpatialAudioManager (3D)   │   │  │  │
│  │  │  └──────────────────────────────────────────────┘   │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Flask Blueprints (RESTful)                    │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  main_bp: Static Pages                              │  │  │
│  │  │  - GET /             → dashboard.html               │  │  │
│  │  │  - GET /static/*     → CSS, JS, assets              │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  api_bp: REST API                                   │  │  │
│  │  │  - POST /api/query   → Send user text query         │  │  │
│  │  │  - POST /api/voice   → Upload WAV audio (base64)    │  │  │
│  │  │  - GET /api/status   → Current detections (JSON)    │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  stream_bp: Real-Time Streams                       │  │  │
│  │  │  - GET /stream/video → MJPEG (yield from queue)     │  │  │
│  │  │  - GET /stream/metrics → SSE (poll queues @ 2Hz)    │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│                Web Browser (Client)                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  dashboard.html (Biotech UI from code.html)               │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  <img id="video" src="/stream/video">              │  │  │
│  │  │  → MJPEG auto-updates (browser-native)             │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  EventSource("/stream/metrics")                     │  │  │
│  │  │  → Updates FPS, CPU, detections every 500ms        │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  fetch("/api/query", {text: "..."})                 │  │  │
│  │  │  → Send user queries                                │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 TECHNICAL IMPLEMENTATION

### 1. Application Factory Pattern
**File:** `src/flask_app/app.py`

```python
from flask import Flask
from flask_app.blueprints import main_bp, api_bp, stream_bp
from flask_app.cortex_core import get_cortex_core
import os
import logging

logger = logging.getLogger(__name__)

def create_app(config=None):
    """Create and configure Flask application."""
    app = Flask(
        __name__,
        static_folder='flask_app/static',
        template_folder='flask_app/templates'
    )
    
    # Configuration
    app.config.from_mapping(
        SECRET_KEY=os.getenv('SECRET_KEY', 'cortex_dev_2026'),
        TEMPLATES_AUTO_RELOAD=True,
        JSON_SORT_KEYS=False,
    )
    
    if config:
        app.config.update(config)
    
    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(stream_bp, url_prefix='/stream')
    
    # Initialize Cortex Core on first request
    @app.before_request
    def init_cortex():
        core = get_cortex_core()
        if not core.is_running:
            core.start()  # Starts background threads (camera + yolo)
    
    # Cleanup on shutdown
    @app.teardown_appcontext
    def shutdown_cortex(exception=None):
        core = get_cortex_core()
        if core.is_running:
            core.stop()
    
    logger.info("✅ Flask app created")
    return app
```

---

### 2. Core Logic (Direct Port from `cortex_gui.py`)
**File:** `src/flask_app/cortex_core.py`

```python
import threading
import queue
import time
import cv2
import logging
from collections import deque
from datetime import datetime

from dual_yolo_handler import DualYOLOHandler
from layer1_reflex.detection_aggregator import DetectionAggregator
from layer1_reflex.whisper_handler import WhisperSTT
from layer1_reflex.kokoro_handler import KokoroTTS
from layer2_thinker.gemini_tts_handler import GeminiTTS
from layer2_thinker.gemini_live_handler import GeminiLiveManager
from layer1_reflex.vad_handler import VADHandler

logger = logging.getLogger(__name__)

# Configuration (from environment variables)
YOLO_MODEL_PATH = 'models/yolo11n_ncnn_model'
YOLOE_LEARNER_PATH = 'models/yoloe-11s-seg.pt'
YOLO_DEVICE = 'cpu'
YOLO_CONFIDENCE = 0.5

class CortexCore:
    """
    Core logic extracted from cortex_gui.py ProjectCortexGUI class.
    Runs background threads for camera capture and YOLO processing.
    Uses queues for thread-safe communication (NO LOCKS).
    """
    
    def __init__(self):
        # AI Handlers (lazy-loaded)
        self.dual_yolo = None
        self.aggregator = DetectionAggregator()
        self.whisper_stt = None
        self.kokoro_tts = None
        self.gemini_tts = None
        self.vad_handler = None
        
        # Camera
        self.cap = None
        self.picamera2 = None
        self.is_running = False
        
        # Thread-safe queues (same as cortex_gui.py)
        self.frame_queue = queue.Queue(maxsize=2)
        self.processed_frame_queue = queue.Queue(maxsize=2)
        self.status_queue = queue.Queue()
        self.detection_queue = queue.Queue()
        self.metrics_queue = queue.Queue()  # NEW: For FPS, CPU, RAM, etc.
        
        # Detection tracking
        self.last_detections = "nothing detected"
        self.last_learner_detections = []
        self.last_guardian_detections = []
        
        # Threads
        self._threads = []
        self._stop_event = threading.Event()
        
        logger.info("✅ CortexCore initialized")
    
    def start(self):
        """Start camera and YOLO processing threads."""
        if self.is_running:
            return
        
        self.is_running = True
        self._stop_event.clear()
        
        logger.info("🚀 Starting Cortex Core threads...")
        
        # Load YOLO models (blocking, done once)
        self._load_yolo()
        
        # Initialize camera
        self._init_camera()
        
        # Start background threads
        self._threads = [
            threading.Thread(target=self._video_capture_thread, daemon=True, name="CameraThread"),
            threading.Thread(target=self._yolo_processing_thread, daemon=True, name="YOLOThread"),
        ]
        
        for t in self._threads:
            t.start()
        
        logger.info("✅ All threads started")
    
    def stop(self):
        """Stop all threads and release resources."""
        logger.info("🛑 Stopping Cortex Core...")
        self.is_running = False
        self._stop_event.set()
        
        # Release camera
        if self.cap:
            self.cap.release()
        if self.picamera2:
            self.picamera2.stop()
        
        # Wait for threads to finish
        for t in self._threads:
            t.join(timeout=2.0)
        
        logger.info("✅ Cortex Core stopped")
    
    def _load_yolo(self):
        """Load Dual YOLO Handler (Guardian + Learner)."""
        try:
            logger.info("📦 Loading Dual YOLO Handler...")
            self.dual_yolo = DualYOLOHandler(
                guardian_model_path=YOLO_MODEL_PATH,
                learner_model_path=YOLOE_LEARNER_PATH,
                device=YOLO_DEVICE,
                max_workers=2,
                learner_mode='TEXT_PROMPTS'  # Default mode
            )
            self.status_queue.put("✅ YOLO models loaded")
            logger.info("✅ Dual YOLO ready")
        except Exception as e:
            logger.error(f"❌ YOLO loading failed: {e}")
            self.status_queue.put(f"❌ YOLO failed: {e}")
    
    def _init_camera(self):
        """Initialize camera (Picamera2 or OpenCV fallback)."""
        try:
            # Try Picamera2 first (Raspberry Pi)
            from picamera2 import Picamera2
            logger.info("📹 Initializing Picamera2...")
            self.picamera2 = Picamera2()
            config = self.picamera2.create_preview_configuration(
                main={"size": (640, 480), "format": "RGB888"}
            )
            self.picamera2.configure(config)
            self.picamera2.start()
            self.status_queue.put("✅ Picamera2 connected")
            logger.info("✅ Picamera2 ready")
        except Exception as e:
            logger.warning(f"Picamera2 failed: {e}, using OpenCV")
            # Fallback to OpenCV webcam
            self.cap = cv2.VideoCapture(0)
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.status_queue.put("✅ Webcam connected")
                logger.info("✅ Webcam ready")
            else:
                logger.error("❌ Failed to open webcam")
                self.status_queue.put("❌ Camera failed")
    
    def _video_capture_thread(self):
        """Capture frames at 30 FPS (exact copy from cortex_gui.py)."""
        logger.info("🎥 Camera thread started")
        
        while not self._stop_event.is_set():
            try:
                # Capture frame (Picamera2 or OpenCV)
                if self.picamera2:
                    frame = self.picamera2.capture_array()
                elif self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if not ret:
                        time.sleep(0.1)
                        continue
                else:
                    time.sleep(0.1)
                    continue
                
                # Put in queue (non-blocking)
                if not self.frame_queue.full():
                    self.frame_queue.put(frame, block=False)
                
                time.sleep(1/30)  # 30 FPS
                
            except Exception as e:
                logger.error(f"Camera error: {e}")
                time.sleep(1)
        
        logger.info("🛑 Camera thread stopped")
    
    def _yolo_processing_thread(self):
        """
        YOLO inference thread (exact copy from cortex_gui.py).
        Processes frames and creates annotated output.
        """
        logger.info("🧠 YOLO thread started")
        
        frame_count = 0
        fps_counter = deque(maxlen=30)
        
        while not self._stop_event.is_set():
            try:
                # Get frame (blocking with timeout)
                frame = self.frame_queue.get(timeout=1)
                start_time = time.time()
                frame_count += 1
                
                # Run Dual YOLO inference
                if self.dual_yolo:
                    g_results, l_results = self.dual_yolo.process_frame(frame, confidence=YOLO_CONFIDENCE)
                    
                    # Annotate frame
                    annotated_frame = frame.copy()
                    guardian_detections = []
                    learner_detections = []
                    
                    # Draw Guardian detections (RED)
                    if g_results and hasattr(g_results, 'boxes') and g_results.boxes is not None:
                        for box in g_results.boxes:
                            conf = float(box.conf)
                            if conf > YOLO_CONFIDENCE:
                                cls_id = int(box.cls)
                                cls_name = self.dual_yolo.guardian.model.names[cls_id]
                                guardian_detections.append(f"{cls_name} ({conf:.2f})")
                                
                                # Draw RED box
                                bbox = box.xyxy[0].cpu().numpy().astype(int)
                                x1, y1, x2, y2 = bbox
                                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                                label = f"[G] {cls_name} {conf:.2f}"
                                cv2.putText(annotated_frame, label, (x1, y1-10), 
                                          cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    
                    # Draw Learner detections (GREEN)
                    if l_results and hasattr(l_results, 'boxes') and l_results.boxes is not None:
                        for box in l_results.boxes:
                            conf = float(box.conf)
                            if conf > YOLO_CONFIDENCE:
                                cls_id = int(box.cls)
                                cls_name = l_results.names[cls_id] if hasattr(l_results, 'names') else f"class_{cls_id}"
                                learner_detections.append(f"{cls_name} ({conf:.2f})")
                                
                                # Draw GREEN box
                                bbox = box.xyxy[0].cpu().numpy().astype(int)
                                x1, y1, x2, y2 = bbox
                                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                label = f"[L] {cls_name} {conf:.2f}"
                                cv2.putText(annotated_frame, label, (x1, max(y2+20, y1-10)), 
                                          cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    
                    # Add legend
                    cv2.putText(annotated_frame, "[G] Guardian (Safety)", (10, 30), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    cv2.putText(annotated_frame, "[L] Learner (Context)", (10, 60), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    
                    # Store detections
                    self.last_guardian_detections = guardian_detections
                    self.last_learner_detections = learner_detections
                    
                    # Update detection string
                    detections_str = ", ".join(sorted(set(guardian_detections))) or "nothing"
                    self.detection_queue.put(detections_str)
                    self.last_detections = detections_str
                    
                    # Calculate metrics
                    latency_ms = (time.time() - start_time) * 1000
                    fps_counter.append(1.0 / (time.time() - start_time))
                    avg_fps = sum(fps_counter) / len(fps_counter) if fps_counter else 0
                    
                    # Put metrics in queue
                    self.metrics_queue.put({
                        'fps': avg_fps,
                        'latency': latency_ms,
                        'frame_count': frame_count,
                        'detections': detections_str
                    })
                    
                    # Put annotated frame in queue (clear old if full)
                    if self.processed_frame_queue.full():
                        try:
                            self.processed_frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    self.processed_frame_queue.put(annotated_frame)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"YOLO processing error: {e}")
                time.sleep(1)
        
        logger.info("🛑 YOLO thread stopped")
    
    # Lazy-loading methods (same as cortex_gui.py)
    def init_whisper_stt(self):
        """Initialize Whisper STT on demand."""
        if self.whisper_stt is None:
            try:
                logger.info("⏳ Loading Whisper STT...")
                self.whisper_stt = WhisperSTT(model_size="base")
                self.whisper_stt.load_model()
                logger.info("✅ Whisper STT ready")
                return True
            except Exception as e:
                logger.error(f"❌ Whisper init failed: {e}")
                return False
        return True
    
    def init_kokoro_tts(self):
        """Initialize Kokoro TTS on demand."""
        if self.kokoro_tts is None:
            try:
                logger.info("⏳ Loading Kokoro TTS...")
                self.kokoro_tts = KokoroTTS(lang_code="a", default_voice="af_alloy")
                self.kokoro_tts.load_pipeline()
                logger.info("✅ Kokoro TTS ready")
                return True
            except Exception as e:
                logger.error(f"❌ Kokoro init failed: {e}")
                return False
        return True


# Singleton accessor
_core_instance = None

def get_cortex_core():
    """Get or create CortexCore instance (singleton)."""
    global _core_instance
    if _core_instance is None:
        _core_instance = CortexCore()
    return _core_instance
```

---

### 3. Flask Blueprints

#### 3.1 Main Blueprint (Static Pages)
**File:** `src/flask_app/blueprints/main_routes.py`

```python
from flask import Blueprint, render_template

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Serve main dashboard HTML."""
    return render_template('dashboard.html')

@main_bp.route('/health')
def health():
    """Health check endpoint."""
    return {'status': 'ok'}, 200
```

#### 3.2 API Blueprint (REST Endpoints)
**File:** `src/flask_app/blueprints/api_routes.py`

```python
from flask import Blueprint, jsonify, request
from flask_app.cortex_core import get_cortex_core
import queue
import logging

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__)

@api_bp.route('/status')
def get_status():
    """Get system status (non-blocking, queue-based)."""
    core = get_cortex_core()
    
    # Read from queues (non-blocking - cortex_gui.py pattern)
    status_msg = None
    try:
        status_msg = core.status_queue.get_nowait()
    except queue.Empty:
        pass
    
    # Get latest metrics (drain queue to get most recent)
    metrics = {'fps': 0, 'latency': 0, 'detections': 'Initializing...'}
    try:
        while True:
            metrics = core.metrics_queue.get_nowait()
    except queue.Empty:
        pass
    
    return jsonify({
        'running': core.is_running,
        'fps': round(metrics.get('fps', 0), 2),
        'latency': round(metrics.get('latency', 0), 2),
        'detections': metrics.get('detections', 'N/A'),
        'status_message': status_msg
    })

@api_bp.route('/control/start', methods=['POST'])
def start_system():
    """Start Cortex Core (camera + YOLO threads)."""
    core = get_cortex_core()
    if not core.is_running:
        core.start()
        return jsonify({'status': 'started'}), 200
    return jsonify({'status': 'already_running'}), 200

@api_bp.route('/control/stop', methods=['POST'])
def stop_system():
    """Stop Cortex Core."""
    core = get_cortex_core()
    if core.is_running:
        core.stop()
        return jsonify({'status': 'stopped'}), 200
    return jsonify({'status': 'not_running'}), 200

@api_bp.route('/control/yolo/<mode>', methods=['POST'])
def set_yolo_mode(mode):
    """Switch YOLOE mode: TEXT_PROMPTS, IMAGE_PROMPTS, MEMORY."""
    core = get_cortex_core()
    
    if core.dual_yolo and hasattr(core.dual_yolo, 'learner'):
        try:
            valid_modes = ['TEXT_PROMPTS', 'IMAGE_PROMPTS', 'MEMORY']
            mode_upper = mode.upper()
            
            if mode_upper not in valid_modes:
                return jsonify({'error': f'Invalid mode. Use: {valid_modes}'}), 400
            
            core.dual_yolo.learner.set_mode(mode_upper)
            logger.info(f"✅ Mode changed: {mode_upper}")
            return jsonify({'status': 'ok', 'mode': mode_upper}), 200
            
        except Exception as e:
            logger.error(f"❌ Mode switch failed: {e}")
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'YOLO not initialized'}), 500
```

#### 3.3 Stream Blueprint (Real-Time Data)
**File:** `src/flask_app/blueprints/stream_routes.py`

```python
from flask import Blueprint, Response
import time
import json
import cv2
import queue
import logging

from flask_app.cortex_core import get_cortex_core

logger = logging.getLogger(__name__)

stream_bp = Blueprint('stream', __name__)

@stream_bp.route('/video')
def video_stream():
    """
    MJPEG video stream (multipart/x-mixed-replace).
    Reads from processed_frame_queue (non-blocking - cortex_gui.py pattern).
    """
    
    def generate():
        core = get_cortex_core()
        frame_count = 0
        
        while True:
            try:
                # Get frame (non-blocking - cortex_gui.py pattern)
                try:
                    frame = core.processed_frame_queue.get_nowait()
                    frame_count += 1
                    
                    # Encode JPEG
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    jpeg_bytes = buffer.tobytes()
                    
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
                    
                except queue.Empty:
                    # No frame available, wait
                    time.sleep(1/30)  # 30 FPS max polling rate
                    continue
                
            except GeneratorExit:
                logger.info(f"🛑 Video stream closed ({frame_count} frames)")
                break
            except Exception as e:
                logger.error(f"❌ Stream error: {e}")
                break
    
    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@stream_bp.route('/metrics')
def metrics_stream():
    """
    Server-Sent Events (SSE) for metrics updates.
    Polls metrics_queue at 2 Hz (non-blocking - cortex_gui.py pattern).
    """
    
    def generate():
        core = get_cortex_core()
        
        while True:
            try:
                # Get latest metrics (drain queue to get most recent)
                metrics = {'fps': 0, 'latency': 0, 'detections': 'N/A'}
                try:
                    while True:
                        metrics = core.metrics_queue.get_nowait()
                except queue.Empty:
                    pass
                
                # Send SSE event
                data = json.dumps({
                    'fps': round(metrics.get('fps', 0), 2),
                    'latency': round(metrics.get('latency', 0), 2),
                    'detections': metrics.get('detections', 'N/A'),
                    'frame_count': metrics.get('frame_count', 0),
                    'timestamp': time.time()
                })
                
                yield f'data: {data}\n\n'
                time.sleep(0.5)  # 2 Hz polling
                
            except GeneratorExit:
                logger.info("🛑 SSE stream closed")
                break
            except Exception as e:
                logger.error(f"❌ SSE error: {e}")
                time.sleep(1)
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )
```

**File:** `src/flask_app/blueprints/__init__.py`

```python
from .main_routes import main_bp
from .api_routes import api_bp
from .stream_routes import stream_bp

__all__ = ['main_bp', 'api_bp', 'stream_bp']
```

---

### 4. HTML Template
**File:** `src/flask_app/templates/dashboard.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Project Cortex Dashboard</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <div class="container">
        <!-- Video Feed -->
        <div class="video-panel">
            <img id="videoFeed" src="/stream/video" alt="Camera Feed">
        </div>
        
        <!-- Metrics Panel -->
        <div class="metrics-panel">
            <div class="metric">
                <span>FPS:</span>
                <span id="fps">0</span>
            </div>
            <div class="metric">
                <span>CPU:</span>
                <span id="cpu">0%</span>
            </div>
            <div class="metric">
                <span>RAM:</span>
                <span id="ram">0 MB</span>
            </div>
            <div class="metric">
                <span>Temp:</span>
                <span id="temp">0°C</span>
            </div>
        </div>
        
        <!-- Detections -->
        <div class="detections-panel">
            <h3>Detections</h3>
            <p id="detections">Initializing...</p>
        </div>
        
        <!-- Chat Input -->
        <div class="chat-panel">
            <input type="text" id="queryInput" placeholder="Ask me anything...">
            <button onclick="sendQuery()">Send</button>
            <button onclick="recordVoice()">🎤 Record</button>
        </div>
    </div>
    
    <script src="{{ url_for('static', filename='js/dashboard.js') }}"></script>
</body>
</html>
```

---

### 5. JavaScript Client
**File:** `src/flask_app/static/js/dashboard.js`

```javascript
// Server-Sent Events for metrics
const eventSource = new EventSource('/stream/metrics');

eventSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    document.getElementById('fps').textContent = data.fps.toFixed(1);
    document.getElementById('latency').textContent = data.latency.toFixed(0) + ' ms';
    document.getElementById('detections').textContent = data.detections;
};
};

// Send text query
function sendQuery() {
    const text = document.getElementById('queryInput').value;
    if (!text) return;
    
    fetch('/api/query', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text})
    })
    .then(res => res.json())
    .then(data => console.log('Query sent:', data))
    .catch(err => console.error('Error:', err));
    
    document.getElementById('queryInput').value = '';
}

// Record voice
async function recordVoice() {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = async () => {
        const blob = new Blob(chunks, {type: 'audio/wav'});
        const reader = new FileReader();
        
        reader.onloadend = () => {
            const base64 = reader.result.split(',')[1];
            
            fetch('/api/voice', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({audio: base64})
            })
            .then(res => res.json())
            .then(data => {
                document.getElementById('queryInput').value = data.text;
            });
        };
        
        reader.readAsDataURL(blob);
    };
    
    recorder.start();
    setTimeout(() => recorder.stop(), 5000);  // 5s recording
}
```

---

## 📦 FILE STRUCTURE

```
src/
├── flask_app/
│   ├── __init__.py
│   ├── app.py                    # Application factory
│   ├── cortex_core.py            # Core logic (from cortex_gui.py)
│   ├── blueprints/
│   │   ├── __init__.py
│   │   ├── main_routes.py        # HTML pages
│   │   ├── api_routes.py         # REST endpoints
│   │   └── stream_routes.py      # MJPEG + SSE
│   ├── templates/
│   │   └── dashboard.html        # Main UI
│   └── static/
│       ├── css/
│       │   └── style.css         # Biotech theme
│       └── js/
│           └── dashboard.js      # Client-side logic
├── run_flask_dashboard.py        # Entry point
└── gunicorn_config.py           # Production config
```

---

## 🚀 MIGRATION PLAN

### Phase 1: Core Infrastructure (Week 1)
1. ⏳ Create `flask_app/` directory structure
2. ⏳ Implement `app.py` (application factory)
3. ⏳ Port threading logic from `cortex_gui.py` to `cortex_core.py`
4. ⏳ Test threading model (Camera → YOLO → Queue)

### Phase 2: Video Streaming (Week 1)
5. ⏳ Implement MJPEG streaming (`/stream/video`) using `processed_frame_queue`
6. ⏳ Test latency and FPS (target: 30 FPS @ <100ms)

### Phase 3: Metrics & UI (Week 2)
7. ✅ Implement SSE endpoint (`/stream/events`)
8. ✅ Create HTML template with Biotech CSS
9. ✅ Implement JavaScript client

### Phase 4: API Integration (Week 2)
10. ✅ REST API for queries and voice
11. ✅ Integrate Gemini/Router logic

### Phase 5: Testing & Optimization (Week 3)
12. ✅ Load testing (100+ concurrent users)
13. ✅ RAM profiling (target: <300MB)
14. ✅ Deploy to RPi 5

---

## 🎯 SUCCESS METRICS

| Metric | Target | Current (NiceGUI) |
|--------|--------|-------------------|
| RAM Usage | <300 MB | ~400 MB |
| Video Latency | <100ms | ~150ms |
| FPS | 12 FPS | 10 FPS |
| CPU Usage | <30% | ~40% |
| Startup Time | <5s | ~8s |

---

## 📝 NEXT STEPS

1. ✅ **Review this plan** with Haziq for approval
2. ⏳ **Create Phase 1 files** (`app.py`, `cortex_core.py`)
3. ⏳ **Test basic Flask server** with health check endpoint
4. ⏳ **Implement MJPEG streaming** using queue-based pattern from `cortex_gui.py`
5. ⏳ **Create HTML template** with video stream and SSE metrics
6. ⏳ **Test on RPi 5** with real camera and YOLO models

---

**Status:** ✅ Planning Complete (Based on cortex_gui.py ONLY)  
**Next Action:** Awaiting approval to begin Phase 1 implementation
