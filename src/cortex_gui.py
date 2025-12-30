"""
Project-Cortex v2.0 - Main GUI Application (Laptop Development Version)

This is the laptop-first development version that uses:
- USB Webcam (instead of IMX415)
- Tkinter GUI for testing
- Same 3-Layer AI architecture as production
- Easy deployment to RPi 5 via VS Code Remote SSH

HYBRID 3-LAYER AI ARCHITECTURE:
================================
Layer 1 (Reflex) - Local YOLO Object Detection:
  - Runs on CPU (Raspberry Pi compatible)
  - Uses YOLOv11x for maximum accuracy
  - Real-time object detection (<100ms latency target)
  - Provides safety-critical alerts (obstacles, hazards)
  - Always active, works offline

Layer 2 (Thinker) - Cloud Multimodal AI (Google Gemini):
  - Analyzes complex scenes using visual + Layer 1 context
  - Handles OCR, text reading, detailed scene descriptions
  - Requires internet connection (via mobile hotspot)
  - Triggered by user queries
  - Uses Layer 1 detections to enhance accuracy

Layer 3 (Guide) - Audio Interface & Navigation:
  - Text-to-Speech (Piper TTS local, Murf AI for rich descriptions)
  - Speech-to-Text (Whisper Large v3 via Hugging Face)
  - 3D Spatial Audio (OpenAL - future implementation)
  - GPS Navigation (optional for YIA demo)

DEVICE CONFIGURATION:
=====================
- YOLO_DEVICE='cpu' is MANDATORY for Raspberry Pi deployment
- Model runs entirely on CPU (no CUDA/GPU required)
- Optimized for RPi 5's Quad-core ARM Cortex-A76 @ 2.4GHz
- Expected inference time: ~500-800ms on RPi 5 with yolo11x.pt

Author: Haziq (@IRSPlays)
Date: November 17, 2025
Competition: Young Innovators Awards (YIA) 2026
"""

import os
import cv2
import customtkinter as ctk
from tkinter import messagebox
import threading
import queue
import time
import traceback
import numpy as np
import torch
from PIL import Image, ImageTk
# Deprecated: google.generativeai (now using google-genai in GeminiTTS handler)
import sounddevice as sd
from scipy.io.wavfile import write as write_wav
from gradio_client import Client as GradioClient, file as gradio_file
from ultralytics import YOLO
from dotenv import load_dotenv
import logging
import sys
import warnings

# Import Dual YOLO Handler (Layer 0 Guardian + Layer 1 Learner)
from dual_yolo_handler import DualYOLOHandler
from layer1_learner import YOLOEMode
from layer1_learner import YOLOEMode  # NEW: Three detection modes

# Import Detection Aggregator (Layer 0 + Layer 1 composition)
from layer1_reflex.detection_aggregator import DetectionAggregator

# Import our custom AI handlers
from layer1_reflex.whisper_handler import WhisperSTT
from layer1_reflex.kokoro_handler import KokoroTTS
from layer1_reflex.vad_handler import VADHandler  # NEW: Voice Activity Detection
from layer2_thinker.gemini_tts_handler import GeminiTTS  # Gemini 2.5 Flash Vision (Tier 1 - now uses Kokoro TTS)
from layer2_thinker.gemini_live_handler import GeminiLiveManager  # Gemini Live API (Tier 0 - WebSocket)
from layer2_thinker.streaming_audio_player import StreamingAudioPlayer  # Real-time PCM audio playback
from layer2_thinker.glm4v_handler import GLM4VHandler  # GLM-4.6V Z.ai API (Tier 2 fallback)

# Import routing logic
from layer3_guide.detection_router import DetectionRouter  # Smart detection confidence routing
from layer3_guide.router import IntentRouter

# Import Spatial Audio Manager (3D Audio Navigation)
try:
    from layer3_guide.spatial_audio import SpatialAudioManager, print_navigation_notice
    from layer3_guide.spatial_audio.manager import Detection as SpatialDetection
    SPATIAL_AUDIO_AVAILABLE = True
except ImportError as e:
    SPATIAL_AUDIO_AVAILABLE = False
    SpatialDetection = None
    print(f"⚠️ Spatial Audio not available: {e}")

# Import Layer 4 Memory Manager
try:
    from layer4_memory import get_memory_manager, MEMORY_AVAILABLE
    MEMORY_AVAILABLE = True
except ImportError as e:
    MEMORY_AVAILABLE = False
    print(f"⚠️ Memory system not available: {e}")

# Suppress pygame deprecation warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='pygame')

# Configure UTF-8 output for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import pygame  # Import after console reconfiguration

# Load environment variables
load_dotenv()

# Configure logging with UTF-8 encoding to handle emojis on Windows
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cortex_gui.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)  # Use sys.stdout instead of default stderr
    ]
)
logger = logging.getLogger(__name__)

# --- Configuration from Environment ---
GOOGLE_API_KEY = os.getenv('GEMINI_API_KEY', os.getenv('GOOGLE_API_KEY', ''))
GEMINI_MODEL_ID = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash-latest')
MURF_API_KEY = os.getenv('MURF_API_KEY', '')
WHISPER_API_URL = os.getenv('WHISPER_MODEL', 'hf-audio/whisper-large-v3')
YOLO_MODEL_PATH = os.getenv('YOLO_MODEL_PATH', 'models/yolo11x.pt')  # Using yolo11x for best accuracy
YOLO_CONFIDENCE = float(os.getenv('YOLO_CONFIDENCE', '0.5'))
YOLO_DEVICE = os.getenv('YOLO_DEVICE', 'cuda')  # Use CUDA for GPU acceleration (auto-fallback to CPU if unavailable)

# Temporary files
AUDIO_FILE_FOR_WHISPER = os.path.abspath("temp_mic_input.wav")
TEMP_TTS_OUTPUT_FILE = os.path.abspath("temp_tts_output.wav")  # Fixed: Kokoro outputs WAV format

# Camera source: 0 for webcam, will be configurable for RPi IMX415
CAMERA_SOURCE = 0  # USB webcam
USE_PICAMERA = False  # Set to True when running on RPi 5

