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
import google.generativeai as genai
import sounddevice as sd
from scipy.io.wavfile import write as write_wav
from gradio_client import Client as GradioClient, file as gradio_file
from ultralytics import YOLO
from dotenv import load_dotenv
import logging
import sys
import warnings

# Import our custom AI handlers
from layer1_reflex.whisper_handler import WhisperSTT
from layer1_reflex.kokoro_handler import KokoroTTS
from layer1_reflex.vad_handler import VADHandler  # NEW: Voice Activity Detection
from layer2_thinker.gemini_tts_handler import GeminiTTS  # NEW: Gemini 2.5 Flash TTS (replaces old GeminiVision)
from layer3_guide.router import IntentRouter

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
AUDIO_FILE_FOR_WHISPER = "temp_mic_input.wav"
TEMP_TTS_OUTPUT_FILE = "temp_tts_output.mp3"

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
        self.model = None  # YOLO model
        self.classes = {}  # YOLO class names
        self.last_detections = "nothing detected"
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
        self.gemini_tts = None   # NEW: Gemini 2.5 Flash TTS (image + prompt -> audio)
        self.vad_handler = None  # NEW: Voice Activity Detection handler
        
        # --- Voice Activation State ---
        self.voice_activation_enabled = ctk.BooleanVar(value=False)
        self.vad_listening = False
        self.vad_speech_buffer = None
        
        # --- Build UI ---
        self.init_ui()
        
        # --- Initialize Systems ---
        self.init_audio()
        self.init_yolo()
        
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
        self.create_status_indicator("GEMINI-TTS", "#555555")  # NEW: Gemini 2.5 TTS indicator
        self.create_status_indicator("KOKORO", "#555555")  # Kept for backward compatibility

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
        """Lazy initialize Kokoro TTS (called on first TTS request)."""
        if self.kokoro_tts is None:
            try:
                self.update_handler_status("kokoro", "processing")
                self.debug_print("⏳ Loading Kokoro TTS...")
                self.kokoro_tts = KokoroTTS(lang_code="a", default_voice="af_alloy")
                self.kokoro_tts.load_pipeline()
                self.debug_print("✅ Kokoro TTS ready")
                logger.info("✅ Kokoro TTS initialized")
                self.update_handler_status("kokoro", "active")
            except Exception as e:
                logger.error(f"❌ Kokoro TTS init failed: {e}")
                self.debug_print(f"❌ Kokoro failed: {e}")
                self.update_handler_status("kokoro", "error")
                self.kokoro_tts = None
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
    
    def on_canvas_resize(self, event):
        """Handles canvas resize for video scaling."""
        self.canvas_width = event.width
        self.canvas_height = event.height
    
    def init_yolo(self):
        """Loads YOLO model in background thread."""
        self.status_queue.put("Status: Loading YOLO model...")
        self.update_handler_status("yolo", "processing")
        threading.Thread(target=self._init_yolo_thread, daemon=True).start()
    
    def _init_yolo_thread(self):
        """Background YOLO model loading with forced CPU inference."""
        try:
            if not os.path.exists(YOLO_MODEL_PATH):
                logger.error(f"❌ Model not found: {YOLO_MODEL_PATH}")
                self.status_queue.put(f"Status: ERROR - Model not found")
                self.debug_print(f"❌ FATAL: {YOLO_MODEL_PATH} not found")
                self.update_handler_status("yolo", "error")
                return
            
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
            
            logger.info(f"Loading YOLO on device: {device}")
            self.debug_print(f"🔄 Loading YOLO {os.path.basename(YOLO_MODEL_PATH)} on {device}...")
            
            # Load model with explicit device specification
            self.model = YOLO(YOLO_MODEL_PATH)
            self.yolo_device = device  # Store actual device for inference
            # Note: Ultralytics automatically uses specified device during inference
            self.classes = self.model.names
            
            # Run warm-up inference to verify model works and load to GPU memory
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            self.model(dummy, verbose=False, device=device)
            
            self.status_queue.put(f"Status: YOLO ready ({device})")
            self.debug_print(f"✅ YOLO loaded: {os.path.basename(YOLO_MODEL_PATH)} on {device}")
            logger.info(f"✅ YOLO model loaded successfully on {device}")
            self.update_handler_status("yolo", "active")
            
        except Exception as e:
            logger.error(f"❌ YOLO loading failed: {e}", exc_info=True)
            self.status_queue.put("Status: YOLO FAILED")
            self.debug_print(f"❌ ERROR: {e}")
            self.update_handler_status("yolo", "error")
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
        Layer 1 (Reflex): Real-time object detection with CPU inference.
        Processes frames with YOLO and puts annotated frames in queue.
        """
        while not self.stop_event.is_set():
            if self.model is None:
                time.sleep(0.5)
                continue
            
            try:
                frame = self.frame_queue.get(timeout=1)
                
                # Run YOLO inference with verified device
                results = self.model(frame, conf=YOLO_CONFIDENCE, verbose=False, device=self.yolo_device)
                annotated_frame = results[0].plot()
                
                # Extract detections (only above confidence threshold)
                detections = []
                for box in results[0].boxes:
                    confidence = float(box.conf)
                    if confidence > YOLO_CONFIDENCE:  # Explicit threshold check
                        class_id = int(box.cls)
                        class_name = self.classes[class_id]
                        detections.append(f"{class_name} ({confidence:.2f})")
                
                detections_str = ", ".join(sorted(set(detections))) or "nothing"
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
                logger.error(f"YOLO processing error: {e}")
                time.sleep(1)
    
    def update_video(self):
        """Gets an annotated frame from the queue and displays it on the canvas."""
        try:
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
        self.debug_print("🗣️ Speech detected - Recording...")
        self.status_queue.put("Status: LISTENING...")
        self.update_handler_status("vad", "processing")
    
    def on_vad_speech_end(self, audio_data):
        """Callback when VAD detects speech end."""
        try:
            duration_ms = len(audio_data) / 16000 * 1000
            self.debug_print(f"🎤 Speech ended: {duration_ms:.0f}ms")
            
            # Save audio to file for Whisper
            # Convert from float32 [-1, 1] to int16
            audio_int16 = (audio_data * 32767).astype(np.int16)
            write_wav(AUDIO_FILE_FOR_WHISPER, 16000, audio_int16)
            self.debug_print(f"💾 VAD audio saved: {AUDIO_FILE_FOR_WHISPER}")
            
            # Process audio through the same pipeline as manual recording
            self.process_recorded_audio()
            
            # Reset VAD status
            self.update_handler_status("vad", "active")
            self.status_queue.put("Status: VOICE-ACTIVATED MODE")
            
        except Exception as e:
            logger.error(f"VAD speech end processing failed: {e}")
            self.debug_print(f"❌ VAD processing error: {e}")
            self.update_handler_status("vad", "error")
    
    def init_vad(self):
        """Initialize VAD handler (lazy loading)."""
        if self.vad_handler is not None:
            return True
        
        try:
            self.debug_print("⏳ Loading Silero VAD...")
            self.update_handler_status("vad", "loading")
            
            # Create VAD handler with callbacks
            self.vad_handler = VADHandler(
                sample_rate=16000,
                chunk_size=512,  # 32ms at 16kHz
                threshold=0.5,   # Balanced sensitivity
                min_speech_duration_ms=500,  # Minimum 0.5s of speech
                min_silence_duration_ms=700,  # 0.7s silence to end
                padding_duration_ms=300,  # 300ms padding before/after
                on_speech_start=self.on_vad_speech_start,
                on_speech_end=self.on_vad_speech_end
            )
            
            if not self.vad_handler.load_model():
                raise Exception("Failed to load VAD model")
            
            self.update_handler_status("vad", "inactive")
            self.debug_print("✅ Silero VAD loaded")
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
        """Background pipeline: Whisper -> Router -> Layer Handler."""
        try:
            # 1. Transcribe with Whisper
            if not self.init_whisper_stt():
                self.debug_print("❌ Whisper not available")
                self.update_handler_status("whisper", "error")
                return
            
            self.debug_print("🔄 Transcribing...")
            transcribed_text = self.whisper_stt.transcribe_file(AUDIO_FILE_FOR_WHISPER)
            
            if not transcribed_text or not transcribed_text.strip():
                self.debug_print("⚠️ Empty transcription")
                self.status_queue.put("Status: Transcription empty")
                self.update_handler_status("whisper", "active")
                return

            self.debug_print(f"📝 User said: '{transcribed_text}'")
            self.input_entry.delete(0, "end")
            self.input_entry.insert(0, transcribed_text)
            self.update_handler_status("whisper", "active")
            
            # 2. Route Intent
            target_layer = self.router.route(transcribed_text)
            layer_desc = self.router.get_layer_description(target_layer)
            self.debug_print(f"🧠 Routing to {layer_desc}")
            self.status_queue.put(f"Status: {layer_desc}")
            
            # 3. Execute Layer Logic
            if target_layer == "layer1":
                self._execute_layer1_reflex(transcribed_text)
            elif target_layer == "layer2":
                self._execute_layer2_thinker(transcribed_text)
            elif target_layer == "layer3":
                self._execute_layer3_guide(transcribed_text)
            
        except Exception as e:
            logger.error(f"Audio pipeline failed: {e}", exc_info=True)
            self.debug_print(f"❌ Pipeline error: {e}")
            self.status_queue.put("Status: Error")
            self.update_handler_status("whisper", "error")

    def _execute_layer1_reflex(self, text):
        """Layer 1: Local Object Detection Report."""
        self.debug_print("⚡ Layer 1 (Reflex) Activated")
        
        # Get current detections
        detections = self.last_detections
        if not detections or detections == "nothing":
            response = "I don't see anything specific right now."
        else:
            # Simple sentence structure logic
            items = detections.split(", ")
            unique_items = set([i.split(" (")[0] for i in items])
            response = f"I see {', '.join(unique_items)}."
        
        self.response_text.delete('1.0', "end")
        self.response_text.insert("end", f"[Layer 1] {response}")
        self.generate_tts(response)

    def _execute_layer2_thinker(self, text):
        """Layer 2: Cloud Gemini Vision."""
        self.debug_print("☁️ Layer 2 (Thinker) Activated")
        self.send_query()  # Re-use existing Gemini logic

    def _execute_layer3_guide(self, text):
        """Layer 3: Navigation & Memory (Using Gemini TTS for spoken guidance)."""
        self.debug_print("🗺️ Layer 3 (Guide) Activated")
        
        # For now, we use Gemini TTS for navigation guidance
        # In the future, this would connect to GPS/Maps API
        
        if not self.init_gemini_tts():
            self.debug_print("❌ Gemini TTS not available for Layer 3")
            return

        prompt = f"""You are the Navigation Guide for a blind user.
