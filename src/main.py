"""
Project-Cortex v2.0 - Main Application Entry Point (Headless Mode for Raspberry Pi)

This is the orchestration layer that coordinates all 3 AI layers without GUI.
Optimized for Raspberry Pi 5 deployment with IMX415 camera.

Architecture:
- Layer 1 (Reflex): Local YOLO object detection + Whisper STT + Kokoro TTS
- Layer 2 (Thinker): Cloud-based scene analysis via Gemini Vision API
- Layer 3 (Guide): Audio feedback, button control, and optional dashboard

Usage:
  python src/main.py                    # Run headless mode (RPi)
  python src/cortex_gui.py              # Run GUI mode (laptop dev)

Author: Haziq (@IRSPlays)
Date: November 17, 2025
Competition: Young Innovators Awards (YIA) 2026
"""

import logging
import sys
import signal
import time
import os
import threading
import queue
from typing import NoReturn, Optional
import numpy as np
import cv2
from dotenv import load_dotenv

# Import handler modules
try:
    from layer1_reflex.whisper_handler import WhisperSTT
    from layer1_reflex.kokoro_handler import KokoroTTS
    from layer2_thinker.gemini_handler import GeminiVision
    from ultralytics import YOLO
    HANDLERS_AVAILABLE = True
except ImportError as e:
    logging.error(f"Failed to import handlers: {e}")
    HANDLERS_AVAILABLE = False

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('cortex.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Configuration from environment
YOLO_MODEL_PATH = os.getenv('YOLO_MODEL_PATH', 'models/yolo11s.pt')  # Use smaller model for RPi
YOLO_CONFIDENCE = float(os.getenv('YOLO_CONFIDENCE', '0.5'))
YOLO_DEVICE = os.getenv('YOLO_DEVICE', 'cpu')  # CPU for Raspberry Pi
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')


class ProjectCortex:
    """Main headless application class orchestrating all AI layers for Raspberry Pi."""
    
    def __init__(self, use_picamera: bool = True):
        """
        Initialize all subsystems.
        
        Args:
            use_picamera: If True, use Raspberry Pi camera (IMX415). If False, use USB webcam.
        """
        logger.info("🧠 Project-Cortex v2.0 Initializing (Headless Mode)...")
        
        if not HANDLERS_AVAILABLE:
            raise RuntimeError("❌ AI handlers not available. Check imports.")
        
        # Camera configuration
        self.use_picamera = use_picamera
        self.camera = None
        self.picamera2 = None
        
        # AI Handlers (lazy loaded)
        self.yolo_model: Optional[YOLO] = None
        self.whisper_stt: Optional[WhisperSTT] = None
        self.kokoro_tts: Optional[KokoroTTS] = None
        self.gemini_vision: Optional[GeminiVision] = None
        
        # State
        self.running = False
        self.stop_event = threading.Event()
        self.frame_queue = queue.Queue(maxsize=2)
        self.detection_queue = queue.Queue()
        self.last_detections = "nothing detected"
        self.latest_frame = None
        
        # Initialize systems
        self._init_camera()
        self._init_yolo()
        self._init_kokoro()  # Load TTS early for startup message
        
        logger.info("✅ Project-Cortex initialized")
    
    def _init_camera(self):
        """Initialize camera (Raspberry Pi IMX415 or USB webcam)."""
        if self.use_picamera:
            try:
                from picamera2 import Picamera2
                logger.info("📹 Initializing IMX415 camera...")
                self.picamera2 = Picamera2()
                config = self.picamera2.create_preview_configuration(
                    main={"size": (1920, 1080), "format": "RGB888"}
                )
                self.picamera2.configure(config)
                self.picamera2.start()
                logger.info("✅ IMX415 camera ready")
            except Exception as e:
                logger.error(f"❌ IMX415 init failed: {e}, falling back to webcam")
                self.use_picamera = False
                self._init_webcam()
        else:
            self._init_webcam()
    
    def _init_webcam(self):
        """Initialize USB webcam."""
        logger.info("📹 Initializing USB webcam...")
        self.camera = cv2.VideoCapture(0)
        if self.camera.isOpened():
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            logger.info("✅ USB webcam ready")
        else:
            raise RuntimeError("❌ Failed to open webcam")
    
    def _init_yolo(self):
        """Initialize YOLO model."""
        try:
            logger.info(f"🔄 Loading YOLO model: {YOLO_MODEL_PATH}")
            self.yolo_model = YOLO(YOLO_MODEL_PATH)
            # Warm-up inference
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            self.yolo_model(dummy, verbose=False, device=YOLO_DEVICE)
            logger.info(f"✅ YOLO model loaded on {YOLO_DEVICE}")
        except Exception as e:
            logger.error(f"❌ YOLO init failed: {e}")
            raise
    
    def _init_whisper(self):
        """Lazy initialize Whisper STT."""
        if self.whisper_stt is None:
            logger.info("🎤 Loading Whisper STT...")
            self.whisper_stt = WhisperSTT(model_size="base", device=YOLO_DEVICE)
            self.whisper_stt.load_model()
            logger.info("✅ Whisper STT ready")
    
    def _init_kokoro(self):
        """Initialize Kokoro TTS."""
        if self.kokoro_tts is None:
            logger.info("🔊 Loading Kokoro TTS...")
            self.kokoro_tts = KokoroTTS(lang_code="a", default_voice="af_alloy")
            self.kokoro_tts.load_pipeline()
            logger.info("✅ Kokoro TTS ready")
            # Startup message
            self.speak("Project Cortex initialized and ready")
    
    def _init_gemini(self):
        """Lazy initialize Gemini Vision."""
        if self.gemini_vision is None:
            logger.info("🧠 Loading Gemini Vision...")
            self.gemini_vision = GeminiVision(api_key=GOOGLE_API_KEY)
            self.gemini_vision.initialize()
            logger.info("✅ Gemini Vision ready")
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture a frame from the camera."""
        try:
            if self.use_picamera:
                frame = self.picamera2.capture_array()
                # Convert RGB to BGR for OpenCV compatibility
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                return frame
            else:
                ret, frame = self.camera.read()
                return frame if ret else None
        except Exception as e:
            logger.error(f"Frame capture error: {e}")
            return None
    
    def detect_objects(self, frame: np.ndarray) -> str:
        """Run YOLO detection on frame."""
        try:
            results = self.yolo_model(frame, conf=YOLO_CONFIDENCE, verbose=False, device=YOLO_DEVICE)
            detections = []
            for box in results[0].boxes:
                confidence = float(box.conf)
                if confidence > YOLO_CONFIDENCE:
                    class_id = int(box.cls)
                    class_name = self.yolo_model.names[class_id]
                    detections.append(f"{class_name} ({confidence:.2f})")
            
            detections_str = ", ".join(sorted(set(detections))) or "nothing"
            return detections_str
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return "error"
    
    def speak(self, text: str, voice: str = "af_alloy"):
        """Generate and play TTS audio."""
        try:
            if self.kokoro_tts is None:
                logger.warning("Kokoro TTS not initialized")
                return
            
            logger.info(f"🔊 Speaking: '{text[:50]}...'")
            audio_data = self.kokoro_tts.generate_speech(text, voice=voice)
            
            if audio_data is not None:
                # Save and play audio (simplified for headless mode)
                import scipy.io.wavfile as wavfile
                temp_file = "temp_tts.wav"
                wavfile.write(temp_file, 24000, audio_data)
                
                # Play audio using system command (works on Raspberry Pi)
                os.system(f"aplay {temp_file} >/dev/null 2>&1")
                logger.info("✅ Speech played")
            else:
                logger.error("❌ TTS generation failed")
        except Exception as e:
            logger.error(f"Speech error: {e}")
    
    def start(self) -> None:
        """Start the main application loop."""
        logger.info("🚀 Starting Project-Cortex headless mode...")
        self.running = True
        
        # Start background threads
        threading.Thread(target=self._capture_thread, daemon=True).start()
        threading.Thread(target=self._detection_thread, daemon=True).start()
        
        try:
            while self.running:
                # Main loop: Check for button presses, process detections, etc.
                # For now, just maintain the loop
                time.sleep(0.1)
                
                # Log detections periodically
                if not self.detection_queue.empty():
                    self.last_detections = self.detection_queue.get()
                    logger.info(f"👁️  Detected: {self.last_detections}")
                
        except KeyboardInterrupt:
            logger.info("⚠️  Received shutdown signal")
            self.stop()
    
    def _capture_thread(self):
        """Background thread for camera capture."""
        while not self.stop_event.is_set():
            try:
                frame = self.capture_frame()
                if frame is not None:
                    self.latest_frame = frame
                    if not self.frame_queue.full():
                        self.frame_queue.put(frame)
                else:
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"Capture thread error: {e}")
                time.sleep(1)
    
    def _detection_thread(self):
        """Background thread for YOLO detection."""
        while not self.stop_event.is_set():
            try:
                frame = self.frame_queue.get(timeout=1)
                detections = self.detect_objects(frame)
                self.detection_queue.put(detections)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Detection thread error: {e}")
                time.sleep(0.5)
            
    def stop(self) -> None:
        """Gracefully shutdown all subsystems."""
        logger.info("🛑 Shutting down Project-Cortex...")
        self.running = False
        self.stop_event.set()
        
        # Stop camera
        if self.camera:
            try:
                self.camera.stop()
                logger.info("📷 Camera stopped")
            except:
                pass
        
        # Close webcam
        if self.webcam:
            self.webcam.release()
            logger.info("📹 Webcam released")
        
        logger.info("✅ Shutdown complete")
        

def signal_handler(signum, frame) -> NoReturn:
    """Handle system signals for graceful shutdown."""
    logger.warning(f"Received signal {signum}")
    sys.exit(0)


def main() -> None:
    """Application entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run application
    app = ProjectCortex()
    
    try:
        app.start()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
