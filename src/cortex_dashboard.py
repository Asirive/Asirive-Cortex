"""
Project-Cortex v2.4 - Biotech Interface Neural Dashboard
Redesigned with Organic/Biotech aesthetic based on user-provided HTML template.

Features:
- Organic "Biotech" design language (Teal/Amber/Rose/Indigo)
- Real-time System Vitals (CPU, Temp, RAM)
- Cortex Layer Status (Reflex, Cognition, Memory)
- Neural Stream (Live logs)
- Memory Recalls (Visual gallery)
- Protocol Override (Controls)

Author: Haziq (@IRSPlays)
Date: January 1, 2026
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
logger = logging.getLogger(__name__)

# Import Core Handlers
from camera_handler import CameraHandler
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

# Constants
YOLO_MODEL_PATH = os.getenv('YOLO_MODEL_PATH', 'models/yolo11n_ncnn_model')
YOLO_DEVICE = os.getenv('YOLO_DEVICE', 'cpu')
GOOGLE_API_KEY = os.getenv('GEMINI_API_KEY')
AUDIO_TEMP_DIR = "temp_audio"
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)

# Custom CSS for Biotech Theme
BIOTECH_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@300;400;500;600;700&family=Space+Mono:ital,wght@0,400;0,700;1,400&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap');

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
    background-color: var(--bio-base);
    color: var(--bio-text);
    font-family: 'Quicksand', sans-serif;
    background-image: radial-gradient(circle at top right, #0f766e 0%, #042f2e 25%, #011618 100%);
    overflow: hidden;
}

.font-mono { font-family: 'Space Mono', monospace; }

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #115e59; border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: #2dd4bf; }

.glass-panel {
    background: rgba(8, 40, 42, 0.65);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(45, 212, 191, 0.1);
    border-radius: 1.5rem;
}

.scanline {
    width: 100%;
    height: 100px;
    z-index: 10;
    background: linear-gradient(0deg, rgba(0,0,0,0) 0%, rgba(45, 212, 191, 0.1) 50%, rgba(0,0,0,0) 100%);
    opacity: 0.1;
    background-size: 100% 100%;
    animation: scanline 8s linear infinite;
    position: absolute;
    pointer-events: none;
}

@keyframes scanline {
    0% { top: -100px; }
    100% { top: 100%; }
}

.breathing-glow { animation: breathe 4s ease-in-out infinite; }
@keyframes breathe {
    0%, 100% { box-shadow: 0 0 5px rgba(45, 212, 191, 0.2); }
    50% { box-shadow: 0 0 20px rgba(45, 212, 191, 0.5); }
}

.rounded-bubble { border-radius: 2rem; }
.shadow-glow { box-shadow: 0 0 15px rgba(45, 212, 191, 0.15); }
.text-shadow-sm { text-shadow: 0 1px 2px rgba(0,0,0,0.5); }
"""

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
        if self._initialized: return
        
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
        
        # Shared State
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
            'network_sent': 0,
            'network_recv': 0,
            'camera_status': 'Initializing...',
            'frame_count': 0,
            'vision_mode': 'Text Prompts',
            'spatial_audio_enabled': False,
            'layers': {
                'reflex': {'active': False, 'msg': 'Offline'},
                'thinker': {'active': False, 'msg': 'Offline'},
                'guide': {'active': False, 'msg': 'Offline'},
                'memory': {'active': False, 'msg': 'Offline'},
            },
            'logs': deque(maxlen=20),
            'last_tts': None
        }
        self.lock = threading.Lock()
        self._initialized = True

    def add_log(self, msg: str):
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {msg}"
        with self.lock:
            self.state['logs'].append(full_msg)
        logger.info(msg)

    async def initialize(self):
        if self.is_running: return
        self.is_running = True
        
        self.add_log("🚀 [SYSTEM] Initializing Neural Core...")
        
        # Layer 0+1: Reflex
        try:
            self.add_log(f"📦 [REFLEX] Loading YOLO11n-NCNN + YOLOE-11s...")
            await asyncio.to_thread(self._load_models)
            self.state['layers']['reflex'] = {'active': True, 'msg': 'Active'}
            self.add_log(f"✅ [REFLEX] Models loaded on {YOLO_DEVICE}")
            
            self.add_log("🎤 [REFLEX] Loading Whisper STT...")
            await asyncio.to_thread(self._load_whisper)
            self.add_log("✅ [REFLEX] Whisper STT Ready")
        except Exception as e:
            self.add_log(f"❌ [REFLEX] Load failed: {e}")
            logger.exception("Failed to load YOLO/Whisper")

        # Camera
        try:
            camera_index = int(os.getenv('CAMERA_INDEX', '0'))
            self.add_log(f"📹 [VIDEO] Connecting to Camera {camera_index}...")
            self.cap = CameraHandler(camera_index=camera_index, width=640, height=480, fps=30)
            
            if not self.cap.isOpened():
                raise Exception(f"Camera {camera_index} not found")
            
            backend = self.cap.getBackendName()
            self.state['camera_status'] = f'Active ({backend})'
            self.add_log(f"✅ [VIDEO] Camera connected ({backend})")
        except Exception as e:
            self.add_log(f"❌ [VIDEO] Connection failed: {e}")
            self.state['camera_status'] = 'Offline'

        # Layer 2: Thinker
        try:
            self.add_log("🔊 [THINKER] Loading Kokoro TTS...")
            await asyncio.to_thread(self._load_kokoro)
            self.state['layers']['thinker'] = {'active': True, 'msg': 'Ready'}
            self.add_log("✅ [THINKER] Kokoro TTS initialized")
        except Exception as e:
            self.add_log(f"❌ [THINKER] Kokoro failed: {e}")

        # Layer 3: Guide (Gemini)
        try:
            self.add_log("☁️ [GUIDE] Initializing Gemini...")
            await asyncio.to_thread(self._init_gemini)
            self.state['layers']['guide'] = {'active': True, 'msg': 'Connected'}
            self.add_log("✅ [GUIDE] Gemini API connected")
        except Exception as e:
            self.add_log(f"❌ [GUIDE] Gemini failed: {e}")

        # Layer 4: Memory
        self.state['layers']['memory'] = {'active': True, 'msg': 'Online'}
        
        # Start loops
        threading.Thread(target=self._inference_loop, daemon=True).start()
        threading.Thread(target=self._system_monitor_loop, daemon=True).start()
        self.add_log("🎯 [SYSTEM] Neural Core Online!")

    def _load_models(self):
        self.dual_yolo = DualYOLOHandler(
            guardian_model_path=YOLO_MODEL_PATH,
            learner_model_path="models/yoloe-11s-seg.pt",
            device=YOLO_DEVICE
        )

    def _load_whisper(self):
        self.whisper_stt = WhisperSTT(model_size='base', device=YOLO_DEVICE)
        self.whisper_stt.load_model()

    def _load_kokoro(self):
        self.kokoro_tts = KokoroTTS(lang_code="a", default_voice="af_alloy")
        self.kokoro_tts.load_pipeline()

    def _init_gemini(self):
        if GOOGLE_API_KEY:
            self.gemini_tts = GeminiTTS(api_key=GOOGLE_API_KEY)
            self.gemini_tts.initialize()
            self.streaming_player = StreamingAudioPlayer()
            self.gemini_live = GeminiLiveManager(
                api_key=GOOGLE_API_KEY,
                audio_callback=self._on_live_audio
            )

    def _on_live_audio(self, audio_bytes):
        if self.streaming_player:
            self.streaming_player.add_audio_chunk(audio_bytes)

    async def process_query(self, text: str):
        try:
            self.add_log(f"🧠 Processing: '{text}'")
            
            # Memory Commands
            text_lower = text.lower()
            if 'remember' in text_lower or 'save this' in text_lower:
                await self._execute_memory_store(text)
                return
            elif 'find my' in text_lower or 'where is my' in text_lower:
                await self._execute_memory_recall(text)
                return

            # Intent Routing
            layer = self.intent_router.route(text)
            self.add_log(f"🎯 Routed to: {layer}")
            
            if layer == 'layer1':
                await self._execute_layer1(text)
            elif layer == 'layer2':
                await self._execute_layer2(text)
            elif layer == 'layer3':
                await self._execute_layer3(text)
        except Exception as e:
            self.add_log(f"❌ Query error: {e}")
            await self.speak("Sorry, I encountered an error.")

    async def _execute_memory_store(self, text: str):
        try:
            obj_name = "object"
            if "remember" in text.lower():
                parts = text.lower().split("remember")
                if len(parts) > 1:
                    obj_name = parts[1].replace("this", "").replace("the", "").strip()
            
            if not self.state['last_frame']:
                await self.speak("No video frame to save.")
                return

            frame_b64 = self.state['last_frame'].split(',')[1]
            frame_bytes = base64.b64decode(frame_b64)
            
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

    async def _execute_memory_recall(self, text: str):
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

    async def _execute_layer1(self, text: str):
        detections = self.state['detections']
        response = f"I see {detections}."
        await self.speak(response)

    async def _execute_layer2(self, text: str):
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
            await self.speak("Sorry, I couldn't analyze the image.")

    async def _execute_layer3(self, text: str):
        if 'where am i' in text.lower():
            await self.speak("GPS location not yet implemented.")
        else:
            await self.speak("Navigation system ready.")

    async def speak(self, text: str):
        try:
            if not self.kokoro_tts: return
            self.add_log(f"🔊 Speaking: {text}")
            audio_data = await asyncio.to_thread(self.kokoro_tts.generate_speech, text)
            if audio_data is not None:
                import scipy.io.wavfile as wavfile
                ts = int(time.time())
                path = f"temp_audio/tts_{ts}.wav"
                wavfile.write(path, 24000, audio_data)
                with self.lock:
                    self.state['last_tts'] = f"/{path}"
        except Exception as e:
            self.add_log(f"❌ TTS error: {e}")

    async def set_vision_mode(self, mode: str):
        try:
            if not self.dual_yolo: return
            mode_map = {
                'Prompt-Free': YOLOEMode.PROMPT_FREE,
                'Text Prompts': YOLOEMode.TEXT_PROMPTS,
                'Visual Prompts': YOLOEMode.VISUAL_PROMPTS
            }
            if mode in mode_map:
                await asyncio.to_thread(setattr, self.dual_yolo.learner, 'mode', mode_map[mode])
                with self.lock:
                    self.state['vision_mode'] = mode
                self.add_log(f"✅ Vision Mode: {mode}")
        except Exception as e:
            self.add_log(f"❌ Mode switch error: {e}")

    async def toggle_spatial_audio(self, enabled: bool):
        with self.lock:
            self.state['spatial_audio_enabled'] = enabled
        self.add_log(f"🎧 Spatial Audio: {'ON' if enabled else 'OFF'}")

    def _inference_loop(self):
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
                        
                        # Inference
                        if self.dual_yolo:
                            g_results, l_results = self.dual_yolo.process_frame(frame)
                        else:
                            g_results, l_results = None, None
                        
                        # Aggregation
                        g_list = [f"{g_results.names[int(b.cls)]}" for b in g_results.boxes] if g_results else []
                        l_list = [f"{l_results.names[int(b.cls)]}" for b in l_results.boxes] if l_results else []
                        merged = self.aggregator.merge_detections(g_list, l_list)
                        
                        # Stats
                        latency = (time.time() - start_time) * 1000
                        fps_counter.append(1.0 / (time.time() - start_time) if time.time() - start_time > 0 else 0)
                        avg_fps = sum(fps_counter) / len(fps_counter) if fps_counter else 0
                        
                        with self.lock:
                            self.state['latency'] = latency
                            self.state['detections'] = merged if merged else 'Scanning...'
                            self.state['fps'] = avg_fps
                            self.state['frame_count'] = frame_count
                        
                        # Encode
                        current_time = time.time()
                        if current_time - last_encode_time >= frame_interval:
                            annotated = frame.copy()
                            if g_results:
                                for box in g_results.boxes:
                                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            
                            _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 60])
                            b64 = base64.b64encode(buffer).decode('utf-8')
                            
                            with self.lock:
                                self.state['last_frame'] = f'data:image/jpeg;base64,{b64}'
                            
                            last_encode_time = current_time
                time.sleep(0.01)
            except Exception as e:
                logger.error(f"Inference error: {e}")
                time.sleep(0.1)

    def _system_monitor_loop(self):
        """Background loop for system stats."""
        while self.is_running:
            try:
                cpu = psutil.cpu_percent()
                mem = psutil.virtual_memory().used / 1024 / 1024 # MB
                disk = psutil.disk_usage('/').percent
                net = psutil.net_io_counters()
                
                # Get temp (RPi specific)
                temp = 0
                try:
                    with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                        temp = int(f.read()) / 1000.0
                except:
                    pass

                with self.lock:
                    self.state['cpu_usage'] = cpu
                    self.state['ram_usage'] = mem
                    self.state['disk_usage'] = disk
                    self.state['cpu_temp'] = temp
                    # Simple net calculation could be added here
                
                time.sleep(1)
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                time.sleep(5)

    def cleanup(self):
        self.is_running = False
        if self.cap: self.cap.release()