User Query: "{text}"
Current Visual Context: {self.last_detections}

If the user asks for location, simulate a GPS response (e.g., "You are currently at your desk").
If the user asks to go somewhere, provide general direction based on the visual context (e.g., "I see a door to your left").
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

    def _transcribe_thread(self):
        """Deprecated: Old transcription thread."""
        pass
    
    def send_query(self):
        """Layer 2 (Thinker): Send query to Gemini 2.5 Flash TTS with video frame (image + prompt -> audio)."""
        query = self.input_entry.get().strip()
        if not query:
            messagebox.showwarning("Input Error", "Please enter a query")
            return
        
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
                self.play_audio(audio_path)
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
                # Save to temp file
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
            pygame.mixer.music.play()
            self.debug_print(f"🔊 Playing: {file_path}")
        except Exception as e:
            logger.error(f"Audio playback failed: {e}")
            self.debug_print(f"❌ Playback error: {e}")
    
    def debug_print(self, msg):
        """Thread-safe debug console logging."""
        def _update():
            timestamp = time.strftime('%H:%M:%S')
            self.debug_text.insert("end", f"[{timestamp}] {msg}\n")
            self.debug_text.see("end")
        
        if self.window.winfo_exists():
            self.window.after(0, _update)
    
    def on_closing(self):
        """Graceful shutdown."""
        logger.info("🛑 Shutting down Project-Cortex GUI")
        self.debug_print("👋 Closing application...")
        
        # Stop voice activation if active
        if self.vad_listening:
            self.stop_voice_activation()
        
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
