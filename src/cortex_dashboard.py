"""
Project-Cortex v2.0 - Modern Neural Dashboard (NiceGUI Refactor)

A high-performance, web-based dashboard for visualizing the 5-Layer AI Brain.
Features:
- Responsive Tailwind CSS styling with Glassmorphism
- Neural Layer Cards with real-time status glow
- Integrated Chat Stream for conversational AI
- Low-latency Video Feed via Global Hardware Manager
- Real-time System Boot Log
- YOLOE 3-Mode Selector (Prompt-Free, Text, Visual)
- Spatial Audio Toggle
- Performance Metrics (FPS, Latency, RAM)

Author: Haziq (@IRSPlays)
Date: December 31, 2025
Fixed: Duplicate __init__, error handling, client context protection
"""

import os
import cv2
import time
import base64
import asyncio
import logging
import threading
import psutil
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional
from collections import deque
from nicegui import ui, app, context

# Enhanced logging for debugging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Import Core Handlers (Reusing existing logic)
from camera_handler import CameraHandler  # Unified camera interface (Picamera2 + OpenCV)
from layer1_reflex.whisper_handler import WhisperSTT
from layer1_reflex.kokoro_handler import KokoroTTS
from layer2_thinker.gemini_tts_handler import GeminiTTS
from layer2_thinker.gemini_live_handler import GeminiLiveManager
from layer2_thinker.streaming_audio_player import StreamingAudioPlayer
from layer3_guide.router import IntentRouter
from layer3_guide.detection_router import DetectionRouter
from dual_yolo_handler import DualYOLOHandler
from layer1_learner import YOLOEMode, YOLOELearner
from layer1_reflex.detection_aggregator import DetectionAggregator
from layer4_memory import get_memory_manager

# Multi-Process Pipeline (optional)
try:
    from process_manager import ProcessManager, WorkerState
    from frame_queue import SharedFrameBuffer
    MULTIPROCESS_AVAILABLE = True
except ImportError:
    MULTIPROCESS_AVAILABLE = False
    ProcessManager = None

# Multi-process mode flag (set to True to enable parallel YOLO on separate cores)
ENABLE_MULTIPROCESS = os.getenv('CORTEX_MULTIPROCESS', 'false').lower() == 'true'

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /home/cortex/cortex
YOLO_MODEL_PATH = os.path.join(PROJECT_ROOT, 'models', 'yolo11n_ncnn_model')
YOLOE_LEARNER_PATH = os.path.join(PROJECT_ROOT, 'models', 'yoloe-11s-seg.pt')
YOLO_DEVICE = os.getenv('YOLO_DEVICE', 'cpu')
GOOGLE_API_KEY = os.getenv('GEMINI_API_KEY')
AUDIO_TEMP_DIR = os.path.join(PROJECT_ROOT, 'temp_audio')
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)

# Biotech UI Custom CSS (from code.html design)
BIOTECH_CSS = '''
<link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@300;400;500;600;700&family=Space+Mono:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>
<style>
/* Biotech Color Palette */
:root {
    --bio-base: #011618;
    --bio-dark: #042124;
    --bio-panel: rgba(10, 48, 51, 0.6);
    --bio-border: #134e4a;
    --bio-highlight: #115e59;
    --bio-text: #ccfbf1;
    --bio-muted: #5eead4;
    --accent-teal: #2dd4bf;
    --accent-amber: #fbbf24;
    --accent-rose: #fb7185;
    --accent-indigo: #818cf8;
}

body {
    background: radial-gradient(circle at top right, #0f766e 0%, #042f2e 25%, #011618 100%);
    color: var(--bio-text);
    font-family: 'Quicksand', sans-serif !important;
}

/* Glassmorphism Panels */
.glass-panel {
    background: rgba(8, 40, 42, 0.65) !important;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(45, 212, 191, 0.1) !important;
    border-radius: 1.5rem !important;
}

/* Glowing Effects */
.glow-teal {
    box-shadow: 0 0 15px rgba(45, 212, 191, 0.15);
}

.glow-amber {
    box-shadow: 0 0 15px rgba(251, 191, 36, 0.15);
}

/* Breathing Animation */
@keyframes breathe {
    0%, 100% { box-shadow: 0 0 5px rgba(45, 212, 191, 0.2); }
    50% { box-shadow: 0 0 20px rgba(45, 212, 191, 0.5); }
}

.breathing-glow {
    animation: breathe 4s ease-in-out infinite;
}

/* Scanline Effect */
@keyframes scanline {
    0% { top: -100px; }
    100% { top: 100%; }
}

.scanline {
    position: absolute;
    width: 100%;
    height: 100px;
    background: linear-gradient(0deg, rgba(0,0,0,0) 0%, rgba(45, 212, 191, 0.1) 50%, rgba(0,0,0,0) 100%);
    animation: scanline 8s linear infinite;
    pointer-events: none;
    opacity: 0.1;
    z-index: 10;
}

/* Custom Scrollbar */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}

::-webkit-scrollbar-track {
    background: transparent;
}

::-webkit-scrollbar-thumb {
    background: var(--bio-highlight);
    border-radius: 10px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--accent-teal);
}

/* Organic Borders */
.organic-radius {
    border-radius: 1.5rem !important;
}

.bubble-radius {
    border-radius: 2rem !important;
}

/* Mono Text */
.text-mono {
    font-family: 'Space Mono', monospace !important;
}

/* Bio-themed cards */
.bio-card {
    background: var(--bio-panel) !important;
    border: 1px solid rgba(45, 212, 191, 0.1) !important;
    border-radius: 1.5rem !important;
    backdrop-filter: blur(12px);
    transition: all 0.3s ease;
}

.bio-card:hover {
    border-color: rgba(45, 212, 191, 0.3) !important;
    box-shadow: 0 0 15px rgba(45, 212, 191, 0.15);
    transform: scale(1.02);
}

/* Layer status indicators */
.layer-active {
    box-shadow: 0 0 8px rgba(45, 212, 191, 1) !important;
}

/* Progress bars */
.q-linear-progress__track {
    background: var(--bio-dark) !important;
    border: 1px solid var(--bio-border) !important;
}

/* Input fields */
.q-field__control {
    background: rgba(4, 33, 36, 0.6) !important;
    border: 1px solid var(--bio-border) !important;
    border-radius: 2rem !important;
}

.q-field__control:hover {
    border-color: var(--accent-teal) !important;
}

/* Buttons */
.q-btn {
    border-radius: 2rem !important;
}

/* Header styling */
.q-header {
    background: transparent !important;
    backdrop-filter: blur(8px);
}

/* Badge styling */
.q-badge {
    border-radius: 1rem !important;
    font-family: 'Space Mono', monospace !important;
}

/* Video container */
.video-container {
    background: #000 !important;
    border: 1px solid var(--bio-border) !important;
    border-radius: 1.5rem !important;
    position: relative;
    overflow: hidden;
}

/* Corner decorations */
.corner-tl {
    position: absolute;
    top: 1rem;
    left: 1rem;
    width: 8rem;
    height: 8rem;
    border-left: 1px solid rgba(45, 212, 191, 0.3);
    border-top: 1px solid rgba(45, 212, 191, 0.3);
    border-radius: 3rem 0 0 0;
    pointer-events: none;
}

.corner-br {
    position: absolute;
    bottom: 1rem;
    right: 1rem;
    width: 8rem;
    height: 8rem;
    border-right: 1px solid rgba(45, 212, 191, 0.3);
    border-bottom: 1px solid rgba(45, 212, 191, 0.3);
    border-radius: 0 0 3rem 0;
    pointer-events: none;
}

/* Gradient Progress Bars with Glow */
.gradient-progress-teal .q-linear-progress__model {
    background: linear-gradient(to right, #0f766e, #2dd4bf) !important;
    box-shadow: 0 0 10px rgba(45, 212, 191, 0.4);
}

.gradient-progress-amber .q-linear-progress__model {
    background: linear-gradient(to right, #a16207, #fbbf24) !important;
    box-shadow: 0 0 10px rgba(251, 191, 36, 0.4);
}

.gradient-progress-indigo .q-linear-progress__model {
    background: linear-gradient(to right, #312e81, #818cf8) !important;
    box-shadow: 0 0 10px rgba(129, 140, 248, 0.4);
}

.gradient-progress-rose .q-linear-progress__model {
    background: linear-gradient(to right, #881337, #fb7185) !important;
    box-shadow: 0 0 10px rgba(251, 113, 133, 0.4);
}

/* Slow Spin Animation for Settings */
@keyframes spin-slow {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

.animate-spin-slow {
    animation: spin-slow 10s linear infinite;
}

/* Enhanced Layer Card Hover */
.layer-card {
    transition: all 0.3s ease;
}

.layer-card:hover {
    border-color: rgba(45, 212, 191, 0.3) !important;
    box-shadow: 0 0 20px rgba(45, 212, 191, 0.2);
    transform: translateY(-2px) scale(1.02);
}

/* Shadow Glow Effect */
.shadow-glow {
    box-shadow: 0 0 15px rgba(45, 212, 191, 0.3);
}

.shadow-glow-amber {
    box-shadow: 0 0 15px rgba(251, 191, 36, 0.3);
}

/* Fade In Animation */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.animate-fadeIn {
    animation: fadeIn 0.5s ease-out forwards;
}
</style>
'''

