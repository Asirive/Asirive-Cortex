# Flask Dashboard Implementation - COMPLETE ✅

## 🎯 Overview
Production-ready Flask dashboard for Cortex v2.0, replacing the NiceGUI prototype. Features real-time MJPEG video streaming, Server-Sent Events (SSE) for metrics, and RESTful API for system control.

## 📁 File Structure
```
src/flask_app/
├── __init__.py              # Package initialization
├── app.py                   # Flask application factory
├── cortex_core.py           # Core threading logic (ported from cortex_gui.py)
├── blueprints/
│   ├── __init__.py          # Blueprint exports
│   ├── main_routes.py       # Static pages (/dashboard, /health)
│   ├── api_routes.py        # REST API (/api/status, /api/control/*)
│   └── stream_routes.py     # Streaming endpoints (/stream/video, /stream/metrics)
├── templates/
│   └── dashboard.html       # Main dashboard UI
└── static/
    ├── css/
    │   └── style.css        # Biotech dark theme styling
    └── js/
        └── dashboard.js     # Client-side JavaScript (SSE, MJPEG, API calls)

src/
├── run_flask_dashboard.py   # Development server entry point
└── gunicorn_config.py       # Production WSGI configuration

cortex-dashboard.service     # Systemd service file
```

## 🏗️ Architecture

### Backend (Flask + Gunicorn)
- **Flask Application Factory**: Modular app creation with blueprints
- **CortexCore Singleton**: Queue-based threading (camera + YOLO inference)
- **MJPEG Streaming**: 30 FPS video via `/stream/video` (multipart/x-mixed-replace)
- **SSE Metrics**: Real-time metrics via `/stream/metrics` (text/event-stream)
- **RESTful API**: Control endpoints for start/stop/mode switching

### Frontend (Vanilla JS + HTML5 + CSS3)
- **EventSource API**: SSE connection for live metrics updates
- **MJPEG Video Player**: HTML `<img>` tag with streaming source
- **MediaRecorder API**: Voice input capture (ready for Layer 2 integration)
- **Biotech Dark Theme**: Cyberpunk-inspired neon accents on dark background

### Threading Model (Queue-Based)
```
┌─────────────────────────────────────────────────┐
│           FLASK REQUEST THREADS (4x)            │
│  /stream/video  │  /stream/metrics  │  /api/*   │
└─────────────────────────────────────────────────┘
                        ▲
                        │ (Queue Communication)
                        │
┌─────────────────────────────────────────────────┐
│              CORTEX CORE THREADS                │
│  video_capture_thread  │  yolo_processing_thread │
└─────────────────────────────────────────────────┘
           │                      │
   frame_queue              processed_frame_queue
  (maxsize=2)                   (maxsize=2)
```

**Key Queues:**
- `frame_queue`: Raw frames from camera (maxsize=2)
- `processed_frame_queue`: Annotated frames with RED/GREEN boxes (maxsize=2)
- `status_queue`: System status updates (unbounded)
- `detection_queue`: Detection events log (unbounded)
- `metrics_queue`: FPS/latency/detections metrics (unbounded)

## 🚀 Quick Start

### 1. Development Mode (Flask Dev Server)
```bash
cd /home/cortex/cortex/src
python3 run_flask_dashboard.py
```

Open browser: `http://localhost:5000`

### 2. Production Mode (Gunicorn)
```bash
cd /home/cortex/cortex/src
gunicorn -c gunicorn_config.py run_flask_dashboard:app
```

### 3. Systemd Auto-Start (Production)
```bash
# Copy service file
sudo cp cortex-dashboard.service /etc/systemd/system/

# Enable and start
sudo systemctl enable cortex-dashboard
sudo systemctl start cortex-dashboard

# Check status
sudo systemctl status cortex-dashboard

# View logs
sudo journalctl -u cortex-dashboard -f
```

## 📡 API Reference

### Static Pages
- `GET /` - Main dashboard UI
- `GET /health` - Health check JSON

### REST API
- `GET /api/status` - System status (queue-based)
- `POST /api/control/start` - Start Cortex Core
- `POST /api/control/stop` - Stop Cortex Core
- `POST /api/control/yolo/<mode>` - Switch YOLO mode (COCO_80 | PERSONAL_ITEMS | TEXT_PROMPTS)
- `GET /api/detections/recent` - Last 10 detections