# Global Manager
manager = CortexHardwareManager()

class AudioBridge:
    """JavaScript ↔ Python audio communication bridge (per-client)."""
    def __init__(self):
        ui.add_body_html('''
        <script>
        window.audioRecorder = {
            mediaRecorder: null,
            audioChunks: [],
            stream: null,
            start: async function() {
                try {
                    this.stream = await navigator.mediaDevices.getUserMedia({audio: true});
                    this.mediaRecorder = new MediaRecorder(this.stream);
                    this.audioChunks = [];
                    this.mediaRecorder.ondataavailable = e => this.audioChunks.push(e.data);
                    this.mediaRecorder.start();
                    return true;
                } catch (err) { console.error(err); return false; }
            },
            stop: function() {
                return new Promise(resolve => {
                    if (!this.mediaRecorder) return resolve(null);
                    this.mediaRecorder.onstop = () => {
                        const blob = new Blob(this.audioChunks, {type: 'audio/wav'});
                        const reader = new FileReader();
                        reader.readAsDataURL(blob);
                        reader.onloadend = () => {
                            resolve(reader.result.split(',')[1]);
                            this.stream.getTracks().forEach(t => t.stop());
                        };
                    };
                    this.mediaRecorder.stop();
                });
            }
        };
        </script>
        ''')
        
    async def start_recording(self):
        return await ui.run_javascript('return window.audioRecorder.start();')
        
    async def stop_recording(self):
        b64 = await ui.run_javascript('return window.audioRecorder.stop();')
        return base64.b64decode(b64) if b64 else None

