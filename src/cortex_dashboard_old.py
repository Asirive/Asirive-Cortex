"""
Project-Cortex v2.0 - Modern Neural Dashboard (NiceGUI Refactor)

A high-performance, web-based dashboard for visualizing the 4-Layer AI Brain.
Features:
- Responsive Tailwind CSS styling with Glassmorphism
- Neural Layer Cards with real-time status glow
- Integrated Chat Stream for conversational AI
- Low-latency Video Feed via Global Hardware Manager
- Real-time System Boot Log

Author: Haziq (@IRSPlays)
Date: December 30, 2025
"""

import os
import cv2
import time
import base64
import asyncio
import logging
import threading
from datetime import datetime
from typing import List, Dict, Optional
from collections import deque
from nicegui import ui, app

# Import Core Handlers (Reusing existing logic)
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

class AudioBridge:
    """JavaScript ↔ Python audio communication bridge."""
    
    def __init__(self):
        # Inject JavaScript
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
        return await ui.run_javascript(f'return window.audioRecorder.start("{device_id or ""}");')
        
    async def stop_recording(self):
        """Signal JavaScript to stop and return audio."""
        audio_b64 = await ui.run_javascript('return window.audioRecorder.stop();')
        if audio_b64:
            return base64.b64decode(audio_b64)
        return None
        
    async def list_devices(self):
        """Get audio device list from browser."""
        return await ui.run_javascript('return window.audioRecorder.getDevices();')

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
        self.dual_yolo = None
        self.aggregator = DetectionAggregator()
        self.whisper_stt = None
        self.kokoro_tts = None
        self.gemini_tts = None
        self.gemini_live = None
        self.streaming_player = None
        self.intent_router = IntentRouter()
        self.detection_router = DetectionRouter()
        self.cap = None
        self.is_running = False
        self.state = {
            'last_frame': '',
            'latency': 0,
            'detections': 'Scanning...',
            'frame_id': 0,
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
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {msg}"
        self.state['logs'].append(full_msg)
        logger.info(msg)

    async def initialize(self):
        """Initialize models and hardware in background."""
        if self.is_running: return
        self.is_running = True
        
        self.add_log("🚀 [SYSTEM] Initializing Neural Core...")
        
        # Layer 1: Reflex (YOLO + Whisper)
        try:
            self.add_log("📦 [REFLEX] Loading YOLOv11x + YOLOE-11m...")
            # Run blocking init in thread to keep web server responsive
            await asyncio.to_thread(self._load_models)
            self.state['layers']['reflex'] = {'active': True, 'msg': 'Safety Scanning Active'}
            self.add_log(f"✅ [REFLEX] Layers loaded on {YOLO_DEVICE}")
            
            # Load Whisper
            self.add_log("🎤 [REFLEX] Loading Whisper STT...")
            await asyncio.to_thread(self._load_whisper)
            self.add_log("✅ [REFLEX] Whisper STT Ready")
            
        except Exception as e:
            self.add_log(f"❌ [REFLEX] Load failed: {e}")

        # Camera
        try:
            self.add_log("📹 [VIDEO] Connecting to Camera 0...")
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened(): raise Exception("Camera not found")
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.add_log("✅ [VIDEO] Camera connected")
        except Exception as e:
            self.add_log(f"❌ [VIDEO] Connection failed: {e}")

        # Initialize Other Layers
        try:
            self.add_log("🔊 [GUIDE] Loading Kokoro TTS...")
            await asyncio.to_thread(self._load_kokoro)
            self.state['layers']['guide'] = {'active': True, 'msg': 'Kokoro TTS Ready'}
            self.add_log("✅ [GUIDE] Kokoro TTS initialized")
        except Exception as e:
            self.add_log(f"❌ [GUIDE] Kokoro failed: {e}")

        try:
            self.add_log("☁️ [THINKER] Initializing Gemini...")
            await asyncio.to_thread(self._init_gemini)
            self.state['layers']['thinker'] = {'active': True, 'msg': 'Gemini Ready'}
            self.add_log("✅ [THINKER] Gemini API connected")
        except Exception as e:
            self.add_log(f"❌ [THINKER] Gemini failed: {e}")

        self.state['layers']['memory'] = {'active': True, 'msg': 'SQLite Connected'}
        
        # Start Inference thread
        threading.Thread(target=self._inference_loop, daemon=True).start()

    def _load_models(self):
        self.dual_yolo = DualYOLOHandler(
            guardian_model_path=YOLO_MODEL_PATH,
            learner_model_path="models/yoloe-11m-seg.pt",
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
            # self.gemini_live.start() # Start on demand

    def _on_live_audio(self, audio_bytes):
        if self.streaming_player:
            self.streaming_player.add_audio_chunk(audio_bytes)

    def __init__(self):
        if self._initialized: return
        self.dual_yolo = None
        self.aggregator = DetectionAggregator()
        self.whisper_stt = None
        self.kokoro_tts = None
        self.gemini_tts = None
        self.gemini_live = None
        self.streaming_player = None
        self.intent_router = IntentRouter()
        self.detection_router = DetectionRouter()
        self.memory_manager = get_memory_manager()
        self.cap = None
        self.is_running = False
        self.state = {
            'last_frame': '',
            'latency': 0,
            'detections': 'Scanning...',
            'frame_id': 0,
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

    async def process_query(self, text: str):
        """Route and execute query."""
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

    async def _execute_memory_store(self, text: str):
        """Store current frame in memory."""
        # Extract object name (simplified)
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

    async def _execute_memory_recall(self, text: str):
        """Recall object from memory."""
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
            # TODO: Show memory image in UI
        else:
            await self.speak(f"I don't have any memory of your {obj_name}.")

    async def _execute_layer1(self, text: str):
        """Reflex: Fast object detection response."""
        detections = self.state['detections']
        response = f"I see {detections}."
        await self.speak(response)

    async def _execute_layer2(self, text: str):
        """Thinker: Gemini Vision analysis."""
        if not self.gemini_tts:
            await self.speak("Gemini is not available.")
            return

        frame_b64 = self.state['last_frame'].split(',')[1] # Remove header
        
        try:
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
        """Guide: Navigation and Memory."""
        if 'where am i' in text.lower():
            await self.speak("GPS location not yet implemented.")
        else:
            await self.speak("Navigation system ready.")

    async def speak(self, text: str):
        """Generate and play TTS."""
        if not self.kokoro_tts:
            self.add_log(f"💬 [No TTS]: {text}")
            return

        self.add_log(f"🔊 Speaking: {text}")
        audio_data = await asyncio.to_thread(
            self.kokoro_tts.generate_speech, text
        )
        
        if audio_data is not None:
            # Save to temp file for browser playback
            import scipy.io.wavfile as wavfile
            ts = int(time.time())
            path = f"temp_audio/tts_{ts}.wav"
            wavfile.write(path, 24000, audio_data)
            # Signal UI to play (via state or event)
            self.state['last_tts'] = f"/{path}" # UI will pick this up

    async def set_vision_mode(self, mode: str):
        """Switch YOLOE vision mode."""
        if not self.dual_yolo: return
        
        self.add_log(f"🔄 Switching to {mode} mode...")
        mode_map = {
            'Prompt-Free': YOLOEMode.PROMPT_FREE,
            'Text Prompts': YOLOEMode.TEXT_PROMPTS,
            'Visual Prompts': YOLOEMode.VISUAL_PROMPTS
        }
        
        if mode in mode_map:
            await asyncio.to_thread(
                self.dual_yolo.learner.switch_mode,
                mode_map[mode]
            )
            self.add_log(f"✅ Vision Mode: {mode}")

    def _inference_loop(self):
        """High-frequency background loop for AI inference with frame rate limiting."""
        # Frame rate limiting
        TARGET_ENCODE_FPS = 12  # Only encode 12 FPS for web display
        frame_interval = 1.0 / TARGET_ENCODE_FPS
        last_encode_time = 0
        frame_count = 0
        
        while self.is_running:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    start_time = time.time()
                    frame_count += 1
                    
                    # Parallel Inference (ALWAYS run for real-time detection)
                    g_results, l_results = self.dual_yolo.process_frame(frame)
                    
                    # Aggregation
                    g_list = [f"{g_results.names[int(b.cls)]}" for b in g_results.boxes] if g_results else []
                    l_list = [f"{l_results.names[int(b.cls)]}" for b in l_results.boxes] if l_results else []
                    merged = self.aggregator.merge_detections(g_list, l_list)
                    
                    # Update detections (always)
                    with self.lock:
                        self.state['latency'] = (time.time() - start_time) * 1000
                        self.state['detections'] = merged if merged else 'Scanning...'
                    
                    # Conditional Encoding (Skip frames to save CPU/Bandwidth)
                    current_time = time.time()
                    if current_time - last_encode_time >= frame_interval:
                        # Annotation (Safety bounding boxes)
                        annotated = frame.copy()
                        if g_results:
                            for box in g_results.boxes:
                                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
                        
                        # Encode to Base64 (Low quality for speed)
                        _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 65])
                        b64 = base64.b64encode(buffer).decode('utf-8')
                        
                        # Update Global State
                        with self.lock:
                            self.state['last_frame'] = f'data:image/jpeg;base64,{b64}'
                            self.state['frame_id'] = frame_count
                        
                        last_encode_time = current_time
            
            time.sleep(0.01)

    def cleanup(self):
        self.is_running = False
        if self.cap:
            self.cap.release()

# Global Hardware Manager Instance
manager = CortexHardwareManager()

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
        self.status_dot.style(f'color: {"#10b981" if active else "#ef4444"}')
        self.content.set_text(text)
        if active:
            self.classes('shadow-[0_0_20px_rgba(16,185,129,0.1)]')
        else:
            self.classes('shadow-none')

class CortexDashboard:
    def __init__(self):
        self.cards: Dict[str, NeuralCard] = {}
        self.image_view = None
        self.latency_label = None
        self.detection_badge = None
        self.log_terminal = None
        self.chat_container = None
        self.input_field = None
        self.audio_bridge = AudioBridge()
        self.is_recording = False
        self.record_btn = None

    async def process_voice_input(self):
        """Process recorded audio through Whisper."""
        if not self.is_recording:
            # Start Recording
            success = await self.audio_bridge.start_recording()
            if success:
                self.is_recording = True
                self.record_btn.props('color=red icon=stop')
                ui.notify('Listening...', type='info')
        else:
            # Stop Recording & Process
            self.is_recording = False
            self.record_btn.props('color=blue-6 icon=mic')
            ui.notify('Processing audio...', type='info')
            
            audio_bytes = await self.audio_bridge.stop_recording()
            if not audio_bytes:
                ui.notify('No audio recorded', type='warning')
                return

            # Save to temp file
            timestamp = int(time.time())
            wav_path = os.path.join(AUDIO_TEMP_DIR, f"rec_{timestamp}.wav")
            with open(wav_path, 'wb') as f:
                f.write(audio_bytes)
            
            # Transcribe
            if manager.whisper_stt:
                text = await asyncio.to_thread(
                    manager.whisper_stt.transcribe_file, wav_path
                )
                
                if text.strip():
                    # Update Chat
                    with self.chat_container:
                        ui.chat_message(text, name='User', sent=True).classes('text-sm')
                    
                    # Process Query
                    await manager.process_query(text)
                else:
                    ui.notify('Could not understand audio', type='warning')
            else:
                ui.notify('Whisper not initialized', type='negative')

    def build_ui(self):
        """Build the dashboard layout with modern gradients."""
        ui.query('body').classes('bg-gradient-to-br from-slate-950 via-slate-900 to-black min-h-screen text-slate-200 font-sans')
        
        # Header
        with ui.header().classes('bg-slate-900/80 backdrop-blur-lg border-b border-white/10 py-4 px-8 items-center justify-between'):
            with ui.row().classes('items-center gap-4'):
                ui.label('🧠 Project-Cortex').classes('text-2xl font-black tracking-tighter text-blue-500')
                ui.badge('v2.0 Neural Dashboard').props('color=blue-10 outline')
            
            with ui.row().classes('items-center gap-6'):
                self.latency_label = ui.label('Latency: -- ms').classes('text-xs font-mono text-slate-500')
                ui.button(icon='refresh', on_click=lambda: ui.notify('Re-syncing core...')).props('flat round color=slate-400')

        # Main Layout (3 columns)
        with ui.row().classes('w-full p-6 no-wrap gap-6 items-stretch'):
            
            # Left Column: Neural Layers
            with ui.column().classes('w-1/4 gap-4'):
                ui.label('NEURAL ARCHITECTURE').classes('text-[10px] font-black text-slate-500 tracking-[0.2em] mb-2')
                self.cards['reflex'] = NeuralCard('Layer 1: Reflex', '⚡', '#10b981')
                self.cards['thinker'] = NeuralCard('Layer 2: Thinker', '☁️', '#3b8ed0')
                self.cards['guide'] = NeuralCard('Layer 3: Guide', '🧭', '#f59e0b')
                self.cards['memory'] = NeuralCard('Layer 4: Memory', '💾', '#8b5cf6')
                
                with ui.card().classes('w-full bg-slate-900/40 backdrop-blur-md border border-white/10 mt-4 p-4'):
                    ui.label('SYSTEM CONTROLS').classes('text-[10px] font-black text-slate-500 tracking-widest mb-4')
                    ui.switch('Voice Activation').bind_value(app.storage.user, 'vad').classes('text-sm')
                    ui.switch('Spatial Audio').bind_value(app.storage.user, 'spatial').classes('text-sm')
                    ui.select(
                        ['Prompt-Free', 'Text Prompts', 'Visual Prompts'],
                        value='Text Prompts',
                        label='Vision Mode',
                        on_change=lambda e: asyncio.create_task(manager.set_vision_mode(e.value))
                    ).classes('w-full')
                    
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
                    # Placeholder memories
                    for i in range(6):
                        with ui.card().classes('p-0 bg-slate-800/50 border border-white/5 overflow-hidden transition-transform hover:scale-105'):
                            ui.image('https://picsum.photos/200?random=' + str(i)).classes('h-24')
                            ui.label(f'Recall {i}').classes('text-[10px] p-2 text-slate-400 font-mono')

    def send_message(self):
        text = self.input_field.value
        if not text: return
        with self.chat_container:
            ui.chat_message(text, name='User', sent=True).classes('text-sm')
            self.input_field.value = ''
        
        # Process text input
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
        """Polling function to sync per-client UI with global hardware state."""
        nonlocal last_tts_played
        state = manager.state
        
        # Update Video
        if state['last_frame']:
            dashboard.image_view.set_source(state['last_frame'])
        
        # Update Latency & Detections
        dashboard.latency_label.set_text(f"Latency: {state['latency']:.1f} ms")
        dashboard.detection_badge.set_text(state['detections'])
        
        # Update Layer Cards
        for key, card in dashboard.cards.items():
            layer_info = state['layers'].get(key, {'active': False, 'msg': 'Offline'})
            card.update_status(layer_info['active'], layer_info['msg'])
            
        # Update Neural Console (Simple refresh)
        dashboard.log_terminal.clear()
        for log in state['logs']:
            dashboard.log_terminal.push(log)
            
        # Check for new TTS
        if 'last_tts' in state and state['last_tts'] != last_tts_played:
            last_tts_played = state['last_tts']
            audio_player.set_source(last_tts_played)
            # Add AI response to chat
            with dashboard.chat_container:
                ui.chat_message('Playing audio response...', name='Cortex', sent=False).classes('text-sm')

    # UI Refresh Timer (15 FPS - Optimized)
    ui.timer(0.066, update_tick)
    
    # Serve temp audio files
    app.add_static_files('/temp_audio', 'temp_audio')

# Register shutdown handler
app.on_shutdown(manager.cleanup)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='Cortex Neural Dashboard',
        dark=True,
        port=8080,
        host='0.0.0.0',
        storage_secret='project_cortex_secret_key_2026',
        favicon='🧠'
    )