### Streaming Endpoints
- `GET /stream/video` - MJPEG video stream (multipart/x-mixed-replace)
- `GET /stream/metrics` - SSE metrics stream (text/event-stream)

## 🧪 Testing Phases

### Phase 1: Core Threading (Standalone Test)
```python
from flask_app.cortex_core import get_cortex_core
core = get_cortex_core()
core.start()  # Verify camera/YOLO threads start
# Check: Camera thread alive? YOLO thread alive? Queues populated?
core.stop()   # Verify graceful shutdown
```

### Phase 2: Flask Server (Health Check)
```bash
curl http://localhost:5000/health
# Expected: {"status": "healthy", "cortex_running": true, ...}
```

### Phase 3: MJPEG Streaming
Open browser: `http://localhost:5000/stream/video`
- Verify: Frames displayed at ~30 FPS
- Verify: Latency <100ms (use Network tab)
- Verify: RED boxes (Guardian) and GREEN boxes (Learner)

### Phase 4: SSE Metrics
Open browser: `http://localhost:5000` (dashboard)
- Open DevTools → Network tab → Filter "metrics"
- Verify: EventSource connection established
- Verify: Metrics updating every ~500ms
- Verify: FPS/Latency/Detections displayed correctly

### Phase 5: API Endpoints
```bash
# Status check
curl http://localhost:5000/api/status

# Switch YOLO mode
curl -X POST http://localhost:5000/api/control/yolo/TEXT_PROMPTS

# Get recent detections
curl http://localhost:5000/api/detections/recent
```

## ⚙️ Configuration

### Environment Variables
```bash
export FLASK_HOST=0.0.0.0         # Server host (default: 0.0.0.0)
export FLASK_PORT=5000            # Server port (default: 5000)
export FLASK_DEBUG=False          # Debug mode (default: False)
export SECRET_KEY=your_secret     # Flask secret key (default: cortex_dev_2026)
```

### Gunicorn Settings (Production)
- **Workers**: 1 (CRITICAL: CortexCore is singleton, multiple workers break camera access)
- **Threads**: 4 (handles concurrent HTTP connections)
- **Worker Class**: gthread (for I/O-heavy workloads like streaming)
- **Timeout**: 120s (for long-running SSE connections)

## 🔧 Key Implementation Details

### 1. CortexCore Singleton Pattern
```python
_cortex_core_instance = None

def get_cortex_core():
    global _cortex_core_instance
    if _cortex_core_instance is None:
        _cortex_core_instance = CortexCore()
    return _cortex_core_instance
```
**Why?** Prevents multiple camera/YOLO instances (resource conflict).

### 2. Flask Application Factory
```python
def create_app(config=None):
    app = Flask(__name__)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(stream_bp, url_prefix='/stream')
    
    @app.before_request
    def init_cortex():
        core = get_cortex_core()
        if not core.is_running:
            core.start()  # Auto-start on first request
    
    return app
```
**Why?** Testable, modular, production-ready pattern.

### 3. MJPEG Generator (Streaming)
```python
def generate_video_frames():
    core = get_cortex_core()
    while True:
        frame = core.processed_frame_queue.get(timeout=1.0)
        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
```
**Why?** Yields frames with MIME boundaries for `multipart/x-mixed-replace`.

### 4. SSE Generator (Metrics)
```python
def generate_metrics():
    core = get_cortex_core()
    while True:
        try:
            metrics = core.metrics_queue.get(timeout=1.0)
            yield f"data: {metrics}\n\n"
        except Empty:
            yield f": heartbeat {time.time()}\n\n"  # Keep connection alive
```
**Why?** SSE format requires `data: JSON\n\n` format with heartbeats.

### 5. Queue-Based Status API
```python
@api_bp.route('/status')
def get_status():
    core = get_cortex_core()
    try:
        status = core.status_queue.get_nowait()  # Non-blocking
        return jsonify(status)
    except Empty:
        return jsonify({'cortex_running': core.is_running, ...})
```
**Why?** Non-blocking queue read prevents API from hanging.

## 📊 Performance Targets

| Metric           | Target      | Measured    |
|------------------|-------------|-------------|
| Video FPS        | 30 FPS      | TBD         |
| Latency          | <100ms      | TBD         |
| MJPEG Streaming  | <2% drops   | TBD         |
| SSE Update Rate  | 500ms       | TBD         |
| Memory (RPi)     | <4GB        | TBD         |

## 🛡️ Safety & Reliability

