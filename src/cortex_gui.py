"""
Project-Cortex v2.0 - Main GUI Application (Laptop Development Version)

This is the laptop-first development version that uses:
- USB Webcam (instead of IMX415)
- Tkinter GUI for testing
- Same 3-Layer AI architecture as production
- Easy deployment to RPi 5 via VS Code Remote SSH

Author: Haziq (@IRSPlays)
Date: November 16, 2025
"""

import os
import cv2
import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import queue
import time
import traceback
import numpy as np
import torch
from PIL import Image, ImageTk
import google.generativeai as genai
import pygame
import sounddevice as sd
from scipy.io.wavfile import write as write_wav
from gradio_client import Client as GradioClient, file as gradio_file
from ultralytics import YOLO
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cortex_gui.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Configuration from Environment ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')
GEMINI_MODEL_ID = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash-latest')
MURF_API_KEY = os.getenv('MURF_API_KEY', '')
WHISPER_API_URL = os.getenv('WHISPER_MODEL', 'hf-audio/whisper-large-v3')
YOLO_MODEL_PATH = os.getenv('YOLO_MODEL_PATH', 'models/yolo11s.pt')
YOLO_CONFIDENCE = float(os.getenv('YOLO_CONFIDENCE', '0.5'))

# Temporary files
AUDIO_FILE_FOR_WHISPER = "temp_mic_input.wav"
TEMP_TTS_OUTPUT_FILE = "temp_tts_output.mp3"

