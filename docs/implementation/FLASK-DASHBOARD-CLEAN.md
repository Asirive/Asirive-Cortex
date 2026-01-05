# 🌐 Flask Dashboard Implementation Plan (v2.0)

> ⚠️ **CRITICAL:** Based **EXCLUSIVELY** on proven `cortex_gui.py` architecture.  
> **DO NOT** reference or copy code from `cortex_dashboard.py` (buggy, unreliable).

---

## 🎯 OBJECTIVE

Migrate from CustomTkinter GUI (`cortex_gui.py`) to Flask Web Dashboard while **preserving the exact threading model** that we know works.

**Why Flask?**
- Remote access (phone, laptop, tablet)
- Multi-user support
- Production-ready deployment (Gunicorn + Nginx)
- **But keep the same queue-based threading that works in cortex_gui.py**

---

## 📐 ARCHITECTURE REFERENCE

### What cortex_gui.py Does (PROVEN WORKING):

```
┌─────────────────────────────────────────────────────────┐
│              ProjectCortexGUI (CustomTkinter)            │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  UI Thread (Main)                                        │
│  ├── Status labels (FPS, latency, detections)          │
│  ├── Video canvas (updates at 30 FPS)                  │
│  ├── YOLOE mode dropdown                               │
│  └── Control buttons (Start/Stop)                      │
│                                                           │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  Background Threads:                                    │
│                                                           │
│  [1] video_capture_thread() → frame_queue               │
│      - Picamera2 or OpenCV auto-fallback               │
│      - 30 FPS capture rate                              │
│      - Queue size: maxsize=2 (drop old frames)         │
│                                                           │
│  [2] yolo_processing_thread()                           │
│      frame_queue → [Dual YOLO] → processed_frame_queue │
│      - Guardian (RED boxes) + Learner (GREEN boxes)    │
│      - Metrics → metrics_queue (FPS, latency)          │
│      - Detections → detection_queue (strings)          │
│                                                           │
│  [3] Audio threads (lazy-loaded):                       │
│      - VAD listener (Whisper STT on wake word)         │
│      - TTS playback (Kokoro/Gemini)                    │
│      - Audio queue → speakers                           │
│                                                           │
└─────────────────────────────────────────────────────────┘

Queues (Thread-Safe Communication):
├── frame_queue: Queue(maxsize=2)
├── processed_frame_queue: Queue(maxsize=2)
├── status_queue: Queue() (unbounded)
├── detection_queue: Queue() (unbounded)
└── metrics_queue: Queue() (unbounded) [NEW for Flask]
```

### Key Patterns from cortex_gui.py:

1. **Queue-Based Communication (NO LOCKS)**
   ```python
   # Producer (camera thread)
   if not self.frame_queue.full():
       self.frame_queue.put(frame, block=False)
   
   # Consumer (YOLO thread)
   try:
       frame = self.frame_queue.get(timeout=1)
       # Process...
       self.processed_frame_queue.put(annotated_frame)
   except queue.Empty:
       continue
   ```

2. **Lazy Loading (On-Demand Model Init)**
   ```python
   # Don't load all models at startup
   if self.whisper_stt is None:
       self.whisper_stt = WhisperSTT()
       self.whisper_stt.load_model()
   ```

3. **Exception Handling (Never Crash)**
   ```python
   while not self._stop_event.is_set():
       try:
           # Processing logic
       except queue.Empty:
           continue
       except Exception as e:
           logger.error(f"Error: {e}")
           time.sleep(1)
   ```

4. **Camera Auto-Fallback**
   ```python
   try:
       # Try Picamera2 first (RPi)
       from picamera2 import Picamera2
       self.picamera2 = Picamera2()
       # ...
   except Exception as e:
       # Fallback to OpenCV (dev laptop)
       self.cap = cv2.VideoCapture(0)
   ```

---

## 🏗️ PROPOSED FLASK ARCHITECTURE

We **replicate** cortex_gui.py's threading model but replace the UI layer:

