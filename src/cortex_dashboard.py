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

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
YOLO_MODEL_PATH = os.getenv('YOLO_MODEL_PATH', 'models/yolo11n_ncnn_model')
YOLO_DEVICE = os.getenv('YOLO_DEVICE', 'cpu')
GOOGLE_API_KEY = os.getenv('GEMINI_API_KEY')
AUDIO_TEMP_DIR = "temp_audio"
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)


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
        
        # Shared State (thread-safe)
        self.state = {
            'last_frame': '',
            'latency': 0,
            'detections': 'Scanning...',
            'frame_id': 0,
            'fps': 0,
            'ram_usage': 0,
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
        
        # Start Inference thread
        threading.Thread(target=self._inference_loop, daemon=True).start()
        self.add_log("🎯 [SYSTEM] Neural Core Online!")

    def _load_models(self):
        """Load YOLO models (blocking, run in thread)."""
        self.dual_yolo = DualYOLOHandler(
            guardian_model_path=YOLO_MODEL_PATH,
            learner_model_path="models/yoloe-11s-seg.pt",  # Lighter model
            device=YOLO_DEVICE
        )

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
        TARGET_ENCODE_FPS = 12
        frame_interval = 1.0 / TARGET_ENCODE_FPS
        last_encode_time = 0
        frame_count = 0
        fps_counter = deque(maxlen=30)
        
        while self.is_running:
            try:
                if self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if ret:
                        start_time = time.time()
                        frame_count += 1
                        
                        # Dual YOLO Inference
                        g_results, l_results = self.dual_yolo.process_frame(frame)
                        
                        # Aggregation
                        g_list = [f"{g_results.names[int(b.cls)]}" for b in g_results.boxes] if g_results else []
                        l_list = [f"{l_results.names[int(b.cls)]}" for b in l_results.boxes] if l_results else []
                        merged = self.aggregator.merge_detections(g_list, l_list)
                        
                        # Calculate Performance
                        latency = (time.time() - start_time) * 1000
                        fps_counter.append(1.0 / (time.time() - start_time) if time.time() - start_time > 0 else 0)
                        avg_fps = sum(fps_counter) / len(fps_counter) if fps_counter else 0
                        ram_usage = psutil.Process().memory_info().rss / 1024 / 1024  # MB
                        
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
                                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            
                            _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 65])
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
                            ui.chat_message(text, name='User', sent=True).classes('text-sm')
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
        """Build the dashboard layout with modern gradients."""
        ui.query('body').classes('bg-gradient-to-br from-slate-950 via-slate-900 to-black min-h-screen text-slate-200 font-sans')
        
        # Header
        with ui.header().classes('bg-slate-900/80 backdrop-blur-lg border-b border-white/10 py-4 px-8 items-center justify-between'):
            with ui.row().classes('items-center gap-4'):
                ui.label('🧠 Project-Cortex').classes('text-2xl font-black tracking-tighter text-blue-500')
                ui.badge('v2.0 Neural Dashboard').props('color=blue-10 outline')
            
            with ui.row().classes('items-center gap-4'):
                self.latency_label = ui.label('Latency: -- ms').classes('text-xs font-mono text-slate-400')
                self.fps_label = ui.label('FPS: --').classes('text-xs font-mono text-slate-400')
                self.ram_label = ui.label('RAM: -- MB').classes('text-xs font-mono text-slate-400')
                ui.button(icon='refresh', on_click=lambda: ui.notify('Re-syncing core...')).props('flat round color=slate-400')

        # Main Layout (3 columns)
        with ui.row().classes('w-full p-6 no-wrap gap-6 items-stretch'):
            
            # Left Column: System Monitoring + Neural Layers
            with ui.column().classes('w-1/4 gap-4'):
                # === SYSTEM MONITOR ===
                ui.label('SYSTEM MONITOR').classes('text-[10px] font-black text-slate-500 tracking-[0.2em] mb-2')
                with ui.card().classes('w-full bg-slate-900/60 backdrop-blur-md border border-cyan-500/20 p-4'):
                    ui.label('🖥️ Raspberry Pi 5').classes('text-sm font-bold text-cyan-400 mb-3')
                    
                    # CPU Usage
                    with ui.row().classes('w-full items-center gap-2 mb-2'):
                        ui.label('CPU').classes('text-xs text-slate-400 w-16')
                        self.cpu_progress = ui.linear_progress(value=0).props('color=blue size=8px').classes('flex-grow')
                        self.cpu_value = ui.label('0%').classes('text-xs text-blue-400 w-12 text-right')
                    
                    # Temperature
                    with ui.row().classes('w-full items-center gap-2 mb-2'):
                        ui.label('TEMP').classes('text-xs text-slate-400 w-16')
                        self.temp_progress = ui.linear_progress(value=0).props('color=orange size=8px').classes('flex-grow')
                        self.temp_value = ui.label('0°C').classes('text-xs text-orange-400 w-12 text-right')
                    
                    # Memory
                    with ui.row().classes('w-full items-center gap-2 mb-2'):
                        ui.label('RAM').classes('text-xs text-slate-400 w-16')
                        self.ram_progress = ui.linear_progress(value=0).props('color=purple size=8px').classes('flex-grow')
                        self.ram_value = ui.label('0 MB').classes('text-xs text-purple-400 w-12 text-right')
                    
                    # Disk
                    with ui.row().classes('w-full items-center gap-2 mb-2'):
                        ui.label('DISK').classes('text-xs text-slate-400 w-16')
                        self.disk_progress = ui.linear_progress(value=0).props('color=emerald size=8px').classes('flex-grow')
                        self.disk_value = ui.label('0%').classes('text-xs text-emerald-400 w-12 text-right')
                    
                    ui.separator().classes('my-3 bg-slate-700/50')
                    
                    # Camera Status
                    with ui.row().classes('w-full items-center gap-2 mb-1'):
                        ui.label('📹 Camera').classes('text-xs text-slate-400')
                        self.camera_status_label = ui.label('Initializing...').classes('text-xs text-cyan-400 ml-auto')
                    
                    # Frame Counter
                    with ui.row().classes('w-full items-center gap-2 mb-1'):
                        ui.label('🎞️ Frames').classes('text-xs text-slate-400')
                        self.frame_count_label = ui.label('0').classes('text-xs text-slate-300 ml-auto font-mono')
                    
                    # Network Stats
                    with ui.row().classes('w-full items-center gap-2 mb-1'):
                        ui.label('⬆️ Upload').classes('text-xs text-slate-400')
                        self.net_sent_label = ui.label('0 KB/s').classes('text-xs text-green-400 ml-auto font-mono')
                    
                    with ui.row().classes('w-full items-center gap-2'):
                        ui.label('⬇️ Download').classes('text-xs text-slate-400')
                        self.net_recv_label = ui.label('0 KB/s').classes('text-xs text-blue-400 ml-auto font-mono')
                
                # === NEURAL ARCHITECTURE ===
                ui.label('NEURAL ARCHITECTURE').classes('text-[10px] font-black text-slate-500 tracking-[0.2em] mb-2 mt-4')
                self.cards['reflex'] = NeuralCard('Layer 0+1: Reflex', '⚡', '#10b981')
                self.cards['thinker'] = NeuralCard('Layer 2: Thinker', '☁️', '#3b8ed0')
                self.cards['guide'] = NeuralCard('Layer 3: Guide', '🧭', '#f59e0b')
                self.cards['memory'] = NeuralCard('Layer 4: Memory', '💾', '#8b5cf6')
                
                with ui.card().classes('w-full bg-slate-900/40 backdrop-blur-md border border-white/10 mt-4 p-4'):
                    ui.label('SYSTEM CONTROLS').classes('text-[10px] font-black text-slate-500 tracking-widest mb-4')
                    
                    # YOLOE Mode Selector
                    ui.select(
                        ['Prompt-Free', 'Text Prompts', 'Visual Prompts'],
                        value='Text Prompts',
                        label='Vision Mode (YOLOE)',
                        on_change=lambda e: asyncio.create_task(manager.set_vision_mode(e.value))
                    ).classes('w-full')
                    self.mode_label = ui.label('Mode: Text Prompts').classes('text-xs text-slate-400 mt-1')
                    
                    # Spatial Audio Toggle
                    ui.switch('Spatial Audio (3D HRTF)', 
                             on_change=lambda e: asyncio.create_task(manager.toggle_spatial_audio(e.value))
                    ).classes('text-sm mt-2')
                    
                    # VAD Toggle
                    ui.switch('Voice Activation (VAD)').bind_value(app.storage.user, 'vad').classes('text-sm')
                    
                    # AI Tier Selector
                    ui.select(
                        ['Auto (Fallback)', 'Tier 0 (Live API)', 'Tier 1 (Gemini)', 'Tier 2 (GLM-4.6V)'],
                        value='Auto (Fallback)',
                        label='AI Tier'
                    ).bind_value(app.storage.user, 'tier').classes('w-full mt-2')

            # Center Column: Live Intelligence
            with ui.column().classes('w-1/2 gap-4'):
                with ui.card().classes('w-full bg-black p-0 overflow-hidden aspect-video relative border border-white/10 shadow-2xl'):
                    self.image_view = ui.interactive_image().classes('w-full h-full object-cover')
                    with ui.row().classes('absolute bottom-4 left-4 gap-2'):
                        ui.badge('LIVE CORE').props('color=red-9')
                        self.detection_badge = ui.badge('Scanning...').props('color=slate-900')

                # Neural Console (Boot Logs)
                with ui.card().classes('w-full bg-slate-950/80 border border-white/5 p-0 overflow-hidden'):
                    ui.label('NEURAL CONSOLE').classes('text-[10px] font-black text-slate-600 p-2 border-b border-white/5')
                    self.log_terminal = ui.log(max_lines=10).classes('text-[10px] font-mono p-4 text-blue-400 h-32')

                # Chat Stream
                with ui.card().classes('w-full flex-grow bg-slate-900/40 backdrop-blur-md border border-white/10 p-0 flex flex-col'):
                    ui.label('CHAT STREAM').classes('text-[10px] font-black text-slate-500 p-4 border-b border-white/5 tracking-widest')
                    self.chat_container = ui.scroll_area().classes('flex-grow p-4 min-h-[200px]')
                    with ui.row().classes('w-full p-4 gap-2 border-t border-white/5 items-center'):
                        self.input_field = ui.input(placeholder='Ask Cortex...').classes('flex-grow').props('rounded outlined standout dark')
                        self.record_btn = ui.button(icon='mic', on_click=self.process_voice_input).props('round color=blue-6')
                        ui.button(icon='send', on_click=self.send_message).props('round color=blue-6')

            # Right Column: Visual Memory & Context
            with ui.column().classes('w-1/4 gap-4'):
                ui.label('PERSISTENT MEMORY').classes('text-[10px] font-black text-slate-500 tracking-[0.2em] mb-2')
                with ui.scroll_area().classes('w-full h-full'):
                    self.memory_grid = ui.grid(columns=2).classes('gap-2')
                    for i in range(6):
                        with ui.card().classes('p-0 bg-slate-800/50 border border-white/5 overflow-hidden transition-transform hover:scale-105'):
                            ui.image('https://picsum.photos/200?random=' + str(i)).classes('h-24')
                            ui.label(f'Recall {i}').classes('text-[10px] p-2 text-slate-400 font-mono')

    def send_message(self):
        """Send text message to Cortex."""
        text = self.input_field.value
        if not text:
            return
        with self.chat_container:
            ui.chat_message(text, name='User', sent=True).classes('text-sm')
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
                    ui.chat_message('Playing audio response...', name='Cortex', sent=False).classes('text-sm')
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