### Graceful Degradation
- **Camera Failure**: Fallback to OpenCV webcam, then black frame with error message
- **YOLO Failure**: Continue video stream, disable detections, log error
- **SSE Disconnect**: Client auto-reconnects after 5 seconds
- **MJPEG Disconnect**: Client reloads `<img>` tag on error

### Resource Cleanup
- `@app.teardown_appcontext`: Stops CortexCore on app shutdown
- `CortexCore.stop()`: Joins threads with 2-second timeout, releases camera

### Error Handling
- Try-except blocks in all generators (MJPEG/SSE)
- Logging at INFO level (stdout + file)
- Queue timeout prevents infinite blocking

## 🔄 Migration from cortex_gui.py

### What Was Ported?
- ✅ Threading model (video_capture_thread, yolo_processing_thread)
- ✅ Queue communication (5 queues)
- ✅ DualYOLOHandler integration (RED Guardian + GREEN Learner)
- ✅ Picamera2/OpenCV fallback logic
- ✅ FPS calculation and metrics generation

### What Was NOT Ported?
- ❌ NiceGUI UI components (replaced with HTML/CSS/JS)
- ❌ Qt-based UI update logic (replaced with SSE push)
- ❌ Blocking `Queue.get()` in UI thread (replaced with generators)

### Key Differences
| cortex_gui.py | Flask Dashboard |
|---------------|----------------|
| Pull model (UI polls queues) | Push model (SSE/MJPEG streaming) |
| Single-threaded UI updates | Multi-threaded HTTP requests |
| Desktop app (local only) | Web app (network accessible) |

## 🚨 Known Limitations & Future Work

### Current Limitations
- ⚠️ **No Layer 2 Integration**: Chat/Voice interface is placeholder (needs Whisper + Gemini Live API)
- ⚠️ **No Layer 3 Integration**: No VIO/SLAM visualization (server integration pending)
- ⚠️ **No Layer 4 Integration**: No memory system integration (SQLite REST API pending)

### Future Enhancements
- [ ] WebSocket for Layer 2 Gemini Live API (bidirectional audio streaming)
- [ ] 3D spatial audio visualization (Layer 3 output)
- [ ] Memory timeline view (Layer 4 output)
- [ ] User authentication (optional, for multi-user demos)
- [ ] PWA support (offline capability, install to home screen)

## 📝 Maintenance

### Logs
```bash
# Application logs
tail -f logs/flask_dashboard.log

# Systemd logs
sudo journalctl -u cortex-dashboard -f

# Gunicorn access logs
# (stdout in systemd journal)
```

### Updating
```bash
# Pull latest code
git pull

# Restart service
sudo systemctl restart cortex-dashboard
```

### Debugging
```bash
# Check CortexCore status
curl http://localhost:5000/health

# Test video stream
curl -I http://localhost:5000/stream/video
# Expected: Content-Type: multipart/x-mixed-replace

# Test metrics stream
curl http://localhost:5000/stream/metrics
# Expected: text/event-stream with SSE events
```

## 🏆 Success Criteria

✅ **Core Implementation (Tasks 1-12)**: COMPLETE
- [x] Flask app factory with blueprints
- [x] CortexCore threading logic
- [x] MJPEG video streaming
- [x] SSE metrics streaming
- [x] REST API endpoints
- [x] Frontend UI (HTML/CSS/JS)
- [x] Production config (Gunicorn)
- [x] Systemd service file

⏳ **Testing (Tasks 13-17)**: PENDING
- [ ] Phase 1: Core threading test
- [ ] Phase 2: Flask server health check
- [ ] Phase 3: MJPEG streaming validation
- [ ] Phase 4: SSE metrics validation
- [ ] Phase 5: API endpoint validation

## 🎓 References
- Flask Application Factory: https://flask.palletsprojects.com/en/2.3.x/patterns/appfactories/
- Flask Blueprints: https://flask.palletsprojects.com/en/2.3.x/blueprints/
- MJPEG Streaming: https://blog.miguelgrinberg.com/post/video-streaming-with-flask
- Server-Sent Events: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
- Gunicorn Deployment: https://docs.gunicorn.org/en/stable/deploy.html

---

**Status**: ✅ **IMPLEMENTATION COMPLETE** - Ready for Testing  
**Next Steps**: Run test phases 1-5 to validate functionality  
**Author**: Cortex CTO (GitHub Copilot)  
**Date**: 2025-01-08
