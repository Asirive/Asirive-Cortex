"""
Layer 1: The Learner - Adaptive Context-Aware Object Detection

This module handles dynamic object detection using YOLOE-11s with adaptive text prompts.
The system learns new objects WITHOUT retraining by updating its vocabulary in real-time.

KEY FEATURES:
- YOLOE-11s-seg (80MB, 0.8GB RAM, 90-130ms on RPi CPU)
- 15-100 Adaptive Text Prompts (UPDATES DYNAMICALLY)
- Learns from Gemini scene descriptions
- Learns from Google Maps nearby POI
- Learns from user memory (Layer 4)
- MobileCLIP-B(LT) text encoder (100MB RAM, cached)

INNOVATION:
This is the "learner" in the dual-model cascade. While Layer 0 (Guardian)
provides static safety detection, Layer 1 adapts its vocabulary based on context:
- User asks "Describe the scene" → Gemini says "fire extinguisher" → Layer 1 learns it
- User walks near Starbucks → Layer 1 pre-loads "coffee shop sign", "menu board"
- User stores "brown leather wallet" → Layer 1 adds it to vocabulary

No model retraining needed. Just update text prompts via set_classes() (<50ms overhead).

Author: Haziq (@IRSPlays)
Competition: Young Innovators Awards (YIA) 2026
"""

import logging
import time
from typing import List, Dict, Any, Optional
import numpy as np

try:
    from ultralytics import YOLOE
    YOLOE_AVAILABLE = True
except ImportError:
    YOLOE_AVAILABLE = False
    logging.warning("⚠️ ultralytics YOLOE not installed. Run: pip install ultralytics")

from layer1_learner.adaptive_prompt_manager import AdaptivePromptManager

logger = logging.getLogger(__name__)


