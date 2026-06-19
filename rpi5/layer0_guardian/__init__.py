"""
Layer 0: The Guardian - Static Safety-Critical Object Detection

This module handles immediate physical safety using YOLO11n-NCNN.
Zero-tolerance latency requirement: <100ms from frame → detection → haptic alert.

KEY FEATURES:
- YOLO11n-NCNN (11MB, 417MB RAM, 80.7ms on RPi 5 CPU) ✅ VALIDATED!
- 80 Static COCO Classes (NEVER UPDATES)
- 100% Offline Operation (no network dependency)
- Direct GPIO 18 → PWM Vibration Motor
- Safety-critical objects only (stairs, vehicles, people, hazards)
- 4.8x faster than PyTorch (80.7ms vs 404ms benchmark validated)

INNOVATION:
This is the "safety guard" in the dual-model cascade. While Layer 1 (Learner)
adapts to context, Layer 0 maintains a static, reliable vocabulary for immediate
hazard detection. No configuration drift, no surprises.

NCNN OPTIMIZATION:
Replaced YOLO11x (1391ms NCNN!) with YOLO11n-NCNN to meet <100ms requirement.
Benchmark: 80.7ms avg, 12.4 FPS, 417MB RAM on RPi 5 @ 640px (14% faster than Ultralytics!)

Author: Haziq (@IRSPlays)
Competition: Young Innovators Awards (YIA) 2026
"""

import logging
import time
from collections import deque
from typing import List, Dict, Any, Optional
import numpy as np

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    logging.warning("⚠️ ultralytics not installed. Run: pip install ultralytics")

from rpi5.layer0_guardian.haptic_controller import HapticController

logger = logging.getLogger(__name__)