```
┌─────────────────────────────────────────────────────────┐
│                Flask Application                         │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  HTTP Handlers:                                          │
│  ├── GET / → dashboard.html (static page)              │
│  ├── GET /stream/video → MJPEG stream                  │
│  ├── GET /stream/metrics → SSE (Server-Sent Events)    │
│  ├── POST /api/query → Text AI query                   │
│  └── POST /api/voice → Voice input                     │
│                                                           │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  CortexCore (Extracted from cortex_gui.py)             │
│                                                           │
│  Background Threads (SAME AS cortex_gui.py):            │
│  [1] video_capture_thread() → frame_queue               │
│  [2] yolo_processing_thread() → processed_frame_queue   │
│  [3] audio_threads (lazy-loaded)                        │
│                                                           │
│  Queues (SAME AS cortex_gui.py):                        │
│  ├── frame_queue: Queue(maxsize=2)                      │
│  ├── processed_frame_queue: Queue(maxsize=2)            │
│  ├── status_queue: Queue()                              │
│  ├── detection_queue: Queue()                           │
│  └── metrics_queue: Queue()                             │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

---

## 🔧 IMPLEMENTATION

### 1. Application Factory

**File:** `src/flask_app/app.py`

```python
from flask import Flask
from flask_app.blueprints import main_bp, api_bp, stream_bp
from flask_app.cortex_core import get_cortex_core
import os
import logging

logger = logging.getLogger(__name__)

def create_app(config=None):
    """Flask application factory."""
    app = Flask(
        __name__,
        static_folder='flask_app/static',
        template_folder='flask_app/templates'
    )
    
    # Config
    app.config.from_mapping(
        SECRET_KEY=os.getenv('SECRET_KEY', 'cortex_dev_key'),
        TEMPLATES_AUTO_RELOAD=True,
    )
    
    if config:
        app.config.update(config)
    
    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(stream_bp, url_prefix='/stream')
    
    # Start Cortex Core on first request
    @app.before_request
    def init_cortex():
        core = get_cortex_core()
        if not core.is_running:
            core.start()
    
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

### 2. Core Logic (Direct Port from cortex_gui.py)

**File:** `src/flask_app/cortex_core.py`