class CortexDashboard:
    def __init__(self):
        self.audio_bridge = AudioBridge()
        self.is_recording = False
        self.chat_container = None
        
        # UI References
        self.video_image = None
        self.latency_label = None
        self.fps_label = None
        self.mem_label = None
        self.cpu_bar = None
        self.cpu_val = None
        self.temp_bar = None
        self.temp_val = None
        self.mem_bar = None
        self.mem_val = None
        self.layer_status = {}
        self.log_container = None
        self.mic_btn = None

    async def toggle_recording(self):
        if not self.is_recording:
            if await self.audio_bridge.start_recording():
                self.is_recording = True
                self.mic_btn.classes('bg-accent-rose animate-pulse')
                ui.notify('Listening...', type='info')
        else:
            self.is_recording = False
            self.mic_btn.classes(remove='bg-accent-rose animate-pulse').classes('bg-bio-highlight/20')
            ui.notify('Processing...', type='info')
            audio = await self.audio_bridge.stop_recording()
            if audio:
                # Save and process
                ts = int(time.time())
                path = os.path.join(AUDIO_TEMP_DIR, f"rec_{ts}.wav")
                with open(path, 'wb') as f: f.write(audio)
                
                if manager.whisper_stt:
                    text = await asyncio.to_thread(manager.whisper_stt.transcribe_file, path)
                    if text:
                        self.add_chat_message(text, 'User')
                        await manager.process_query(text)

    def add_chat_message(self, text, sender):
        with self.chat_container:
            ui.chat_message(text, name=sender, sent=(sender=='User')).classes('text-xs font-mono')

    def build_ui(self):
        ui.add_head_html('<style>' + BIOTECH_CSS + '</style>')
        
        # FIX: Replaced top-level ui.column() with ui.element('div') to avoid layout nesting errors
        # NiceGUI wraps page content in a layout, adding header inside column caused the error
        with ui.element('div').classes('w-full h-screen p-0 m-0 overflow-hidden bg-bio-base text-bio-text flex flex-col'):
            
            # --- HEADER ---
            # NOTE: ui.header() creates a fixed header. It shouldn't be inside a flex column if we want standard flow,
            # but NiceGUI's page layout handles it. The error was likely due to nesting header inside a column that was inside page.
            # Here we simulate a header with a div to be safe and flexible within our custom flex container.
            with ui.row().classes('h-20 px-8 flex items-center justify-between z-20 shrink-0 bg-transparent w-full'):
                with ui.row().classes('items-center gap-4'):
                    with ui.element('div').classes('w-12 h-12 rounded-full bg-gradient-to-tr from-accent-teal to-blue-600 flex items-center justify-center shadow-glow breathing-glow'):
                        ui.icon('psychology_alt', color='white').classes('text-3xl')
                    with ui.column().classes('gap-0'):
                        ui.label('Project Cortex').classes('text-2xl font-bold tracking-tight text-white drop-shadow-sm')
                        with ui.row().classes('items-center gap-2'):
                            ui.label('Biotech Interface v2.4').classes('text-xs font-mono text-accent-teal uppercase tracking-widest opacity-80')
                            ui.element('span').classes('w-1.5 h-1.5 rounded-full bg-accent-amber animate-pulse')

                with ui.element('div').classes('glass-panel px-6 py-2 rounded-full flex items-center gap-6 text-xs font-mono text-bio-muted shadow-lg'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('network_check', size='xs')
                        self.latency_label = ui.label('LAT: --ms').classes('text-white')
                    ui.element('div').classes('w-px h-4 bg-bio-border')
                    self.fps_label = ui.label('FPS: --').classes('text-white')
                    ui.element('div').classes('w-px h-4 bg-bio-border')
                    self.mem_label = ui.label('MEM: -- GB').classes('text-accent-amber')
                    ui.button(icon='refresh', on_click=lambda: ui.notify('Refreshing...')).props('flat round size=sm').classes('text-white hover:text-accent-teal ml-2')

            # --- MAIN GRID ---
            with ui.grid().classes('flex-1 grid-cols-12 gap-6 p-8 pt-2 overflow-hidden h-[calc(100vh-80px)] w-full'):
                
                # --- LEFT COLUMN (VITALS & LAYERS) ---
                with ui.column().classes('col-span-12 lg:col-span-3 flex flex-col gap-6 overflow-y-auto pr-2 pb-10 custom-scrollbar'):
                    
                    # System Vitals
                    with ui.element('section').classes('glass-panel rounded-[1.5rem] p-6 relative overflow-hidden group shadow-lg'):
                        ui.element('div').classes('absolute top-0 right-0 w-32 h-32 bg-accent-teal/5 rounded-full blur-2xl -mr-10 -mt-10 pointer-events-none')
                        with ui.row().classes('mb-6 items-center gap-2'):
                            ui.icon('vital_signs', color='accent-teal').classes('text-lg')
                            ui.label('System Vitals').classes('text-xs font-bold text-accent-teal uppercase tracking-widest')
                        
                        with ui.column().classes('space-y-6 font-mono text-xs w-full'):
                            # CPU
                            with ui.column().classes('w-full gap-1'):
                                with ui.row().classes('justify-between w-full text-bio-text/70'):
                                    ui.label('NEURAL_CPU')
                                    self.cpu_val = ui.label('0%')
                                self.cpu_bar = ui.linear_progress(value=0).props('color=teal-800').classes('h-3 rounded-full')
                            # Temp
                            with ui.column().classes('w-full gap-1'):
                                with ui.row().classes('justify-between w-full text-bio-text/70'):
                                    ui.label('CORE_TEMP')
                                    self.temp_val = ui.label('0°C').classes('text-accent-amber')
                                self.temp_bar = ui.linear_progress(value=0).props('color=yellow-800').classes('h-3 rounded-full')
                            # RAM
                            with ui.column().classes('w-full gap-1'):
                                with ui.row().classes('justify-between w-full text-bio-text/70'):
                                    ui.label('SYNAPTIC_MEM')
                                    self.mem_val = ui.label('0 GB').classes('text-accent-indigo')
                                self.mem_bar = ui.linear_progress(value=0).props('color=indigo-900').classes('h-3 rounded-full')

                    # Cortex Layers
                    with ui.column().classes('space-y-4 w-full'):
                        ui.label('Cortex Layers').classes('text-xs font-bold text-accent-teal uppercase tracking-widest pl-2')
                        
                        def layer_card(name, icon, color_cls, key):
                            with ui.element('div').classes(f'group relative bg-bio-panel hover:bg-bio-highlight/20 border border-bio-border/30 rounded-[2rem] p-4 transition-all duration-300 hover:scale-[1.02] cursor-pointer hover:shadow-glow hover:border-{color_cls}/30 w-full'):
                                with ui.row().classes('items-center justify-between w-full'):
                                    with ui.row().classes('items-center gap-4'):
                                        with ui.element('div').classes(f'w-10 h-10 rounded-full bg-bio-dark flex items-center justify-center border border-bio-border text-{color_cls}'):
                                            ui.icon(icon)
                                        with ui.column().classes('gap-0'):
                                            ui.label(name).classes('font-semibold text-white text-sm')
                                            self.layer_status[key] = ui.label('STATUS: OFFLINE').classes(f'text-[10px] text-{color_cls} font-mono mt-0.5')
                                    ui.element('span').classes(f'w-2 h-2 rounded-full bg-{color_cls} shadow-[0_0_8px_rgba(45,212,191,1)]')

                        layer_card('Reflex Layer', 'bolt', 'accent-teal', 'reflex')
                        layer_card('Cognition Layer', 'psychology', 'accent-indigo', 'thinker')
                        layer_card('Memory Core', 'memory', 'accent-rose', 'memory')

                    # Controls
                    with ui.element('section').classes('glass-panel rounded-[1.5rem] p-5 mt-auto w-full'):
                        with ui.row().classes('justify-between items-center mb-4 w-full'):
                            ui.label('Protocol Override').classes('text-xs font-bold text-accent-teal uppercase tracking-widest')
                            ui.icon('settings', color='accent-amber').classes('text-sm animate-spin-slow')
                        
                        with ui.column().classes('space-y-3 w-full'):
                            ui.switch('Autonomous Mode', value=True).props('color=teal').classes('text-sm text-bio-text w-full')
                            ui.switch('Voice Synthesis', on_change=lambda e: ui.notify(f'Voice: {e.value}')).props('color=teal').classes('text-sm text-bio-text w-full')
                            ui.select(['Text Prompts', 'Visual Prompts', 'Prompt-Free'], value='Text Prompts', 
                                     label='Vision Mode', on_change=lambda e: asyncio.create_task(manager.set_vision_mode(e.value))
                                     ).classes('w-full').props('dark filled')

                # --- CENTER COLUMN (VIDEO & STREAM) ---
                with ui.column().classes('col-span-12 lg:col-span-7 flex flex-col gap-6 h-full'):
                    
                    # Video Feed
                    with ui.element('div').classes('flex-grow bg-black rounded-[1.5rem] border border-bio-border relative overflow-hidden shadow-2xl flex items-center justify-center group ring-1 ring-white/5'):
                        ui.element('div').classes('scanline')
                        # Corner accents
                        ui.element('div').classes('absolute top-4 left-4 w-32 h-32 border-l border-t border-accent-teal/30 rounded-tl-3xl')
                        ui.element('div').classes('absolute bottom-4 right-4 w-32 h-32 border-r border-b border-accent-teal/30 rounded-br-3xl')
                        
                        # Image container
                        self.video_image = ui.interactive_image().classes('w-full h-full object-cover opacity-90')
                        
                        # Overlay status
                        with ui.row().classes('absolute bottom-6 left-8 gap-3'):
                            with ui.element('span').classes('flex items-center gap-2 px-3 py-1 rounded-full bg-accent-rose/10 border border-accent-rose/30 text-accent-rose text-[10px] font-bold shadow-glow'):
                                ui.element('span').classes('w-1.5 h-1.5 rounded-full bg-accent-rose animate-pulse')
                                ui.label('LIVE CORE')
                            with ui.element('span').classes('px-3 py-1 rounded-full bg-bio-dark/80 text-bio-text backdrop-blur-md border border-bio-border text-[10px] font-mono'):
                                self.detection_label = ui.label('SCAN_MODE: ACTIVE')

                    # Neural Stream (Chat)
                    with ui.element('div').classes('h-[35%] glass-panel rounded-[1.5rem] flex flex-col shadow-lg overflow-hidden border border-bio-border/50'):
                        with ui.row().classes('px-6 py-3 border-b border-bio-border/30 bg-bio-dark/30 justify-between items-center backdrop-blur-sm w-full'):
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('terminal', size='sm')
                                ui.label('Neural Stream').classes('text-xs font-bold text-accent-teal uppercase tracking-widest')
                            with ui.row().classes('gap-1.5'):
                                ui.element('span').classes('w-2.5 h-2.5 rounded-full bg-bio-border border border-bio-highlight')
                                ui.element('span').classes('w-2.5 h-2.5 rounded-full bg-bio-border border border-bio-highlight')

                        self.chat_container = ui.scroll_area().classes('flex-grow p-6 font-mono text-sm space-y-3 custom-scrollbar bg-transparent')
                        
                        # Input Area
                        with ui.row().classes('p-4 bg-bio-dark/40 items-center gap-3 border-t border-bio-border/30 backdrop-blur-md w-full'):
                            self.mic_btn = ui.button(icon='mic', on_click=self.toggle_recording).classes('w-10 h-10 rounded-full bg-bio-highlight/20 hover:bg-bio-highlight/40 text-accent-teal transition-colors flex items-center justify-center shadow-none border-none')
                            self.input_field = ui.input(placeholder='Enter command or query...').classes('flex-grow').props('rounded outlined bg-color=transparent text-color=white')
                            ui.button(icon='arrow_upward', on_click=lambda: asyncio.create_task(manager.process_query(self.input_field.value))).classes('w-10 h-10 rounded-full bg-accent-teal hover:bg-teal-300 text-bio-base shadow-glow transition-all transform hover:scale-105 flex items-center justify-center border-none')

                # --- RIGHT COLUMN (MEMORY) ---
                with ui.column().classes('col-span-12 lg:col-span-2 flex flex-col h-full overflow-hidden'):
                    with ui.row().classes('items-center justify-between mb-6 px-2 w-full'):
                        ui.label('Memory Recalls').classes('text-xs font-bold text-accent-teal uppercase tracking-widest')
                        ui.label('5 Active').classes('text-[10px] bg-accent-amber/10 text-accent-amber px-2 py-0.5 rounded-full border border-accent-amber/20')
                    
                    with ui.scroll_area().classes('flex-grow pr-2 space-y-5 custom-scrollbar pb-10 w-full'):
                        # Placeholder memory cards
                        for i in range(4):
                            with ui.element('div').classes('group relative rounded-[2rem] overflow-hidden h-40 border border-bio-border/50 bg-bio-panel transition-all duration-300 hover:scale-[1.03] hover:-translate-y-1 hover:shadow-glow cursor-pointer w-full'):
                                ui.image(f'https://picsum.photos/300/200?random={i}').classes('w-full h-full object-cover opacity-70 group-hover:opacity-100 transition-opacity duration-500 scale-110 group-hover:scale-100')
                                ui.element('div').classes('absolute inset-0 bg-gradient-to-t from-bio-base via-transparent to-transparent opacity-90')
                                with ui.column().classes('absolute bottom-0 w-full p-4'):
                                    ui.label(f'RECALL_NODE_0{i}').classes('text-[10px] font-mono text-accent-amber block mb-1')
                                    ui.label(f'Memory Trace {i}').classes('text-sm font-semibold text-white leading-tight')

@ui.page('/')
async def main_page():
    dashboard = CortexDashboard()
    dashboard.build_ui()
    
    # Audio player
    audio_player = ui.audio(src='').props('autoplay').classes('hidden')
    
    # Start Manager
    if not manager.is_running:
        asyncio.create_task(manager.initialize())

    last_tts_played = None

    async def update_loop():
        nonlocal last_tts_played
        try:
            state = manager.state
            
            # Video
            if state['last_frame']:
                dashboard.video_image.set_source(state['last_frame'])
            
            # Top Bar
            dashboard.latency_label.set_text(f"LAT: {state['latency']:.0f}ms")
            dashboard.fps_label.set_text(f"FPS: {state['fps']:.1f}")
            dashboard.mem_label.set_text(f"MEM: {state['ram_usage']:.1f} MB")
            
            # Vitals
            dashboard.cpu_val.set_text(f"{state['cpu_usage']}%")
            dashboard.cpu_bar.set_value(state['cpu_usage']/100)
            dashboard.temp_val.set_text(f"{state['cpu_temp']:.1f}°C")
            dashboard.temp_bar.set_value(min(state['cpu_temp']/85, 1.0))
            dashboard.mem_val.set_text(f"{state['ram_usage']:.0f} MB")
            dashboard.mem_bar.set_value(state['ram_usage']/4000)
            
            # Layers
            for key, lbl in dashboard.layer_status.items():
                info = state['layers'].get(key, {'msg': 'OFFLINE'})
                lbl.set_text(f"STATUS: {info['msg'].upper()}")
            
            # Detection Label
            dashboard.detection_label.set_text(f"SCAN: {str(state['detections'])[:20]}...")
            
            # TTS
            if state['last_tts'] and state['last_tts'] != last_tts_played:
                last_tts_played = state['last_tts']
                audio_player.set_source(last_tts_played)
                dashboard.add_chat_message("Audio response playing...", "Cortex")

        except Exception as e:
            logger.error(f"Update loop error: {e}")

    ui.timer(0.05, update_loop)
    app.add_static_files('/temp_audio', 'temp_audio')

# Cleanup
app.on_shutdown(manager.cleanup)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='Project Cortex v2.4',
        port=8080,
        dark=True,
        favicon='🧠'
    )