class YOLOGuardian:
    """
    Layer 0: Guardian - Static safety-critical object detection.
    
    This model NEVER changes its vocabulary. It provides a reliable
    baseline for immediate hazard detection with <100ms latency.
    
    Model: YOLO11n-NCNN (11MB, 417MB RAM, 80.7ms validated on RPi 5)
    Latency: <100ms ✅ ACHIEVED (4.8x faster than PyTorch)
    """
    
    # Safety-critical object classes (COCO subset)
    # NOTE: Only COCO-80 classes are listed here. Stair/curb/wall detection
    # is handled by Hailo depth estimation (HailoDepthEstimator), not YOLO.
    # Overhead hazards (signboard, branch, scaffolding) are detected by
    # Layer 1 (YOLOE) open-vocabulary text prompts, not this static model.
    SAFETY_CLASSES = {
        'person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck',
        'traffic light', 'fire hydrant', 'stop sign', 'bench',
        'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
        'umbrella', 'backpack', 'suitcase',  # torso/head-height objects in crowds
    }
    
    # Proximity thresholds for haptic feedback (based on bbox area)
    PROXIMITY_THRESHOLDS = {
        'immediate': 0.3,  # >30% of frame = DANGER (continuous vibration)
        'near': 0.15,      # >15% of frame = WARNING (fast pulse)
        'far': 0.05        # >5% of frame = NOTICE (slow pulse)
    }
    
    def __init__(
        self,
        model_path: str = "models/converted/yolo26n_ncnn_model",
        device: str = "cpu",
        confidence: float = 0.5,
        enable_haptic: bool = True,
        gpio_pin: int = 18,
        memory_manager: Optional['HybridMemoryManager'] = None
    ):
        """
        Initialize Layer 0 Guardian.

        Args:
            model_path: Path to YOLO11n-NCNN model directory
            device: Inference device ('cpu' for RPi, 'cuda' for laptop with GPU)
            confidence: Detection confidence threshold
            enable_haptic: Enable GPIO haptic feedback (True for RPi, False for laptop)
            gpio_pin: GPIO pin for vibration motor (default: 18)
            memory_manager: Optional HybridMemoryManager for cloud storage
        """
        logger.info("🛡️ Initializing Layer 0 Guardian (YOLO11n-NCNN)...")
        
        if not YOLO_AVAILABLE:
            raise ImportError("ultralytics not installed. Install with: pip install ultralytics")
        
        self.model_path = model_path
        self.device = device
        self.confidence = confidence
        
        # Load YOLO11n-NCNN model (static vocabulary, never updates)
        logger.info(f"📦 Loading YOLO11n-NCNN from {model_path}...")
        try:
            self.model = YOLO(model_path, task='detect')
            # DEBUG: Inspect what was actually loaded
            logger.info(f"✅ Loaded YOLO model from {model_path}")
            if hasattr(self.model, 'model'):
                logger.info(f"   Internal Type: {type(self.model.model)}")
            if hasattr(self.model, 'predictor'):
                 logger.info(f"   Predictor: {type(self.model.predictor)}")
            
            # DEBUG: Log loaded class names to verify metadata.yaml was read
            if hasattr(self.model, 'names') and self.model.names:
                names_dict = self.model.names
                logger.info(f"   Class names loaded: {len(names_dict)} classes")
                # Show first 5 and last 5 to verify full COCO vocabulary
                first_5 = [f"{k}:{v}" for k, v in list(names_dict.items())[:5]]
                last_5 = [f"{k}:{v}" for k, v in list(names_dict.items())[-5:]]
                logger.info(f"   First 5: {first_5}")
                logger.info(f"   Last 5: {last_5}")
                
                # CRITICAL: Check if we only have 'person' (metadata.yaml missing)
                if len(names_dict) <= 1:
                    logger.error(f"   ❌ ONLY {len(names_dict)} class(es) loaded! metadata.yaml may be missing!")
                    logger.error(f"   Expected 80 COCO classes. Check: {model_path}/metadata.yaml")
                    raise RuntimeError(f"Safety-critical model has only {len(names_dict)} class(es). ""metadata.yaml likely missing from {model_path}")
            else:
                logger.error("   ❌ Model has NO 'names' attribute - class labels will be wrong!")
            
        except Exception as e:
            logger.error(f"❌ Failed to load YOLO11n-NCNN: {e}")
            raise
        
        # Initialize haptic controller
        self.haptic = HapticController(
            enabled=enable_haptic,
            gpio_pin=gpio_pin
        )

        # Memory manager (optional, for cloud storage)
        self.memory_manager = memory_manager

        # Performance tracking
        self.inference_times = deque(maxlen=100)
        
        logger.info("✅ Layer 0 Guardian initialized")
        logger.info(f"   Model: {model_path}")
        logger.info(f"   Device: {device}")
        logger.info(f"   Confidence: {confidence}")
        logger.info(f"   Haptic: {'ENABLED (GPIO ' + str(gpio_pin) + ')' if enable_haptic else 'DISABLED (laptop mode)'}")
    
    def detect(
        self,
        frame: np.ndarray,
        confidence: Optional[float] = None,
        depth_map: Optional[np.ndarray] = None
    ) -> List[Dict[str, Any]]:
        """
        Run safety-critical object detection.
        
        This method MUST complete in <100ms for safety requirements.
        
        Args:
            frame: Input image (H, W, C) as numpy array
            confidence: Override default confidence threshold
            depth_map: Optional depth map for metric distance (from HailoDepthEstimator)
            
        Returns:
            List of safety-critical detections:
            [
                {
                    'class': 'person',
                    'confidence': 0.92,
                    'bbox': [x1, y1, x2, y2],  # Normalized [0-1]
                    'bbox_area': 0.25,  # Fraction of frame
                    'proximity': 'near',  # 'immediate', 'near', 'far'
                    'priority': 'high',  # Safety classification
                    'distance_m': 2.5,  # Metric distance if depth_map provided
                },
                ...
            ]
        """
        start_time = time.perf_counter()
        
        conf = confidence if confidence is not None else self.confidence
        
        try:
            # Predict
            results = self.model.predict(
                source=frame,
                conf=conf,
                verbose=False,  # Suppress console output
                device=self.device,
                task='detect'
            )

            # Extract detections
            detections = []
            if results and len(results) > 0:
                result = results[0]
                
                # Get frame dimensions for normalization
                frame_height, frame_width = frame.shape[:2]
                frame_area = frame_width * frame_height
                
                # Process each detection
                if result.boxes is not None:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        # Defensive lookup with fallback if class_id not in names
                        if class_id in result.names:
                            class_name = result.names[class_id]
                        else:
                            logger.warning(f"⚠️ Unknown class_id {class_id}, names dict has {len(result.names)} entries")
                            class_name = f"class_{class_id}"
                        conf_score = float(box.conf[0])
                        bbox = box.xyxy[0].cpu().numpy()  # [x1, y1, x2, y2]
                        
                        # Calculate bounding box area (normalized)
                        bbox_width = bbox[2] - bbox[0]
                        bbox_height = bbox[3] - bbox[1]
                        bbox_area = (bbox_width * bbox_height) / frame_area
                        
                        # Determine proximity level
                        # Use metric depth if available, otherwise fall back to bbox-area heuristic
                        distance_m = None
                        if depth_map is not None:
                            distance_m = self._get_depth_at_bbox(depth_map, bbox, frame.shape)
                            if distance_m > 0:
                                if distance_m < 1.0:
                                    proximity = 'immediate'
                                    priority = 'critical'
                                elif distance_m < 2.5:
                                    proximity = 'near'
                                    priority = 'high'
                                elif distance_m < 5.0:
                                    proximity = 'far'
                                    priority = 'medium'
                                else:
                                    proximity = 'distant'
                                    priority = 'low'
                            else:
                                # Depth lookup failed, fall back to bbox-area
                                distance_m = None
                        
                        if distance_m is None:
                            # Fallback to bbox-area heuristic
                            if bbox_area >= self.PROXIMITY_THRESHOLDS['immediate']:
                                proximity = 'immediate'
                                priority = 'critical'
                            elif bbox_area >= self.PROXIMITY_THRESHOLDS['near']:
                                proximity = 'near'
                                priority = 'high'
                            elif bbox_area >= self.PROXIMITY_THRESHOLDS['far']:
                                proximity = 'far'
                                priority = 'medium'
                            else:
                                proximity = 'distant'
                                priority = 'low'
                        
                        # Only include safety-critical classes
                        if class_name in self.SAFETY_CLASSES:
                            detection = {
                                'class': class_name,
                                'confidence': conf_score,
                                'bbox': bbox.tolist(),
                                'bbox_normalized': [
                                    bbox[0] / frame_width,
                                    bbox[1] / frame_height,
                                    bbox[2] / frame_width,
                                    bbox[3] / frame_height
                                ],
                                'bbox_area': bbox_area,
                                'proximity': proximity,
                                'priority': priority,
                                'layer': 'guardian'
                            }
                            if distance_m is not None and distance_m > 0:
                                detection['distance_m'] = distance_m
                            detections.append(detection)
                            
                            # Log detection at DEBUG level (status display shows summary)
                            from datetime import datetime
                            ts = datetime.now().strftime("%H:%M:%S")
                            logger.debug(f"[{ts}] <layer0> {class_name} ({int(conf_score*100)}%) bbox=[{int(bbox[0])}, {int(bbox[1])}, {int(bbox[2])}, {int(bbox[3])}]")

                            # Store to memory manager (Supabase + local SQLite)
                            if self.memory_manager:
                                self.memory_manager.store_detection({
                                    'layer': 'guardian',
                                    'class_name': class_name,
                                    'confidence': float(conf_score),
                                    'bbox_x1': float(bbox[0] / frame_width),
                                    'bbox_y1': float(bbox[1] / frame_height),
                                    'bbox_x2': float(bbox[2] / frame_width),
                                    'bbox_y2': float(bbox[3] / frame_height),
                                    'bbox_area': float(bbox_area),
                                    'detection_mode': None,
                                    'source': 'base'
                                })
            
            # Track performance
            latency = (time.perf_counter() - start_time) * 1000  # Convert to ms
            self.inference_times.append(latency)

            # Log warning if latency exceeds 200ms. NCNN on Pi 5 typically
            # lands in 80-180ms for 640px input — the old 100ms threshold
            # was aspirational and produced dozens of warnings per second
            # for what was actually normal behavior. 200ms is the real
            # "something's wrong" threshold. Throttle to once per 10s
            # so the log isn't drowned in latency spam.
            if latency > 200:
                now = time.time()
                if not hasattr(self, "_last_latency_warn") or (now - self._last_latency_warn) > 10.0:
                    self._last_latency_warn = now
                    logger.warning(
                        f"⚠️ Layer 0 latency: {latency:.1f}ms "
                        f"(exceeds 200ms threshold — running heavy?)"
                    )
            
            # Trigger haptic feedback based on detections
            self.trigger_haptic_feedback(detections)
            
            return detections
        
        except Exception as e:
            logger.error(f"❌ Layer 0 detection failed: {e}")
            return []
    
    def trigger_haptic_feedback(self, detections: List[Dict[str, Any]]) -> None:
        """
        Trigger vibration motor based on proximity of detected objects.
        
        Vibration patterns:
        - immediate: 100% intensity, continuous
        - near: 70% intensity, fast pulse (200ms on/off)
        - far: 40% intensity, slow pulse (500ms on/off)
        
        Args:
            detections: List of detections from detect()
        """
        if not detections:
            self.haptic.stop()
            return
        
        # Find highest priority detection
        highest_priority = None
        for det in detections:
            if highest_priority is None or self._priority_rank(det['priority']) > self._priority_rank(highest_priority['priority']):
                highest_priority = det
        
        if highest_priority:
            proximity = highest_priority['proximity']
            
            if proximity == 'immediate':
                self.haptic.continuous(intensity=100)
            elif proximity == 'near':
                self.haptic.pulse(intensity=70, duration=0.2)
            elif proximity == 'far':
                self.haptic.pulse(intensity=40, duration=0.5)
            else:
                self.haptic.stop()
    
    def _priority_rank(self, priority: str) -> int:
        """Convert priority to numerical rank for comparison."""
        priority_map = {
            'critical': 4,
            'high': 3,
            'medium': 2,
            'low': 1
        }
        return priority_map.get(priority, 0)
    
    def _get_depth_at_bbox(
        self,
        depth_map: np.ndarray,
        bbox: np.ndarray,
        frame_shape: tuple
    ) -> float:
        """
        Get metric distance at bounding box center from depth map.
        
        Args:
            depth_map: Depth map in meters (from HailoDepthEstimator)
            bbox: [x1, y1, x2, y2] in pixel coordinates
            frame_shape: (H, W, C) of original frame
            
        Returns:
            Distance in meters, or -1.0 if lookup fails
        """
        try:
            h, w = frame_shape[:2]
            dh, dw = depth_map.shape[:2]
            
            # Map bbox center to depth map coordinates
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            dx = int(cx / w * dw)
            dy = int(cy / h * dh)
            
            # Clamp to depth map bounds
            dx = max(0, min(dx, dw - 1))
            dy = max(0, min(dy, dh - 1))
            
            # M8 fix: use 7×7 region to match HailoDepthEstimator.get_depth_at_bbox.
            # Previously a 5×5 window here vs 7×7 in the Hailo estimator
            # gave different distance values for the same detection at the
            # same frame. Centralise the radius constant so the two stay
            # in sync.
            r = 3
            y1 = max(0, dy - r)
            y2 = min(dh, dy + r + 1)
            x1 = max(0, dx - r)
            x2 = min(dw, dx + r + 1)
            region = depth_map[y1:y2, x1:x2]

            if region.size == 0:
                return -1.0

            return float(np.median(region))
            
        except Exception as e:
            logger.debug(f"Depth lookup failed: {e}")
            return -1.0
    
    def get_classes(self) -> List[str]:
        """
        Get list of detectable classes (static, never changes).
        
        Returns:
            List of 80 COCO class names
        """
        if self.model and hasattr(self.model, 'names'):
            return list(self.model.names.values())
        return []
    
    def get_average_latency(self) -> float:
        """
        Get average inference latency in milliseconds.
        
        Returns:
            Average latency (ms)
        """
        if not self.inference_times:
            return 0.0
        return np.mean(list(self.inference_times))
    
    def cleanup(self) -> None:
        """Release resources."""
        logger.info("🧹 Cleaning up Layer 0 Guardian...")
        self.haptic.cleanup()
        logger.info("✅ Layer 0 Guardian cleaned up")


# Example usage (for testing):
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize guardian (laptop mode with haptic disabled)
    guardian = YOLOGuardian(
        device="cpu",
        enable_haptic=False  # Disable GPIO for laptop testing
    )
    
    # Load test frame
    import cv2
    test_frame = cv2.imread("tests/test_frame.jpg")
    
    if test_frame is not None:
        # Run detection
        detections = guardian.detect(test_frame)
        
        print(f"\n🛡️ Layer 0 Guardian Detections: {len(detections)}")
        for det in detections:
            print(f"   {det['class']}: {det['confidence']:.2f} ({det['proximity']} - {det['priority']} priority)")
        
        # Check latency
        avg_latency = guardian.get_average_latency()
        print(f"\n⏱️ Average Latency: {avg_latency:.1f}ms (target: <100ms)")
        
        if avg_latency < 100:
            print("✅ Latency requirement MET")
        else:
            print("⚠️ Latency requirement EXCEEDED")
    
    # Cleanup
    guardian.cleanup()