class YOLOELearner:
    """
    Layer 1: Learner - Adaptive context-aware object detection.
    
    This model LEARNS new objects without retraining by updating
    its text prompts based on Gemini descriptions, Maps POI, and user memory.
    """
    
    def __init__(
        self,
        model_path: str = "models/yoloe-11m-seg.pt",
        device: str = "cpu",
        confidence: float = 0.25,
        prompt_manager: Optional[AdaptivePromptManager] = None
    ):
        """
        Initialize Layer 1 Learner.
        
        Args:
            model_path: Path to YOLOE-11s weights
            device: Inference device ('cpu' for RPi, 'cuda' for laptop with GPU)
            confidence: Detection confidence threshold
            prompt_manager: Adaptive prompt manager (created if None)
        """
        logger.info("🎯 Initializing Layer 1 Learner (YOLOE-11s)...")
        
        if not YOLOE_AVAILABLE:
            raise ImportError("ultralytics YOLOE not installed. Install with: pip install ultralytics")
        
        self.model_path = model_path
        self.device = device
        self.confidence = confidence
        
        # Load YOLOE-11s model (adaptive vocabulary, updates dynamically)
        logger.info(f"📦 Loading YOLOE-11s from {model_path}...")
        try:
            self.model = YOLOE(model_path)
            self.model.to(device)
            logger.info(f"✅ YOLOE-11s loaded on {device}")
        except Exception as e:
            logger.error(f"❌ Failed to load YOLOE-11s: {e}")
            raise
        
        # Initialize prompt manager (SIMPLIFIED: base 15 classes only)
        self.prompt_manager = prompt_manager or AdaptivePromptManager()
        
        # Set initial classes (BASE ONLY - no dynamic learning at startup)
        self.current_classes = [
            "person", "car", "phone", "wallet", "keys",
            "door", "stairs", "chair", "table", "bottle",
            "cup", "book", "laptop", "bag", "glasses"
        ]
        self.text_embeddings = None
        
        # Performance tracking
        self.inference_times = []
        self.prompt_update_times = []
        
        logger.info(f"🎯 [Learner] Using simplified 15-class base vocabulary (no adaptive learning at startup)")
        # Skip prompt update to avoid 883ms startup delay
        # self._update_classes_internal()
        
        # Performance tracking
        self.inference_times = []
        self.prompt_update_times = []
        
        logger.info("✅ Layer 1 Learner initialized")
        logger.info(f"   Model: {model_path}")
        logger.info(f"   Device: {device}")
        logger.info(f"   Confidence: {confidence}")
        logger.info(f"   Initial Classes: {len(self.current_classes)}")
    
    def detect(
        self,
        frame: np.ndarray,
        confidence: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Run adaptive object detection.
        
        Uses current text prompts to detect objects. Vocabulary can be updated
        dynamically without retraining the model.
        
        Args:
            frame: Input image (H, W, C) as numpy array
            confidence: Override default confidence threshold
            
        Returns:
            List of adaptive detections:
            [
                {
                    'class': 'fire extinguisher',  # Can be dynamic learned class
                    'confidence': 0.87,
                    'bbox': [x1, y1, x2, y2],  # Normalized [0-1]
                    'bbox_area': 0.12,
                    'mask': np.ndarray,  # Segmentation mask (if available)
                    'source': 'gemini',  # 'base', 'gemini', 'maps', 'memory'
                    'layer': 'learner'
                },
                ...
            ]
        """
        start_time = time.time()
        
        conf = confidence if confidence is not None else self.confidence
        
        try:
            # Run YOLOE inference with current text prompts
            results = self.model(
                frame,
                conf=conf,
                verbose=False,
                device=self.device
            )
            
            # Extract detections
            detections = []
            if results and len(results) > 0:
                result = results[0]
                
                # Get frame dimensions
                frame_height, frame_width = frame.shape[:2]
                frame_area = frame_width * frame_height
                
                # Process each detection
                if result.boxes is not None:
                    for i, box in enumerate(result.boxes):
                        class_id = int(box.cls[0])
                        class_name = result.names[class_id] if hasattr(result, 'names') else self.current_classes[class_id]
                        conf_score = float(box.conf[0])
                        bbox = box.xyxy[0].cpu().numpy()  # [x1, y1, x2, y2]
                        
                        # Calculate bbox area
                        bbox_width = bbox[2] - bbox[0]
                        bbox_height = bbox[3] - bbox[1]
                        bbox_area = (bbox_width * bbox_height) / frame_area
                        
                        # Get segmentation mask if available
                        mask = None
                        if hasattr(result, 'masks') and result.masks is not None:
                            if i < len(result.masks.data):
                                mask = result.masks.data[i].cpu().numpy()
                        
                        # Determine source of class (base vocab, gemini, maps, memory)
                        source = self.prompt_manager.get_source(class_name) if self.prompt_manager else 'base'
                        
                        detections.append({
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
                            'mask': mask,
                            'source': source,
                            'layer': 'learner'
                        })
            
            # Track performance
            latency = (time.time() - start_time) * 1000
            self.inference_times.append(latency)
            
            return detections
        
        except Exception as e:
            logger.error(f"❌ Layer 1 detection failed: {e}")
            return []
    
    def set_classes(self, class_names: List[str]) -> None:
        """
        Update YOLOE text prompts dynamically.
        
        This is the core method that enables adaptive learning without retraining.
        Text embeddings are computed by MobileCLIP and cached for efficiency.
        
        Args:
            class_names: List of new class names (e.g., ["person", "fire extinguisher", "coffee machine"])
        """
        start_time = time.time()
        
        try:
            # Generate text embeddings using MobileCLIP
            logger.debug(f"🔄 Updating YOLOE prompts: {len(class_names)} classes")
            self.text_embeddings = self.model.get_text_pe(class_names)
            
            # Set classes with embeddings
            self.model.set_classes(class_names, self.text_embeddings)
            self.current_classes = class_names
            
            # Track update time
            update_time = (time.time() - start_time) * 1000
            self.prompt_update_times.append(update_time)
            
            logger.info(f"✅ YOLOE prompts updated: {len(class_names)} classes ({update_time:.1f}ms)")
            
            # Log warning if update takes too long
            if update_time > 50:
                logger.warning(f"⚠️ Prompt update: {update_time:.1f}ms (target: <50ms)")
        
        except Exception as e:
            logger.error(f"❌ Failed to update YOLOE prompts: {e}")
    
    def _update_classes_internal(self) -> None:
        """Internal method to update classes from prompt manager."""
        if self.prompt_manager:
            current_prompts = self.prompt_manager.get_current_prompts()
            self.set_classes(current_prompts)
    
    def get_classes(self) -> List[str]:
        """
        Get current detectable classes (dynamic, updates frequently).
        
        Returns:
            List of current class names (15-100 classes)
        """
        return self.current_classes.copy()
    
    def get_average_latency(self) -> float:
        """
        Get average inference latency in milliseconds.
        
        Returns:
            Average latency (ms)
        """
        if not self.inference_times:
            return 0.0
        return np.mean(self.inference_times)
    
    def get_average_update_time(self) -> float:
        """
        Get average prompt update time in milliseconds.
        
        Returns:
            Average update time (ms)
        """
        if not self.prompt_update_times:
            return 0.0
        return np.mean(self.prompt_update_times)
    
    def cleanup(self) -> None:
        """Release resources."""
        logger.info("🧹 Cleaning up Layer 1 Learner...")
        # YOLOE model cleanup handled by ultralytics
        logger.info("✅ Layer 1 Learner cleaned up")


# Example usage (for testing):
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize learner
    learner = YOLOELearner(device="cpu")
    
    # Load test frame
    import cv2
    test_frame = cv2.imread("tests/test_frame.jpg")
    
    if test_frame is not None:
        # Run detection with base vocabulary
        detections = learner.detect(test_frame)
        print(f"\n🎯 Layer 1 Learner Detections (base vocab): {len(detections)}")
        for det in detections:
            print(f"   {det['class']}: {det['confidence']:.2f} (source: {det['source']})")
        
        # Simulate learning new objects from Gemini
        print("\n📝 Learning new objects from Gemini...")
        new_classes = learner.get_classes() + ["fire extinguisher", "water fountain", "exit sign"]
        learner.set_classes(new_classes)
        
        # Run detection again with updated vocabulary
        detections = learner.detect(test_frame)
        print(f"\n🎯 Layer 1 Learner Detections (updated vocab): {len(detections)}")
        for det in detections:
            print(f"   {det['class']}: {det['confidence']:.2f} (source: {det['source']})")
        
        # Check performance
        avg_latency = learner.get_average_latency()
        avg_update = learner.get_average_update_time()
        print(f"\n⏱️ Performance:")
        print(f"   Inference: {avg_latency:.1f}ms (target: <150ms)")
        print(f"   Prompt Update: {avg_update:.1f}ms (target: <50ms)")
    
    # Cleanup
    learner.cleanup()