# Set CustomTkinter appearance
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ProjectCortexGUI:
    """
    Main GUI application for Project-Cortex v2.0
    
    Implements 3-Layer AI Architecture:
    - Layer 1 (Reflex): Local YOLO detection
    - Layer 2 (Thinker): Gemini scene analysis
    - Layer 3 (Guide): TTS/STT/Audio interface
    """
    
    def __init__(self, window, window_title="Project-Cortex v2.0 - Development GUI"):
        self.window = window
        self.window.title(window_title)
        self.window.geometry("1280x850")
        
        # --- Core State ---
        self.model = None  # Legacy YOLO (replaced by dual_yolo)
        self.dual_yolo = None  # Dual YOLO Handler (Layer 0 + Layer 1)
        self.classes = {}  # YOLO class names
        self.last_detections = "nothing detected"
        self.last_learner_detections = []  # Layer 1 adaptive detections
        self.latest_frame_for_gemini = None
        self.cap = None  # Video capture object
        self.picamera2 = None  # RPi camera (when available)
        
        # --- Threading ---
        self.stop_event = threading.Event()
        self.frame_queue = queue.Queue(maxsize=2)
        self.processed_frame_queue = queue.Queue(maxsize=2)
        self.status_queue = queue.Queue()
        self.detection_queue = queue.Queue()
        
        # --- UI State ---
        self.canvas_width = 640
        self.canvas_height = 480
        self.photo = None
        self.delay = 15  # ms between UI updates
        
        # --- Audio ---
        self.input_devices = {}
        self.output_devices = {}
        self.selected_input_device = ctk.StringVar(value="Loading...")
        self.selected_output_device = ctk.StringVar(value="Loading...")
        self.last_used_output_device = None
        self.recording_active = False
        self.audio_queue = queue.Queue()
        self.last_tts_file = None
        
        # --- AI Handler Instances ---
        self.whisper_stt = None  # Lazy load to avoid startup delay
        self.kokoro_tts = None   # Lazy load to avoid startup delay (kept for backward compatibility)
        self.gemini_tts = None   # Gemini 2.5 Flash Vision (Tier 1 - HTTP vision → Kokoro TTS)
        self.gemini_live = None  # Gemini Live API (Tier 0 - WebSocket audio-to-audio)
        self.glm4v = None  # GLM-4.6V Z.ai API (Tier 2 - final fallback)
        self.streaming_player = None  # Real-time PCM audio player (for Live API)
        self.vad_handler = None  # Voice Activity Detection handler
        self.spatial_audio = None  # 3D Spatial Audio Manager
        
        # Detection router for context-aware routing (Phase 1 + 2)
        self.detection_router = DetectionRouter()  # Smart detection confidence routing
        
        # Detection aggregator for merging Guardian + Learner (NEW)
        self.detection_aggregator = DetectionAggregator()  # Combines Layer 0 + Layer 1 detections
        
        # --- Cascading Fallback State (3-Tier System) ---
        self.active_api = "Live API"  # Current active API: "Live API", "Gemini TTS", "GLM-4.6V"
        self.live_api_enabled = ctk.BooleanVar(value=True)  # Try Live API first
        self.fallback_enabled = ctk.BooleanVar(value=True)  # Enable automatic fallback
        self.selected_tier = ctk.StringVar(value="Testing (FREE)")  # Default to FREE tier for daily testing
        self.video_streaming_enabled = ctk.BooleanVar(value=True)  # Send camera frames
        self.last_video_frame_time = 0  # Track last frame sent (for 2-5 FPS limit)
        self.video_frame_interval = 0.4  # Send frame every 400ms (2.5 FPS)
        
        # --- Voice Activation State ---
        self.voice_activation_enabled = ctk.BooleanVar(value=False)
        self.vad_interrupt_enabled = ctk.BooleanVar(value=False)  # NEW: Allow VAD to interrupt TTS (off by default)
        self.vad_listening = False
        self.vad_speech_buffer = None
        
        # --- 3D Spatial Audio State ---
        self.spatial_audio_enabled = ctk.BooleanVar(value=False)  # NEW: 3D Audio Navigation
        
        # --- YOLOE Mode State (Layer 1 Three-Mode System) ---
        self.yoloe_mode = ctk.StringVar(value="Text Prompts")  # "Prompt-Free", "Text Prompts", "Visual Prompts"
        self.visual_prompts_mode_active = False  # Track if visual prompts mode is enabled
        self.visual_prompt_boxes = []  # Store user-drawn bounding boxes
        
        # --- TTS Playback State (for interrupt detection) ---
        self.tts_playing = False  # Track if TTS audio is currently playing
        self.TTS_END_EVENT = pygame.USEREVENT + 1  # Custom event for TTS completion
        self.tts_interrupt_requested = False  # Thread-safe flag for VAD to request TTS interrupt
        
        # --- Build UI ---
        self.init_ui()
        
        # --- Initialize Systems ---
        self.init_audio()
        self.init_yolo()
        
        # --- Initialize AI Handlers on Startup (TODO #1) ---
        # Load all handlers immediately instead of lazy loading
        # This ensures module indicators turn green on startup
        self.init_whisper_stt()
        self.init_kokoro_tts()
        # DISABLED: Gemini API calls to avoid quota limits at startup
        logger.info("⚠️ Skipping Gemini TTS/Live API initialization (quota limits prevention)")
        # self.init_gemini_tts()  # Tier 1: Gemini 2.5 Flash TTS (HTTP)
        # self.init_gemini_live()  # Tier 0: Gemini Live API (WebSocket)
        self.init_streaming_player()  # For Live API audio playback
        # self.init_glm4v()  # Tier 2: GLM-4.6V Z.ai (final fallback)
        
        # --- Start Background Threads ---
        threading.Thread(target=self.video_capture_thread, daemon=True).start()
        threading.Thread(target=self.yolo_processing_thread, daemon=True).start()
        
        # --- Start UI Update Loops ---
        self.update_video()
        self.update_status()
        self.update_detections()
        
        # --- Graceful Shutdown ---
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        logger.info("🚀 Project-Cortex GUI initialized")
    
    def init_ui(self):
        """Sets up the main UI layout."""
        # Main container with dark theme
        self.window.grid_columnconfigure(0, weight=1)
        self.window.grid_rowconfigure(1, weight=1)
        
        # --- Top Frame: Status HUD ---
        top_frame = ctk.CTkFrame(self.window, corner_radius=10)
        top_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        
        self.status_label = ctk.CTkLabel(
            top_frame, 
            text="SYSTEM STATUS: INITIALIZING...", 
            text_color="#00ff00", 
            font=('Consolas', 14, 'bold')
        )
        self.status_label.pack(side="left", padx=20, pady=10)
        
        # Handler Status Indicators
        self.handler_status_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        self.handler_status_frame.pack(side="right", padx=20)
        
        self.create_status_indicator("YOLO", "#00ff00")
        self.create_status_indicator("WHISPER", "#555555")
        self.create_status_indicator("VAD", "#555555")  # NEW: Voice Activity Detection indicator
        self.create_status_indicator("LIVE-API", "#555555")  # NEW: Gemini Live API indicator
        self.create_status_indicator("GEMINI-TTS", "#555555")  # NEW: Gemini 2.5 TTS indicator (fallback)
        self.create_status_indicator("KOKORO", "#555555")  # Kept for backward compatibility
        self.create_status_indicator("3D-AUDIO", "#555555")  # NEW: 3D Spatial Audio indicator

        # --- Video Frame ---
        video_frame = ctk.CTkFrame(self.window, fg_color="black", corner_radius=0)
        video_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        
        self.canvas = ctk.CTkCanvas(video_frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        
        # --- Controls Frame ---
        controls_frame = ctk.CTkFrame(self.window, corner_radius=10)
        controls_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        
        # Query Section
        query_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        query_frame.pack(fill="x", pady=10, padx=10)
        
        ctk.CTkLabel(query_frame, text="💬 Ask Gemini:", font=('Arial', 12, 'bold')).pack(side="left", padx=5)
        self.input_entry = ctk.CTkEntry(query_frame, placeholder_text="Type your question here...", font=('Arial', 12))
        self.input_entry.pack(side="left", fill="x", expand=True, padx=10)
        self.input_entry.bind('<Return>', lambda e: self.send_query())
        
        self.send_query_btn = ctk.CTkButton(
            query_frame, 
            text="Send 🚀", 
            command=self.send_query,
            font=('Arial', 12, 'bold'),
            width=100
        )
        self.send_query_btn.pack(side="right", padx=5)
        
        # 🆕 Adaptive Learning: Learn from Maps POI
        self.learn_maps_btn = ctk.CTkButton(
            query_frame, 
            text="🗺️ POI", 
            command=self.learn_from_maps,
            font=('Arial', 12, 'bold'),
            width=80,
            fg_color="#2e7d32",
            hover_color="#1b5e20"
        )
        self.learn_maps_btn.pack(side="right", padx=5)
        
        # Response Section
        ctk.CTkLabel(controls_frame, text="🤖 Gemini's Response:", font=('Arial', 12, 'bold')).pack(anchor="w", padx=15)
        self.response_text = ctk.CTkTextbox(
            controls_frame, 
            height=100, 
            font=('Consolas', 12),
            text_color="#00ff00"
        )
        self.response_text.pack(fill="x", expand=True, padx=15, pady=5)
        
        # Audio Controls
        audio_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        audio_frame.pack(fill="x", pady=10, padx=10)
        
        # Voice Activation Toggle
        self.voice_activation_switch = ctk.CTkSwitch(
            audio_frame,
            text="🎙️ Voice Activation",
            variable=self.voice_activation_enabled,
            command=self.toggle_voice_activation,
            font=('Arial', 12, 'bold')
        )
        self.voice_activation_switch.pack(side="left", padx=5)
        
        # VAD Interrupt Toggle (allows interrupting TTS with voice)
        self.vad_interrupt_switch = ctk.CTkSwitch(
            audio_frame,
            text="🔇 Interrupt TTS",
            variable=self.vad_interrupt_enabled,
            command=self.toggle_vad_interrupt,
            font=('Arial', 11)
        )
        self.vad_interrupt_switch.pack(side="left", padx=5)
        
        # 3D Spatial Audio Toggle (enables 3D navigation sounds)
        self.spatial_audio_switch = ctk.CTkSwitch(
            audio_frame,
            text="🔊 3D Audio",
            variable=self.spatial_audio_enabled,
            command=self.toggle_spatial_audio,
            font=('Arial', 11)
        )
        self.spatial_audio_switch.pack(side="left", padx=5)
        
        # Layer 2 Tier Selection Dropdown
        ctk.CTkLabel(audio_frame, text="AI Tier:", font=('Arial', 11)).pack(side="left", padx=(10, 5))
        self.tier_selector = ctk.CTkOptionMenu(
            audio_frame,
            values=["Production (PAID)", "Testing (FREE)", "Experimental (MIXED)"],
            command=self.on_tier_selection_changed,
            variable=self.selected_tier,
            font=('Arial', 11),
            width=180
        )
        self.tier_selector.pack(side="left", padx=5)
        
        # --- YOLOE Mode Selection (Layer 1 Three-Mode System) ---
        mode_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        mode_frame.pack(fill="x", pady=5, padx=10)
        
        ctk.CTkLabel(mode_frame, text="🎯 Layer 1 Mode:", font=('Arial', 12, 'bold')).pack(side="left", padx=5)
        
        self.mode_dropdown = ctk.CTkOptionMenu(
            mode_frame,
            values=["Prompt-Free", "Text Prompts", "Visual Prompts"],
            command=self.on_yoloe_mode_changed,
            variable=self.yoloe_mode,
            font=('Arial', 11),
            width=140
        )
        self.mode_dropdown.pack(side="left", padx=10)
        
        # Mode selector (YOLOE detection mode)
        ctk.CTkLabel(mode_frame, text="Layer 1 Mode:", font=('Arial', 12, 'bold')).pack(side="left", padx=5)
        self.mode_selector = ctk.CTkOptionMenu(
            mode_frame,
            variable=self.yoloe_mode,
            values=[
                "Prompt-Free",    # 4585+ classes, zero setup
                "Text Prompts",   # Adaptive learning (default)
                "Visual Prompts"  # Personal objects
            ],
            command=self.on_yoloe_mode_changed,
            font=('Arial', 10),
            width=140
        )
        self.mode_selector.pack(side="left", padx=5)
        
        # Mode info label
        self.mode_info_label = ctk.CTkLabel(
            mode_frame,
            text="🧠 15-100 adaptive classes (learns from Gemini/Maps/Memory)",
            font=('Arial', 10),
            text_color="#888888"
        )
        self.mode_info_label.pack(side="left", padx=10)
        
        # Tier selector (for Layer 2 cascading fallback)
        tier_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        tier_frame.pack(fill="x", pady=5, padx=10)
        
        ctk.CTkLabel(tier_frame, text="🎚️ Layer 2 Tier:", font=('Arial', 12, 'bold')).pack(side="left", padx=5)
        self.tier_selector = ctk.CTkOptionMenu(
            tier_frame,
            variable=self.selected_tier,
            values=[
                "Testing (FREE)",           # Tier 1 only - for daily testing ($0)
                "Demo Mode (PAID)",         # Tier 0 - for competitions ($1/hour)
                "Auto (Cascading)",         # Smart fallback
                "Tier 0 (Live API)",        # Force Tier 0
                "Tier 1 (Gemini TTS)"       # Force Tier 1
            ],
            command=self.on_tier_selection_changed,
            font=('Arial', 10),
            width=170
        )
        self.tier_selector.pack(side="left", padx=5)
        
        self.record_btn = ctk.CTkButton(
            audio_frame, 
            text="🎤 Record Voice", 
            command=self.toggle_recording,
            fg_color="#dc3545",
            hover_color="#c82333",
            font=('Arial', 12, 'bold')
        )
        self.record_btn.pack(side="left", padx=5)
        
        self.play_tts_btn = ctk.CTkButton(
            audio_frame, 
            text="🔊 Replay TTS", 
            command=self.replay_last_tts,
            fg_color="#28a745",
            hover_color="#218838",
            font=('Arial', 12, 'bold')
        )
        self.play_tts_btn.pack(side="left", padx=5)
        
        # Audio Device Selection
        ctk.CTkLabel(audio_frame, text="Input:").pack(side="left", padx=5)
        self.input_device_menu = ctk.CTkOptionMenu(audio_frame, variable=self.selected_input_device, values=["Loading..."])
        self.input_device_menu.pack(side="left", padx=5)
        
        ctk.CTkLabel(audio_frame, text="Output:").pack(side="left", padx=5)
        self.output_device_menu = ctk.CTkOptionMenu(audio_frame, variable=self.selected_output_device, values=["Loading..."])
        self.output_device_menu.pack(side="left", padx=5)
        
        ctk.CTkButton(
            audio_frame, 
            text="🔄", 
            command=self.populate_audio_devices,
            width=30,
            fg_color="#6c757d"
        ).pack(side="left", padx=5)
        
        # Initialize Debug Console
        self.init_debug_console(controls_frame)
        
        # Initialize Intent Router
        self.router = IntentRouter()

    def create_status_indicator(self, name, color):
        frame = ctk.CTkFrame(self.handler_status_frame, fg_color="transparent")
        frame.pack(side="left", padx=10)
        
        indicator = ctk.CTkLabel(frame, text="●", text_color=color, font=('Arial', 20))
        indicator.pack(side="left")
        
        label = ctk.CTkLabel(frame, text=name, font=('Arial', 10, 'bold'))
        label.pack(side="left", padx=2)
        
        # Store reference to update later
        setattr(self, f"status_indicator_{name.lower()}", indicator)

    def update_handler_status(self, handler, status):
        """Updates the color of the status indicators."""
        color = "#00ff00" if status == "active" else "#555555"
        if status == "processing": color = "#ffff00"
        if status == "error": color = "#ff0000"
        
        indicator = getattr(self, f"status_indicator_{handler}", None)
        if indicator:
            indicator.configure(text_color=color)
    
    def _safe_gui_update(self, callback):
        """Thread-safe GUI update using .after() (TODO #3)."""
        try:
            self.window.after(0, callback)
        except Exception as e:
            logger.error(f"GUI update failed: {e}")

    def init_debug_console(self, parent_frame):
        """Initialize the debug console in the UI."""
        # Debug Console
        debug_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        debug_frame.pack(fill="both", expand=True, pady=5, padx=5)
        
        ctk.CTkLabel(debug_frame, text="🔧 Debug Console:", font=('Arial', 12, 'bold')).pack(anchor="w")
        self.debug_text = ctk.CTkTextbox(
            debug_frame, 
            height=100, 
            font=('Consolas', 10),
            text_color="#00ff00"
        )
        self.debug_text.pack(fill="both", expand=True)
        
        self.debug_print("✅ UI Initialized - Project-Cortex v2.0")
        self.debug_print(f"📂 YOLO Model: {YOLO_MODEL_PATH}")
        self.debug_print(f"🎮 Device: {YOLO_DEVICE}")
        self.debug_print(f"🤖 Gemini Model: {GEMINI_MODEL_ID}")

    def init_whisper_stt(self):
        """Lazy initialize Whisper STT (called on first voice command)."""
        if self.whisper_stt is None:
            try:
                self.update_handler_status("whisper", "processing")
                self.debug_print("⏳ Loading Whisper STT...")
                self.whisper_stt = WhisperSTT(model_size="base", device=None)  # Auto-detect GPU/CPU
                self.whisper_stt.load_model()
                self.debug_print("✅ Whisper STT ready")
                logger.info("✅ Whisper STT initialized")
                self.update_handler_status("whisper", "active")
            except Exception as e:
                logger.error(f"❌ Whisper STT init failed: {e}")
                self.debug_print(f"❌ Whisper failed: {e}")
                self.update_handler_status("whisper", "error")
                self.whisper_stt = None
        return self.whisper_stt is not None
    
    def init_kokoro_tts(self):
        """Lazy initialize Kokoro TTS (called on first TTS request).
        
        NOTE: Kokoro works without eSpeak-NG. eSpeak is only used as a 
        fallback for out-of-dictionary (OOD) words in English. If eSpeak 
        is unavailable, Kokoro will simply skip OOD words.
        """
        if self.kokoro_tts is None:
            try:
                self.update_handler_status("kokoro", "processing")
                self.debug_print("⏳ Loading Kokoro TTS...")
                logger.info("🔊 Initializing Kokoro TTS handler...")
                
                # Step 1: Create KokoroTTS object
                logger.info("   Step 1/3: Creating KokoroTTS instance...")
                self.kokoro_tts = KokoroTTS(lang_code="a", default_voice="af_alloy")
                logger.info("   ✅ KokoroTTS instance created")
                
                # Step 2: Load pipeline (downloads model from HuggingFace if needed)
                logger.info("   Step 2/3: Loading Kokoro pipeline...")
                logger.info("      This may take 30-60s on first run (downloading ~312MB model)")
                pipeline_loaded = self.kokoro_tts.load_pipeline()
                
                if not pipeline_loaded:
                    logger.error("   ❌ Pipeline loading failed - see logs above for details")
                    self.debug_print("❌ Kokoro pipeline failed to load")
                    self.update_handler_status("kokoro", "error")
                    self.kokoro_tts = None
                    return False
                
                logger.info("   ✅ Pipeline loaded successfully")
                
                # Step 3: Verify pipeline is ready
                logger.info("   Step 3/3: Verifying pipeline readiness...")
                if self.kokoro_tts.pipeline is None:
                    logger.error("   ❌ Pipeline is None after load_pipeline() returned True")
                    self.debug_print("❌ Kokoro pipeline verification failed")
                    self.update_handler_status("kokoro", "error")
                    self.kokoro_tts = None
                    return False
                
                logger.info("   ✅ Pipeline verified")
                
                self.debug_print("✅ Kokoro TTS ready")
                logger.info("✅ Kokoro TTS initialized successfully")
                self.update_handler_status("kokoro", "active")
            except Exception as e:
                logger.error(f"❌ Kokoro TTS init failed: {e}", exc_info=True)
                self.debug_print(f"❌ Kokoro failed: {e}")
                self.debug_print("   Gemini TTS will be used instead")
                self.update_handler_status("kokoro", "error")
                self.kokoro_tts = None
        else:
            logger.debug("♻️ Kokoro TTS already initialized, skipping")
        
        return self.kokoro_tts is not None
    
    def init_gemini_tts(self):
        """Lazy initialize Gemini 2.5 Flash TTS (NEW: image + prompt -> audio)."""
        if self.gemini_tts is None:
            try:
                self.update_handler_status("gemini-tts", "processing")
                self.debug_print("⏳ Loading Gemini 2.5 Flash TTS...")
                self.gemini_tts = GeminiTTS(api_key=GOOGLE_API_KEY, voice_name="Kore")
                self.gemini_tts.initialize()
                self.debug_print("✅ Gemini TTS ready")
                logger.info("✅ Gemini TTS initialized")
                self.update_handler_status("gemini-tts", "active")
            except Exception as e:
                logger.error(f"❌ Gemini TTS init failed: {e}")
                self.debug_print(f"❌ Gemini TTS failed: {e}")
                self.update_handler_status("gemini-tts", "error")
                self.gemini_tts = None
        return self.gemini_tts is not None
    
    def init_gemini_live(self):
        """Initialize Gemini Live API WebSocket handler (NEW)."""
        if self.gemini_live is None and GOOGLE_API_KEY:
            try:
                self.update_handler_status("live-api", "processing")
                self.debug_print("⏳ Initializing Gemini Live API...")
                
                # Create Live API manager with audio callback
                self.gemini_live = GeminiLiveManager(
                    api_key=GOOGLE_API_KEY,
                    audio_callback=self._on_live_api_audio
                )
                
                # Start background thread
                self.gemini_live.start()
                
                self.debug_print("✅ Gemini Live API ready")
                logger.info("✅ Gemini Live API initialized")
                self.update_handler_status("live-api", "active")
                
            except Exception as e:
                logger.error(f"❌ Gemini Live API init failed: {e}")
                self.debug_print(f"❌ Live API failed: {e}")
                self.debug_print("   Falling back to Gemini TTS (HTTP API)")
                self.update_handler_status("live-api", "error")
                self.gemini_live = None
        return self.gemini_live is not None
    
    def init_streaming_player(self):
        """Initialize streaming audio player for Live API (NEW)."""
        if self.streaming_player is None:
            try:
                self.debug_print("⏳ Initializing streaming audio player...")
                
                # Create streaming player (24kHz PCM from Gemini Live API)
                self.streaming_player = StreamingAudioPlayer(
                    sample_rate=24000,
                    channels=1,
                    dtype='int16'
                )
                
                # Set playback callbacks
                self.streaming_player.set_callbacks(
                    on_start=lambda: self._on_audio_playback_start(),
                    on_stop=lambda: self._on_audio_playback_stop(),
                    on_interrupt=lambda: self._on_audio_playback_interrupt()
                )
                
                self.debug_print("✅ Streaming audio player ready")
                logger.info("✅ Streaming audio player initialized")
                
            except Exception as e:
                logger.error(f"❌ Streaming player init failed: {e}")
                self.debug_print(f"❌ Streaming player failed: {e}")
                self.streaming_player = None
        return self.streaming_player is not None
    
    def _on_live_api_audio(self, audio_bytes: bytes):
        """Callback for streaming audio from Live API (NEW)."""
        if self.streaming_player and self.streaming_player.is_playing:
            self.streaming_player.add_audio_chunk(audio_bytes)
            logger.debug(f"📥 Received {len(audio_bytes)} bytes from Live API")
    
    def _on_audio_playback_start(self):
        """Callback when audio playback starts (NEW)."""
        self.tts_playing = True
        self.debug_print("🔊 Audio playback started")
    
    def _on_audio_playback_stop(self):
        """Callback when audio playback stops (NEW)."""
        self.tts_playing = False
        self.debug_print("🛑 Audio playback stopped")
        self.status_queue.put("Status: Ready")
    
    def _on_audio_playback_interrupt(self):
        """Callback when audio playback is interrupted by VAD (NEW)."""
        self.tts_playing = False
        self.debug_print("⚠️ Audio playback interrupted by voice")
    
    def init_glm4v(self):
        """Initialize GLM-4.6V Z.ai handler (Fallback Tier 2) - DISABLED (requires API credits)."""
        zai_key = os.getenv("ZAI_API_KEY")
        
        # NOTE: Z.ai Coding Plan quota is ONLY for IDE tools (Cursor, Claude Code, etc.)
        # Direct API calls require separate balance top-up at https://open.bigmodel.cn/pricing
        # Keeping this disabled to avoid error messages. Use Gemini APIs (Tier 0/1) instead.
        
        if False:  # Disabled - requires API credits
            zai_base_url = os.getenv("ZAI_BASE_URL")
            
            if self.glm4v is None and zai_key:
                try:
                    self.debug_print("⏳ Initializing GLM-4.7 (Z.ai)...")
                    
                    self.glm4v = GLM4VHandler(
                        api_key=zai_key,
                        model="glm-4.6v-flashx",
                        api_base=zai_base_url,
                        temperature=0.7,
                        max_retries=5
                    )
                    
                    self.debug_print("✅ GLM-4.7 ready (Tier 2)")
                    logger.info("✅ GLM-4.7 initialized")
                    
                except Exception as e:
                    logger.error(f"❌ GLM-4.7 init failed: {e}")
                    self.debug_print(f"❌ GLM-4.7 failed: {e}")
                    self.glm4v = None
        
        # Z.ai Tier 2 is disabled - using Gemini APIs only
        if self.glm4v is None:
            self.debug_print("ℹ️ ZAI_API_KEY not found - GLM-4.6V unavailable")
            logger.info("ℹ️ ZAI_API_KEY not set - skipping GLM-4.6V initialization")
    
    def on_canvas_resize(self, event):
        """Handles canvas resize for video scaling."""
        self.canvas_width = event.width
        self.canvas_height = event.height
    
    def init_yolo(self):
        """Loads YOLO model in background thread."""
        self.status_queue.put("Status: Loading YOLO model...")
        self.update_handler_status("yolo", "processing")
        
        # Read GUI state in main thread BEFORE spawning background thread
        initial_mode_str = self.yoloe_mode.get()
        
        threading.Thread(
            target=self._init_yolo_thread, 
            args=(initial_mode_str,),  # Pass mode as argument
            daemon=True
        ).start()
    
    def _init_yolo_thread(self, initial_mode_str: str):
        """Background Dual YOLO loading (Layer 0 Guardian + Layer 1 Learner).
        
        Args:
            initial_mode_str: YOLOE mode from GUI ("Prompt-Free", "Text Prompts", "Visual Prompts")
        """
        try:
            # Verify CUDA availability and set device accordingly
            import torch
            if YOLO_DEVICE == 'cuda':
                if torch.cuda.is_available():
                    device = 'cuda'
                    gpu_name = torch.cuda.get_device_name(0)
                    gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
                    logger.info(f"✅ CUDA available: {gpu_name} ({gpu_memory:.1f}GB)")
                    self.debug_print(f"🔥 GPU Detected: {gpu_name} ({gpu_memory:.1f}GB)")
                else:
                    device = 'cpu'
                    logger.warning("⚠️ CUDA requested but not available, falling back to CPU")
                    self.debug_print("⚠️ GPU not available, using CPU")
            else:
                device = YOLO_DEVICE  # Use configured device (cpu, mps, etc.)
            
            logger.info(f"🚀 Loading Dual YOLO Handler on {device}...")
            self.debug_print(f"🔄 Loading Layer 0 (Guardian) + Layer 1 (Learner) on {device}...")
            
            # Determine learner model based on initial mode (passed from main thread)
            if initial_mode_str == "Prompt-Free":
                learner_model = "models/yoloe-11m-seg-pf.pt"  # Prompt-free medium model (4585+ classes)
                learner_mode = YOLOEMode.PROMPT_FREE
                self.debug_print("🔍 Loading prompt-free medium model (4585+ classes)")
            else:
                learner_model = "models/yoloe-11m-seg.pt"  # Standard medium model (text/visual prompts)
                learner_mode = YOLOEMode.TEXT_PROMPTS  # Default to text prompts
                self.debug_print("🧠 Loading medium text prompts model (adaptive learning)")
            
            # Initialize Dual YOLO Handler (parallel inference)
            self.dual_yolo = DualYOLOHandler(
                guardian_model_path=YOLO_MODEL_PATH,  # yolo11x.pt (static 80 classes)
                learner_model_path=learner_model,  # yoloe-11s-seg*.pt (adaptive)
                device=device,
                max_workers=2,  # Parallel inference
                learner_mode=learner_mode  # Set initial mode
            )
            self.yolo_device = device
            
            # Legacy compatibility (for old code paths)
            self.model = self.dual_yolo.guardian
            self.classes = self.dual_yolo.guardian.model.names
            
            self.status_queue.put(f"Status: Dual YOLO ready ({device})")
            self.debug_print(f"✅ Layer 0 Guardian: Static safety detection (80 classes)")
            self.debug_print(f"✅ Layer 1 Learner: Adaptive context ({self.dual_yolo.learner.prompt_manager.get_class_count()} classes)")
            logger.info(f"✅ Dual YOLO Handler loaded successfully on {device}")
            # Thread-safe GUI update
            self._safe_gui_update(lambda: self.update_handler_status("yolo", "active"))
            
        except Exception as e:
            logger.error(f"❌ Dual YOLO loading failed: {e}", exc_info=True)
            self.status_queue.put("Status: Dual YOLO FAILED")
            self.debug_print(f"❌ ERROR: {e}")
            # Thread-safe GUI update
            self._safe_gui_update(lambda: self.update_handler_status("yolo", "error"))
            self.dual_yolo = None
            self.model = None
    
    def video_capture_thread(self):
        """
        Captures frames from webcam (laptop) or IMX415 (RPi).
        Automatically handles fallback and reconnection.
        """
        while not self.stop_event.is_set():
            try:
                if self.cap is None or not self.cap.isOpened():
                    if USE_PICAMERA:
                        self._init_picamera()
                    else:
                        self._init_webcam()
                
                if USE_PICAMERA and self.picamera2:
                    frame = self.picamera2.capture_array()
                elif self.cap:
                    ret, frame = self.cap.read()
                    if not ret:
                        logger.warning("Frame read failed, reconnecting...")
                        if self.cap:
                            self.cap.release()
                        self.cap = None
                        time.sleep(1)
                        continue
                else:
                    time.sleep(1)
                    continue
                
                self.latest_frame_for_gemini = frame.copy()
                
                if not self.frame_queue.full():
                    self.frame_queue.put(frame)
                    
            except Exception as e:
                logger.error(f"Video capture error: {e}")
                self.debug_print(f"❌ Camera error: {e}")
                time.sleep(2)
    
    def _init_webcam(self):
        """Initialize USB webcam."""
        self.status_queue.put("Status: Connecting to webcam...")
        self.cap = cv2.VideoCapture(CAMERA_SOURCE)
        
        if self.cap.isOpened():
            # Set webcam properties for better quality
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            
            self.status_queue.put("Status: Webcam connected")
            self.debug_print("✅ Webcam connected")
            logger.info("✅ Webcam initialized")
        else:
            self.debug_print("❌ Webcam not found")
            self.cap = None
    
    def _init_picamera(self):
        """Initialize Raspberry Pi camera (IMX415)."""
        try:
            from picamera2 import Picamera2
            
            self.status_queue.put("Status: Connecting to IMX415...")
            self.picamera2 = Picamera2()
            config = self.picamera2.create_preview_configuration(
                main={"size": (1920, 1080), "format": "RGB888"}
            )
            self.picamera2.configure(config)
            self.picamera2.start()
            
            self.status_queue.put("Status: IMX415 connected")
            self.debug_print("✅ IMX415 camera connected")
            logger.info("✅ IMX415 initialized")
            
        except ImportError:
            logger.warning("picamera2 not available, falling back to webcam")
            self.debug_print("⚠️ picamera2 not found, using webcam")
            USE_PICAMERA = False
            self._init_webcam()
        except Exception as e:
            logger.error(f"IMX415 init failed: {e}")
            self.debug_print(f"❌ IMX415 error: {e}")
            USE_PICAMERA = False
            self._init_webcam()
    
    def yolo_processing_thread(self):
        """
        Layer 0 + Layer 1: Dual YOLO parallel inference.
        - Layer 0 (Guardian): Static safety detection (80 classes, haptic feedback)
        - Layer 1 (Learner): Adaptive context detection (15-100 classes, learns from Gemini/Maps)
        Processes frames and feeds detections to 3D Spatial Audio.
        """
        while not self.stop_event.is_set():
            if self.dual_yolo is None:
                time.sleep(0.5)
                continue
            
            try:
                frame = self.frame_queue.get(timeout=1)
                logger.debug(f"🎬 [YOLO Thread] Got frame from queue, shape: {frame.shape}")
                
                # Run parallel inference (Layer 0 + Layer 1)
                logger.debug(f"🔄 [YOLO Thread] Starting dual inference...")
                guardian_results, learner_results = self.dual_yolo.process_frame(
                    frame, 
                    confidence=YOLO_CONFIDENCE
                )
                logger.debug(f"✅ [YOLO Thread] Inference complete. Guardian: {type(guardian_results)}, Learner: {type(learner_results)}")
                
                # Create annotated frame with BOTH models
                annotated_frame = frame.copy()
                
                # Draw Layer 0 (Guardian) detections in RED
                guardian_detections = []
                spatial_detections = []  # For 3D spatial audio
                
                if guardian_results and hasattr(guardian_results, 'boxes') and guardian_results.boxes is not None and len(guardian_results.boxes) > 0:
                    logger.debug(f"🛡️ [Guardian] Processing {len(guardian_results.boxes)} detections")
                    for box in guardian_results.boxes:
                        confidence = float(box.conf)
                        if confidence > YOLO_CONFIDENCE:
                            class_id = int(box.cls)
                            class_name = self.classes[class_id]
                            guardian_detections.append(f"{class_name} ({confidence:.2f})")
                            
                            # Draw red bounding box for guardian detections
                            bbox = box.xyxy[0].cpu().numpy().astype(int)
                            x1, y1, x2, y2 = bbox
                            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 2)  # RED for safety
                            label = f"[G] {class_name} {confidence:.2f}"
                            cv2.putText(annotated_frame, label, (x1, y1 - 10), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                            
                            # Create spatial detection for 3D audio
                            if self.spatial_audio and self.spatial_audio_enabled.get() and SpatialDetection:
                                spatial_detections.append(SpatialDetection(
                                    class_name=class_name,
                                    confidence=confidence,
                                    bbox=tuple(bbox),
                                    object_id=None  # Let manager generate stable ID
                                ))
                
                # Draw Layer 1 (Learner) detections in GREEN
                learner_detections = []
                if learner_results and hasattr(learner_results, 'boxes') and learner_results.boxes is not None and len(learner_results.boxes) > 0:
                    logger.debug(f"🎯 [Learner] Processing {len(learner_results.boxes)} detections")
                    for box in learner_results.boxes:
                        confidence = float(box.conf)
                        if confidence > YOLO_CONFIDENCE:
                            class_id = int(box.cls)
                            class_name = learner_results.names[class_id] if hasattr(learner_results, 'names') else f"class_{class_id}"
                            learner_detections.append(f"{class_name} ({confidence:.2f})")
                            
                            # Draw green bounding box for learner detections
                            bbox = box.xyxy[0].cpu().numpy().astype(int)
                            x1, y1, x2, y2 = bbox
                            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)  # GREEN for adaptive
                            label = f"[L] {class_name} {confidence:.2f}"
                            cv2.putText(annotated_frame, label, (x1, max(y2 + 20, y1 - 10)), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
                # Add legend to frame
                cv2.putText(annotated_frame, "[G] Guardian (Safety)", (10, 30), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.putText(annotated_frame, "[L] Learner (Context)", (10, 60), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                # Store learner detections for Gemini context
                self.last_learner_detections = learner_detections
                
                # ✅ NEW: Store Guardian detections for composition
                self.last_guardian_detections = guardian_detections
                
                # Update 3D spatial audio with detections
                if spatial_detections and self.spatial_audio:
                    try:
                        self.spatial_audio.update_detections(spatial_detections)
                    except Exception as sa_err:
                        logger.debug(f"Spatial audio update: {sa_err}")
                
                # Update detection string (Guardian only for safety focus)
                detections_str = ", ".join(sorted(set(guardian_detections))) or "nothing"
                self.detection_queue.put(detections_str)
                
                # Put annotated frame for UI (clear old frames if queue is full)
                if self.processed_frame_queue.full():
                    try:
                        self.processed_frame_queue.get_nowait()  # Remove oldest frame
                    except queue.Empty:
                        pass
                self.processed_frame_queue.put(annotated_frame)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Dual YOLO processing error: {e}")
                time.sleep(1)
    
    def update_video(self):
        """Gets an annotated frame from the queue and displays it on the canvas."""
        try:
            # Poll pygame events for TTS playback completion
            self.poll_pygame_events()
            
            frame = self.processed_frame_queue.get_nowait()
            
            # Resize to fit canvas while maintaining aspect ratio
            h, w, _ = frame.shape
            if self.canvas_width > 1 and self.canvas_height > 1:
                aspect = w / h
                if self.canvas_width / self.canvas_height > aspect:
                    new_h = self.canvas_height
                    new_w = int(new_h * aspect)
                else:
                    new_w = self.canvas_width
                    new_h = int(new_w / aspect)
                
                resized = cv2.resize(frame, (new_w, new_h))
                img = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(img)
                self.photo = ImageTk.PhotoImage(image=img)
                
                self.canvas.delete("all")
                self.canvas.create_image(
                    self.canvas_width // 2, 
                    self.canvas_height // 2, 
                    image=self.photo, 
                    anchor="center"
                )
        except queue.Empty:
            pass  # No new frame, keep displaying the last one
        except Exception as e:
            logger.error(f"Video display error: {e}")
        finally:
            self.window.after(self.delay, self.update_video)
    
    def update_status(self):
        """Updates status label from queue."""
        try:
            message = self.status_queue.get_nowait()
            self.status_label.configure(text=message)
        except queue.Empty:
            pass
        finally:
            self.window.after(100, self.update_status)
    
    def update_detections(self):
        """Updates last detections from queue."""
        try:
            self.last_detections = self.detection_queue.get_nowait()
        except queue.Empty:
            pass
        finally:
            self.window.after(100, self.update_detections)
    
    def init_audio(self):
        """Initialize pygame mixer and populate device lists."""
        try:
            pygame.mixer.init()
            self.debug_print("✅ Audio system initialized")
            logger.info("✅ Pygame mixer initialized")
        except Exception as e:
            logger.error(f"Audio init failed: {e}")
            self.debug_print(f"❌ Audio error: {e}")
        
        self.populate_audio_devices()
    
    def populate_audio_devices(self):
        """Query and populate audio device dropdowns."""
        try:
            devices = sd.query_devices()
            self.input_devices = {
                f"{i}: {d['name']}": i 
                for i, d in enumerate(devices) 
                if d['max_input_channels'] > 0
            }
            self.output_devices = {
                f"{i}: {d['name']}": i 
                for i, d in enumerate(devices) 
                if d['max_output_channels'] > 0
            }
            
            # Update input menu
            if self.input_devices:
                self.input_device_menu.configure(values=list(self.input_devices.keys()))
                default_in = sd.default.device[0]
                default_name = f"{default_in}: {sd.query_devices(default_in)['name']}"
                if default_name in self.input_devices:
                    self.selected_input_device.set(default_name)
                else:
                    self.selected_input_device.set(list(self.input_devices.keys())[0])
            
            # Update output menu
            if self.output_devices:
                self.output_device_menu.configure(values=list(self.output_devices.keys()))
                default_out = sd.default.device[1]
                default_name = f"{default_out}: {sd.query_devices(default_out)['name']}"
                if default_name in self.output_devices:
                    self.selected_output_device.set(default_name)
                else:
                    self.selected_output_device.set(list(self.output_devices.keys())[0])
            
            self.debug_print(f"✅ Found {len(self.input_devices)} input, {len(self.output_devices)} output devices")
            
        except Exception as e:
            logger.error(f"Device enumeration failed: {e}")
            self.debug_print(f"❌ Device error: {e}")
    
    def toggle_recording(self):
        """Toggle audio recording on/off."""
        if self.recording_active:
            self.stop_recording()
        else:
            self.start_recording()
    
    def start_recording(self):
        """Start audio recording in background thread."""
        try:
            device_name = self.selected_input_device.get()
            if not device_name or ":" not in device_name:
                messagebox.showerror("Error", "Select a valid input device")
                return
            
            device_id = self.input_devices[device_name]
            self.debug_print(f"🎤 Recording on: {device_name}")
            
            self.recording_active = True
            self.record_btn.configure(text="🛑 Stop Recording", fg_color='#ff4444')
            self.audio_queue = queue.Queue()
            
            threading.Thread(target=self._record_audio_thread, args=(device_id,), daemon=True).start()
            
        except Exception as e:
            logger.error(f"Recording start failed: {e}")
            self.debug_print(f"❌ Recording error: {e}")
            self.recording_active = False
            self.record_btn.configure(text="🎤 Record Voice", fg_color='#dc3545')
    
    def _record_audio_thread(self, device_id):
        """Audio recording worker thread."""
        samplerate = 44100
        channels = 1
        
        def callback(indata, frames, time, status):
            if status:
                logger.warning(f"Audio callback status: {status}")
            self.audio_queue.put(indata.copy())
        
        try:
            with sd.InputStream(samplerate=samplerate, device=device_id, channels=channels, callback=callback):
                while self.recording_active:
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Recording thread error: {e}")
            self.debug_print(f"❌ Recording failed: {e}")
        finally:
            self.debug_print("🎤 Recording stopped")
    
    def stop_recording(self):
        """Stop recording and process audio."""
        if not self.recording_active:
            return
        
        self.recording_active = False
        self.record_btn.configure(text="🎤 Record Voice", fg_color='#dc3545')
        self.debug_print("Processing audio...")
        
        time.sleep(0.2)  # Wait for last chunks
        
        audio_data = []
        while not self.audio_queue.empty():
            audio_data.append(self.audio_queue.get())
        
        if not audio_data:
            self.debug_print("⚠️ No audio recorded")
            return
        
        audio_data = np.concatenate(audio_data, axis=0)
        write_wav(AUDIO_FILE_FOR_WHISPER, 44100, audio_data)
        self.debug_print(f"💾 Audio saved: {AUDIO_FILE_FOR_WHISPER}")
        
        self.process_recorded_audio()
    
    # =================================================================
    # VOICE ACTIVATION (VAD) METHODS
    # =================================================================
    
    def toggle_voice_activation(self):
        """Toggle voice activation mode on/off."""
        if self.voice_activation_enabled.get():
            self.start_voice_activation()
        else:
            self.stop_voice_activation()
    
    def toggle_vad_interrupt(self):
        """Toggle VAD interrupt mode (allow voice to interrupt TTS playback)."""
        if self.vad_interrupt_enabled.get():
            self.debug_print("🔇 VAD Interrupt ENABLED - Voice can interrupt TTS playback")
            logger.info("VAD interrupt mode enabled")
        else:
            self.debug_print("🔊 VAD Interrupt DISABLED - TTS will play to completion")
            logger.info("VAD interrupt mode disabled")
    
    def toggle_spatial_audio(self):
        """Toggle 3D Spatial Audio navigation on/off."""
        if self.spatial_audio_enabled.get():
            self.start_spatial_audio()
        else:
            self.stop_spatial_audio()
    
    def toggle_visual_prompts_mode(self):
        """Toggle visual prompts marking mode (draw bounding boxes)."""
        self.visual_prompts_mode_active = not self.visual_prompts_mode_active
        
        if self.visual_prompts_mode_active:
            self.visual_prompt_btn.configure(fg_color="#ff5555", text="✅ Marking ON")
            self.debug_print("📦 Visual Prompts Mode: Click and drag on video to mark objects")
            self.debug_print("   Press 'Enter' when done to set prompts")
            # TODO: Add canvas click handlers for bounding box drawing
        else:
            self.visual_prompt_btn.configure(fg_color="#1f538d", text="📦 Mark Objects")
            self.debug_print("Visual Prompts Mode: OFF")
    
    def on_yoloe_mode_changed(self, selected_mode: str):
        """Handle YOLOE mode selection change."""
        mode_map = {
            "Prompt-Free": YOLOEMode.PROMPT_FREE,
            "Text Prompts": YOLOEMode.TEXT_PROMPTS,
            "Visual Prompts": YOLOEMode.VISUAL_PROMPTS
        }
        
        new_mode = mode_map.get(selected_mode, YOLOEMode.TEXT_PROMPTS)
        
        if self.dual_yolo and self.dual_yolo.learner:
            try:
                old_mode = self.dual_yolo.learner.mode
                self.dual_yolo.learner.switch_mode(new_mode)
                
                # Update info label
                mode_info = {
                    YOLOEMode.PROMPT_FREE: "🔍 4585+ classes (zero setup, discovery mode)",
                    YOLOEMode.TEXT_PROMPTS: "🧠 15-100 adaptive classes (learns from Gemini/Maps/Memory)",
                    YOLOEMode.VISUAL_PROMPTS: "👁️ User-defined (mark personal objects with boxes)"
                }
                self.mode_info_label.configure(text=mode_info[new_mode])
                
                logger.info(f"✅ YOLOE mode switched: {old_mode.value} → {new_mode.value}")
                self.debug_print(f"🔄 Layer 1 mode: {old_mode.value} → {new_mode.value}")
            except Exception as e:
                logger.error(f"❌ Failed to switch YOLOE mode: {e}")
                self.debug_print(f"❌ Mode switch failed: {e}")
        else:
            logger.warning("⚠️ Dual YOLO not initialized, mode will be applied on init")
    
    def on_tier_selection_changed(self, selected_tier: str):
        """Callback when user changes Layer 2 tier selection.
        
        Args:
            selected_tier: One of:
                - "Testing (FREE)" - Tier 1 only for daily testing ($0)
                - "Demo Mode (PAID)" - Tier 0 for competitions ($1/hour)
                - "Auto (Cascading)" - Use all tiers with auto-fallback
                - "Tier 0 (Live API)" - Force Gemini Live API only
                - "Tier 1 (Gemini TTS)" - Force Gemini 2.5 Flash TTS only
        """
        tier_map = {
            "Testing (FREE)": "Gemini TTS",
            "Demo Mode (PAID)": "Live API",
            "Auto (Cascading)": "Auto",
            "Tier 0 (Live API)": "Live API",
            "Tier 1 (Gemini TTS)": "Gemini TTS"
        }
        
        tier_name = tier_map.get(selected_tier, "Auto")
        
        if tier_name == "Auto":
            self.debug_print("🔄 AI Tier: AUTO (cascading fallback enabled)")
            self.fallback_enabled.set(True)
        elif tier_name == "Gemini TTS":
            cost_info = " [💰 FREE]" if "FREE" in selected_tier else ""
            self.debug_print(f"🎯 AI Tier: {tier_name} ONLY{cost_info}")
            self.fallback_enabled.set(False)
            self.active_api = tier_name
        elif tier_name == "Live API":
            cost_info = " [💰 ~$1/hour]" if "PAID" in selected_tier else ""
            self.debug_print(f"🎯 AI Tier: {tier_name} ONLY{cost_info}")
            self.fallback_enabled.set(False)
            self.active_api = tier_name
        else:
            self.debug_print(f"🎯 AI Tier: {tier_name} ONLY")
            self.fallback_enabled.set(False)
            self.active_api = tier_name
        
        logger.info(f"Layer 2 tier selection changed: {selected_tier}")
    
    def start_spatial_audio(self):
        """Start 3D spatial audio navigation system."""
        if not SPATIAL_AUDIO_AVAILABLE:
            self.debug_print("❌ 3D Audio not available - Install PyOpenAL")
            self.spatial_audio_enabled.set(False)
            self.update_handler_status("3d-audio", "error")
            return
        
        try:
            self.debug_print("🔊 Starting 3D Spatial Audio...")
            
            # Initialize spatial audio manager if not already loaded
            if self.spatial_audio is None:
                self.spatial_audio = SpatialAudioManager(
                    frame_width=self.canvas_width,
                    frame_height=self.canvas_height
                )
            
            # Start the audio system
            if self.spatial_audio.start():
                self.update_handler_status("3d-audio", "active")
                self.debug_print("✅ 3D Spatial Audio ENABLED")
                
                # Print the body-relative navigation notice
                print_navigation_notice()
                self.debug_print("⚠️ IMPORTANT: Body-Relative Navigation")
                self.debug_print("   Turn your TORSO to center sounds, not just your head!")
            else:
                self.spatial_audio_enabled.set(False)
                self.debug_print("❌ Failed to start 3D audio")
                self.update_handler_status("3d-audio", "error")
                
        except Exception as e:
            logger.error(f"Spatial audio start failed: {e}")
            self.debug_print(f"❌ 3D Audio error: {e}")
            self.spatial_audio_enabled.set(False)
            self.update_handler_status("3d-audio", "error")
    
    def stop_spatial_audio(self):
        """Stop 3D spatial audio navigation system."""
        try:
            if self.spatial_audio:
                self.spatial_audio.stop()
                self.update_handler_status("3d-audio", "inactive")
                self.debug_print("🛑 3D Spatial Audio DISABLED")
                
        except Exception as e:
            logger.error(f"Spatial audio stop failed: {e}")
            self.debug_print(f"❌ 3D Audio stop error: {e}")
    
    def start_voice_activation(self):
        """Start voice activation mode using Silero VAD."""
        try:
            self.debug_print("🎙️ Starting Voice Activation...")
            
            # Initialize VAD handler if not already loaded
            if not self.init_vad():
                self.voice_activation_enabled.set(False)
                return
            
            # Get selected input device
            device_name = self.selected_input_device.get()
            if not device_name or ":" not in device_name:
                messagebox.showerror("Error", "Select a valid input device for voice activation")
                self.voice_activation_enabled.set(False)
                return
            
            device_id = self.input_devices[device_name]
            
            # Start VAD listening
            if self.vad_handler.start_listening(device_index=device_id):
                self.vad_listening = True
                self.update_handler_status("vad", "active")
                self.debug_print("✅ Voice Activation ENABLED - Speak to interact")
                self.status_queue.put("Status: VOICE-ACTIVATED MODE")
                
                # Disable manual record button while VAD is active
                self.record_btn.configure(state="disabled")
            else:
                self.voice_activation_enabled.set(False)
                self.debug_print("❌ Failed to start voice activation")
                
        except Exception as e:
            logger.error(f"Voice activation start failed: {e}")
            self.debug_print(f"❌ VAD error: {e}")
            self.voice_activation_enabled.set(False)
            self.update_handler_status("vad", "error")
    
    def stop_voice_activation(self):
        """Stop voice activation mode."""
        try:
            if self.vad_handler and self.vad_listening:
                self.vad_handler.stop_listening()
                self.vad_listening = False
                self.update_handler_status("vad", "inactive")
                self.debug_print("🛑 Voice Activation DISABLED")
                self.status_queue.put("Status: Ready")
                
                # Re-enable manual record button
                self.record_btn.configure(state="normal")
                
        except Exception as e:
            logger.error(f"Voice activation stop failed: {e}")
            self.debug_print(f"❌ VAD stop error: {e}")
    
    def on_vad_speech_start(self):
        """Callback when VAD detects speech start."""
        # INTERRUPT: If TTS is currently playing AND interrupt is enabled, request stop
        # NOTE: We set a flag instead of calling pygame directly because this callback
        # runs in the VAD thread, and pygame isn't fully thread-safe
        if self.tts_playing and self.vad_interrupt_enabled.get():
            self.tts_interrupt_requested = True  # Will be handled by poll_pygame_events in main thread
            self.debug_print("🛑 TTS INTERRUPT REQUESTED - stopping playback...")
            logger.info("TTS playback interrupt requested by VAD speech detection")
        elif self.tts_playing:
            # TTS playing but interrupt disabled - just log it
            self.debug_print("🔊 TTS playing (interrupt disabled, waiting for completion...)")
        
        self.debug_print("🗣️ VAD: Speech START detected - Recording audio...")
        self.debug_print("⏺️ Recording State: ACTIVE")
        self.status_queue.put("Status: 🎤 RECORDING SPEECH...")
        self.update_handler_status("vad", "processing")
    
    def on_vad_speech_end(self, audio_data):
        """Callback when VAD detects speech end."""
        try:
            duration_ms = len(audio_data) / 16000 * 1000
            self.debug_print(f"🔇 VAD: Speech END detected")
            self.debug_print(f"⏹️ Recording State: STOPPED")
            self.debug_print(f"📊 Audio Stats: Duration={duration_ms:.0f}ms, Samples={len(audio_data)}")
            
            # Save audio to file for Whisper
            # Convert from float32 [-1, 1] to int16
            audio_int16 = (audio_data * 32767).astype(np.int16)
            
            # Use absolute path to ensure file is found
            import os
            wav_file_path = os.path.abspath(AUDIO_FILE_FOR_WHISPER)
            self.debug_print(f"💾 Saving audio to: {wav_file_path}")
            
            # Write WAV file
            write_wav(wav_file_path, 16000, audio_int16)
            
            # Validate file was written correctly AND is readable
            import time
            time.sleep(0.05)  # Give filesystem time to flush (50ms)
            
            if not os.path.exists(wav_file_path):
                self.debug_print(f"❌ ERROR: Audio file not found after write!")
                self.update_handler_status("vad", "error")
                return
            
            file_size = os.path.getsize(wav_file_path)
            if file_size < 100:
                self.debug_print(f"❌ ERROR: Audio file too small ({file_size} bytes)")
                self.update_handler_status("vad", "error")
                return
            
            self.debug_print(f"✅ Audio file saved: {file_size} bytes")
            self.debug_print(f"📤 Sending to Whisper pipeline...")
            
            # Process audio through the same pipeline as manual recording
            self.debug_print("🔄 Sending VAD audio to processing pipeline...")
            self.debug_print(f"📋 Pipeline Entry Point: process_recorded_audio()")
            self.process_recorded_audio()
            
            # Reset VAD status
            self.debug_print("✅ VAD audio sent to pipeline, waiting for next speech...")
            self.update_handler_status("vad", "active")
            self.status_queue.put("Status: VOICE-ACTIVATED MODE")
            
        except Exception as e:
            logger.error(f"VAD speech end processing failed: {e}")
            self.debug_print(f"❌ VAD processing error: {e}")
            self.update_handler_status("vad", "error")
    
    def init_vad(self):
        """Initialize VAD handler (eager loading on startup)."""
        if self.vad_handler is not None:
            self.debug_print("ℹ️ VAD already initialized")
            return True
        
        try:
            self.debug_print("⏳ Initializing Silero VAD...")
            self.update_handler_status("vad", "loading")
            
            # VAD Configuration
            vad_config = {
                "sample_rate": 16000,
                "chunk_size": 512,  # 32ms at 16kHz
                "threshold": 0.5,   # Balanced sensitivity
                "min_speech_duration_ms": 500,  # Minimum 0.5s of speech
                "min_silence_duration_ms": 700,  # 0.7s silence to end
                "padding_duration_ms": 300,  # 300ms padding before/after
            }
            
            self.debug_print("📋 VAD Configuration:")
            self.debug_print(f"   Sample Rate: {vad_config['sample_rate']} Hz")
            self.debug_print(f"   Chunk Size: {vad_config['chunk_size']} samples ({vad_config['chunk_size']/vad_config['sample_rate']*1000:.1f}ms)")
            self.debug_print(f"   Threshold: {vad_config['threshold']} (0.0=sensitive, 1.0=strict)")
            self.debug_print(f"   Min Speech: {vad_config['min_speech_duration_ms']}ms")
            self.debug_print(f"   Min Silence: {vad_config['min_silence_duration_ms']}ms (to end recording)")
            self.debug_print(f"   Padding: {vad_config['padding_duration_ms']}ms (before/after speech)")
            
            # Create VAD handler with callbacks
            self.vad_handler = VADHandler(
                sample_rate=vad_config["sample_rate"],
                chunk_size=vad_config["chunk_size"],
                threshold=vad_config["threshold"],
                min_speech_duration_ms=vad_config["min_speech_duration_ms"],
                min_silence_duration_ms=vad_config["min_silence_duration_ms"],
                padding_duration_ms=vad_config["padding_duration_ms"],
                on_speech_start=self.on_vad_speech_start,
                on_speech_end=self.on_vad_speech_end
            )
            
            self.debug_print("🔄 Loading Silero VAD model...")
            if not self.vad_handler.load_model():
                raise Exception("Failed to load VAD model")
            
            self.update_handler_status("vad", "inactive")
            self.debug_print("✅ Silero VAD initialized and ready")
            return True
            
        except Exception as e:
            logger.error(f"VAD init failed: {e}")
            self.debug_print(f"❌ VAD init error: {e}")
            self.update_handler_status("vad", "error")
            self.vad_handler = None
            return False
    
    # =================================================================
    # END VAD METHODS
    # =================================================================
    
    def process_recorded_audio(self):
        """
        Process recorded audio: Transcribe -> Route -> Execute.
        """
        self.status_queue.put("Status: Transcribing...")
        self.update_handler_status("whisper", "processing")
        threading.Thread(target=self._process_audio_pipeline, daemon=True).start()
    
    def _process_audio_pipeline(self):
        """Background pipeline: Whisper -> Router -> Layer Handler (TODO #2 & #4)."""
        try:
            # === STAGE 1: Whisper Transcription ===
            self.status_queue.put("Status: Whisper transcribing...")
            self.debug_print("🎧 [PIPELINE] Stage 1: Whisper STT")
            
            if not self.init_whisper_stt():
                self.debug_print("❌ Whisper not available")
                self.update_handler_status("whisper", "error")
                return
            
            self.debug_print("🔄 Transcribing audio file...")
            import time
            start_time = time.time()
            transcribed_text = self.whisper_stt.transcribe_file(AUDIO_FILE_FOR_WHISPER)
            whisper_latency = (time.time() - start_time) * 1000
            
            if not transcribed_text or not transcribed_text.strip():
                self.debug_print("⚠️ Empty transcription")
                self.status_queue.put("Status: No speech detected")
                self.update_handler_status("whisper", "active")
                return

            self.debug_print(f"✅ Whisper ({whisper_latency:.0f}ms): '{transcribed_text}'")
            self._safe_gui_update(lambda: self.input_entry.delete(0, "end"))
            self._safe_gui_update(lambda: self.input_entry.insert(0, transcribed_text))
            self.update_handler_status("whisper", "active")
            
            # === STAGE 2: Intent Routing ===
            self.status_queue.put("Status: Routing intent...")
            self.debug_print("🧠 [PIPELINE] Stage 2: Intent Router")
            
            start_time = time.time()
            target_layer = self.router.route(transcribed_text)
            router_latency = (time.time() - start_time) * 1000
            
            layer_desc = self.router.get_layer_description(target_layer)
            self.debug_print(f"✅ Router ({router_latency:.0f}ms): {layer_desc}")
            self.status_queue.put(f"Status: {layer_desc}")
            
            # === STAGE 3: Layer Execution ===
            self.debug_print(f"🚀 [PIPELINE] Stage 3: Executing {target_layer.upper()}")
            
            if target_layer == "layer1":
                self._execute_layer1_reflex(transcribed_text)
            elif target_layer == "layer2":
                self._execute_layer2_thinker(transcribed_text)
            elif target_layer == "layer3":
                self._execute_layer3_guide(transcribed_text)
            
            self.debug_print("✅ [PIPELINE] Complete")
            
        except Exception as e:
            logger.error(f"Audio pipeline failed: {e}", exc_info=True)
            self.debug_print(f"❌ [PIPELINE] ERROR: {e}")
            self.status_queue.put("Status: Pipeline Error")
            self.update_handler_status("whisper", "error")

    def _switch_yoloe_mode(self, target_mode: str, memory_id: str = None):
        """
        Switch YOLOE Learner to specified detection mode.
        
        Implements zero-overhead mode switching with comprehensive logging.
        
        Args:
            target_mode: Target mode string ("PROMPT_FREE", "TEXT_PROMPTS", "VISUAL_PROMPTS")
            memory_id: Memory ID for VISUAL_PROMPTS mode (e.g., "wallet_003")
        """
        if not hasattr(self, 'yoloe_learner') or self.yoloe_learner is None:
            logger.warning("⚠️ [MODE SWITCH] YOLOE Learner not initialized, skipping mode switch")
            return
        
        start_time = time.time()
        current_mode = self.yoloe_learner.mode.value if hasattr(self.yoloe_learner.mode, 'value') else str(self.yoloe_learner.mode)
        
        # Check if already in target mode
        if current_mode.upper() == target_mode.upper():
            logger.debug(f"🔄 [MODE SWITCH] Already in {target_mode} mode, skipping")
            return
        
        logger.info(f"🔄 [MODE SWITCH] {current_mode.upper()} → {target_mode.upper()}")
        
        try:
            if target_mode == "VISUAL_PROMPTS":
                if memory_id:
                    logger.debug(f"   Loading visual prompts for memory_id: {memory_id}")
                    self.yoloe_learner.load_visual_prompts_from_memory(memory_id)
                else:
                    logger.warning("   No memory_id provided for VISUAL_PROMPTS mode")
            
            elif target_mode == "TEXT_PROMPTS":
                self.yoloe_learner.load_text_prompts()
            
            elif target_mode == "PROMPT_FREE":
                self.yoloe_learner.switch_to_prompt_free()
            
            else:
                logger.error(f"❌ [MODE SWITCH] Unknown target mode: {target_mode}")
                return
            
            # Track mode switch overhead
            switch_time = (time.time() - start_time) * 1000  # ms
            logger.info(f"✅ [MODE SWITCH] Mode switch completed in {switch_time:.1f}ms")
            
            if switch_time > 50:
                logger.warning(f"⚠️ [PERFORMANCE] Mode switch exceeded 50ms target ({switch_time:.1f}ms)")
        
        except Exception as e:
            logger.error(f"❌ [MODE SWITCH] Failed to switch mode: {e}", exc_info=True)
            self.debug_print(f"❌ [MODE SWITCH] Error: {e}")
    
    def _execute_layer1_reflex(self, text):
        """Layer 1: Local Object Detection + Quick Memory Recall with Intelligent Mode Switching."""
        self.status_queue.put("Status: Layer 1 analyzing...")
        self.debug_print("⚡ [LAYER 1] Reflex Mode: Adaptive YOLOE")
        
        text_lower = text.lower()
        
        # ✅ INTELLIGENT MODE SWITCHING: Detect optimal YOLOE mode from query
        if hasattr(self, 'intent_router') and self.intent_router:
            recommended_mode = self.intent_router.get_recommended_mode(text_lower, self.last_learner_detections or "")
            self.debug_print(f"🎯 [MODE] Recommended: {recommended_mode}")
            
            # Extract memory_id for personal queries
            memory_id = None
            if recommended_mode == "VISUAL_PROMPTS":
                # Extract object name from query (e.g., "where's my wallet" → "wallet")
                for kw in ["where is my", "where's my", "find my", "show me my"]:
                    if kw in text_lower:
                        object_name = text_lower.split(kw)[1].strip().rstrip('?.,!').split()[0]
                        # TODO: Query Layer 4 for actual memory_id (e.g., "wallet_003")
                        # For now, use object name as placeholder
                        memory_id = f"{object_name}_001"  # Placeholder
                        self.debug_print(f"🔍 [MEMORY] Searching for: {object_name} (id: {memory_id})")
                        break
            
            # Switch YOLOE mode
            self._switch_yoloe_mode(recommended_mode, memory_id)
        
        text_lower = text.lower()
        
        # Check if this is a memory recall query: "where is my [object]"
        if any(kw in text_lower for kw in ["where is my", "find my", "show me my"]):
            # Extract object name
            for kw in ["where is my", "find my", "show me my"]:
                if kw in text_lower:
                    object_name = text_lower.split(kw)[1].strip().rstrip('?.,!')
                    break
            
            self.debug_print(f"🔍 [LAYER 1] Memory recall: Looking for '{object_name}'")
            
            # Check if object is currently visible
            if self.memory_manager:
                # ✅ FIXED: Use Learner detections (YOLOE-11m adaptive classes)
                is_visible = self.memory_manager.check_if_in_view(object_name, self.last_learner_detections)
                
                if is_visible:
                    response = f"I can see your {object_name} right now."
                else:
                    # Check memory for last known location
                    memory = self.memory_manager.recall(object_name)
                    if memory:
                        location = memory.get('location_estimate', 'an unknown location')
                        response = f"I don't see your {object_name} right now. I last saw it at {location}."
                    else:
                        response = f"I don't see your {object_name}, and I don't have any memory of it."
            else:
                response = f"Memory system not available. Looking for {object_name} in current view..."
                is_visible = object_name in (self.last_detections or "").lower()
                if is_visible:
                    response = f"I can see your {object_name} right now."
                else:
                    response = f"I don't see your {object_name} right now."
        else:
            # Standard detection report
            # ✅ NEW: Merge Guardian + Learner detections for complete response
            merged_detections = self.detection_aggregator.merge_detections(
                getattr(self, 'last_guardian_detections', []) or [],
                self.last_learner_detections or []
            )
            
            if not merged_detections or merged_detections == "nothing":
                response = "I don't see anything specific right now."
            else:
                response = f"I see {merged_detections}."
        
        # ✅ NEW: Debug print shows merged Guardian + Learner detections
        self.debug_print(f"🛡️ [LAYER 0] Guardian: {getattr(self, 'last_guardian_detections', [])}")
        self.debug_print(f"🔍 [LAYER 1] Learner: {self.last_learner_detections}")
        self.debug_print(f"🔀 [MERGED] Combined: {merged_detections if 'merged_detections' in locals() else response}")
        self.debug_print(f"💬 [LAYER 1] Response: {response}")
        
        self._safe_gui_update(lambda: self.response_text.delete('1.0', "end"))
        self._safe_gui_update(lambda: self.response_text.insert("end", f"[Layer 1] {response}"))
        
        self.status_queue.put("Status: Generating TTS...")
        self.generate_tts(response)

    def _execute_layer2_thinker(self, text):
        """
        Layer 2: 3-Tier Cascading Fallback System
        
        Supports 2 modes:
        1. AUTO MODE: Cascading fallback across all tiers
        2. MANUAL MODE: Force specific tier only
        
        Tier 0 (Best): Gemini Live API - WebSocket audio-to-audio (<500ms)
        Tier 1 (Good): Gemini 2.5 Flash TTS - HTTP vision+TTS (~1-2s)  
        Tier 2 (Backup): GLM-4.6V - Z.ai vision API (~1-2s)
        """
        self.debug_print("☁️ Layer 2 (Thinker) Activated")
        
        # Check user's tier selection
        selected_tier = self.selected_tier.get()
        
        # MANUAL MODE: Force specific tier
        if selected_tier == "Tier 0 (Live API)":
            self.debug_print("🎯 MANUAL MODE: Tier 0 only")
            self._execute_layer2_live_api(text)
            return
        
        elif selected_tier == "Tier 1 (Gemini TTS)":
            self.debug_print("🎯 MANUAL MODE: Tier 1 only")
            self._execute_layer2_gemini_tts(text)
            return
        
        elif selected_tier == "Tier 2 (GLM-4.6V)":
            self.debug_print("🎯 MANUAL MODE: Tier 2 only")
            self._execute_layer2_glm4v(text)
            return
        
        # AUTO MODE: Cascading fallback (default)
        self.debug_print("🔄 AUTO MODE: 3-tier cascading fallback")
        
        # Attempt Tier 0: Gemini Live API (WebSocket)
        if self.gemini_live and self.live_api_enabled.get() and not hasattr(self.gemini_live.handler, 'quota_exceeded'):
            self.debug_print(f"🔌 Using {self.active_api} (Tier 0 - WebSocket)")
            success = self._execute_layer2_live_api(text)
            
            # Check if quota exceeded
            if not success and hasattr(self.gemini_live.handler, 'quota_exceeded') and self.gemini_live.handler.quota_exceeded:
                self.debug_print("⚠️ Live API quota exceeded - falling back to Tier 1")
                self.active_api = "Gemini TTS"
                # Continue to Tier 1
            elif success:
                return
        
        # Attempt Tier 1: Gemini 2.5 Flash TTS (HTTP)
        if self.gemini_tts and not getattr(self.gemini_tts, 'using_fallback', False):
            self.debug_print(f"📡 Using {self.active_api} (Tier 1 - HTTP)")
            success = self._execute_layer2_gemini_tts(text)
            
            # Check if all Gemini keys exhausted
            if not success or getattr(self.gemini_tts, 'using_fallback', False):
                self.debug_print("⚠️ All Gemini keys exhausted - falling back to Tier 2")
                self.active_api = "GLM-4.6V"
                # Continue to Tier 2
            elif success:
                return
        
        # Attempt Tier 2: GLM-4.6V Z.ai (Final fallback)
        if self.glm4v:
            self.debug_print(f"🌐 Using {self.active_api} (Tier 2 - Z.ai)")
            success = self._execute_layer2_glm4v(text)
            
            if not success:
                self.debug_print("❌ All API tiers failed - check API keys and quotas")
                self.status_queue.put("Status: All AI APIs unavailable")
            return
        
        # No APIs available
        self.debug_print("❌ No AI APIs available - check configuration")
        self.status_queue.put("Status: No AI APIs configured")
    
    def _execute_layer2_live_api(self, text) -> bool:
        """
        Execute Layer 2 using Gemini Live API (WebSocket) - Tier 0.
        
        Features:
        - Real-time audio-to-audio streaming
        - Video frame streaming (2-5 FPS)
        - <500ms latency
        - Stateful conversation
        
        Returns:
            bool: True if successful, False if failed
        """
        if not self.gemini_live:
            self.debug_print("❌ Live API not initialized")
            return False
        
        try:
            # Start streaming audio player
            if self.streaming_player and not self.streaming_player.is_playing:
                self.streaming_player.start()
            
            # Send text prompt
            self.status_queue.put("Status: Sending query to Live API...")
            self.update_handler_status("live-api", "processing")
            
            self.gemini_live.send_text(text)
            self.debug_print(f"📤 Sent query: {text}")
            
            # Send current video frame (if available and enabled)
            if self.video_streaming_enabled.get() and self.latest_frame_for_gemini is not None:
                current_time = time.time()
                
                # Limit to 2-5 FPS (send frame every 400ms)
                if current_time - self.last_video_frame_time >= self.video_frame_interval:
                    # Convert numpy array to PIL Image
                    frame_rgb = cv2.cvtColor(self.latest_frame_for_gemini, cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(frame_rgb)
                    
                    # Send to Live API
                    self.gemini_live.send_video(pil_image)
                    self.last_video_frame_time = current_time
                    self.debug_print(f"📷 Sent video frame ({pil_image.width}x{pil_image.height})")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Live API execution failed: {e}")
            self.debug_print(f"❌ Live API error: {e}")
            return False
    
    def _execute_layer2_gemini_tts(self, text) -> bool:
        """
        Execute Layer 2 using Gemini 2.5 Flash Vision + Kokoro TTS (HTTP) - Tier 1.
        
        Features:
        - Gemini 2.5 Flash for vision analysis (text response)
        - Kokoro TTS for speech output (offline, fast)
        - ~1-2s latency total
        - Multiple API key rotation
        
        Returns:
            bool: True if successful, False if failed
        """
        if not self.gemini_tts:
            self.debug_print("❌ Gemini TTS not initialized")
            return False
        
        try:
            self.status_queue.put("Status: Analyzing scene (Gemini Vision)...")
            self.update_handler_status("gemini-tts", "processing")
            
            # Get current video frame
            if self.latest_frame_for_gemini is not None:
                # Convert numpy array to PIL Image
                frame_rgb = cv2.cvtColor(self.latest_frame_for_gemini, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
                
                # Generate TEXT response from Gemini 2.5 Flash Vision (no TTS)
                # Using the underlying vision API without TTS
                response_text = self.gemini_tts.generate_text_from_image(
                    image=pil_image,
                    prompt=text
                )
                
                if response_text:
                    self.debug_print(f"✅ Gemini response: {response_text[:100]}...")
                    
                    # Use Kokoro TTS for speech output (offline, fast, consistent voice)
                    if self.kokoro_tts or self.init_kokoro_tts():
                        self.status_queue.put("Status: Generating speech (Kokoro TTS)...")
                        audio_file = self.kokoro_tts.generate_audio(
                            text=response_text,
                            save_to_file=True
                        )
                        if audio_file and os.path.exists(audio_file):
                            self.debug_print(f"✅ Audio generated: {audio_file}")
                            self.play_audio_file(audio_file)
                            
                            # Record Gemini learning for DetectionRouter (Phase 2)
                            if hasattr(self, 'detection_router') and self.last_guardian_detections:
                                self.detection_router.record_gemini_learning(
                                    response_text,
                                    self.last_guardian_detections + self.last_learner_detections
                                )
                            
                            return True
                        else:
                            self.debug_print("❌ Kokoro TTS audio generation failed")
                            return False
                    else:
                        self.debug_print("❌ Kokoro TTS not available")
                        return False
                else:
                    self.debug_print("❌ Gemini vision analysis failed")
                    return False
            else:
                self.debug_print("⚠️ No video frame available for Gemini Vision")
                return False
                
        except Exception as e:
            logger.error(f"❌ Gemini Vision + Kokoro TTS execution failed: {e}")
            self.debug_print(f"❌ Layer 2 error: {e}")
            return False
    
    def _execute_layer2_glm4v(self, text) -> bool:
        """
        Execute Layer 2 using GLM-4.6V Z.ai API - Tier 2 (Final Fallback).
        
        Features:
        - 128K context length
        - Native multimodal tool use
        - ~1-2s latency
        - OpenAI-compatible API
        
        Returns:
            bool: True if successful, False if failed
        """
        if not self.glm4v:
            self.debug_print("❌ GLM-4.6V not initialized")
            return False
        
        try:
            self.status_queue.put("Status: Generating response (GLM-4.6V Z.ai)...")
            
            # Get current video frame
            if self.latest_frame_for_gemini is not None:
                # Convert numpy array to PIL Image
                frame_rgb = cv2.cvtColor(self.latest_frame_for_gemini, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
                
                # Generate text response from GLM-4.6V
                response_text = self.glm4v.generate_content(
                    text=text,
                    image=pil_image
                )
                
                if response_text:
                    self.debug_print(f"✅ GLM-4.6V response: {response_text[:100]}...")
                    
                    # Use Kokoro TTS for speech output (since GLM-4.6V is text-only)
                    if self.kokoro_tts or self.init_kokoro_tts():
                        audio_file = self.kokoro_tts.generate_audio(
                            text=response_text,
                            save_to_file=True
                        )
                        if audio_file:
                            self.play_audio_file(audio_file)
                    else:
                        # No TTS available, just display text
                        self.debug_print(f"📝 Response (text-only): {response_text}")
                    
                    return True
                else:
                    self.debug_print("❌ GLM-4.6V response failed")
                    return False
            else:
                self.debug_print("⚠️ No video frame available for GLM-4.6V")
                return False
                
        except Exception as e:
            logger.error(f"❌ GLM-4.6V execution failed: {e}")
            self.debug_print(f"❌ GLM-4.6V error: {e}")
            return False
    
    def _execute_layer2_live_api_old(self, text):
        """
        OLD VERSION - kept for reference.
        Execute Layer 2 using Gemini Live API (WebSocket).
        
        Features:
        - Real-time audio-to-audio streaming
        - Video frame streaming (2-5 FPS)
        - <500ms latency
        - Stateful conversation
        """
        if not self.gemini_live:
            self.debug_print("❌ Live API not initialized")
            return
        
        # Start streaming audio player
        if self.streaming_player and not self.streaming_player.is_playing:
            self.streaming_player.start()
        
        # Send text prompt
        self.status_queue.put("Status: Sending query to Live API...")
        self.update_handler_status("live-api", "processing")
        
        self.gemini_live.send_text(text)
        self.debug_print(f"📤 Sent query: {text}")
        
        # Send current video frame (if available and enabled)
        if self.video_streaming_enabled.get() and self.latest_frame_for_gemini is not None:
            current_time = time.time()
            
            # Limit to 2-5 FPS (send frame every 400ms)
            if current_time - self.last_video_frame_time >= self.video_frame_interval:
                # Convert numpy array to PIL Image
                frame_rgb = cv2.cvtColor(self.latest_frame_for_gemini, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
                
                # Send to Live API
                self.gemini_live.send_video(pil_image)
                self.last_video_frame_time = current_time
                self.debug_print(f"📷 Sent video frame ({pil_image.width}x{pil_image.height})")
        
        # Update response area
        self._safe_gui_update(lambda: self.response_text.delete('1.0', "end"))
        self._safe_gui_update(lambda: self.response_text.insert("end", f"[Live API] Processing (audio streaming)..."))
        
        self.status_queue.put("Status: Streaming audio response...")

    def _execute_layer3_guide(self, text):
        """
        Layer 3: Navigation, Memory & SPATIAL AUDIO (3D Object Localization).
        
        This layer handles:
        1. GPS/Location queries ("where am I?")
        2. Navigation ("go to the door")
        3. MEMORY: Object storage/recall ("remember this wallet", "where is my keys?")
        4. SPATIAL AUDIO: Object localization ("where is the seat?")
           → Uses 3D audio to guide user toward detected objects
        """
        self.debug_print("🗺️ Layer 3 (Guide) Activated")
        
        # Check if this is a MEMORY STORAGE command (Layer 3 handles storage, Layer 1 handles recall)
        text_lower = text.lower()
        memory_storage_keywords = ["remember this", "save this", "memorize this", "store this",
                                   "what do you remember", "list memories", "show saved"]
        
        is_memory_storage = any(kw in text_lower for kw in memory_storage_keywords)
        
        if is_memory_storage:
            self._execute_memory_command(text)
            return
        
        # Check if this is a SPATIAL AUDIO query (object localization)
        spatial_keywords = ["where is", "where's", "where are", "locate", "find the", 
                           "guide me to", "lead me to", "point me to"]
        
        is_spatial_query = any(kw in text_lower for kw in spatial_keywords)
        
        # Extract target object from query (e.g., "where is the seat" -> "seat")
        target_object = None
        if is_spatial_query:
            # Try to extract the object name
            for kw in spatial_keywords:
                if kw in text_lower:
                    # Get text after keyword
                    parts = text_lower.split(kw)
                    if len(parts) > 1:
                        target_object = parts[1].strip().rstrip('?.,!')
                        # Remove "the" prefix if present
                        if target_object.startswith("the "):
                            target_object = target_object[4:]
                        break
            
            self.debug_print(f"🎯 Spatial Query: Looking for '{target_object}'")
        
        # If spatial audio is enabled and we have a target, use 3D audio
        if is_spatial_query and target_object and self.spatial_audio_enabled.get() and self.spatial_audio:
            self._execute_spatial_localization(text, target_object)
            return
        
        # Fallback: Use Gemini TTS for navigation guidance
        if not self.init_gemini_tts():
            self.debug_print("❌ Gemini TTS not available for Layer 3")
            return

        prompt = f"""You are the Navigation Guide for a blind user.
User Query: "{text}"
Current Visual Context: {self.last_detections}

If the user asks for location, simulate a GPS response (e.g., "You are currently at your desk").
If the user asks to go somewhere, provide general direction based on the visual context (e.g., "I see a door to your left").
If the user asks where something is, describe its position relative to the user (left, right, center, far, near).
Speak naturally and keep it short (under 30 words)."""

        self.status_queue.put("Status: Guide Thinking...")
        self.update_handler_status("gemini-tts", "processing")
        
        if self.latest_frame_for_gemini is not None:
            # Use Gemini TTS for navigation response
            from PIL import Image
            rgb_frame = cv2.cvtColor(self.latest_frame_for_gemini, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_frame)
            
            audio_path = self.gemini_tts.generate_speech_from_image(
                image=pil_image,
                prompt=prompt,
                save_to_file=True
            )
            
            if audio_path:
                self.response_text.delete('1.0', "end")
                self.response_text.insert("end", f"[Layer 3] Navigation guidance generated\n")
                self.last_tts_file = audio_path
                self.play_audio(audio_path)
                self.update_handler_status("gemini-tts", "active")
            else:
                self.debug_print("❌ Layer 3 failed")
        else:
            self.debug_print("⚠️ No video frame for Layer 3 context")
    
    def _execute_spatial_localization(self, text: str, target_object: str):
        """
        Execute spatial audio localization for a target object.
        Uses 3D audio to guide user toward the object.
        """
        self.debug_print(f"🔊 [SPATIAL] Searching for '{target_object}' in detections...")
        
        # Get current YOLO detections
        detections = self.last_detections
        if not detections or detections == "nothing":
            self.debug_print(f"⚠️ No objects detected - cannot locate '{target_object}'")
            # Speak a response using TTS
            self._speak_spatial_response(f"I cannot see any {target_object} right now. Please point the camera around.")
            return
        
        # Parse detections to find matching object
        # Format: "person (0.85), chair (0.72), laptop (0.68)"
        found = False
        for detection in detections.split(", "):
            obj_name = detection.split(" (")[0].lower()
            if target_object.lower() in obj_name or obj_name in target_object.lower():
                found = True
                self.debug_print(f"✅ Found '{target_object}' in detections: {detection}")
                
                # The spatial audio manager is already tracking objects via process_detections
                # Just speak confirmation and let the audio beacon guide them
                self._speak_spatial_response(f"I see a {obj_name}. Listen for the sound to guide you.")
                
                # Could also set a specific beacon on this object
                # self.spatial_audio.set_beacon(object_id, position)
                break
        
        if not found:
            self.debug_print(f"⚠️ '{target_object}' not found in current detections")
            self._speak_spatial_response(f"I don't see any {target_object} right now. I can see: {detections}")
    
    def _execute_memory_command(self, text: str):
        """
        Execute memory storage/recall commands.
        
        Handles:
        - "remember this wallet" → Store current frame + detections
        - "where is my keys?" → Recall stored memory
        - "what do you remember?" → List all memories
        """
        self.debug_print(f"💾 [MEMORY] Processing command: {text}")
        text_lower = text.lower()
        
        try:
            # Use Layer 4 Memory Manager
            if not self.memory_manager:
                self._speak_spatial_response("Memory system not initialized.")
                return
            
            # Initialize if needed
            if not self.memory_manager._initialized:
                if not self.memory_manager.initialize():
                    self._speak_spatial_response("Memory system initialization failed.")
                    return
            
            memory = self.memory_manager
            
            # STORE command: "remember this [object]"
            if any(kw in text_lower for kw in ["remember", "save this", "memorize", "store this"]):
                # Extract object name
                for kw in ["remember this", "save this", "memorize this", "store this", 
                          "remember the", "save the", "memorize the", "store the"]:
                    if kw in text_lower:
                        parts = text_lower.split(kw)
                        if len(parts) > 1:
                            object_name = parts[1].strip().rstrip('?.,!').replace(" ", "_")
                            break
                else:
                    # Fallback: use first detected object
                    if self.last_detections and self.last_detections != "nothing":
                        object_name = self.last_detections.split(",")[0].split("(")[0].strip().replace(" ", "_")
                    else:
                        self._speak_spatial_response("I don't see anything to remember right now.")
                        return
                
                # Capture current frame
                if self.latest_frame_for_gemini is None:
                    self._speak_spatial_response("No video frame available to save.")
                    return
                
                # Convert frame to bytes (JPEG)
                import cv2
                from io import BytesIO
                _, buffer = cv2.imencode('.jpg', self.latest_frame_for_gemini, [cv2.IMWRITE_JPEG_QUALITY, 95])
                image_bytes = buffer.tobytes()
                
                # Prepare detections dict
                detections_dict = {
                    "detections": self.last_detections,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # Store in database using Layer 4 Memory Manager
                success, memory_id, message = memory.store(
                    object_name=object_name,
                    image_data=image_bytes,
                    detections=detections_dict,
                    metadata={"query": text},
                    location=None  # Could add GPS location here in future
                )
                
                if success:
                    self.debug_print(f"✅ Memory stored: {memory_id}")
                    self._speak_spatial_response(f"Okay, I've remembered the {object_name.replace('_', ' ')}.")
                else:
                    self.debug_print(f"❌ Memory storage failed: {message}")
                    self._speak_spatial_response("Sorry, I couldn't save that.")
            
            # RECALL command: "where is my [object]"
            elif any(kw in text_lower for kw in ["where is my", "find my", "recall"]):
                # Extract object name
                for kw in ["where is my", "find my", "recall the", "recall my"]:
                    if kw in text_lower:
                        parts = text_lower.split(kw)
                        if len(parts) > 1:
                            object_name = parts[1].strip().rstrip('?.,!').replace(" ", "_")
                            break
                else:
                    self._speak_spatial_response("What do you want me to find?")
                    return
                
                # Recall from database using Layer 4 Memory Manager
                memory_data = memory.recall(object_name, latest=True)
                
                if memory_data:
                    location = memory_data.get('location_estimate', 'unknown location')
                    timestamp = memory_data.get('timestamp', 'sometime')
                    self.debug_print(f"✅ Memory recalled: {memory_data['memory_id']}")
                    
                    # Display image in GUI if possible
                    self._safe_gui_update(lambda: self.response_text.delete('1.0', "end"))
                    self._safe_gui_update(lambda: self.response_text.insert("end", f"[Memory] {object_name.replace('_', ' ')}\nLast seen: {timestamp}\nLocation: {location}\n"))
                    
                    self._speak_spatial_response(f"I last saw your {object_name.replace('_', ' ')} at {location}.")
                else:
                    self.debug_print(f"⚠️ Memory not found: {object_name}")
                    self._speak_spatial_response(f"I don't have any memory of your {object_name.replace('_', ' ')}.")
            
            # LIST command: "what do you remember?"
            elif any(kw in text_lower for kw in ["what do you remember", "show saved", "list memories"]):
                memories = memory.list_all()
                
                if not memories:
                    self._speak_spatial_response("I don't remember anything yet.")
                    return
                
                # Build response
                items = [m['object_name'].replace('_', ' ') for m in memories[:5]]  # Top 5
                if len(memories) <= 3:
                    response = f"I remember: {', '.join(items)}."
                else:
                    response = f"I remember {len(memories)} things, including: {', '.join(items[:3])}, and more."
                
                self.debug_print(f"📋 Memories: {len(memories)} items")
                self._safe_gui_update(lambda: self.response_text.delete('1.0', "end"))
                self._safe_gui_update(lambda: self.response_text.insert("end", f"[Memory] Stored items:\n"))
                for m in memories:
                    self._safe_gui_update(lambda m=m: self.response_text.insert("end", f"  - {m['object_name'].replace('_', ' ')} ({m['count']})\n"))
                
                self._speak_spatial_response(response)
            
        except Exception as e:
            logger.error(f"Memory command failed: {e}", exc_info=True)
            self.debug_print(f"❌ Memory error: {e}")
            self._speak_spatial_response("Sorry, memory system error.")
    
    def _speak_spatial_response(self, text: str):
        """Speak a short response using available TTS (Kokoro preferred for speed)."""
        try:
            # Try Kokoro first (faster, local)
            if self.kokoro_tts and hasattr(self.kokoro_tts, 'synthesize'):
                audio_path = self.kokoro_tts.synthesize(text)
                if audio_path:
                    self.play_audio(audio_path)
                    return
            
            # Fallback to Gemini TTS
            if self.gemini_tts:
                audio_path = self.gemini_tts.generate_speech_from_text(text, save_to_file=True)
                if audio_path:
                    self.play_audio(audio_path)
                    return
            
            # Last resort: just log it
            self.debug_print(f"💬 [Would say]: {text}")
        except Exception as e:
            logger.error(f"Spatial response TTS failed: {e}")
            self.debug_print(f"⚠️ TTS failed: {e}")

    def _transcribe_thread(self):
        """Deprecated: Old transcription thread."""
        pass
    
    def send_query(self):
        """Route text query through Intent Router to determine appropriate layer (Layer 1/2/3)."""
        query = self.input_entry.get().strip()
        if not query:
            messagebox.showwarning("Input Error", "Please enter a query")
            return
        
        # === STAGE 1: Intent Routing (same as voice pipeline) ===
        self.status_queue.put("Status: Routing intent...")
        self.debug_print(f"🧠 [TEXT PIPELINE] Stage 1: Intent Router")
        self.debug_print(f"   Query: '{query}'")
        
        start_time = time.time()
        target_layer = self.router.route(query)
        router_latency = (time.time() - start_time) * 1000
        
        layer_desc = self.router.get_layer_description(target_layer)
        self.debug_print(f"✅ Router ({router_latency:.0f}ms): {layer_desc}")
        self.status_queue.put(f"Status: {layer_desc}")
        
        # === STAGE 2: Layer Execution ===
        self.debug_print(f"🚀 [TEXT PIPELINE] Stage 2: Executing {target_layer.upper()}")
        
        if target_layer == "layer1":
            self._execute_layer1_reflex(query)
        elif target_layer == "layer2":
            self._execute_layer2_thinker_text(query)
        elif target_layer == "layer3":
            self._execute_layer3_guide(query)
        
        self.debug_print("✅ [TEXT PIPELINE] Complete")
    
    def _execute_layer2_thinker_text(self, query):
        """Execute Layer 2 (Thinker) for text input: Gemini vision + TTS."""
        if not GOOGLE_API_KEY:
            messagebox.showerror("API Error", "GEMINI_API_KEY not set in .env file")
            return
        
        if self.latest_frame_for_gemini is None:
            messagebox.showwarning("Video Error", "No video frame available")
            return
        
        self.status_queue.put("Status: Thinking...")
        self.response_text.delete('1.0', "end")
        self.response_text.insert("end", "🎙️ Gemini 2.5 TTS is generating audio...\n")
        self.update_handler_status("gemini-tts", "processing")
        
        frame_copy = self.latest_frame_for_gemini.copy()
        threading.Thread(target=self._send_query_thread, args=(query, frame_copy), daemon=True).start()
    
    def _send_query_thread(self, query, frame):
        """Layer 2 (Thinker): Send image + prompt to Gemini 2.5 Flash TTS and receive audio directly."""
        try:
            # Lazy load Gemini TTS (NEW: Single API call for vision + TTS)
            if not self.init_gemini_tts():
                self.response_text.delete('1.0', "end")
                self.response_text.insert("end", "❌ Gemini TTS not available")
                self.status_queue.put("Status: Gemini TTS unavailable")
                self.update_handler_status("gemini-tts", "error")
                return
            
            self.debug_print(f"🔄 Layer 2 (Gemini TTS): Generating speech for '{query[:50]}...'")
            self.debug_print(f"   Layer 1 Context: {self.last_detections}")
            
            # Build enhanced prompt with Layer 1 context
            enhanced_prompt = f"""You are Project-Cortex, an AI assistant for visually impaired users.

**3-Layer Hybrid AI Architecture:**
- Layer 1 (Reflex - Local YOLO): Currently detected objects: {self.last_detections}
- Layer 2 (Thinker - You): Describe the scene using the image and Layer 1 context
- Layer 3 (Guide): Your spoken response will be played to the user

**User Query:** {query}

**Instructions:**
1. Speak naturally and clearly (your output will be audio, not text)
2. Use Layer 1 detections as context for your description
3. Prioritize safety-critical information (obstacles, hazards)
4. Describe spatial relationships (e.g., "person on your left")
5. Keep response under 50 words for clarity
6. Speak as if talking directly to the visually impaired user"""
            
            # Convert OpenCV frame to PIL Image
            from PIL import Image
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_frame)
            
            # NEW: Single API call to Gemini 2.5 Flash TTS (image + prompt -> audio)
            audio_path = self.gemini_tts.generate_speech_from_image(
                image=pil_image,
                prompt=enhanced_prompt,
                save_to_file=True
            )
            
            if audio_path:
                self.response_text.delete('1.0', "end")
                self.response_text.insert("end", f"✅ Audio generated from Gemini 2.5 Flash TTS\n")
                self.response_text.insert("end", f"🔊 Playing response...\n")
                self.status_queue.put("Status: Playing audio")
                self.debug_print(f"✅ Layer 2 TTS audio saved: {audio_path}")
                self.update_handler_status("gemini-tts", "active")
                
                # Play audio immediately
                self.last_tts_file = audio_path
                self.play_audio_file(audio_path)
            else:
                self.response_text.delete('1.0', "end")
                self.response_text.insert("end", "❌ No response from Gemini")
                self.status_queue.put("Status: Gemini failed")
                self.update_handler_status("gemini", "error")
            
        except Exception as e:
            logger.error(f"Gemini API error: {e}", exc_info=True)
            self.response_text.delete('1.0', "end")
            self.response_text.insert("end", f"❌ Error: {str(e)}")
            self.status_queue.put("Status: Gemini failed")
            self.debug_print(f"❌ Gemini error: {e}")
            self.update_handler_status("gemini", "error")
    
    def generate_tts(self, text):
        """Layer 3 (Guide): Generate TTS audio using Kokoro handler."""
        threading.Thread(target=self._generate_tts_thread, args=(text,), daemon=True).start()
    
    def _generate_tts_thread(self, text):
        """Background TTS generation using KokoroTTS handler."""
        try:
            # Lazy load Kokoro TTS
            if not self.init_kokoro_tts():
                self.debug_print("❌ Kokoro TTS not available")
                self.update_handler_status("kokoro", "error")
                return
            
            self.debug_print("🔊 Generating speech with Kokoro...")
            self.status_queue.put("Status: Generating speech...")
            self.update_handler_status("kokoro", "processing")
            
            # Generate audio
            audio_data = self.kokoro_tts.generate_speech(text)
            
            if audio_data is not None:
                # CRITICAL FIX: Unload pygame music to release file lock (Windows requirement)
                # pygame.mixer.music.load() locks the file until unload() is called
                try:
                    pygame.mixer.music.stop()     # Stop playback first
                    pygame.mixer.music.unload()   # Release file handle (pygame v2.0.0+)
                except:
                    pass  # Ignore if nothing is loaded
                
                # Save to temp file (now safe to overwrite)
                import scipy.io.wavfile as wavfile
                wavfile.write(TEMP_TTS_OUTPUT_FILE, 24000, audio_data)
                self.last_tts_file = TEMP_TTS_OUTPUT_FILE
                
                self.debug_print("✅ Speech generated, playing...")
                self.status_queue.put("Status: Playing audio...")
                self.update_handler_status("kokoro", "active")
                
                # Play audio
                self.play_audio_file(TEMP_TTS_OUTPUT_FILE)
                self.status_queue.put("Status: Ready")
            else:
                self.debug_print("❌ TTS generation failed")
                self.status_queue.put("Status: TTS failed")
                self.update_handler_status("kokoro", "error")
            
        except Exception as e:
            logger.error(f"TTS generation failed: {e}", exc_info=True)
            self.debug_print(f"❌ TTS error: {e}")
            self.status_queue.put("Status: TTS failed")
            self.update_handler_status("kokoro", "error")
    
    def replay_last_tts(self):
        """Replay last generated TTS audio."""
        if self.last_tts_file and os.path.exists(self.last_tts_file):
            self.play_audio_file(self.last_tts_file)
        else:
            self.debug_print("⚠️ No TTS file to replay")
    
    def play_audio_file(self, file_path):
        """Play audio file using pygame."""
        try:
            pygame.mixer.music.load(file_path)
            
            # Set up TTS playback tracking
            self.tts_playing = True
            self.tts_interrupt_requested = False  # Clear any pending interrupt
            pygame.mixer.music.set_endevent(self.TTS_END_EVENT)
            
            pygame.mixer.music.play()
            self.debug_print(f"🔊 Playing: {file_path}")
        except Exception as e:
            logger.error(f"Audio playback failed: {e}")
            self.debug_print(f"❌ Playback error: {e}")
            self.tts_playing = False
    
    def poll_pygame_events(self):
        """Poll pygame events to detect TTS playback completion and handle interrupts."""
        try:
            # Handle TTS interrupt request from VAD thread (thread-safe)
            if self.tts_interrupt_requested and self.tts_playing:
                pygame.mixer.music.stop()
                self.tts_playing = False
                self.tts_interrupt_requested = False
                self.debug_print("🛑 TTS INTERRUPTED by voice input")
                logger.info("TTS playback interrupted successfully")
            
            for event in pygame.event.get():
                if event.type == self.TTS_END_EVENT:
                    self.tts_playing = False
                    self.tts_interrupt_requested = False  # Clear any pending interrupt
                    self.debug_print("✅ TTS playback finished naturally")
                    logger.debug("TTS playback completed")
        except Exception as e:
            logger.debug(f"Pygame event polling error: {e}")
    
    def debug_print(self, msg):
        """Thread-safe debug console logging."""
        def _update():
            try:
                timestamp = time.strftime('%H:%M:%S')
                self.debug_text.insert("end", f"[{timestamp}] {msg}\n")
                self.debug_text.see("end")
            except Exception as e:
                # Silently fail if GUI is not ready
                logger.debug(f"Debug print failed: {e}")
        
        try:
            # Always use .after() for thread safety
            self.window.after(0, _update)
        except Exception:
            # If .after() fails, just log to console
            logger.info(msg)
    
    def learn_from_maps(self):
        """🗺️ Adaptive Learning: Manually add POI objects to Layer 1 vocabulary."""
        if not self.dual_yolo:
            self.debug_print("❌ Dual YOLO not initialized")
            return
        
        # Prompt user for POI type
        from tkinter import simpledialog
        poi_input = simpledialog.askstring(
            "Learn from Maps",
            "Enter place types (comma-separated):\nExamples: Starbucks, Bank, Hospital, Restaurant"
        )
        
        if not poi_input:
            return
        
        try:
            poi_list = [poi.strip() for poi in poi_input.split(",")]
            learned_objects = self.dual_yolo.add_maps_objects(poi_list)
            
            if learned_objects:
                self.debug_print(f"🗺️ Learned from Maps: {', '.join(learned_objects)}")
                self.debug_print(f"   Total vocabulary: {self.dual_yolo.learner.prompt_manager.get_class_count()} classes")
            else:
                self.debug_print("⚠️ No new objects learned (already in vocabulary)")
        except Exception as e:
            logger.error(f"Maps learning error: {e}")
            self.debug_print(f"❌ Maps learning failed: {e}")
    
    def on_closing(self):
        """Graceful shutdown."""
        logger.info("🛑 Shutting down Project-Cortex GUI")
        self.debug_print("👋 Closing application...")
        
        # Stop voice activation if active
        if self.vad_listening:
            self.stop_voice_activation()
        
        # Stop spatial audio if active
        if self.spatial_audio:
            self.stop_spatial_audio()
        
        self.stop_event.set()
        
        if self.cap:
            self.cap.release()
        if self.picamera2:
            self.picamera2.stop()
        
        pygame.mixer.quit()
        self.window.destroy()


def main():
    """Main entry point for Project-Cortex GUI."""
    # Initialize CustomTkinter
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    
    root = ctk.CTk()
    app = ProjectCortexGUI(root)
    root.mainloop()


# --- Main Entry Point ---
if __name__ == "__main__":
    main()
