"""
Layer 1: The Learner - Adaptive Context-Aware Object Detection

This module handles dynamic object detection using YOLOE with THREE detection modes:

MODE 1: PROMPT-FREE (Discovery Mode) 🔍
- Built-in vocabulary of 4,585+ classes (zero setup)
- Works immediately without any prompts
- Best for: General exploration, discovering unknown objects
- Model: yoloe-11*-pf.pt (prompt-free variants)

MODE 2: TEXT PROMPTS (Contextual Learning Mode) 🧠
- 15-100 Adaptive Text Prompts (UPDATES DYNAMICALLY)
- Learns from Gemini scene descriptions
- Learns from Google Maps nearby POI
- Learns from user memory (Layer 4)
- MobileCLIP-B(LT) text encoder (100MB RAM, cached)

MODE 3: VISUAL PROMPTS (Personal Object Mode) 👁️
- User marks objects by drawing bounding boxes
- No text needed - "show, don't tell"
- Perfect for personalized items (user's specific wallet, keys, glasses)
- SAVPE (Semantic-Activated Visual Prompt Encoder)

INNOVATION:
This is the "learner" in the dual-model cascade. While Layer 0 (Guardian)
provides static safety detection, Layer 1 adapts in THREE ways:
1. Prompt-Free: "Show me everything around me" (4585 classes)
2. Text Prompts: "Describe the scene" → Gemini says "fire extinguisher" → Layer 1 learns it
3. Visual Prompts: "Remember this wallet" → User draws box → Layer 1 recognizes it

No model retraining needed. Switch modes dynamically based on user intent.

Author: Haziq (@IRSPlays)
Competition: Young Innovators Awards (YIA) 2026
"""

import logging
import time
from typing import List, Dict, Any, Optional
from enum import Enum
import numpy as np

try:
    from ultralytics import YOLOE
    from ultralytics.models.yolo.yoloe import YOLOEVPSegPredictor
    YOLOE_AVAILABLE = True
except ImportError:
    YOLOE_AVAILABLE = False
    YOLOEVPSegPredictor = None
    logging.warning("⚠️ ultralytics YOLOE not installed. Run: pip install ultralytics")

from layer1_learner.adaptive_prompt_manager import AdaptivePromptManager

logger = logging.getLogger(__name__)