# Camera source: 0 for webcam, will be configurable for RPi IMX415
CAMERA_SOURCE = 0  # USB webcam
USE_PICAMERA = False  # Set to True when running on RPi 5


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
        self.window.geometry("1280x800")
        
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
        self.selected_input_device = tk.StringVar(self.window)
        self.selected_output_device = tk.StringVar(self.window)
        self.last_used_output_device = None
        self.recording_active = False
        self.audio_queue = queue.Queue()
        self.last_tts_file = None
        
        # --- Gemini AI ---
        if GOOGLE_API_KEY:
            genai.configure(api_key=GOOGLE_API_KEY)
            logger.info("✅ Gemini API configured")
        else:
            logger.warning("⚠️ No GOOGLE_API_KEY found in .env")
        
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
        self.window.configure(bg='#1e1e1e')
        
        # --- Top Frame: Status ---
        top_frame = tk.Frame(self.window, bg='#1e1e1e')
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.status_label = tk.Label(
            top_frame, 
            text="Status: Initializing...", 
            fg="#00ff00", 
            bg='#1e1e1e',
            font=('Consolas', 11, 'bold')
        )
        self.status_label.pack(side=tk.LEFT)
        
        camera_label = tk.Label(
            top_frame,
            text=f"📹 Camera: {'RPi IMX415' if USE_PICAMERA else 'USB Webcam'}",
            fg="#00aaff",
            bg='#1e1e1e',
            font=('Consolas', 10)
        )
        camera_label.pack(side=tk.RIGHT)
        
        # --- Video Frame ---
        video_frame = tk.Frame(self.window, bg='#000000')
        video_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.canvas = tk.Canvas(video_frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        
        # --- Controls Frame ---
        controls_frame = tk.Frame(self.window, bg='#2d2d2d')
        controls_frame.pack(fill=tk.BOTH, padx=10, pady=5)
        
        # Query Section
        query_frame = tk.Frame(controls_frame, bg='#2d2d2d')
        query_frame.pack(fill=tk.X, pady=5, padx=5)
        
        tk.Label(query_frame, text="💬 Ask Gemini:", bg='#2d2d2d', fg='white', font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=5)
        self.input_entry = tk.Entry(query_frame, font=('Arial', 10), bg='#3c3c3c', fg='white', insertbackground='white')
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.input_entry.bind('<Return>', lambda e: self.send_query())
        
        self.send_query_btn = tk.Button(
            query_frame, 
            text="Send 🚀", 
            command=self.send_query,
            bg='#007acc',
            fg='white',
            font=('Arial', 10, 'bold'),
            padx=15
        )
        self.send_query_btn.pack(side=tk.RIGHT, padx=5)
        
        # Response Section
        tk.Label(controls_frame, text="🤖 Gemini's Response:", bg='#2d2d2d', fg='white', font=('Arial', 10, 'bold')).pack(anchor=tk.W, padx=5)
        self.response_text = scrolledtext.ScrolledText(
            controls_frame, 
            height=5, 
            wrap=tk.WORD,
            bg='#1e1e1e',
            fg='#00ff00',
            font=('Consolas', 9),
            insertbackground='white'
        )
        self.response_text.pack(fill=tk.X, expand=True, padx=5, pady=2)
        
        # Audio Controls
        audio_frame = tk.Frame(controls_frame, bg='#2d2d2d')
        audio_frame.pack(fill=tk.X, pady=5, padx=5)
        
        self.record_btn = tk.Button(
            audio_frame, 
            text="🎤 Record Voice", 
            command=self.toggle_recording,
            bg='#dc3545',
            fg='white',
            font=('Arial', 10, 'bold'),
            padx=10
        )
        self.record_btn.pack(side=tk.LEFT, padx=5)
        
        self.play_tts_btn = tk.Button(
            audio_frame, 
            text="🔊 Replay TTS", 
            command=self.replay_last_tts,
            bg='#28a745',
            fg='white',
            font=('Arial', 10, 'bold'),
            padx=10
        )
        self.play_tts_btn.pack(side=tk.LEFT, padx=5)
        
        # Audio Device Selection
        tk.Label(audio_frame, text="Input:", bg='#2d2d2d', fg='white').pack(side=tk.LEFT, padx=5)
        self.input_device_menu = tk.OptionMenu(audio_frame, self.selected_input_device, "Loading...")
        self.input_device_menu.config(bg='#3c3c3c', fg='white')
        self.input_device_menu.pack(side=tk.LEFT, padx=2)
        
        tk.Label(audio_frame, text="Output:", bg='#2d2d2d', fg='white').pack(side=tk.LEFT, padx=5)
        self.output_device_menu = tk.OptionMenu(audio_frame, self.selected_output_device, "Loading...")
        self.output_device_menu.config(bg='#3c3c3c', fg='white')
        self.output_device_menu.pack(side=tk.LEFT, padx=2)
        
        tk.Button(
            audio_frame, 
            text="🔄", 
            command=self.populate_audio_devices,
            bg='#6c757d',
            fg='white'
        ).pack(side=tk.LEFT, padx=2)
        
        # Debug Console
        debug_frame = tk.Frame(controls_frame, bg='#2d2d2d')
        debug_frame.pack(fill=tk.BOTH, expand=True, pady=5, padx=5)
        
        tk.Label(debug_frame, text="🔧 Debug Console:", bg='#2d2d2d', fg='white', font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        self.debug_text = scrolledtext.ScrolledText(
            debug_frame, 
            height=4, 
            wrap=tk.WORD,
            bg='#0c0c0c',
            fg='#00ff00',
            font=('Consolas', 8)
        )
        self.debug_text.pack(fill=tk.BOTH, expand=True)
        
        self.debug_print("✅ UI Initialized - Project-Cortex v2.0")
        self.debug_print(f"📂 YOLO Model: {YOLO_MODEL_PATH}")
        self.debug_print(f"🤖 Gemini Model: {GEMINI_MODEL_ID}")
    
    def on_canvas_resize(self, event):
        """Handles canvas resize for video scaling."""
        self.canvas_width = event.width
        self.canvas_height = event.height
    
    def init_yolo(self):
        """Loads YOLO model in background thread."""
        self.status_queue.put("Status: Loading YOLO model...")
        threading.Thread(target=self._init_yolo_thread, daemon=True).start()
    
    def _init_yolo_thread(self):
        """Background YOLO model loading."""
        try:
            if not os.path.exists(YOLO_MODEL_PATH):
                logger.error(f"❌ Model not found: {YOLO_MODEL_PATH}")
                self.status_queue.put(f"Status: ERROR - Model not found")
                self.debug_print(f"❌ FATAL: {YOLO_MODEL_PATH} not found")
                return
            
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            logger.info(f"Loading YOLO on device: {device}")
            self.debug_print(f"🔄 Loading YOLO on {device}...")
            
            self.model = YOLO(YOLO_MODEL_PATH)
            self.model.to(device)
            self.classes = self.model.names
            
            # Test inference
            if device == 'cuda':
                dummy = np.zeros((480, 640, 3), dtype=np.uint8)
                self.model(dummy, verbose=False)
            
            self.status_queue.put(f"Status: YOLO ready ({device})")
            self.debug_print(f"✅ YOLO loaded: {os.path.basename(YOLO_MODEL_PATH)} on {device}")
            logger.info("✅ YOLO model loaded successfully")
            
        except Exception as e:
            logger.error(f"❌ YOLO loading failed: {e}", exc_info=True)
            self.status_queue.put("Status: YOLO FAILED")
            self.debug_print(f"❌ ERROR: {e}")
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
        Layer 1 (Reflex): Real-time object detection.
        Processes frames with YOLO and puts annotated frames in queue.
        """
        while not self.stop_event.is_set():
            if self.model is None:
                time.sleep(0.5)
                continue
            
            try:
                frame = self.frame_queue.get(timeout=1)
                
                # Run YOLO inference
                results = self.model(frame, conf=YOLO_CONFIDENCE, verbose=False)
                annotated_frame = results[0].plot()
                
                # Extract detections
                detections = []
                for box in results[0].boxes:
                    class_id = int(box.cls)
                    class_name = self.classes[class_id]
                    confidence = float(box.conf)
                    detections.append(f"{class_name} ({confidence:.2f})")
                
                detections_str = ", ".join(sorted(set(detections))) or "nothing"
                self.detection_queue.put(detections_str)
                
                # Put annotated frame for UI
                if not self.processed_frame_queue.full():
                    self.processed_frame_queue.put(annotated_frame)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"YOLO processing error: {e}")
                time.sleep(1)
    
    def update_video(self):
        """Updates canvas with annotated video frame."""
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
                    anchor=tk.CENTER
                )
        except queue.Empty:
            pass
        finally:
            self.window.after(self.delay, self.update_video)
    
    def update_status(self):
        """Updates status label from queue."""
        try:
            message = self.status_queue.get_nowait()
            self.status_label.config(text=message)
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
            input_menu = self.input_device_menu["menu"]
            input_menu.delete(0, "end")
            if self.input_devices:
                for name in self.input_devices.keys():
                    input_menu.add_command(
                        label=name, 
                        command=lambda value=name: self.selected_input_device.set(value)
                    )
                default_in = sd.default.device[0]
                default_name = f"{default_in}: {sd.query_devices(default_in)['name']}"
                if default_name in self.input_devices:
                    self.selected_input_device.set(default_name)
                else:
                    self.selected_input_device.set(list(self.input_devices.keys())[0])
            
            # Update output menu
            output_menu = self.output_device_menu["menu"]
            output_menu.delete(0, "end")
            if self.output_devices:
                for name in self.output_devices.keys():
                    output_menu.add_command(
                        label=name, 
                        command=lambda value=name: self.selected_output_device.set(value)
                    )
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
            self.record_btn.config(text="🛑 Stop Recording", bg='#ff4444')
            self.audio_queue = queue.Queue()
            
            threading.Thread(target=self._record_audio_thread, args=(device_id,), daemon=True).start()
            
        except Exception as e:
            logger.error(f"Recording start failed: {e}")
            self.debug_print(f"❌ Recording error: {e}")
            self.recording_active = False
            self.record_btn.config(text="🎤 Record Voice", bg='#dc3545')
    
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
        self.record_btn.config(text="🎤 Record Voice", bg='#dc3545')
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
    
    def process_recorded_audio(self):
        """Layer 3 (Guide): Transcribe audio with Whisper."""
        self.status_queue.put("Status: Transcribing...")
        threading.Thread(target=self._transcribe_thread, daemon=True).start()
    
    def _transcribe_thread(self):
        """Background Whisper transcription."""
        try:
            self.debug_print(f"🔄 Calling Whisper API...")
            client = GradioClient(WHISPER_API_URL)
            
            result = client.predict(
                inputs=gradio_file(AUDIO_FILE_FOR_WHISPER),
                task="transcribe",
                api_name="/predict"
            )
            
            transcribed_text = str(result[0]) if isinstance(result, (list, tuple)) else str(result)
            transcribed_text = transcribed_text.strip()
            
            if transcribed_text:
                self.debug_print(f"📝 Transcribed: '{transcribed_text}'")
                self.input_entry.delete(0, tk.END)
                self.input_entry.insert(0, transcribed_text)
                self.send_query()
            else:
                self.debug_print("⚠️ Empty transcription")
                self.status_queue.put("Status: Transcription empty")
            
        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}", exc_info=True)
            self.debug_print(f"❌ Transcription error: {e}")
            self.status_queue.put("Status: Transcription failed")
    
    def send_query(self):
        """Layer 2 (Thinker): Send query to Gemini with video frame."""
        query = self.input_entry.get().strip()
        if not query:
            messagebox.showwarning("Input Error", "Please enter a query")
            return
        
        if not GOOGLE_API_KEY:
            messagebox.showerror("API Error", "GOOGLE_API_KEY not set in .env file")
            return
        
        if self.latest_frame_for_gemini is None:
            messagebox.showwarning("Video Error", "No video frame available")
            return
        
        self.status_queue.put("Status: Thinking...")
        self.response_text.delete('1.0', tk.END)
        self.response_text.insert(tk.END, "🤔 Gemini is analyzing...\n")
        
        frame_copy = self.latest_frame_for_gemini.copy()
        threading.Thread(target=self._send_query_thread, args=(query, frame_copy), daemon=True).start()
    
    def _send_query_thread(self, query, frame):
        """Background Gemini API call."""
        try:
            # Convert to PIL Image
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(rgb_frame)
            
            # Build context with detections
            context = f"""You are an AI assistant for visually impaired users. 
Current detected objects: {self.last_detections}
User query: {query}

Analyze the image and provide a clear, concise response."""
            
            self.debug_print(f"🔄 Sending to Gemini: '{query[:50]}...'")
            
            model = genai.GenerativeModel(GEMINI_MODEL_ID)
            response = model.generate_content([context, img_pil])
            
            self.response_text.delete('1.0', tk.END)
            self.response_text.insert(tk.END, response.text)
            self.status_queue.put("Status: Response received")
            self.debug_print("✅ Gemini response received")
            
            # TODO: Generate TTS from response
            # self.generate_tts(response.text)
            
        except Exception as e:
            logger.error(f"Gemini API error: {e}", exc_info=True)
            self.response_text.delete('1.0', tk.END)
            self.response_text.insert(tk.END, f"❌ Error: {str(e)}")
            self.status_queue.put("Status: Gemini failed")
            self.debug_print(f"❌ Gemini error: {e}")
    
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
            self.debug_text.insert(tk.END, f"[{timestamp}] {msg}\n")
            self.debug_text.see(tk.END)
        
        if self.window.winfo_exists():
            self.window.after(0, _update)
    
    def on_closing(self):
        """Graceful shutdown."""
        logger.info("🛑 Shutting down Project-Cortex GUI")
        self.debug_print("👋 Closing application...")
        
        self.stop_event.set()
        
        if self.cap:
            self.cap.release()
        if self.picamera2:
            self.picamera2.stop()
        
        pygame.mixer.quit()
        self.window.destroy()


# --- Main Entry Point ---
if __name__ == "__main__":
    root = tk.Tk()
    app = ProjectCortexGUI(root)
    root.mainloop()