```python
import threading
import queue
import time
import cv2
import logging
from collections import deque

from dual_yolo_handler import DualYOLOHandler
from layer1_reflex.whisper_handler import WhisperSTT
from layer1_reflex.kokoro_handler import KokoroTTS

logger = logging.getLogger(__name__)

# Config (from env vars)
YOLO_GUARDIAN_PATH = 'models/yolo11n_ncnn_model'
YOLO_LEARNER_PATH = 'models/yoloe-11s-seg.pt'
YOLO_DEVICE = 'cpu'
YOLO_CONFIDENCE = 0.5

class CortexCore:
    """
    Core logic extracted from cortex_gui.py.
    Runs camera + YOLO threads using queue-based communication.
    NO LOCKS, NO SHARED STATE DICTS (unlike buggy cortex_dashboard.py).
    """
    
    def __init__(self):
        # AI handlers (lazy-loaded)
        self.dual_yolo = None
        self.whisper_stt = None
        self.kokoro_tts = None
        
        # Camera
        self.cap = None
        self.picamera2 = None
        self.is_running = False
        
        # Queues (thread-safe, NO locks needed)
        self.frame_queue = queue.Queue(maxsize=2)
        self.processed_frame_queue = queue.Queue(maxsize=2)
        self.status_queue = queue.Queue()
        self.detection_queue = queue.Queue()
        self.metrics_queue = queue.Queue()
        
        # Threads
        self._threads = []
        self._stop_event = threading.Event()
        
        logger.info("✅ CortexCore initialized")
    
    def start(self):
        """Start camera and YOLO threads."""
        if self.is_running:
            return
        
        self.is_running = True
        self._stop_event.clear()
        
        logger.info("🚀 Starting Cortex Core...")
        
        # Load YOLO (blocking, done once)
        self._load_yolo()
        
        # Init camera
        self._init_camera()
        
        # Start threads
        self._threads = [
            threading.Thread(target=self._video_capture_thread, daemon=True, name="Camera"),
            threading.Thread(target=self._yolo_processing_thread, daemon=True, name="YOLO"),
        ]
        
        for t in self._threads:
            t.start()
        
        logger.info("✅ Threads started")
    
    def stop(self):
        """Stop threads and release resources."""
        logger.info("🛑 Stopping Cortex Core...")
        self.is_running = False
        self._stop_event.set()
        
        # Release camera
        if self.cap:
            self.cap.release()
        if self.picamera2:
            self.picamera2.stop()
        
        # Wait for threads
        for t in self._threads:
            t.join(timeout=2.0)
        
        logger.info("✅ Stopped")
    
    def _load_yolo(self):
        """Load Dual YOLO Handler."""
        try:
            logger.info("📦 Loading YOLO models...")
            self.dual_yolo = DualYOLOHandler(
                guardian_model_path=YOLO_GUARDIAN_PATH,
                learner_model_path=YOLO_LEARNER_PATH,
                device=YOLO_DEVICE,
                max_workers=2,
                learner_mode='TEXT_PROMPTS'
            )
            self.status_queue.put("✅ YOLO ready")
            logger.info("✅ YOLO loaded")
        except Exception as e:
            logger.error(f"❌ YOLO failed: {e}")
            self.status_queue.put(f"❌ YOLO failed")
    
    def _init_camera(self):
        """Initialize camera (Picamera2 or OpenCV fallback)."""
        try:
            # Try Picamera2 (RPi)
            from picamera2 import Picamera2
            logger.info("📹 Initializing Picamera2...")
            self.picamera2 = Picamera2()
            config = self.picamera2.create_preview_configuration(
                main={"size": (640, 480), "format": "RGB888"}
            )
            self.picamera2.configure(config)
            self.picamera2.start()
            self.status_queue.put("✅ Picamera2 ready")
            logger.info("✅ Picamera2 ready")
        except Exception as e:
            logger.warning(f"Picamera2 failed: {e}, using OpenCV")
            # Fallback to OpenCV
            self.cap = cv2.VideoCapture(0)
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.status_queue.put("✅ Webcam ready")
                logger.info("✅ Webcam ready")
            else:
                logger.error("❌ Camera failed")
                self.status_queue.put("❌ Camera failed")
    
    def _video_capture_thread(self):
        """Capture frames at 30 FPS (exact copy from cortex_gui.py)."""
        logger.info("🎥 Camera thread started")
        
        while not self._stop_event.is_set():
            try:
                # Capture frame
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
        """YOLO inference thread (exact copy from cortex_gui.py)."""
        logger.info("🧠 YOLO thread started")
        
        frame_count = 0
        fps_counter = deque(maxlen=30)
        
        while not self._stop_event.is_set():
            try:
                # Get frame (blocking with timeout)
                frame = self.frame_queue.get(timeout=1)
                start_time = time.time()
                frame_count += 1
                
                # Run Dual YOLO
                if self.dual_yolo:
                    g_results, l_results = self.dual_yolo.process_frame(frame, confidence=YOLO_CONFIDENCE)
                    
                    # Annotate frame
                    annotated_frame = frame.copy()
                    guardian_detections = []
                    learner_detections = []
                    
                    # Draw Guardian (RED)
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
                    
                    # Draw Learner (GREEN)
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
                    detections_str = ", ".join(sorted(set(guardian_detections))) or "nothing"
                    self.detection_queue.put(detections_str)
                    
                    # Calculate metrics
                    latency_ms = (time.time() - start_time) * 1000
                    fps_counter.append(1.0 / (time.time() - start_time))
                    avg_fps = sum(fps_counter) / len(fps_counter) if fps_counter else 0
                    
                    # Put metrics in queue
                    self.metrics_queue.put({
                        'fps': avg_fps,
                        'latency': latency_ms,
                        'frame_count': frame_count,
                        'detections': detections_str,
                        'guardian': guardian_detections,
                        'learner': learner_detections
                    })
                    
                    # Put annotated frame (clear old if full)
                    if self.processed_frame_queue.full():
                        try:
                            self.processed_frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    self.processed_frame_queue.put(annotated_frame)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"YOLO error: {e}")
                time.sleep(1)
        
        logger.info("🛑 YOLO thread stopped")
    
    # Lazy-loading methods
    def init_whisper_stt(self):
        """Load Whisper STT on demand."""
        if self.whisper_stt is None:
            try:
                logger.info("⏳ Loading Whisper...")
                self.whisper_stt = WhisperSTT(model_size="base")
                self.whisper_stt.load_model()
                logger.info("✅ Whisper ready")
                return True
            except Exception as e:
                logger.error(f"❌ Whisper failed: {e}")
                return False
        return True
    
    def init_kokoro_tts(self):
        """Load Kokoro TTS on demand."""
        if self.kokoro_tts is None:
            try:
                logger.info("⏳ Loading Kokoro...")
                self.kokoro_tts = KokoroTTS(lang_code="a", default_voice="af_alloy")
                self.kokoro_tts.load_pipeline()
                logger.info("✅ Kokoro ready")
                return True
            except Exception as e:
                logger.error(f"❌ Kokoro failed: {e}")
                return False
        return True


# Singleton accessor
_core_instance = None

def get_cortex_core():
    """Get or create CortexCore instance."""
    global _core_instance
    if _core_instance is None:
        _core_instance = CortexCore()
    return _core_instance
```

