"""
Learner Worker - Layer 1 Adaptive Detection (YOLOE Prompt-Free)
================================================================

This worker is responsible for:
- Adaptive object detection using YOLOE (prompt-free)
- Learning common objects in the environment
- Personalized detection for the user
- Lower priority than Guardian (not safety-critical)

CPU Assignment: Core 2
Model: YOLOE-11s-seg-pf (prompt-free segmentation)
Priority: MEDIUM (adaptive, not safety-critical)

Author: Project Cortex Team
Date: 2025
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Any, Dict
from dataclasses import dataclass, field
from collections import defaultdict

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
    print("Warning: ultralytics not available, LearnerWorker will run in mock mode")


# ============================================================================
# CONSTANTS
# ============================================================================

# YOLOE model path (prompt-free segmentation)
DEFAULT_MODEL_PATH = "models/yoloe-11s-seg-pf.pt"
FALLBACK_MODEL_PATH = "models/yolo11s.pt"

# Confidence threshold
MIN_CONFIDENCE = 0.3

# Learning settings
LEARNING_HISTORY_SIZE = 100  # Number of frames to remember
COMMON_OBJECT_THRESHOLD = 10  # Minimum occurrences to be considered "common"


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class LearnerDetection:
    """A detection from the learner model."""
    class_id: int
    class_name: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 (normalized)
    mask: Optional[Any] = None  # Segmentation mask if available
    is_common: bool = False  # True if this is a frequently seen object


@dataclass
class LearnerResult:
    """Result from learner inference."""
    detections: List[LearnerDetection]
    new_objects: List[str]  # Objects seen for the first time
    common_objects: List[str]  # Frequently seen objects
    inference_time_ms: float
    has_segmentation: bool


@dataclass
class ObjectMemory:
    """Memory of seen objects for learning."""
    object_counts: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    first_seen: Dict[int, float] = field(default_factory=dict)
    last_seen: Dict[int, float] = field(default_factory=dict)
    
    def record(self, class_id: int, timestamp: float) -> bool:
        """
        Record an object sighting.
        
        Args:
            class_id: Object class ID
            timestamp: When it was seen
            
        Returns:
            True if this is the first time seeing this object
        """
        is_new = class_id not in self.first_seen
        
        if is_new:
            self.first_seen[class_id] = timestamp
        
        self.last_seen[class_id] = timestamp
        self.object_counts[class_id] += 1
        
        return is_new
    
    def is_common(self, class_id: int) -> bool:
        """Check if an object is commonly seen."""
        return self.object_counts.get(class_id, 0) >= COMMON_OBJECT_THRESHOLD
    
    def get_stats(self) -> Dict:
        """Get memory statistics."""
        return {
            "total_classes": len(self.object_counts),
            "common_classes": sum(1 for c in self.object_counts.values() 
                                  if c >= COMMON_OBJECT_THRESHOLD),
            "total_sightings": sum(self.object_counts.values()),
            "top_objects": sorted(
                self.object_counts.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:10]
        }


# ============================================================================
# LEARNER WORKER
# ============================================================================

class LearnerWorker(BaseWorker):
    """
    Adaptive YOLOE detection worker with learning capability.
    
    Runs YOLOE prompt-free on Core 2, learns common objects in environment.
    Target latency: <200ms (not safety-critical).
    """
    
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        frame_buffer_name: str = "cortex_frames",
        enable_learning: bool = True,
        log_level: int = logging.INFO
    ):
        """
        Initialize the learner worker.
        
        Args:
            model_path: Path to YOLOE model file
            frame_buffer_name: Name of shared frame buffer
            enable_learning: Whether to enable object learning
            log_level: Logging level
        """
        super().__init__(
            name="Learner",
            cpu_core=2,  # Dedicated core for adaptive detection
            frame_buffer_name=frame_buffer_name,
            worker_id=2,  # Worker ID for marking processed frames
            log_level=log_level
        )
        
        self.model_path = model_path
        self.enable_learning = enable_learning
        
        # Will be set in setup()
        self.model: Optional[Any] = None
        self.has_segmentation: bool = False
        
        # Object memory for learning
        self.memory = ObjectMemory()
    
    def setup(self) -> None:
        """Load YOLOE model."""
        if not YOLO_AVAILABLE:
            self.logger.warning("YOLO not available, running in mock mode")
            return
        
        # Try YOLOE prompt-free model first
        model_full_path = Path(__file__).parent.parent.parent / self.model_path
        
        if not model_full_path.exists():
            # Try fallback model
            fallback_path = Path(__file__).parent.parent.parent / FALLBACK_MODEL_PATH
            if fallback_path.exists():
                model_full_path = fallback_path
                self.logger.info(f"Using fallback model: {fallback_path.name}")
            else:
                self.logger.error(f"No model found at {self.model_path} or {FALLBACK_MODEL_PATH}")
                return
        
        self.logger.info(f"Loading model: {model_full_path}")
        
        try:
            self.model = YOLO(str(model_full_path))
            
            # Check if model supports segmentation
            model_name = model_full_path.name.lower()
            self.has_segmentation = 'seg' in model_name
            
            self.logger.info(
                f"Model loaded: {model_full_path.name}, "
                f"segmentation={'enabled' if self.has_segmentation else 'disabled'}"
            )
            
            # Warm up
            import numpy as np
            dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            _ = self.model.predict(dummy_frame, verbose=False)
            self.logger.info("Model warmed up")
            
        except Exception as e:
            self.logger.error(f"Failed to load model: {e}")
            self.model = None
    
    def process_frame(self, frame, metadata: FrameMetadata) -> Optional[LearnerResult]:
        """
        Run YOLOE inference and learn from detections.
        
        Args:
            frame: NumPy array (H, W, 3)
            metadata: Frame metadata
            
        Returns:
            LearnerResult with detections and learning info
        """
        start_time = time.perf_counter()
        
        if self.model is None:
            return self._mock_inference(start_time)
        
        # Run inference
        results = self.model.predict(
            frame,
            conf=MIN_CONFIDENCE,
            verbose=False,
            device='cpu'
        )
        
        # Parse results
        detections = []
        new_objects = []
        common_objects = []
        
        if results and len(results) > 0:
            result = results[0]
            
            if result.boxes is not None:
                masks = result.masks if hasattr(result, 'masks') and result.masks is not None else None
                
                for i, box in enumerate(result.boxes):
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    bbox = tuple(box.xyxyn[0].tolist())
                    
                    # Get class name
                    class_name = result.names.get(class_id, f"class_{class_id}")
                    
                    # Get mask if available
                    mask = None
                    if masks is not None and i < len(masks.data):
                        mask = masks.data[i]
                    
                    # Learning: record sighting
                    if self.enable_learning:
                        is_new = self.memory.record(class_id, metadata.timestamp)
                        if is_new:
                            new_objects.append(class_name)
                        
                        is_common = self.memory.is_common(class_id)
                        if is_common:
                            common_objects.append(class_name)
                    else:
                        is_common = False
                    
                    detection = LearnerDetection(
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence,
                        bbox=bbox,
                        mask=mask,
                        is_common=is_common
                    )
                    detections.append(detection)
        
        inference_time_ms = (time.perf_counter() - start_time) * 1000
        
        return LearnerResult(
            detections=detections,
            new_objects=list(set(new_objects)),  # Deduplicate
            common_objects=list(set(common_objects)),
            inference_time_ms=inference_time_ms,
            has_segmentation=self.has_segmentation
        )
    
    def _mock_inference(self, start_time) -> LearnerResult:
        """Mock inference for testing."""
        time.sleep(0.1)  # Simulate 100ms inference
        
        inference_time_ms = (time.perf_counter() - start_time) * 1000
        
        return LearnerResult(
            detections=[],
            new_objects=[],
            common_objects=[],
            inference_time_ms=inference_time_ms,
            has_segmentation=False
        )
    
    def on_result(self, result: LearnerResult, metadata: FrameMetadata, latency_ms: float) -> None:
        """Log learning results."""
        # Log new objects
        if result.new_objects:
            self.logger.info(f"🆕 New objects discovered: {', '.join(result.new_objects)}")
        
        # Log stats periodically
        if self._frames_processed.value % 50 == 0:
            stats = self.get_stats()
            memory_stats = self.memory.get_stats()
            
            self.logger.info(
                f"Stats: frames={stats['frames_processed']}, "
                f"avg_latency={stats['avg_latency_ms']:.1f}ms, "
                f"learned_classes={memory_stats['total_classes']}"
            )
    
    def get_learned_objects(self) -> Dict:
        """Get the learned object statistics."""
        return self.memory.get_stats()
    
    def cleanup(self) -> None:
        """Clean up resources."""
        if self.enable_learning:
            memory_stats = self.memory.get_stats()
            self.logger.info(
                f"Learner cleanup: learned {memory_stats['total_classes']} classes, "
                f"{memory_stats['total_sightings']} total sightings"
            )


# ============================================================================
# STANDALONE TESTING
# ============================================================================

def test_learner_worker():
    """Test learner worker in standalone mode."""
    import numpy as np
    
    print("=" * 60)
    print("Testing Learner Worker")
    print("=" * 60)
    
    # Create test frame buffer
    buffer = SharedFrameBuffer.create(name="test_learner")
    
    # Create worker
    worker = LearnerWorker(
        model_path="models/yolo11s.pt",  # Use smaller model for testing
        frame_buffer_name="test_learner",
        enable_learning=True,
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
        time.sleep(0.15)  # Slower than guardian
    
    # Wait for processing
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
    test_learner_worker()