class YOLOEMode(Enum):
    """YOLOE detection modes."""
    PROMPT_FREE = "prompt_free"  # 4585+ classes, no setup
    TEXT_PROMPTS = "text_prompts"  # Adaptive text learning (current)
    VISUAL_PROMPTS = "visual_prompts"  # Personal object recognition


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
        mode: YOLOEMode = YOLOEMode.TEXT_PROMPTS,
        prompt_manager: Optional[AdaptivePromptManager] = None
    ):
        """
        Initialize Layer 1 Learner.
        
        Args:
            model_path: Path to YOLOE weights (use *-pf.pt for prompt-free mode)
            device: Inference device ('cpu' for RPi, 'cuda' for laptop with GPU)
            confidence: Detection confidence threshold
            mode: Detection mode (PROMPT_FREE, TEXT_PROMPTS, VISUAL_PROMPTS)
            prompt_manager: Adaptive prompt manager (created if None)
        """
        logger.info(f"🎯 Initializing Layer 1 Learner (Mode: {mode.value})...")
        
        if not YOLOE_AVAILABLE:
            raise ImportError("ultralytics YOLOE not installed. Install with: pip install ultralytics")
        
        self.model_path = model_path
        self.device = device
        self.confidence = confidence
        self.mode = mode
        
        # Detect mode from model filename if not explicitly set
        if "-pf.pt" in model_path and mode != YOLOEMode.PROMPT_FREE:
            logger.warning(f"⚠️ Model filename suggests prompt-free mode, switching from {mode.value} to prompt_free")
            self.mode = YOLOEMode.PROMPT_FREE
        
        # Load YOLOE model (mode-specific configuration)
        logger.info(f"📦 Loading YOLOE from {model_path} (mode: {self.mode.value})...")
        try:
            self.model = YOLOE(model_path)
            self.model.to(device)
            
            # Verify model supports selected mode
            is_prompt_free = hasattr(self.model.model.model[-1], 'lrpc')
            if is_prompt_free and self.mode == YOLOEMode.TEXT_PROMPTS:
                raise ValueError(f"Model {model_path} is prompt-free and does not support set_classes(). Use YOLOEMode.PROMPT_FREE.")
            
            logger.info(f"✅ YOLOE loaded on {device} (prompt-free: {is_prompt_free})")
        except Exception as e:
            logger.error(f"❌ Failed to load YOLOE: {e}")
            raise
        
        # Mode-specific initialization
        self.current_classes = []
        self.text_embeddings = None
        self.visual_prompts = None  # Format: {"bboxes": np.array, "cls": np.array}
        self.reference_image = None  # For visual prompts mode
        
        if self.mode == YOLOEMode.PROMPT_FREE:
            # Prompt-free: Built-in 4585+ classes, no setup needed
            logger.info("🔍 [Prompt-Free Mode] Using built-in 4585+ class vocabulary")
            logger.info("   No initialization required - model ready for inference")
            self.prompt_manager = None
        
        elif self.mode == YOLOEMode.TEXT_PROMPTS:
            # Text prompts: Adaptive learning from Gemini/Maps/Memory
            self.prompt_manager = prompt_manager or AdaptivePromptManager()
            
            # Set initial classes (BASE ONLY - no dynamic learning at startup)
            self.current_classes = [
                "person", "car", "phone", "wallet", "keys",
                "door", "stairs", "chair", "table", "bottle",
                "cup", "book", "laptop", "bag", "glasses"
            ]
            logger.info(f"🧠 [Text Prompts Mode] Using {len(self.current_classes)}-class base vocabulary")
            logger.info("   Adaptive learning enabled (Gemini/Maps/Memory integration)")
            # Skip prompt update to avoid 883ms startup delay
            # self._update_classes_internal()
        
        elif self.mode == YOLOEMode.VISUAL_PROMPTS:
            # Visual prompts: Personal object recognition (user's specific items)
            logger.info("👁️ [Visual Prompts Mode] Ready for personal object recognition")
            logger.info("   Use set_visual_prompts() to mark user's objects")
            self.prompt_manager = None
        
        # Performance tracking
        self.inference_times = []
        self.prompt_update_times = []
        
        logger.info("✅ Layer 1 Learner initialized")
        logger.info(f"   Model: {model_path}")
        logger.info(f"   Device: {device}")
        logger.info(f"   Mode: {self.mode.value}")
        logger.info(f"   Confidence: {confidence}")
        if self.mode == YOLOEMode.TEXT_PROMPTS:
            logger.info(f"   Initial Classes: {len(self.current_classes)}")
    
    def switch_to_prompt_free(self):
        """
        Switch to Prompt-Free mode (4585+ built-in classes).
        
        This is a zero-overhead mode switch for discovery queries.
        No prompt loading required - uses built-in vocabulary.
        """
        if self.mode == YOLOEMode.PROMPT_FREE:
            logger.debug("🔄 [MODE SWITCH] Already in PROMPT_FREE mode, skipping")
            return
        
        logger.info("🔄 [MODE SWITCH] PROMPT_FREE mode activated")
        logger.info("   Using 4585+ built-in classes (no prompts needed)")
        
        self.mode = YOLOEMode.PROMPT_FREE
        self.current_classes = []
        self.text_embeddings = None
        self.visual_prompts = None
        
        logger.debug("✅ [MODE SWITCH] Prompt-Free mode ready")
    
    def load_text_prompts(self):
        """
        Switch to Text Prompts mode (adaptive vocabulary).
        
        Loads text embeddings from adaptive_prompts.json.
        Uses Gemini/Maps/Memory learned classes.
        """
        if self.mode == YOLOEMode.TEXT_PROMPTS and self.text_embeddings is not None:
            logger.debug("🔄 [MODE SWITCH] Already in TEXT_PROMPTS mode with embeddings loaded, skipping")
            return
        
        logger.info("🔄 [MODE SWITCH] TEXT_PROMPTS mode activated")
        
        # Load adaptive vocabulary from prompt manager
        if self.prompt_manager:
            self.current_classes = self.prompt_manager.get_all_classes()
            logger.info(f"   Loaded {len(self.current_classes)} adaptive classes")
        else:
            # Fallback to base vocabulary
            self.current_classes = [
                "person", "car", "phone", "wallet", "keys",
                "door", "stairs", "chair", "table", "bottle",
                "cup", "book", "laptop", "bag", "glasses"
            ]
            logger.warning(f"   No prompt manager - using base {len(self.current_classes)}-class vocabulary")
        
        # Generate text embeddings
        try:
            self.text_embeddings = self.model.get_text_pe(self.current_classes)
            self.model.set_classes(self.current_classes, self.text_embeddings)
            logger.debug(f"   Text embeddings generated ({len(self.current_classes)} classes)")
        except Exception as e:
            logger.error(f"❌ [MODE SWITCH] Failed to generate text embeddings: {e}")
            raise
        
        self.mode = YOLOEMode.TEXT_PROMPTS
        self.visual_prompts = None
        
        logger.debug("✅ [MODE SWITCH] Text Prompts mode ready")
    
    def detect(
        self,
        frame: np.ndarray,
        confidence: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Run adaptive object detection (mode-aware).
        
        Behavior depends on mode:
        - PROMPT_FREE: Detect from 4585+ built-in classes
        - TEXT_PROMPTS: Detect using current text vocabulary (Gemini/Maps/Memory)
        - VISUAL_PROMPTS: Detect user's personal objects marked via bounding boxes
        
        Args:
            frame: Input image (H, W, C) as numpy array
            confidence: Override default confidence threshold
            
        Returns:
            List of adaptive detections:
            [
                {
                    'class': 'fire extinguisher',  # Class name
                    'confidence': 0.87,
                    'bbox': [x1, y1, x2, y2],  # Absolute coordinates
                    'bbox_normalized': [x1, y1, x2, y2],  # Normalized [0-1]
                    'bbox_area': 0.12,  # % of frame
                    'mask': np.ndarray,  # Segmentation mask (if available)
                    'source': 'prompt_free' | 'gemini' | 'maps' | 'memory' | 'visual',
                    'mode': 'prompt_free' | 'text_prompts' | 'visual_prompts',
                    'layer': 'learner'
                },
                ...
            ]
        """
        start_time = time.time()
        
        conf = confidence if confidence is not None else self.confidence
        
        try:
            # Run YOLOE inference (mode-specific)
            if self.mode == YOLOEMode.VISUAL_PROMPTS and self.visual_prompts is not None:
                # Visual prompts: Use specialized predictor
                if YOLOEVPSegPredictor is None:
                    raise ImportError("YOLOEVPSegPredictor not available. Update ultralytics.")
                
                kwargs = {
                    "visual_prompts": self.visual_prompts,
                    "predictor": YOLOEVPSegPredictor,
                    "conf": conf,
                    "verbose": False,
                    "device": self.device
                }
                
                # Add reference image if set
                if self.reference_image is not None:
                    kwargs["refer_image"] = self.reference_image
                
                results = self.model(frame, **kwargs)
            else:
                # Prompt-free or text prompts: Standard inference
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
                        
                        # ✅ CONFIDENCE LOGGING: Track detection quality
                        logger.debug(f"   Detected: {class_name} (conf={conf_score:.3f}, mode={self.mode.value})")
                        
                        # Confidence validation by mode
                        if self.mode == YOLOEMode.PROMPT_FREE and conf_score < 0.3:
                            logger.warning(f"⚠️ Low confidence in Prompt-Free mode: {class_name} ({conf_score:.3f}) - Expected: 0.3-0.6")
                        elif self.mode == YOLOEMode.TEXT_PROMPTS and conf_score < 0.5:
                            logger.warning(f"⚠️ Low confidence in Text Prompts mode: {class_name} ({conf_score:.3f}) - Expected: 0.7-0.9")
                        elif self.mode == YOLOEMode.VISUAL_PROMPTS and conf_score < 0.6:
                            logger.warning(f"⚠️ Low confidence in Visual Prompts mode: {class_name} ({conf_score:.3f}) - Expected: 0.6-0.95")
                        
                        # Calculate bbox area
                        bbox_width = bbox[2] - bbox[0]
                        bbox_height = bbox[3] - bbox[1]
                        bbox_area = (bbox_width * bbox_height) / frame_area
                        
                        # Get segmentation mask if available
                        mask = None
                        if hasattr(result, 'masks') and result.masks is not None:
                            if i < len(result.masks.data):
                                mask = result.masks.data[i].cpu().numpy()
                        
                        # Determine source based on mode
                        if self.mode == YOLOEMode.PROMPT_FREE:
                            source = 'prompt_free'
                        elif self.mode == YOLOEMode.VISUAL_PROMPTS:
                            source = 'visual'
                        else:  # TEXT_PROMPTS
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
                            'mode': self.mode.value,
                            'layer': 'learner'
                        })
            
            # Track performance
            latency = (time.time() - start_time) * 1000
            self.inference_times.append(latency)
            
            # ✅ PERFORMANCE METRICS: Detection summary
            avg_conf = sum([d['confidence'] for d in detections]) / len(detections) if detections else 0.0
            logger.info(f"🎯 [LAYER 1] Detected {len(detections)} objects in {latency:.1f}ms (mode={self.mode.value}, avg_conf={avg_conf:.3f})")
            
            # Log individual detections for debugging
            if detections:
                det_summary = ", ".join([f"{d['class']} ({d['confidence']:.2f})" for d in detections[:5]])
                if len(detections) > 5:
                    det_summary += f" + {len(detections) - 5} more"
                logger.debug(f"   Detections: {det_summary}")
            
            return detections
        
        except Exception as e:
            logger.error(f"❌ Layer 1 detection failed: {e}")
            return []
    
    def set_classes(self, class_names: List[str]) -> None:
        """
        Update YOLOE text prompts dynamically (TEXT_PROMPTS mode only).
        
        This is the core method that enables adaptive learning without retraining.
        Text embeddings are computed by MobileCLIP and cached for efficiency.
        
        Args:
            class_names: List of new class names (e.g., ["person", "fire extinguisher", "coffee machine"])
            
        Raises:
            ValueError: If called on prompt-free model
        """
        if self.mode != YOLOEMode.TEXT_PROMPTS:
            raise ValueError(f"set_classes() only works in TEXT_PROMPTS mode. Current mode: {self.mode.value}")
        
        start_time = time.time()
        
        try:
            # Generate text embeddings using MobileCLIP
            logger.debug(f"🔄 Updating YOLOE text prompts: {len(class_names)} classes")
            self.text_embeddings = self.model.get_text_pe(class_names)
            
            # Set classes with embeddings
            self.model.set_classes(class_names, self.text_embeddings)
            self.current_classes = class_names
            
            # Track update time
            update_time = (time.time() - start_time) * 1000
            self.prompt_update_times.append(update_time)
            
            logger.info(f"✅ YOLOE text prompts updated: {len(class_names)} classes ({update_time:.1f}ms)")
            
            # Log warning if update takes too long
            if update_time > 50:
                logger.warning(f"⚠️ Prompt update: {update_time:.1f}ms (target: <50ms)")
        
        except Exception as e:
            logger.error(f"❌ Failed to update YOLOE text prompts: {e}")
    
    def _update_classes_internal(self) -> None:
        """Internal method to update classes from prompt manager."""
        if self.prompt_manager:
            current_prompts = self.prompt_manager.get_current_prompts()
            self.set_classes(current_prompts)
    
    def set_visual_prompts(
        self,
        bboxes: np.ndarray,
        cls: np.ndarray,
        reference_image: Optional[np.ndarray] = None
    ) -> None:
        """
        Set visual prompts for personal object recognition (VISUAL_PROMPTS mode only).
        
        Visual prompts allow the user to "teach" the model by marking objects
        with bounding boxes. This is perfect for recognizing their specific
        wallet, keys, glasses, etc. without needing to name them.
        
        Args:
            bboxes: Bounding boxes [[x1,y1,x2,y2], ...] (absolute coordinates)
            cls: Class IDs [0, 1, 2, ...] (temporary identifiers for each box)
            reference_image: Optional reference image containing the marked objects.
                            If provided, embeddings are permanent (use for "Remember this wallet").
                            If None, prompts are applied to each inference image (one-time detection).
        
        Example (User stores their wallet):
            ```python
            # User says "Remember this wallet" and draws box
            learner.set_visual_prompts(
                bboxes=np.array([[120, 200, 350, 450]]),  # User's wallet box
                cls=np.array([0]),  # ID 0 = "my wallet"
                reference_image=frame  # Current frame becomes reference
            )
            
            # Now all future frames will detect this specific wallet
            detections = learner.detect(new_frame)
            # → [{'class': 'object_0', 'source': 'visual', ...}]
            ```
        
        Raises:
            ValueError: If called on non-visual-prompts model
        """
        if self.mode != YOLOEMode.VISUAL_PROMPTS:
            raise ValueError(f"set_visual_prompts() only works in VISUAL_PROMPTS mode. Current mode: {self.mode.value}")
        
        start_time = time.time()
        
        try:
            # Store visual prompts
            self.visual_prompts = {
                "bboxes": bboxes if isinstance(bboxes, np.ndarray) else np.array(bboxes),
                "cls": cls if isinstance(cls, np.ndarray) else np.array(cls)
            }
            
            # Store reference image if provided (makes prompts permanent)
            if reference_image is not None:
                self.reference_image = reference_image
                logger.info(f"👁️ Visual prompts set with REFERENCE IMAGE (permanent embeddings)")
            else:
                self.reference_image = None
                logger.info(f"👁️ Visual prompts set WITHOUT reference (per-image detection)")
            
            update_time = (time.time() - start_time) * 1000
            self.prompt_update_times.append(update_time)
            
            logger.info(f"✅ Visual prompts updated: {len(cls)} objects ({update_time:.1f}ms)")
            for i, (bbox, class_id) in enumerate(zip(bboxes, cls)):
                logger.info(f"   Object {class_id}: bbox={bbox}")
        
        except Exception as e:
            logger.error(f"❌ Failed to set visual prompts: {e}")
            raise
    
    def get_classes(self) -> List[str]:
        """
        Get current detectable classes (mode-dependent).
        
        Returns:
            - PROMPT_FREE: ["All 4585+ classes available"]
            - TEXT_PROMPTS: List of current class names (15-100 classes)
            - VISUAL_PROMPTS: List of visual prompt IDs (e.g., ["object_0", "object_1"])
        """
        if self.mode == YOLOEMode.PROMPT_FREE:
            return ["All 4585+ classes available (prompt-free mode)"]
        elif self.mode == YOLOEMode.VISUAL_PROMPTS:
            if self.visual_prompts is not None:
                return [f"object_{i}" for i in self.visual_prompts["cls"]]
            return ["No visual prompts set"]
        else:  # TEXT_PROMPTS
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
    
    def switch_mode(self, new_mode: YOLOEMode) -> None:
        """
        Switch between detection modes dynamically.
        
        This allows the system to adapt based on user intent:
        - "Show me everything" → PROMPT_FREE
        - "Describe the scene" → TEXT_PROMPTS (Gemini learning)
        - "Remember this wallet" → VISUAL_PROMPTS (personal objects)
        
        Args:
            new_mode: Target mode
        
        Raises:
            ValueError: If model doesn't support target mode
        """
        if new_mode == self.mode:
            logger.info(f"Already in {new_mode.value} mode")
            return
        
        logger.info(f"🔄 Switching mode: {self.mode.value} → {new_mode.value}")
        
        # Validate model supports target mode
        is_prompt_free = hasattr(self.model.model.model[-1], 'lrpc')
        if is_prompt_free and new_mode == YOLOEMode.TEXT_PROMPTS:
            raise ValueError(f"Model {self.model_path} is prompt-free and does not support TEXT_PROMPTS mode")
        
        # Switch mode
        old_mode = self.mode
        self.mode = new_mode
        
        # Reset mode-specific state
        if new_mode == YOLOEMode.PROMPT_FREE:
            self.current_classes = []
            self.text_embeddings = None
            self.visual_prompts = None
            self.reference_image = None
            logger.info("🔍 Switched to PROMPT_FREE: 4585+ classes available")
        
        elif new_mode == YOLOEMode.TEXT_PROMPTS:
            if old_mode == YOLOEMode.PROMPT_FREE:
                # Initialize prompt manager if needed
                if self.prompt_manager is None:
                    self.prompt_manager = AdaptivePromptManager()
                self.current_classes = self.prompt_manager.get_current_prompts()
            self.visual_prompts = None
            self.reference_image = None
            logger.info(f"🧠 Switched to TEXT_PROMPTS: {len(self.current_classes)} classes")
        
        elif new_mode == YOLOEMode.VISUAL_PROMPTS:
            self.current_classes = []
            self.text_embeddings = None
            logger.info("👁️ Switched to VISUAL_PROMPTS: Ready for personal objects")
        
        logger.info(f"✅ Mode switch complete: {old_mode.value} → {new_mode.value}")
    
    def cleanup(self) -> None:
        """Release resources."""
        logger.info("🧹 Cleaning up Layer 1 Learner...")
        # YOLOE model cleanup handled by ultralytics
        logger.info("✅ Layer 1 Learner cleaned up")
    
    def load_visual_prompts_from_memory(self, memory_id: str):
        """
        Load visual prompts from Layer 4 memory for personal object detection.
        
        This method integrates Layer 1 (Learner) with Layer 4 (Memory) for
        cross-session visual prompt persistence.
        
        Args:
            memory_id: Memory ID (e.g., "wallet_003")
            
        Example:
            >>> from layer1_learner.visual_prompt_manager import VisualPromptManager
            >>> vpm = VisualPromptManager()
            >>> learner.load_visual_prompts_from_memory("wallet_003")
            >>> # Now learner is in VISUAL_PROMPTS mode, ready to detect user's wallet
        """
        try:
            from layer1_learner.visual_prompt_manager import VisualPromptManager
            
            vpm = VisualPromptManager()
            prompt = vpm.load_visual_prompt(memory_id)
            
            if prompt:
                # Load visual embeddings
                vpe = vpm.get_visual_embedding(memory_id)
                
                if vpe is not None:
                    # Set classes with visual embeddings
                    self.model.set_classes([prompt.object_name], vpe)
                    
                    # Store prompts for inference
                    self.visual_prompts = {
                        "bboxes": [prompt.bboxes],
                        "cls": [prompt.cls]
                    }
                    
                    # Store reference image path
                    self.reference_image = prompt.reference_image_path
                    
                    # Update mode
                    self.mode = YOLOEMode.VISUAL_PROMPTS
                    self.current_classes = [prompt.object_name]
                    
                    logger.info(f"✅ Visual prompts loaded: {prompt.object_name} ({memory_id})")
                    logger.info(f"   Bboxes: {prompt.bboxes.shape}")
                    logger.info(f"   SLAM coords: {prompt.slam_coordinates}")
                else:
                    logger.error(f"❌ Failed to load visual embedding for {memory_id}")
            else:
                logger.warning(f"⚠️ Visual prompt not found: {memory_id}")
                
        except ImportError:
            logger.error("❌ VisualPromptManager not available. Ensure visual_prompt_manager.py exists.")
        except Exception as e:
            logger.error(f"❌ Failed to load visual prompts: {e}", exc_info=True)


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