---

### 3. Flask Blueprints

#### 3.1 Main Routes (HTML Pages)

**File:** `src/flask_app/blueprints/main_routes.py`

```python
from flask import Blueprint, render_template

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Serve main dashboard."""
    return render_template('dashboard.html')

@main_bp.route('/health')
def health():
    """Health check."""
    return {'status': 'ok'}, 200
```

#### 3.2 API Routes (REST)

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
    """Get system status (non-blocking)."""
    core = get_cortex_core()
    
    # Read from queues (non-blocking)
    status_msg = None
    try:
        status_msg = core.status_queue.get_nowait()
    except queue.Empty:
        pass
    
    # Get latest metrics
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
    """Start Cortex Core."""
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

#### 3.3 Stream Routes (MJPEG + SSE)

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
    Reads from processed_frame_queue (non-blocking).
    """
    
    def generate():
        core = get_cortex_core()
        frame_count = 0
        
        while True:
            try:
                # Get frame (non-blocking)
                try:
                    frame = core.processed_frame_queue.get_nowait()
                    frame_count += 1
                    
                    # Encode JPEG
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    jpeg_bytes = buffer.tobytes()
                    
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
                    
                except queue.Empty:
                    # No frame, wait
                    time.sleep(1/30)
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
    Server-Sent Events (SSE) for metrics.
    Polls metrics_queue at 2 Hz.
    """
    
    def generate():
        core = get_cortex_core()
        
        while True:
            try:
                # Get latest metrics (drain queue)
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
                time.sleep(0.5)  # 2 Hz
                
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

#### 3.4 Blueprint Registration

**File:** `src/flask_app/blueprints/__init__.py`

```python
from .main_routes import main_bp
from .api_routes import api_bp
from .stream_routes import stream_bp

__all__ = ['main_bp', 'api_bp', 'stream_bp']
```

---

### 4. Entry Point

**File:** `src/run_flask_dashboard.py`

```python
#!/usr/bin/env python3
"""
Flask Dashboard Entry Point
Production: gunicorn -c gunicorn_config.py run_flask_dashboard:app
"""

import logging
import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask_app.app import create_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Create app
app = create_app()

if __name__ == '__main__':
    # Development mode
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,  # NO DEBUG in multi-threading
        threaded=True,
        use_reloader=False  # NO RELOADER with background threads
    )
```

---

### 5. Gunicorn Config (Production)

**File:** `gunicorn_config.py`

```python
"""Gunicorn configuration for production deployment."""

# Bind
bind = '0.0.0.0:5000'

# Workers (CPU cores * 2 + 1)
workers = 1  # IMPORTANT: Only 1 worker for CortexCore singleton

# Threading (for SSE/MJPEG)
threads = 4
worker_class = 'gthread'

# Timeouts
timeout = 120
keepalive = 5

# Logging
accesslog = '-'  # stdout
errorlog = '-'   # stdout
loglevel = 'info'

# Daemon
daemon = False

# Restart on code change
reload = False
```