# Validate model paths
if not os.path.exists(YOLO_MODEL_PATH):
    logger.error(f"❌ YOLO Guardian model not found: {YOLO_MODEL_PATH}")
    YOLO_MODEL_PATH = None  # Graceful degradation
else:
    logger.info(f"✅ YOLO Guardian model found: {YOLO_MODEL_PATH}")

if not os.path.exists(YOLOE_LEARNER_PATH):
    logger.error(f"❌ YOLOE Learner model not found: {YOLOE_LEARNER_PATH}")
    YOLOE_LEARNER_PATH = None
else:
    logger.info(f"✅ YOLOE Learner model found: {YOLOE_LEARNER_PATH}")


class CortexHardwareManager:
    """Singleton manager for AI models and Camera hardware."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CortexHardwareManager, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize hardware manager (singleton pattern)."""
        if self._initialized:
            return
            
        # AI Models
        self.dual_yolo = None
        self.aggregator = DetectionAggregator()
        self.whisper_stt = None
        self.kokoro_tts = None
        self.gemini_tts = None
        self.gemini_live = None
        self.streaming_player = None
        
        # Routers
        self.intent_router = IntentRouter()
        self.detection_router = DetectionRouter()
        self.memory_manager = get_memory_manager()
        
        # Hardware
        self.cap = None
        self.is_running = False
        
        # Multi-Process Pipeline
        self.process_manager = None
        self.use_multiprocess = ENABLE_MULTIPROCESS and MULTIPROCESS_AVAILABLE
        
        # Shared State (thread-safe)
        self.state = {
            'last_frame': '',
            'latency': 0,
            'detections': 'Scanning...',
            'frame_id': 0,
            'fps': 0,
            'ram_usage': 0,
            'cpu_usage': 0,
            'cpu_temp': 0,
            'disk_usage': 0,
            'camera_status': 'Initializing',
            'frame_count': 0,
            'network_sent': 0,
            'network_recv': 0,
            'vision_mode': 'Text Prompts',
            'spatial_audio_enabled': False,
            'layers': {
                'reflex': {'active': False, 'msg': 'Offline'},
                'thinker': {'active': False, 'msg': 'Offline'},
                'guide': {'active': False, 'msg': 'Offline'},
                'memory': {'active': False, 'msg': 'Offline'},
            },
            'logs': deque(maxlen=20)
        }
        self.lock = threading.Lock()
        self._initialized = True

    def add_log(self, msg: str):
        """Thread-safe logging to state."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {msg}"
        with self.lock:
            self.state['logs'].append(full_msg)
        logger.info(msg)

    async def initialize(self):
        """Initialize models and hardware in background."""
        if self.is_running:
            return
        self.is_running = True
        
        self.add_log("🚀 [SYSTEM] Initializing Neural Core...")
        
        # Layer 0+1: Guardian + Learner (YOLO)
        try:
            self.add_log(f"📦 [REFLEX] Loading YOLO11n-NCNN + YOLOE-11s...")
            await asyncio.to_thread(self._load_models)
            self.state['layers']['reflex'] = {'active': True, 'msg': 'Safety Scanning Active'}
            self.add_log(f"✅ [REFLEX] Models loaded on {YOLO_DEVICE} (80.7ms latency)")
            
            # Load Whisper STT
            self.add_log("🎤 [REFLEX] Loading Whisper STT...")
            await asyncio.to_thread(self._load_whisper)
            self.add_log("✅ [REFLEX] Whisper STT Ready")
            
        except Exception as e:
            self.add_log(f"❌ [REFLEX] Load failed: {e}")
            logger.exception("Failed to load YOLO/Whisper")

        # Camera with Picamera2/OpenCV auto-detection
        try:
            camera_index = int(os.getenv('CAMERA_INDEX', '0'))  # PiCamera Module 3 Wide on /dev/video0 (CSI)
            logger.debug(f"[CAMERA DEBUG] Attempting to open camera index: {camera_index}")
            self.add_log(f"📹 [VIDEO] Connecting to Camera {camera_index}...")
            
            # Use unified camera handler (auto-detects Picamera2 or OpenCV)
            self.cap = CameraHandler(camera_index=camera_index, width=640, height=480, fps=30)
            logger.debug(f"[CAMERA DEBUG] CameraHandler initialized")
            
            if not self.cap.isOpened():
                logger.error(f"[CAMERA DEBUG] Camera {camera_index} failed to open")
                raise Exception(f"Camera {camera_index} not found")
            
            # Get camera properties
            backend = self.cap.getBackendName()
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            logger.debug(f"[CAMERA DEBUG] Camera properties:")
            logger.debug(f"  - Resolution: {actual_width}x{actual_height}")
            logger.debug(f"  - Backend: {backend}")
            
            # Test frame capture
            ret, test_frame = self.cap.read()
            if ret:
                logger.debug(f"[CAMERA DEBUG] Test frame captured successfully: shape={test_frame.shape}")
                self.state['camera_status'] = f'✅ Active ({actual_width}x{actual_height}, {backend})'
            else:
                logger.error(f"[CAMERA DEBUG] Test frame capture failed")
                self.state['camera_status'] = '❌ Capture Failed'
                
            self.add_log(f"✅ [VIDEO] Camera {camera_index} connected ({actual_width}x{actual_height}, {backend} backend)")
        except Exception as e:
            self.add_log(f"❌ [VIDEO] Connection failed: {e}")
            logger.exception("Camera init failed")

        # Layer 2: Thinker (TTS)
        try:
            self.add_log("🔊 [THINKER] Loading Kokoro TTS...")
            await asyncio.to_thread(self._load_kokoro)
            self.state['layers']['thinker'] = {'active': True, 'msg': 'Kokoro TTS Ready'}
            self.add_log("✅ [THINKER] Kokoro TTS initialized")
        except Exception as e:
            self.add_log(f"❌ [THINKER] Kokoro failed: {e}")
            logger.exception("Kokoro TTS failed")

        # Layer 2: Gemini (Cloud AI)
        try:
            self.add_log("☁️ [THINKER] Initializing Gemini...")
            await asyncio.to_thread(self._init_gemini)
            self.state['layers']['guide'] = {'active': True, 'msg': 'Gemini API Ready'}
            self.add_log("✅ [THINKER] Gemini API connected")
        except Exception as e:
            self.add_log(f"❌ [THINKER] Gemini failed: {e}")
            logger.exception("Gemini init failed")

        # Layer 4: Memory
        self.state['layers']['memory'] = {'active': True, 'msg': 'SQLite Connected'}
        
        # Start Inference (Multi-Process or Thread mode)
        if self.use_multiprocess:
            await self._start_multiprocess_pipeline()
        else:
            threading.Thread(target=self._inference_loop, daemon=True).start()
            self.add_log("🎯 [SYSTEM] Neural Core Online! (Thread Mode)")

    async def _start_multiprocess_pipeline(self):
        """Start the multi-process parallel inference pipeline."""
        try:
            self.add_log("🔄 [SYSTEM] Starting Multi-Process Pipeline...")
            self.add_log("  • Core 0: Dashboard (NiceGUI)")
            self.add_log("  • Core 1: Guardian (YOLO11n)")
            self.add_log("  • Core 2: Learner (YOLOE-11s)")
            self.add_log("  • Core 3: Camera (Picamera2)")
            
            # Create ProcessManager
            self.process_manager = ProcessManager(
                frame_width=640,
                frame_height=480,
                target_fps=30,
                guardian_model=YOLO_MODEL_PATH if YOLO_MODEL_PATH else 'models/yolo11n.pt',
                learner_model=YOLOE_LEARNER_PATH if YOLOE_LEARNER_PATH else 'models/yoloe-11s-seg.pt',
                enable_guardian=True,
                enable_learner=True,
                enable_camera=True,
                enable_gpio=True  # Enable vibration motor on RPi
            )
            
            # Start in thread to not block
            success = await asyncio.to_thread(self.process_manager.start)
            
            if success:
                self.add_log("✅ [SYSTEM] Multi-Process Pipeline Active!")
                self.add_log("🎯 [SYSTEM] Neural Core Online! (4-Core Mode)")
                
                # Start polling thread for frame updates
                threading.Thread(target=self._multiprocess_poll_loop, daemon=True).start()
            else:
                self.add_log("⚠️ [SYSTEM] Multi-Process failed, falling back to Thread mode")
                self.use_multiprocess = False
                threading.Thread(target=self._inference_loop, daemon=True).start()
                
        except Exception as e:
            self.add_log(f"❌ [SYSTEM] Multi-Process error: {e}, using Thread mode")
            logger.exception("Multi-process startup failed")
            self.use_multiprocess = False
            threading.Thread(target=self._inference_loop, daemon=True).start()

    def _multiprocess_poll_loop(self):
        """Poll SharedFrameBuffer for frames and update dashboard state."""
        import numpy as np
        
        TARGET_ENCODE_FPS = 24
        frame_interval = 1.0 / TARGET_ENCODE_FPS
        last_encode_time = 0
        frame_count = 0
        fps_counter = deque(maxlen=30)
        prev_frame = None  # For motion-adaptive encoding
        
        while self.is_running and self.process_manager and self.process_manager.is_running():
            try:
                buffer = self.process_manager.get_frame_buffer()
                if buffer is None:
                    time.sleep(0.01)
                    continue
                
                slot = buffer.get_latest_frame()
                if slot is None:
                    time.sleep(0.01)
                    continue
                
                start_time = time.time()
                frame_count += 1
                
                # Get detection results from workers (via stats for now)
                status = self.process_manager.get_status()
                
                # Build detection string from worker stats
                guardian_stats = status.workers.get('Guardian')
                learner_stats = status.workers.get('Learner')
                
                detections = []
                if guardian_stats and guardian_stats.state == WorkerState.RUNNING:
                    detections.append(f"Guardian: {guardian_stats.frames_processed} frames")
                if learner_stats and learner_stats.state == WorkerState.RUNNING:
                    detections.append(f"Learner: {learner_stats.frames_processed} frames")
                
                merged = ' | '.join(detections) if detections else 'Multi-Process Active'
                
                # Calculate latency
                latency = (time.time() - start_time) * 1000
                fps_counter.append(1.0 / (time.time() - start_time) if time.time() - start_time > 0 else 0)
                avg_fps = sum(fps_counter) / len(fps_counter) if fps_counter else 0
                ram_usage = psutil.Process().memory_info().rss / 1024 / 1024
                
                # System monitoring
                if frame_count % 30 == 0:
                    try:
                        cpu_usage = psutil.cpu_percent(interval=0)
                        cpu_temp = 0
                        try:
                            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                                cpu_temp = float(f.read().strip()) / 1000.0
                        except:
                            pass
                        
                        disk_usage = psutil.disk_usage('/').percent
                        
                        with self.lock:
                            self.state['cpu_usage'] = cpu_usage
                            self.state['cpu_temp'] = cpu_temp
                            self.state['disk_usage'] = disk_usage
                            self.state['frame_count'] = frame_count
                    except Exception as e:
                        logger.debug(f"System monitoring error: {e}")
                
                # Update state
                with self.lock:
                    self.state['latency'] = latency
                    self.state['detections'] = merged
                    self.state['fps'] = avg_fps
                    self.state['ram_usage'] = ram_usage
                
                # Encode frame for display
                current_time = time.time()
                if current_time - last_encode_time >= frame_interval:
                    # Convert RGB to BGR for cv2
                    frame_bgr = cv2.cvtColor(slot.frame, cv2.COLOR_RGB2BGR)
                    
                    # Motion-adaptive JPEG quality
                    if prev_frame is not None:
                        diff = cv2.absdiff(frame_bgr, prev_frame)
                        motion = np.mean(diff)
                        quality = 50 if motion > 20 else 75  # Lower quality during motion
                    else:
                        quality = 65
                    prev_frame = frame_bgr.copy()
                    
                    _, buffer_jpg = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
                    b64 = base64.b64encode(buffer_jpg).decode('utf-8')
                    
                    with self.lock:
                        self.state['last_frame'] = f'data:image/jpeg;base64,{b64}'
                        self.state['frame_id'] = frame_count
                    
                    last_encode_time = current_time
                
                time.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Multi-process poll error: {e}")
                time.sleep(0.1)

    def _load_models(self):
        """Load YOLO models (blocking, run in thread)."""
        if YOLO_MODEL_PATH is None or YOLOE_LEARNER_PATH is None:
            logger.error("❌ Cannot load YOLO models - paths not found")
            self.dual_yolo = None
            return
        
        try:
            self.dual_yolo = DualYOLOHandler(
                guardian_model_path=YOLO_MODEL_PATH,
                learner_model_path=YOLOE_LEARNER_PATH,
                device=YOLO_DEVICE
            )
            logger.info("✅ DualYOLOHandler initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize DualYOLOHandler: {e}")
            self.dual_yolo = None

    def _load_whisper(self):
        """Load Whisper STT (blocking, run in thread)."""
        self.whisper_stt = WhisperSTT(model_size='base', device=YOLO_DEVICE)
        self.whisper_stt.load_model()

    def _load_kokoro(self):
        """Load Kokoro TTS (blocking, run in thread)."""
        self.kokoro_tts = KokoroTTS(lang_code="a", default_voice="af_alloy")
        self.kokoro_tts.load_pipeline()

    def _init_gemini(self):
        """Initialize Gemini API (blocking, run in thread)."""
        if GOOGLE_API_KEY:
            self.gemini_tts = GeminiTTS(api_key=GOOGLE_API_KEY)
            self.gemini_tts.initialize()
            
            self.streaming_player = StreamingAudioPlayer()
            self.gemini_live = GeminiLiveManager(
                api_key=GOOGLE_API_KEY,
                audio_callback=self._on_live_audio
            )

    def _on_live_audio(self, audio_bytes):
        """Callback for Gemini Live API audio."""
        if self.streaming_player:
            self.streaming_player.add_audio_chunk(audio_bytes)

    async def process_query(self, text: str):
        """Route and execute query with error handling."""
        try:
            self.add_log(f"🧠 Processing: '{text}'")
            
            # Check for memory commands first
            text_lower = text.lower()
            if 'remember' in text_lower or 'save this' in text_lower:
                await self._execute_memory_store(text)
                return
            elif 'find my' in text_lower or 'where is my' in text_lower:
                await self._execute_memory_recall(text)
                return

            # Stage 1: Intent Routing
            layer = self.intent_router.route(text)
            self.add_log(f"🎯 Routed to: {layer}")
            
            if layer == 'layer1':
                await self._execute_layer1(text)
            elif layer == 'layer2':
                await self._execute_layer2(text)
            elif layer == 'layer3':
                await self._execute_layer3(text)
        except Exception as e:
            self.add_log(f"❌ Query processing failed: {e}")
            logger.exception("process_query error")
            await self.speak("Sorry, I encountered an error processing that request.")

    async def _execute_memory_store(self, text: str):
        """Store current frame in memory."""
        try:
            obj_name = "object"
            if "remember" in text.lower():
                parts = text.lower().split("remember")
                if len(parts) > 1:
                    obj_name = parts[1].replace("this", "").replace("the", "").strip()
            
            if not self.state['last_frame']:
                await self.speak("No video frame to save.")
                return

            # Decode base64 frame
            frame_b64 = self.state['last_frame'].split(',')[1]
            frame_bytes = base64.b64decode(frame_b64)
            
            # Store
            success, mem_id, msg = self.memory_manager.store(
                object_name=obj_name,
                image_data=frame_bytes,
                detections={"raw": self.state['detections']},
                metadata={"query": text}
            )
            
            if success:
                self.add_log(f"💾 Saved memory: {mem_id}")
                await self.speak(f"I've remembered the {obj_name}.")
            else:
                self.add_log(f"❌ Memory save failed: {msg}")
                await self.speak("Sorry, I couldn't save that.")
        except Exception as e:
            self.add_log(f"❌ Memory store error: {e}")
            logger.exception("_execute_memory_store error")

    async def _execute_memory_recall(self, text: str):
        """Recall object from memory."""
        try:
            obj_name = "object"
            if "find my" in text.lower():
                obj_name = text.lower().split("find my")[1].strip()
            elif "where is my" in text.lower():
                obj_name = text.lower().split("where is my")[1].strip()
                
            memory = self.memory_manager.recall(obj_name)
            
            if memory:
                loc = memory.get('location_estimate', 'unknown location')
                ts = memory.get('timestamp', 'recently')
                await self.speak(f"I last saw your {obj_name} at {loc} on {ts}.")
            else:
                await self.speak(f"I don't have any memory of your {obj_name}.")
        except Exception as e:
            self.add_log(f"❌ Memory recall error: {e}")
            logger.exception("_execute_memory_recall error")

    async def _execute_layer1(self, text: str):
        """Reflex: Fast object detection response."""
        detections = self.state['detections']
        response = f"I see {detections}."
        await self.speak(response)

    async def _execute_layer2(self, text: str):
        """Thinker: Gemini Vision analysis."""
        try:
            if not self.gemini_tts:
                await self.speak("Gemini is not available.")
                return

            frame_b64 = self.state['last_frame'].split(',')[1]
            
            response = await asyncio.to_thread(
                self.gemini_tts.generate_response_from_image,
                frame_b64,
                text
            )
            await self.speak(response)
        except Exception as e:
            self.add_log(f"❌ Gemini error: {e}")
            logger.exception("_execute_layer2 error")
            await self.speak("Sorry, I couldn't analyze the image.")

    async def _execute_layer3(self, text: str):
        """Guide: Navigation and Memory."""
        if 'where am i' in text.lower():
            await self.speak("GPS location not yet implemented.")
        else:
            await self.speak("Navigation system ready.")

    async def speak(self, text: str):
        """Generate and play TTS with error handling."""
        try:
            if not self.kokoro_tts:
                self.add_log(f"💬 [No TTS]: {text}")
                return

            self.add_log(f"🔊 Speaking: {text}")
            audio_data = await asyncio.to_thread(
                self.kokoro_tts.generate_speech, text
            )
            
            if audio_data is not None:
                import scipy.io.wavfile as wavfile
                ts = int(time.time())
                path = f"temp_audio/tts_{ts}.wav"
                wavfile.write(path, 24000, audio_data)
                with self.lock:
                    self.state['last_tts'] = f"/{path}"
        except Exception as e:
            self.add_log(f"❌ TTS error: {e}")
            logger.exception("speak error")

    async def set_vision_mode(self, mode: str):
        """Switch YOLOE vision mode."""
        try:
            if not self.dual_yolo or not self.dual_yolo.learner:
                self.add_log("❌ YOLOE not initialized")
                return
            
            self.add_log(f"🔄 Switching to {mode} mode...")
            mode_map = {
                'Prompt-Free': YOLOEMode.PROMPT_FREE,
                'Text Prompts': YOLOEMode.TEXT_PROMPTS,
                'Visual Prompts': YOLOEMode.VISUAL_PROMPTS
            }
            
            if mode in mode_map:
                await asyncio.to_thread(
                    setattr, self.dual_yolo.learner, 'mode', mode_map[mode]
                )
                with self.lock:
                    self.state['vision_mode'] = mode
                self.add_log(f"✅ Vision Mode: {mode}")
        except Exception as e:
            self.add_log(f"❌ Mode switch error: {e}")
            logger.exception("set_vision_mode error")

    async def toggle_spatial_audio(self, enabled: bool):
        """Toggle 3D spatial audio."""
        try:
            with self.lock:
                self.state['spatial_audio_enabled'] = enabled
            self.add_log(f"🎧 Spatial Audio: {'ON' if enabled else 'OFF'}")
        except Exception as e:
            self.add_log(f"❌ Spatial audio error: {e}")
            logger.exception("toggle_spatial_audio error")

    def _inference_loop(self):
        """High-frequency background loop for AI inference with performance tracking."""
        TARGET_ENCODE_FPS = 15  # Limit to 15 FPS for RPi performance
        frame_interval = 1.0 / TARGET_ENCODE_FPS
        last_encode_time = 0
        frame_count = 0
        fps_counter = deque(maxlen=30)
        prev_frame = None  # For motion-adaptive encoding
        
        while self.is_running:
            try:
                if self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if ret:
                        start_time = time.time()
                        frame_count += 1
                        
                        # Dual YOLO Inference (with null safety)
                        if self.dual_yolo is not None:
                            g_results, l_results = self.dual_yolo.process_frame(frame)
                            
                            # Aggregation
                            g_list = [f"{g_results.names[int(b.cls)]}" for b in g_results.boxes] if g_results else []
                            l_list = [f"{l_results.names[int(b.cls)]}" for b in l_results.boxes] if l_results else []
                            merged = self.aggregator.merge_detections(g_list, l_list)
                        else:
                            # Model not loaded - skip inference
                            g_results, l_results = None, None
                            merged = '⚠️ YOLO Models Not Loaded'
                        
                        # Calculate Performance
                        latency = (time.time() - start_time) * 1000
                        fps_counter.append(1.0 / (time.time() - start_time) if time.time() - start_time > 0 else 0)
                        avg_fps = sum(fps_counter) / len(fps_counter) if fps_counter else 0
                        ram_usage = psutil.Process().memory_info().rss / 1024 / 1024  # MB
                        
                        # System Monitoring (update every 30 frames to reduce overhead)
                        if frame_count % 30 == 0:
                            try:
                                cpu_usage = psutil.cpu_percent(interval=0)
                                cpu_temp = 0
                                try:
                                    # RPi 5 temperature sensor
                                    with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                                        cpu_temp = float(f.read().strip()) / 1000.0
                                except:
                                    cpu_temp = 0
                                
                                disk_usage = psutil.disk_usage('/').percent
                                net_io = psutil.net_io_counters()
                                network_sent = net_io.bytes_sent / 1024  # KB
                                network_recv = net_io.bytes_recv / 1024  # KB
                                
                                with self.lock:
                                    self.state['cpu_usage'] = cpu_usage
                                    self.state['cpu_temp'] = cpu_temp
                                    self.state['disk_usage'] = disk_usage
                                    self.state['network_sent'] = network_sent / 1024  # Convert to MB
                                    self.state['network_recv'] = network_recv / 1024  # Convert to MB
                                    self.state['frame_count'] = frame_count
                            except Exception as e:
                                logger.debug(f"System monitoring error: {e}")
                        
                        # Update State
                        with self.lock:
                            self.state['latency'] = latency
                            self.state['detections'] = merged if merged else 'Scanning...'
                            self.state['fps'] = avg_fps
                            self.state['ram_usage'] = ram_usage
                        
                        # Conditional Encoding (Frame Rate Limiting)
                        current_time = time.time()
                        if current_time - last_encode_time >= frame_interval:
                            annotated = frame.copy()
                            if g_results:
                                for box in g_results.boxes:
                                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            
                            # Motion-adaptive JPEG quality
                            if prev_frame is not None:
                                diff = cv2.absdiff(annotated, prev_frame)
                                motion = np.mean(diff)
                                quality = 40 if motion > 20 else 60  # Lower quality during motion
                            else:
                                quality = 50
                            prev_frame = annotated.copy()
                            
                            _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, quality])
                            b64 = base64.b64encode(buffer).decode('utf-8')
                            
                            with self.lock:
                                self.state['last_frame'] = f'data:image/jpeg;base64,{b64}'
                                self.state['frame_id'] = frame_count
                            
                            last_encode_time = current_time
                
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"Inference loop error: {e}")
                time.sleep(0.1)

    def cleanup(self):
        """Cleanup resources."""
        self.is_running = False
        
        # Stop multi-process pipeline if active
        if self.process_manager:
            try:
                self.process_manager.stop()
                self.process_manager = None
                logger.info("Multi-process pipeline stopped")
            except Exception as e:
                logger.error(f"Error stopping process manager: {e}")
        
        if self.cap:
            self.cap.release()


# Global Hardware Manager Instance
manager = CortexHardwareManager()


class AudioBridge:
    """JavaScript ↔ Python audio communication bridge (per-client)."""
    
    def __init__(self):
        # Inject JavaScript (once per client)
        ui.add_body_html('''
        <script>
        window.audioRecorder = {
            mediaRecorder: null,
            audioChunks: [],
            stream: null,

            start: async function(deviceId) {
                try {
                    const constraints = {
                        audio: deviceId ? { deviceId: { exact: deviceId } } : true
                    };
                    
                    this.stream = await navigator.mediaDevices.getUserMedia(constraints);
                    this.mediaRecorder = new MediaRecorder(this.stream);
                    this.audioChunks = [];

                    this.mediaRecorder.ondataavailable = event => {
                        this.audioChunks.push(event.data);
                    };

                    this.mediaRecorder.start();
                    console.log("🎤 Recording started");
                    return true;
                } catch (err) {
                    console.error("❌ Error starting recording:", err);
                    return false;
                }
            },

            stop: function() {
                return new Promise((resolve, reject) => {
                    if (!this.mediaRecorder) {
                        resolve(null);
                        return;
                    }

                    this.mediaRecorder.onstop = async () => {
                        const audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
                        const reader = new FileReader();
                        
                        reader.readAsDataURL(audioBlob);
                        reader.onloadend = () => {
                            const base64String = reader.result.split(',')[1];
                            resolve(base64String);
                            
                            // Cleanup
                            this.stream.getTracks().forEach(track => track.stop());
                            this.mediaRecorder = null;
                            this.stream = null;
                            console.log("🛑 Recording stopped");
                        };
                    };

                    this.mediaRecorder.stop();
                });
            },

            getDevices: async function() {
                try {
                    await navigator.mediaDevices.getUserMedia({ audio: true });
                    const devices = await navigator.mediaDevices.enumerateDevices();
                    return devices
                        .filter(d => d.kind === 'audioinput')
                        .map(d => ({
                            id: d.deviceId,
                            label: d.label || `Microphone ${d.deviceId.slice(0, 5)}`
                        }));
                } catch (err) {
                    console.error("❌ Error getting devices:", err);
                    return [];
                }
            }
        };
        </script>
        ''')
        
    async def start_recording(self, device_id=None):
        """Signal JavaScript to start MediaRecorder."""
        try:
            return await ui.run_javascript(f'return window.audioRecorder.start("{device_id or ""}");')
        except Exception as e:
            logger.error(f"Start recording error: {e}")
            return False
        
    async def stop_recording(self):
        """Signal JavaScript to stop and return audio."""
        try:
            audio_b64 = await ui.run_javascript('return window.audioRecorder.stop();')
            if audio_b64:
                return base64.b64decode(audio_b64)
        except Exception as e:
            logger.error(f"Stop recording error: {e}")
        return None
        
    async def list_devices(self):
        """Get audio device list from browser."""
        try:
            return await ui.run_javascript('return window.audioRecorder.getDevices();')
        except Exception as e:
            logger.error(f"List devices error: {e}")
            return []


class NeuralCard(ui.card):
    """Custom NiceGUI card for AI Layers with Glassmorphism."""
    def __init__(self, title: str, icon: str, color: str):
        super().__init__()
        self.classes('w-full bg-slate-900/40 backdrop-blur-md border border-white/10 shadow-xl transition-all duration-500')
        self.style(f'border-left: 4px solid {color}')
        
        with self:
            with ui.row().classes('w-full items-center justify-between'):
                with ui.row().classes('items-center gap-2'):
                    ui.label(icon).classes('text-2xl')
                    ui.label(title).classes('text-lg font-bold text-slate-100')
                self.status_dot = ui.label('●').classes('text-xl transition-colors duration-300')
                self.status_dot.style('color: gray')
            
            self.content = ui.label('Offline').classes('text-xs font-mono text-slate-400 mt-2')
            
    def update_status(self, active: bool, text: str):
        """Update card status with thread-safe UI updates."""
        try:
            self.status_dot.style(f'color: {"#10b981" if active else "#ef4444"}')
            self.content.set_text(text)
            if active:
                self.classes('shadow-[0_0_20px_rgba(16,185,129,0.1)]')
            else:
                self.classes('shadow-none')
        except Exception as e:
            logger.error(f"NeuralCard update error: {e}")


class LayerCard:
    """Biotech-styled layer status card with update methods."""
    def __init__(self, title: str, icon: str, color: str):
        self.title = title
        self.icon = icon
        self.color = color
        self.active = False
        
        with ui.card().classes('bio-card layer-card p-4 transition-all duration-300 cursor-pointer'):
            with ui.row().classes('items-center justify-between'):
                with ui.row().classes('items-center gap-4'):
                    with ui.element('div').classes('w-10 h-10 rounded-full flex items-center justify-center').style(f'background: #042124; border: 1px solid #134e4a; color: {color};'):
                        ui.html(f'<span class="material-symbols-outlined">{icon}</span>', sanitize=False)
                    with ui.column().classes('gap-0'):
                        ui.label(title).classes('font-semibold text-white text-sm')
                        self.status_label = ui.label('STATUS: OFFLINE').classes('text-[10px] text-[#ccfbf1] opacity-50 text-mono mt-0.5')
                self.dot = ui.element('span').classes('w-2 h-2 rounded-full bg-[#134e4a]')
    
    def update_status(self, active: bool, msg: str):
        """Update layer card status and visual state."""
        self.active = active
        if active:
            self.status_label.set_text(f'STATUS: {msg.upper()}')
            self.status_label.classes('text-[10px] text-[#2dd4bf] text-mono mt-0.5')
            self.dot.classes('w-2 h-2 rounded-full bg-[#2dd4bf]')
            self.dot.style('box-shadow: 0 0 8px rgba(45, 212, 191, 1);')
        else:
            self.status_label.set_text(f'STATUS: {msg.upper()}')
            self.status_label.classes('text-[10px] text-[#ccfbf1] opacity-50 text-mono mt-0.5')
            self.dot.classes('w-2 h-2 rounded-full bg-[#134e4a]')
            self.dot.style('')


class CortexDashboard:
    """Main dashboard controller."""
    
    def __init__(self):
        self.cards: Dict[str, NeuralCard] = {}
        self.image_view = None
        self.latency_label = None
        self.fps_label = None
        self.ram_label = None
        self.detection_badge = None
        self.log_terminal = None
        self.chat_container = None
        self.input_field = None
        self.audio_bridge = AudioBridge()
        self.is_recording = False
        self.record_btn = None
        self.mode_label = None

    async def process_voice_input(self):
        """Process recorded audio through Whisper."""
        try:
            if not self.is_recording:
                success = await self.audio_bridge.start_recording()
                if success:
                    self.is_recording = True
                    self.record_btn.props('color=red icon=stop')
                    ui.notify('Listening...', type='info')
            else:
                self.is_recording = False
                self.record_btn.props('color=blue-6 icon=mic')
                ui.notify('Processing audio...', type='info')
                
                audio_bytes = await self.audio_bridge.stop_recording()
                if not audio_bytes:
                    ui.notify('No audio recorded', type='warning')
                    return

                timestamp = int(time.time())
                wav_path = os.path.join(AUDIO_TEMP_DIR, f"rec_{timestamp}.wav")
                with open(wav_path, 'wb') as f:
                    f.write(audio_bytes)
                
                if manager.whisper_stt:
                    text = await asyncio.to_thread(
                        manager.whisper_stt.transcribe_file, wav_path
                    )
                    
                    if text.strip():
                        with self.chat_container:
                            ui.chat_message(text, name='User', sent=True).classes('text-sm animate-fadeIn')
                        await manager.process_query(text)
                    else:
                        ui.notify('Could not understand audio', type='warning')
                else:
                    ui.notify('Whisper not initialized', type='negative')
        except Exception as e:
            logger.exception("Voice input error")
            ui.notify(f'Error: {str(e)}', type='negative')
            self.is_recording = False
            self.record_btn.props('color=blue-6 icon=mic')

    def build_ui(self):
        """Build the biotech-themed dashboard layout."""
        # Inject biotech CSS
        ui.add_head_html(BIOTECH_CSS, shared=True)
        
        # Override body styling
        ui.query('body').classes('bg-[#011618] min-h-screen text-[#ccfbf1] font-[Quicksand] overflow-hidden flex flex-col antialiased')
        
        # Header with breathing logo
        with ui.header().classes('bg-transparent h-20 px-8 flex items-center justify-between z-20'):
            with ui.row().classes('items-center gap-4'):
                # Logo with breathing glow
                with ui.element('div').classes('w-12 h-12 rounded-full flex items-center justify-center breathing-glow').style('background: linear-gradient(to top right, #2dd4bf, #3b82f6); box-shadow: 0 0 15px rgba(45, 212, 191, 0.3);'):
                    ui.html('<span class="material-symbols-outlined text-white text-3xl">psychology_alt</span>', sanitize=False)
                
                with ui.column().classes('gap-0'):
                    ui.label('Project Cortex').classes('text-2xl font-bold tracking-tight text-white drop-shadow-sm')
                    with ui.row().classes('items-center gap-2'):
                        ui.label('BIOTECH INTERFACE V2.4').classes('text-xs text-mono text-[#2dd4bf] uppercase tracking-widest opacity-80')
                        ui.element('span').classes('w-1.5 h-1.5 rounded-full bg-[#fbbf24] animate-pulse')
            
            # Performance Metrics
            with ui.row().classes('glass-panel px-6 py-2 rounded-full gap-6 text-xs text-mono').style('box-shadow: 0 4px 6px rgba(0,0,0,0.1);'):
                with ui.row().classes('items-center gap-2'):
                    ui.html('<span class="material-symbols-outlined text-sm">network_check</span>', sanitize=False)
                    ui.label('LAT:').classes('text-[#5eead4]')
                    self.latency_label = ui.label('0ms').classes('text-white')
                ui.element('div').classes('w-px h-4 bg-[#134e4a]')
                ui.label('FPS:').classes('text-[#5eead4]')
                self.fps_label = ui.label('0.0').classes('text-white')
                ui.element('div').classes('w-px h-4 bg-[#134e4a]')
                self.cpu_label = ui.label('CPU: 0%').classes('text-white')
                ui.element('div').classes('w-px h-4 bg-[#134e4a]')
                self.temp_label = ui.label('Temp: 0°C').classes('text-[#fbbf24]')
                ui.element('div').classes('w-px h-4 bg-[#134e4a]')
                self.ram_label = ui.label('RAM: 0 MB').classes('text-[#818cf8]')
                ui.element('div').classes('w-px h-4 bg-[#134e4a]')
                self.camera_label = ui.label('Cam: 0f').classes('text-[#2dd4bf]')
                ui.button(icon='refresh', on_click=lambda: ui.notify('Resyncing...', type='info')).props('flat round size=sm').classes('ml-2 hover:text-white transition-colors')

        # Main 12-Column Grid Layout (3-7-2 ratio matching code.html)
        with ui.element('main').classes('flex-1 grid grid-cols-12 gap-6 p-8 pt-2 overflow-hidden').style('height: calc(100vh - 80px);'):
            
            # ========== LEFT SIDEBAR: System Vitals + Layer Cards (col-span-3) ==========
            with ui.column().classes('col-span-3 flex flex-col gap-6 overflow-y-auto pr-2 pb-10'):
                # System Vitals Card
                with ui.card().classes('glass-panel p-6 relative overflow-hidden shadow-lg'):
                    ui.html('<div class="absolute top-0 right-0 w-32 h-32 rounded-full blur-2xl pointer-events-none" style="background: rgba(45, 212, 191, 0.05); margin-right: -2.5rem; margin-top: -2.5rem;"></div>', sanitize=False)
                    
                    with ui.row().classes('items-center gap-2 mb-6'):
                        ui.html('<span class="material-symbols-outlined text-lg text-[#2dd4bf]">vital_signs</span>', sanitize=False)
                        ui.label('SYSTEM VITALS').classes('text-xs font-bold text-[#2dd4bf] uppercase tracking-widest')
                    
                    # CPU Usage
                    with ui.element('div').classes('group mb-6'):
                        with ui.row().classes('justify-between mb-2 text-xs'):
                            ui.label('NEURAL_CPU').classes('text-[#ccfbf1] opacity-70 group-hover:text-white transition-colors')
                            self.cpu_value = ui.label('12%').classes('text-[#ccfbf1] opacity-70')
                        self.cpu_progress = ui.linear_progress(value=0.12).props('size=12px rounded').classes('w-full gradient-progress-teal').style('background: #042124; border: 1px solid rgba(19, 78, 74, 0.5);')
                        self.cpu_progress.props('color=teal')
                    
                    # Temperature
                    with ui.element('div').classes('group mb-6'):
                        with ui.row().classes('justify-between mb-2 text-xs'):
                            ui.label('CORE_TEMP').classes('text-[#ccfbf1] opacity-70 group-hover:text-white transition-colors')
                            self.temp_value = ui.label('42°C').classes('text-[#fbbf24]')
                        self.temp_progress = ui.linear_progress(value=0.42).props('size=12px rounded color=amber').classes('w-full gradient-progress-amber').style('background: #042124; border: 1px solid rgba(19, 78, 74, 0.5);')
                    
                    # Memory
                    with ui.element('div').classes('group mb-6'):
                        with ui.row().classes('justify-between mb-2 text-xs'):
                            ui.label('SYNAPTIC_MEM').classes('text-[#ccfbf1] opacity-70 group-hover:text-white transition-colors')
                            self.ram_value = ui.label('2.4 GB').classes('text-[#818cf8]')
                        self.ram_progress = ui.linear_progress(value=0.30).props('size=12px rounded color=indigo').classes('w-full gradient-progress-indigo').style('background: #042124; border: 1px solid rgba(19, 78, 74, 0.5);')
                    
                    # Disk Storage
                    with ui.element('div').classes('group mb-6'):
                        with ui.row().classes('justify-between mb-2 text-xs'):
                            ui.label('STORAGE_VAULT').classes('text-[#ccfbf1] opacity-70 group-hover:text-white transition-colors')
                            self.disk_value = ui.label('45.2%').classes('text-[#fb7185]')
                        self.disk_progress = ui.linear_progress(value=0.45).props('size=12px rounded color=rose').classes('w-full gradient-progress-rose').style('background: #042124; border: 1px solid rgba(19, 78, 74, 0.5);')
                    
                    ui.separator().classes('my-4').style('background: rgba(19, 78, 74, 0.5);')
                    
                    # Camera Status
                    with ui.row().classes('justify-between mb-2'):
                        ui.label('OPTICS').classes('text-[10px] text-[#ccfbf1] opacity-50 uppercase')
                        self.camera_status_label = ui.label('READY').classes('text-[10px] text-[#2dd4bf] text-mono font-bold')
                    with ui.row().classes('justify-between mb-4'):
                        ui.label('FRAME_COUNT').classes('text-[10px] text-[#ccfbf1] opacity-50 uppercase')
                        self.frame_count_label = ui.label('0').classes('text-[10px] text-white text-mono')
                    
                    ui.separator().classes('my-4').style('background: rgba(19, 78, 74, 0.5);')
                    
                    # Network/Camera Stats
                    with ui.row().classes('gap-3 mt-4'):
                        with ui.card().classes('flex-1 p-3 text-center').style('background: rgba(4, 33, 36, 0.5); border: 1px solid rgba(19, 78, 74, 0.3); border-radius: 1rem;'):
                            ui.html('<span class="material-symbols-outlined text-[#2dd4bf] text-xl mb-1">upload</span>', sanitize=False)
                            ui.label('UPSTREAM').classes('text-[10px] text-[#ccfbf1] opacity-50 uppercase')
                            self.net_sent_label = ui.label('12.5 MB/s').classes('text-xs text-mono font-bold text-white')
                        
                        with ui.card().classes('flex-1 p-3 text-center').style('background: rgba(4, 33, 36, 0.5); border: 1px solid rgba(19, 78, 74, 0.3); border-radius: 1rem;'):
                            ui.html('<span class="material-symbols-outlined text-[#818cf8] text-xl mb-1">download</span>', sanitize=False)
                            ui.label('DOWNSTREAM').classes('text-[10px] text-[#ccfbf1] opacity-50 uppercase')
                            self.net_recv_label = ui.label('1.2 GB/s').classes('text-xs text-mono font-bold text-white')
                
                # Neural Layers Section
                ui.label('CORTEX LAYERS').classes('text-xs font-bold text-[#2dd4bf] uppercase tracking-widest pl-2 mt-4 mb-4')
                
                # Initialize cards dictionary for update_tick
                self.cards = {}
                
                # Layer 0+1: Reflex
                reflex_card = LayerCard('Reflex Layer', 'bolt', '#fbbf24')
                self.reflex_status = reflex_card.status_label
                self.reflex_dot = reflex_card.dot
                self.cards['reflex'] = reflex_card
                
                # Layer 2: Thinker
                thinker_card = LayerCard('Cognition Layer', 'psychology', '#818cf8')
                self.thinker_status = thinker_card.status_label
                self.thinker_dot = thinker_card.dot
                self.cards['thinker'] = thinker_card
                
                # Layer 3+4: Guide + Memory
                memory_card = LayerCard('Memory Core', 'memory', '#fb7185')
                self.memory_status = memory_card.status_label
                self.memory_dot = memory_card.dot
                self.cards['memory'] = memory_card
                self.cards['guide'] = memory_card  # Guide shares the same visual as memory
                
                # System Controls
                with ui.card().classes('glass-panel p-5 mt-4'):
                    with ui.row().classes('justify-between items-center mb-4'):
                        ui.label('PROTOCOL OVERRIDE').classes('text-xs font-bold text-[#2dd4bf] uppercase tracking-widest')
                        ui.html('<span class="material-symbols-outlined text-[#fbbf24] text-sm animate-spin-slow">settings</span>', sanitize=False)
                    
                    # YOLOE Mode Selector
                    ui.select(
                        ['Prompt-Free', 'Text Prompts', 'Visual Prompts'],
                        value='Text Prompts',
                        label='Vision Mode',
                        on_change=lambda e: asyncio.create_task(manager.set_vision_mode(e.value))
                    ).classes('w-full text-sm')
                    self.mode_label = ui.label('Mode: Text Prompts').classes('text-xs text-[#5eead4] mt-1')
                    
                    # Toggles
                    with ui.element('label').classes('flex items-center justify-between p-2 rounded-xl hover:bg-[#115e59] opacity-10 cursor-pointer transition-colors mt-3'):
                        ui.label('Spatial Audio').classes('text-sm font-medium text-[#ccfbf1]')
                        ui.switch().props('color=teal')
                    
                    with ui.element('label').classes('flex items-center justify-between p-2 rounded-xl hover:bg-[#115e59] opacity-10 cursor-pointer transition-colors'):
                        ui.label('Voice Synthesis').classes('text-sm font-medium text-[#ccfbf1]')
                        ui.switch().props('color=teal')

            # ========== CENTER: Video Feed + Neural Stream (col-span-7) ==========
            with ui.column().classes('col-span-7 flex flex-col gap-6 h-full'):
                # Video Feed with scanline and corner decorations
                with ui.card().classes('flex-grow bg-black relative overflow-hidden').style('border-radius: 1.5rem; border: 1px solid #134e4a; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);'):
                    # Scanline effect
                    ui.html('<div class="scanline"></div>', sanitize=False)
                    
                    # Corner decorations
                    ui.html('<div class="corner-tl"></div>', sanitize=False)
                    ui.html('<div class="corner-br"></div>', sanitize=False)
                    
                    # Vignette overlay
                    ui.html('<div class="absolute inset-0 pointer-events-none" style="background: radial-gradient(circle at center, transparent 0%, #000000 120%);"></div>', sanitize=False)
                    
                    # Offline State (Centered)
                    with ui.column().classes('absolute inset-0 flex items-center justify-center z-0'):
                        with ui.element('div').classes('text-center opacity-60'):
                            with ui.element('div').classes('w-24 h-24 rounded-full border-2 border-dashed border-[#134e4a] mx-auto mb-4 flex items-center justify-center animate-spin-slow'):
                                ui.html('<span class="material-symbols-outlined text-4xl text-[#5eead4] opacity-50">videocam_off</span>', sanitize=False)
                            ui.label('OPTICAL FEED OFFLINE').classes('font-mono text-sm tracking-[0.2em] text-[#2dd4bf] opacity-70')
                            ui.label('SEARCHING FOR SIGNAL...').classes('font-mono text-[10px] text-[#ccfbf1] opacity-30 mt-2')

                    # Video feed (z-index 10 to cover offline state when active)
                    self.image_view = ui.interactive_image().classes('w-full h-full object-cover z-10 hidden')
                    
                    # Status badges (z-index 20)
                    with ui.row().classes('absolute bottom-6 left-8 gap-3 items-center z-20'):
                        with ui.element('span').classes('flex items-center gap-2 px-3 py-1 rounded-full text-[10px] font-bold shadow-glow').style('background: rgba(251, 113, 133, 0.1); border: 1px solid rgba(251, 113, 133, 0.3); color: #fb7185;'):
                            ui.element('span').classes('w-1.5 h-1.5 rounded-full bg-[#fb7185] animate-pulse')
                            ui.label('LIVE CORE')
                        
                        self.detection_badge = ui.badge('SCAN_MODE: ACTIVE').props('outline').classes('text-[10px] text-mono').style('background: rgba(4, 33, 36, 0.8); color: #ccfbf1; border: 1px solid #134e4a; backdrop-filter: blur(12px);')
                    
                    # Grain texture (z-index 30)
                    ui.html('<div class="absolute inset-0 pointer-events-none mix-blend-overlay opacity-10 z-30" style="background-image: url(https://grainy-gradients.vercel.app/noise.svg);"></div>', sanitize=False)
                
                # Neural Stream Chat (35% height)
                with ui.card().classes('glass-panel flex flex-col overflow-hidden').style('height: 35%; border: 1px solid rgba(19, 78, 74, 0.5);'):
                    # Header
                    with ui.row().classes('px-6 py-3 border-b justify-between items-center').style('background: rgba(4, 33, 36, 0.3); border-color: rgba(19, 78, 74, 0.3); backdrop-filter: blur(8px);'):
                        with ui.row().classes('items-center gap-2'):
                            ui.html('<span class="material-symbols-outlined text-sm text-[#2dd4bf]">terminal</span>', sanitize=False)
                            ui.label('NEURAL STREAM').classes('text-xs font-bold text-[#2dd4bf] uppercase tracking-widest')
                        with ui.row().classes('gap-1.5'):
                            ui.element('span').classes('w-2.5 h-2.5 rounded-full border').style('background: #134e4a; border-color: #115e59;')
                            ui.element('span').classes('w-2.5 h-2.5 rounded-full border').style('background: #134e4a; border-color: #115e59;')
                    
                    # Chat messages
                    self.chat_container = ui.scroll_area().classes('flex-grow p-6 text-mono text-sm')
                    with self.chat_container:
                        ui.label('-- STREAM INITIALIZED --').classes('text-[#ccfbf1] opacity-30 text-[10px] text-center tracking-widest mb-4')
                    
                    # Input area
                    with ui.row().classes('p-4 items-center gap-3').style('background: rgba(4, 33, 36, 0.4); border-top: 1px solid rgba(19, 78, 74, 0.3); backdrop-filter: blur(12px);'):
                        self.record_btn = ui.button(icon='mic', on_click=self.process_voice_input).props('round flat').classes('w-10 h-10 rounded-full transition-colors').style('background: rgba(17, 94, 89, 0.2); color: #2dd4bf;')
                        
                        self.input_field = ui.input(placeholder='Enter command or query...').props('rounded outlined standout').classes('flex-grow text-sm').style('background: rgba(1, 22, 24, 0.6); border: 1px solid rgba(19, 78, 74, 0.5); border-radius: 2rem; color: white;')
                        
                        ui.button(icon='arrow_upward', on_click=self.send_message).props('round').classes('w-10 h-10 shadow-glow transform transition-all hover:scale-105').style('background: #2dd4bf; color: #011618;')

            # ========== RIGHT SIDEBAR: Memory Recalls (col-span-2) ==========
            with ui.column().classes('col-span-2 flex flex-col h-full overflow-hidden'):
                with ui.row().classes('items-center justify-between mb-6 px-2'):
                    ui.label('MEMORY RECALLS').classes('text-xs font-bold text-[#2dd4bf] uppercase tracking-widest')
                    ui.badge('5 ACTIVE').classes('text-[10px] px-2 py-0.5 rounded-full').style('background: rgba(251, 191, 36, 0.1); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.2);')
                
                # Memory cards with staggered organic borders
                self.memory_grid = ui.scroll_area().classes('flex-grow pr-2 pb-10')
                with self.memory_grid:
                    with ui.column().classes('gap-5'):
                        for i, (title, color, node_id) in enumerate([
                            ('Fauna Pattern', '#fbbf24', '00'),
                            ('Urban Grid', '#2dd4bf', '01'),
                            ('Audio Input', '#818cf8', '02'),
                            ('Terrain Data', '#fb7185', '03'),
                            ('Social Hub', '#fbbf24', '04')
                        ]):
                            heights = ['h-40', 'h-48', 'h-36', 'h-44', 'h-32']
                            border_styles = ['rounded-tr-sm', 'rounded-bl-sm', 'rounded-tl-sm', 'rounded-br-sm', 'rounded-tl-sm']
                            
                            with ui.card().classes(f'group relative bubble-radius {border_styles[i]} overflow-hidden {heights[i]} border transition-all duration-300 hover:scale-[1.03] hover:-translate-y-1 cursor-pointer').style(f'border-color: rgba(19, 78, 74, 0.5); background: rgba(10, 48, 51, 0.6);'):
                                ui.image(f'https://picsum.photos/400/400?random={i}').classes('w-full h-full object-cover opacity-70 group-hover:opacity-100 transition-opacity duration-500 scale-110 group-hover:scale-100')
                                
                                # Gradient overlay
                                ui.html('<div class="absolute inset-0 opacity-90" style="background: linear-gradient(to top, #011618, transparent, transparent);"></div>', sanitize=False)
                                
                                # Info overlay
                                with ui.row().classes('absolute bottom-0 w-full p-4 justify-between items-end'):
                                    with ui.column().classes('gap-0'):
                                        ui.label(f'RECALL_NODE_{node_id}').classes('text-[10px] text-mono mb-1').style(f'color: {color};')
                                        ui.label(title).classes('text-sm font-semibold text-white leading-tight')
                                    ui.html('<span class="material-symbols-outlined text-white text-lg opacity-0 group-hover:opacity-100 transition-all transform translate-y-2 group-hover:translate-y-0">open_in_new</span>', sanitize=False)

        # Terminal Log for Neural Console
        self.log_terminal = ui.log().classes('hidden')  # Hidden but accessible for update_tick logging

    def send_message(self):
        """Send text message to Cortex."""
        text = self.input_field.value
        if not text:
            return
        with self.chat_container:
            ui.chat_message(text, name='User', sent=True).classes('text-sm animate-fadeIn')
            self.input_field.value = ''
        
        asyncio.create_task(manager.process_query(text))


@ui.page('/')
async def main_page():
    """Main dashboard page with real-time state polling."""
    dashboard = CortexDashboard()
    dashboard.build_ui()
    
    # Audio player for TTS
    audio_player = ui.audio(src='').props('autoplay').classes('hidden')
    
    # Start Hardware Core if not running
    if not manager.is_running:
        asyncio.create_task(manager.initialize())

    last_tts_played = None

    async def update_tick():
        """Polling function with client context protection."""
        nonlocal last_tts_played
        
        try:
            state = manager.state
            
            # Update Video
            if state['last_frame']:
                dashboard.image_view.set_source(state['last_frame'])
                dashboard.image_view.classes(remove='hidden')
            else:
                dashboard.image_view.classes(add='hidden')
            
            # Update Top Bar Performance Metrics
            dashboard.latency_label.set_text(f"Latency: {state['latency']:.1f} ms")
            dashboard.fps_label.set_text(f"FPS: {state['fps']:.1f}")
            dashboard.cpu_label.set_text(f"CPU: {state['cpu_usage']:.1f}%")
            dashboard.temp_label.set_text(f"Temp: {state['cpu_temp']:.1f}°C")
            dashboard.ram_label.set_text(f"RAM: {state['ram_usage']:.0f} MB")
            dashboard.camera_label.set_text(f"Cam: {state['frame_count']}f")
            dashboard.detection_badge.set_text(state['detections'])
            
            # Update System Monitor Sidebar
            dashboard.cpu_progress.set_value(state['cpu_usage'] / 100.0)
            dashboard.cpu_value.set_text(f"{state['cpu_usage']:.1f}%")
            
            dashboard.temp_progress.set_value(min(state['cpu_temp'] / 85.0, 1.0))  # Max 85°C
            dashboard.temp_value.set_text(f"{state['cpu_temp']:.1f}°C")
            
            dashboard.ram_progress.set_value(state['ram_usage'] / 3900.0)  # 4GB RPi 5
            dashboard.ram_value.set_text(f"{state['ram_usage']:.0f} MB")
            
            dashboard.disk_progress.set_value(state['disk_usage'] / 100.0)
            dashboard.disk_value.set_text(f"{state['disk_usage']:.1f}%")
            
            dashboard.camera_status_label.set_text(state['camera_status'])
            dashboard.frame_count_label.set_text(str(state['frame_count']))
            dashboard.net_sent_label.set_text(f"{state['network_sent']:.1f} KB/s")
            dashboard.net_recv_label.set_text(f"{state['network_recv']:.1f} KB/s")
            
            # Update Mode Label
            if dashboard.mode_label:
                dashboard.mode_label.set_text(f"Mode: {state['vision_mode']}")
            
            # Update Layer Cards
            for key, card in dashboard.cards.items():
                layer_info = state['layers'].get(key, {'active': False, 'msg': 'Offline'})
                card.update_status(layer_info['active'], layer_info['msg'])
                
            # Update Neural Console
            dashboard.log_terminal.clear()
            for log in state['logs']:
                dashboard.log_terminal.push(log)
                
            # Check for new TTS
            if 'last_tts' in state and state['last_tts'] != last_tts_played:
                last_tts_played = state['last_tts']
                audio_player.set_source(last_tts_played)
                with dashboard.chat_container:
                    ui.chat_message('Playing audio response...', name='Cortex', sent=False).classes('text-sm animate-fadeIn')
        except Exception as e:
            logger.error(f"Update tick error: {e}")

    # UI Refresh Timer (15 FPS)
    ui.timer(0.066, update_tick)
    
    # Serve temp audio files
    app.add_static_files('/temp_audio', 'temp_audio')


# Register shutdown handler
app.on_shutdown(manager.cleanup)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='Cortex Neural Dashboard',
        dark=True,
        port=5000,
        host='0.0.0.0',
        storage_secret='project_cortex_secret_key_2026',
        favicon='🧠'
    )
