"""
Guardian Worker - Layer 1 Reflex (Safety-Critical YOLO Detection)
===================================================================

This worker is responsible for:
- Real-time object detection using YOLO11n
- Safety-critical hazard detection (vehicles, obstacles)
- PWM vibration motor control via GPIO 18
- Strict <100ms latency requirement

CPU Assignment: Core 1
Model: YOLO11n (smallest, fastest)
Priority: HIGHEST (safety-critical)

Author: Project Cortex Team
Date: 2025
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from workers import BaseWorker, setup_worker_logging
from frame_queue import SharedFrameBuffer, FrameMetadata

# Try to import YOLO
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("Warning: ultralytics not available, GuardianWorker will run in mock mode")

# Try to import GPIO (only available on RPi)
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False


# ============================================================================
# CONSTANTS
# ============================================================================

# YOLO model path (relative to project root)
DEFAULT_MODEL_PATH = "models/yolo11n.pt"

# Safety-critical classes (COCO dataset)
# These trigger immediate vibration alerts
HAZARD_CLASSES = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    16: "dog",
    17: "cat",
    # Add more as needed
}

# Confidence thresholds
MIN_CONFIDENCE = 0.4  # Minimum confidence for detection
HAZARD_CONFIDENCE = 0.5  # Higher threshold for hazard alerts

# GPIO settings
VIBRATION_PIN = 18  # PWM pin for vibration motor
PWM_FREQUENCY = 1000  # Hz

# Vibration intensity levels (duty cycle 0-100)
VIBRATION_OFF = 0
VIBRATION_LOW = 30
VIBRATION_MEDIUM = 60
VIBRATION_HIGH = 100


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Detection:
    """A single object detection."""
    class_id: int
    class_name: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 (normalized)
    is_hazard: bool
    distance_estimate: float  # Rough distance estimate based on bbox size


@dataclass
class GuardianResult:
    """Result from guardian inference."""
    detections: List[Detection]
    hazard_detected: bool
    hazard_level: int  # 0=none, 1=low, 2=medium, 3=high
    vibration_intensity: int  # PWM duty cycle 0-100
    inference_time_ms: float


# ============================================================================
# GUARDIAN WORKER
# ============================================================================

class GuardianWorker(BaseWorker):
    """
    Safety-critical YOLO detection worker.
    
    Runs YOLO11n on Core 1, monitors for hazards, controls vibration motor.
    Target latency: <100ms (safety requirement).
    """
    
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        frame_buffer_name: str = "cortex_frames",
        enable_gpio: bool = True,
        log_level: int = logging.INFO
    ):
        """
        Initialize the guardian worker.
        
        Args:
            model_path: Path to YOLO model file
            frame_buffer_name: Name of shared frame buffer
            enable_gpio: Whether to enable GPIO for vibration motor
            log_level: Logging level
        """
        super().__init__(
            name="Guardian",
            cpu_core=1,  # Dedicated core for safety-critical task
            frame_buffer_name=frame_buffer_name,
            worker_id=1,  # Worker ID for marking processed frames
            log_level=log_level
        )
        
        self.model_path = model_path
        self.enable_gpio = enable_gpio and GPIO_AVAILABLE
        
        # Will be set in setup()
        self.model: Optional[Any] = None
        self.pwm: Optional[Any] = None
        
        # State
        self.last_hazard_time = 0.0
        self.consecutive_hazards = 0
    
    def setup(self) -> None:
        """Load YOLO model and initialize GPIO."""
        # Load YOLO model
        if YOLO_AVAILABLE:
            model_full_path = Path(__file__).parent.parent.parent / self.model_path
            
            if not model_full_path.exists():
                self.logger.error(f"Model not found: {model_full_path}")
                # Try alternative path
                model_full_path = Path(self.model_path)
            
            if model_full_path.exists():
                self.logger.info(f"Loading YOLO model: {model_full_path}")
                self.model = YOLO(str(model_full_path))
                
                # Warm up with dummy inference
                import numpy as np
                dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                _ = self.model.predict(dummy_frame, verbose=False)
                self.logger.info("YOLO model loaded and warmed up")
            else:
                self.logger.warning(f"Model not found, running in mock mode")
                self.model = None
        else:
            self.logger.warning("YOLO not available, running in mock mode")
            self.model = None
        
        # Initialize GPIO
        if self.enable_gpio:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(VIBRATION_PIN, GPIO.OUT)
                self.pwm = GPIO.PWM(VIBRATION_PIN, PWM_FREQUENCY)
                self.pwm.start(0)  # Start with 0 duty cycle
                self.logger.info(f"GPIO initialized on pin {VIBRATION_PIN}")
            except Exception as e:
                self.logger.warning(f"GPIO init failed: {e}")
                self.pwm = None
        else:
            self.logger.info("GPIO disabled")
    
    def process_frame(self, frame, metadata: FrameMetadata) -> Optional[GuardianResult]:
        """
        Run YOLO inference on a frame and check for hazards.
        
        Args:
            frame: NumPy array (H, W, 3)
            metadata: Frame metadata
            
        Returns:
            GuardianResult with detections and hazard info
        """
        start_time = time.perf_counter()
        
        if self.model is None:
            # Mock mode - simulate detection
            return self._mock_inference(frame, metadata, start_time)
        
        # Run YOLO inference
        results = self.model.predict(
            frame,
            conf=MIN_CONFIDENCE,
            verbose=False,
            device='cpu'  # Force CPU for consistent performance
        )
        
        # Parse results
        detections = []
        hazard_detected = False
        max_hazard_level = 0
        
        if results and len(results) > 0:
            result = results[0]
            
            if result.boxes is not None:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    bbox = tuple(box.xyxyn[0].tolist())  # Normalized coordinates
                    
                    # Get class name
                    class_name = result.names.get(class_id, f"class_{class_id}")
                    
                    # Check if this is a hazard
                    is_hazard = class_id in HAZARD_CLASSES and confidence >= HAZARD_CONFIDENCE
                    
                    # Estimate distance based on bbox size
                    bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                    distance_estimate = self._estimate_distance(bbox_area, class_id)
                    
                    detection = Detection(
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence,
                        bbox=bbox,
                        is_hazard=is_hazard,
                        distance_estimate=distance_estimate
                    )
                    detections.append(detection)
                    
                    if is_hazard:
                        hazard_detected = True
                        hazard_level = self._calculate_hazard_level(detection)
                        max_hazard_level = max(max_hazard_level, hazard_level)
        
        # Calculate vibration intensity
        vibration_intensity = self._calculate_vibration(max_hazard_level, hazard_detected)
        
        # Update vibration motor
        self._set_vibration(vibration_intensity)
        
        # Calculate inference time
        inference_time_ms = (time.perf_counter() - start_time) * 1000
        
        return GuardianResult(
            detections=detections,
            hazard_detected=hazard_detected,
            hazard_level=max_hazard_level,
            vibration_intensity=vibration_intensity,
            inference_time_ms=inference_time_ms
        )
    
    def _mock_inference(self, frame, metadata, start_time) -> GuardianResult:
        """Mock inference for testing without YOLO."""
        # Simulate inference time
        time.sleep(0.05)  # 50ms mock inference
        
        inference_time_ms = (time.perf_counter() - start_time) * 1000
        
        return GuardianResult(
            detections=[],
            hazard_detected=False,
            hazard_level=0,
            vibration_intensity=VIBRATION_OFF,
            inference_time_ms=inference_time_ms
        )
    
    def _estimate_distance(self, bbox_area: float, class_id: int) -> float:
        """
        Estimate distance to object based on bounding box size.
        
        This is a rough approximation - larger bbox = closer object.
        
        Args:
            bbox_area: Normalized bounding box area (0-1)
            class_id: Object class
            
        Returns:
            Estimated distance in meters (rough)
        """
        # Base sizes for common objects at 2m distance
        base_sizes = {
            0: 0.05,   # person
            2: 0.15,   # car
            3: 0.08,   # motorcycle
            5: 0.20,   # bus
            7: 0.20,   # truck
        }
        
        base_size = base_sizes.get(class_id, 0.05)
        
        if bbox_area <= 0:
            return 10.0  # Far away
        
        # Simple inverse relationship
        distance = (base_size / bbox_area) ** 0.5 * 2.0
        return min(max(distance, 0.5), 10.0)  # Clamp to 0.5-10m
    
    def _calculate_hazard_level(self, detection: Detection) -> int:
        """
        Calculate hazard level based on detection.
        
        Args:
            detection: Detection object
            
        Returns:
            Hazard level (0-3)
        """
        distance = detection.distance_estimate
        
        if distance < 1.5:
            return 3  # HIGH - immediate danger
        elif distance < 3.0:
            return 2  # MEDIUM - caution
        elif distance < 5.0:
            return 1  # LOW - awareness
        else:
            return 0  # NONE - far away
    
    def _calculate_vibration(self, hazard_level: int, hazard_detected: bool) -> int:
        """
        Calculate vibration intensity based on hazard level.
        
        Args:
            hazard_level: 0-3
            hazard_detected: Whether any hazard was detected
            
        Returns:
            PWM duty cycle (0-100)
        """
        if not hazard_detected:
            self.consecutive_hazards = 0
            return VIBRATION_OFF
        
        # Track consecutive hazards for persistent warnings
        self.consecutive_hazards += 1
        
        vibration_map = {
            0: VIBRATION_OFF,
            1: VIBRATION_LOW,
            2: VIBRATION_MEDIUM,
            3: VIBRATION_HIGH
        }
        
        return vibration_map.get(hazard_level, VIBRATION_OFF)
    
    def _set_vibration(self, intensity: int) -> None:
        """
        Set vibration motor intensity.
        
        Args:
            intensity: PWM duty cycle (0-100)
        """
        if self.pwm is not None:
            try:
                self.pwm.ChangeDutyCycle(intensity)
            except Exception as e:
                self.logger.error(f"GPIO error: {e}")
    
    def on_result(self, result: GuardianResult, metadata: FrameMetadata, latency_ms: float) -> None:
        """Log detection results."""
        if result.hazard_detected:
            hazard_count = sum(1 for d in result.detections if d.is_hazard)
            self.logger.warning(
                f"⚠️ HAZARD! Level={result.hazard_level}, "
                f"Count={hazard_count}, Latency={latency_ms:.1f}ms"
            )
        
        # Log stats periodically
        if self._frames_processed.value % 30 == 0:
            stats = self.get_stats()
            self.logger.info(
                f"Stats: frames={stats['frames_processed']}, "
                f"avg_latency={stats['avg_latency_ms']:.1f}ms"
            )
    
    def cleanup(self) -> None:
        """Clean up GPIO."""
        if self.pwm is not None:
            self.pwm.stop()
        
        if self.enable_gpio and GPIO_AVAILABLE:
            try:
                GPIO.cleanup(VIBRATION_PIN)
            except Exception:
                pass
        
        self.logger.info("Guardian cleanup complete")


# ============================================================================
# STANDALONE TESTING
# ============================================================================

def test_guardian_worker():
    """Test guardian worker in standalone mode."""
    import numpy as np
    from multiprocessing import Value, Lock
    
    print("=" * 60)
    print("Testing Guardian Worker")
    print("=" * 60)
    
    # Create test frame buffer
    buffer = SharedFrameBuffer.create(name="test_guardian")
    
    # Create worker
    worker = GuardianWorker(
        model_path="models/yolo11n.pt",
        frame_buffer_name="test_guardian",
        enable_gpio=False,  # Don't use GPIO in test
        log_level=logging.DEBUG
    )
    
    # Start worker
    worker.start(write_index=buffer.write_index, slot_locks=buffer.slot_locks)
    
    # Wait for ready
    if not worker.wait_ready(timeout=30):
        print("Worker failed to start!")
        worker.stop()
        buffer.close()
        buffer.unlink()
        return
    
    print("Worker ready, pushing test frames...")
    
    # Push some test frames
    for i in range(10):
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        buffer.push_frame(frame)
        time.sleep(0.1)
    
    # Wait a bit for processing
    time.sleep(2)
    
    # Print stats
    print(f"Worker stats: {worker.get_stats()}")
    
    # Stop worker
    worker.stop()
    
    # Cleanup
    buffer.close()
    buffer.unlink()
    
    print("Test complete!")


if __name__ == "__main__":
    test_guardian_worker()