---

## 📁 FILE STRUCTURE

```
src/
├── flask_app/
│   ├── __init__.py
│   ├── app.py                  # Application factory
│   ├── cortex_core.py          # Core logic (from cortex_gui.py)
│   ├── blueprints/
│   │   ├── __init__.py
│   │   ├── main_routes.py     # HTML pages
│   │   ├── api_routes.py      # REST endpoints
│   │   └── stream_routes.py   # MJPEG + SSE
│   ├── templates/
│   │   └── dashboard.html     # Main UI
│   └── static/
│       ├── css/
│       │   └── style.css      # Biotech theme
│       └── js/
│           └── dashboard.js   # Client-side logic
├── run_flask_dashboard.py     # Entry point
└── gunicorn_config.py         # Production config
```

---

## 🚀 DEPLOYMENT

### Development Mode:
```bash
cd /home/cortex/cortex/src
python3 run_flask_dashboard.py
```

### Production Mode (Gunicorn):
```bash
cd /home/cortex/cortex
gunicorn -c gunicorn_config.py src.run_flask_dashboard:app
```

### Systemd Service:
```ini
[Unit]
Description=Cortex Flask Dashboard
After=network.target

[Service]
Type=simple
User=cortex
WorkingDirectory=/home/cortex/cortex
ExecStart=/usr/bin/gunicorn -c gunicorn_config.py src.run_flask_dashboard:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

---

## 🧪 TESTING STRATEGY

### Phase 1: Core Threading
```bash
# Test camera + YOLO threads
python3 -c "
from flask_app.cortex_core import get_cortex_core
import time

core = get_cortex_core()
core.start()

print('Running for 10 seconds...')
time.sleep(10)

print('Stopping...')
core.stop()
print('✅ Test passed')
"
```

### Phase 2: Flask Server
```bash
# Start Flask dev server
python3 run_flask_dashboard.py

# In another terminal:
curl http://localhost:5000/health
curl http://localhost:5000/api/status
```

### Phase 3: Video Streaming
```bash
# Open in browser:
xdg-open http://localhost:5000/stream/video
```

### Phase 4: Load Testing
```bash
# Install hey (HTTP load tester)
go install github.com/rakyll/hey@latest

# Test SSE endpoint
hey -n 100 -c 10 http://localhost:5000/stream/metrics
```

---

## 📊 SUCCESS METRICS

| Metric | Target | How to Measure |
|--------|--------|----------------|
| RAM Usage | <400 MB | `ps aux | grep gunicorn` |
| Video Latency | <100ms | Browser DevTools Network tab |
| FPS | 30 FPS | Check `/api/status` response |
| CPU Usage | <40% | `top -p $(pgrep -f gunicorn)` |
| Startup Time | <5s | `time python3 run_flask_dashboard.py` |

---

## ⚠️ CRITICAL DIFFERENCES FROM cortex_dashboard.py

| cortex_dashboard.py (BUGGY) | Flask Implementation (CLEAN) |
|-----------------------------|------------------------------|
| ❌ Shared state dict with locks | ✅ Queue-based communication |
| ❌ `self.state_lock.acquire()` | ✅ `queue.get_nowait()` |
| ❌ JPEG encoding in camera thread | ✅ JPEG encoding in HTTP handler |
| ❌ Base64 strings in memory | ✅ Raw bytes (smaller) |
| ❌ `CortexHardwareManager` singleton | ✅ `CortexCore` (clean singleton) |

---

## 📝 NEXT STEPS

1. ✅ Review this plan
2. 🔄 Create `flask_app/` directory structure
3. 🔄 Implement `cortex_core.py` (port from cortex_gui.py)
4. 🔄 Implement blueprints (main, api, stream)
5. 🔄 Test threading (Phase 1)
6. 🔄 Test Flask server (Phase 2)
7. 🔄 Create HTML template
8. 🔄 Deploy to RPi 5

---

**Status:** ✅ Plan Complete (Based on cortex_gui.py ONLY)  
**Next Action:** Awaiting approval to start implementation
