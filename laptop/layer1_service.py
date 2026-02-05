import logging
import threading
import time
import cv2
import numpy as np
import torch
from ultralytics import YOLO
from typing import Optional, Dict, Any, Callable

logger = logging.getLogger(__name__)

class Layer1Service:
    """
    Offloaded Layer 1 (Learner) running on Laptop GPU.
    Consumes frames from VideoReceiver and runs YOLOE inference.
    
    Optimizations:
    - FP16 (half precision) for faster inference
    - Explicit GPU placement
    - cuDNN benchmark mode for optimal kernels
    """
    def __init__(self, model_path: str = "yolov8n.pt", device: str = "cuda:0", confidence: float = 0.5, use_half: bool = True):
        self.model_path = model_path
        self.device = device if torch.cuda.is_available() else "cpu"
        self.confidence = confidence
        self.use_half = use_half and (self.device != "cpu")  # FP16 only on GPU
        self.running = False
        self.model = None
        self.thread = None
        
        # State
        self.latest_frame = None
        self.latest_results = []
        self.processing = False
        
        # Callbacks
        self.on_result: Optional[Callable[[Dict], None]] = None

    def initialize(self):
        """Load model with GPU optimizations"""
        try:
            # Check for CUDA availability and user preference
            if "cuda" in self.device and not torch.cuda.is_available():
                logger.warning(f"⚠️  CUDA requested but not available, falling back to CPU")
                self.device = "cpu"
                self.use_half = False

            if "cuda" in self.device:
                try:
                    gpu_name = torch.cuda.get_device_name(0)
                    logger.info(f"🚀 Using GPU: {gpu_name} (CUDA {torch.version.cuda})")
                    # Enable cuDNN benchmark for optimal convolution algorithms
                    torch.backends.cudnn.benchmark = True
                except Exception as e:
                    logger.warning(f"⚠️ Failed to initialize CUDA: {e}. Falling back to CPU.")
                    self.device = "cpu"
                    self.use_half = False
            
            if self.device == "cpu":
                logger.info("💻 Using CPU for inference")
                self.use_half = False

            logger.info(f"🚀 Loading Layer 1 Model: {self.model_path} on {self.device}")
            
            # Allow loading local file if it exists in current dir or project root
            import os
            if not os.path.exists(self.model_path):
                possible_path = os.path.join("models", self.model_path)
                if os.path.exists(possible_path):
                    self.model_path = possible_path
                    logger.info(f"📁 Found model in {self.model_path}")
            
            self.model = YOLO(self.model_path)
            
            # Explicitly move model to device
            self.model.to(self.device)
            logger.info(f"✅ Model moved to {self.device}")
            
            if self.use_half and self.device != "cpu":
                logger.info("✅ FP16 (half precision) enabled - faster inference")
            
            # Warmup inference to initialize CUDA kernels
            logger.info("🔥 Warming up model...")
            dummy_frame = np.zeros((640, 640, 3), dtype=np.uint8)
            for _ in range(3):
                self.model(dummy_frame, conf=self.confidence, device=self.device, verbose=False, half=self.use_half)
            logger.info("✅ Model warmed up and ready")
            
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")

    def start(self):
        """Start inference loop"""
        if not self.model:
            self.initialize()
            
        self.running = True
        self.thread = threading.Thread(target=self._inference_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)

    def process_frame(self, frame: np.ndarray):
        """Receive frame (called by VideoReceiver)"""
        # Only update if we are not falling behind?
        # Actually ZMQ Conflate handles network lag.
        # But if inference is slow, we should just overwrite the 'latest_frame'
        # and let the inference loop pick it up.
        self.latest_frame = frame

    def _inference_loop(self):
        """Continuous inference with GPU optimizations"""
        while self.running:
            if self.latest_frame is None:
                time.sleep(0.01)
                continue
                
            frame = self.latest_frame # Get reference
            
            try:
                start_t = time.time()
                
                start_time = time.time()
                # Use half precision if enabled for faster inference
                results = self.model(frame, conf=self.confidence, device=self.device, verbose=False, half=self.use_half)
                inference_time = (time.time() - start_time) * 1000
                
                # logger.debug(f"Inf: {inference_time:.1f}ms | Dets: {len(results[0].boxes)}")
                
                # Parse Results
                parsed_results = []
                frame_h, frame_w = frame.shape[:2]
                
                for r in results:
                    boxes = r.boxes
                    for box in boxes:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                        cls = int(box.cls[0])
                        conf = float(box.conf[0])
                        name = self.model.names[cls]
                        
                        # Calculate normalized coordinates
                        nx1 = round(x1 / frame_w, 4)
                        ny1 = round(y1 / frame_h, 4)
                        nx2 = round(x2 / frame_w, 4)
                        ny2 = round(y2 / frame_h, 4)
                        
                        parsed_results.append({
                            "class": name,
                            "confidence": conf,
                            # Normalized bbox for Protocol/RPi5
                            "bbox": {"x1": nx1, "y1": ny1, "x2": nx2, "y2": ny2},
                            # Absolute coords for Local UI
                            "x1": int(x1),
                            "y1": int(y1),
                            "x2": int(x2),
                            "y2": int(y2),
                            "layer": "layer1"
                        })
                
                # CRITICAL FIX: Update latest_results so video frame handler can access them
                self.latest_results = parsed_results
                
                inference_time = (time.time() - start_t) * 1000
                
                # Emit result
                if self.on_result:
                    self.on_result({
                        "type": "DETECTION",
                        "layer": "layer1",
                        "data": parsed_results,
                        "inference_time_ms": inference_time
                    })
                    
            except Exception as e:
                logger.error(f"Inference Error: {e}")
                
            # Limit FPS? No, run as fast as possible.

    def set_model(self, model_path: str):
        """Hot-swap model"""
        logger.info(f"🔄 Switching model to: {model_path}")
        self.model_path = model_path
        # Reload
        self.initialize()
