"""
Hailo 8L OCR Pipeline — Two-Stage Text Recognition

Stage 1: CPU-based text detection via PaddleOCR (detects text bounding boxes)
Stage 2: Hailo NPU text recognition via paddle_ocr_v3_recognition.hef (123 FPS)

Lazy-loads PaddleOCR on first use to save ~200MB RAM at startup.
Shared Hailo VDevice with depth model (HailoRT handles time-multiplexing).

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ─── Hailo Runtime Import (graceful degradation) ────────────────────────────
try:
    from hailo_platform import (
        HEF,
        VDevice,
        HailoStreamInterface,
        ConfigureParams,
        InputVStreamParams,
        OutputVStreamParams,
        FormatType,
    )
    HAILO_AVAILABLE = True
except ImportError:
    HAILO_AVAILABLE = False
    logger.warning("hailo_platform not available — Hailo OCR recognition disabled")


# ─── Character Dictionary ────────────────────────────────────────────────────
# PaddleOCR v3 recognition model uses this character set for CTC decoding.
# Index 0 = blank token (CTC), characters start at index 1.
PADDLE_OCR_CHARS = (
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    " "
)


# ─── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class TextResult:
    """A detected and recognized text region."""
    text: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2 in original frame coords


# ─── OCR Pipeline ────────────────────────────────────────────────────────────

class HailoOCRPipeline:
    """
    Two-stage OCR pipeline for Hailo-8L NPU.
    
    Stage 1 (CPU): PaddleOCR text detection — finds text bounding boxes
    Stage 2 (NPU): Hailo recognition via paddle_ocr_v3_recognition.hef — reads text
    
    Features:
    - Lazy-loads PaddleOCR on first OCR query (saves ~200MB RAM)
    - CTC greedy decoder for recognition output
    - Shared Hailo device with depth model (time-multiplexed)
    - Returns structured TextResult list + speech-ready formatting
    """

    # Recognition model input dimensions (PaddleOCR v3)
    REC_HEIGHT = 48
    REC_WIDTH = 320
    REC_CHANNELS = 3

    def __init__(
        self,
        recognition_hef_path: str = "models/hailo/paddle_ocr_v3_recognition.hef",
        confidence_threshold: float = 0.5,
        max_text_regions: int = 20,
    ):
        """
        Initialize the OCR pipeline.
        
        Args:
            recognition_hef_path: Path to PaddleOCR v3 recognition HEF
            confidence_threshold: Minimum confidence for recognized text
            max_text_regions: Maximum text regions to process per frame
        """
        self.recognition_hef_path = recognition_hef_path
        self.confidence_threshold = confidence_threshold
        self.max_text_regions = max_text_regions

        # PaddleOCR detector (lazy-loaded)
        self._detector = None
        self._detector_loaded = False

        # Hailo recognition model
        self._rec_hef = None
        self._rec_vdevice = None
        self._rec_network_group = None
        self._rec_input_info = None
        self._rec_output_info = None
        self._rec_initialized = False

        # Character dictionary for CTC decoding
        self._chars = list(PADDLE_OCR_CHARS)
        self._char_to_idx = {c: i + 1 for i, c in enumerate(self._chars)}

        # Latency tracking
        self._latency_history: List[float] = []

        # Initialize Hailo recognition
        if HAILO_AVAILABLE:
            self._init_recognition()

    def _init_recognition(self):
        """Load Hailo recognition HEF and configure streams."""
        try:
            hef_path = Path(self.recognition_hef_path)
            if not hef_path.exists():
                logger.warning(f"OCR recognition HEF not found: {hef_path}")
                return

            logger.info(f"Loading Hailo OCR recognition model: {hef_path}")

            self._rec_hef = HEF(str(hef_path))
            self._rec_vdevice = VDevice()

            configure_params = ConfigureParams.create_from_hef(
                hef=self._rec_hef,
                interface=HailoStreamInterface.PCIe,
            )
            self._rec_network_group = self._rec_vdevice.configure(
                self._rec_hef, configure_params
            )[0]

            self._rec_input_info = self._rec_hef.get_input_vstream_infos()
            self._rec_output_info = self._rec_hef.get_output_vstream_infos()

            for info in self._rec_input_info:
                logger.info(f"  OCR Input: {info.name}, shape={info.shape}")
            for info in self._rec_output_info:
                logger.info(f"  OCR Output: {info.name}, shape={info.shape}")

            self._rec_initialized = True
            logger.info("Hailo OCR recognition model initialized")

        except Exception as e:
            logger.error(f"Failed to initialize Hailo OCR recognition: {e}")
            self._rec_initialized = False

    def _lazy_load_detector(self):
        """
        Lazy-load PaddleOCR text detection on first use.
        
        This saves ~200MB RAM at startup since OCR is only needed
        when the user asks "read this" or "what does it say".
        """
        if self._detector_loaded:
            return

        try:
            from paddleocr import PaddleOCR

            logger.info("Lazy-loading PaddleOCR text detector (~200MB)...")
            start = time.perf_counter()

            # det=True, rec=False: only load the detection model
            # We handle recognition on Hailo NPU
            self._detector = PaddleOCR(
                use_angle_cls=False,
                lang="en",
                det=True,
                rec=False,
                cls=False,
                show_log=False,
                use_gpu=False,  # CPU only on RPi5
            )

            elapsed = time.perf_counter() - start
            logger.info(f"PaddleOCR detector loaded in {elapsed:.1f}s")
            self._detector_loaded = True

        except ImportError:
            logger.error(
                "paddleocr not installed. Run: pip install paddleocr paddlepaddle"
            )
            self._detector_loaded = True  # Don't retry
            self._detector = None
        except Exception as e:
            logger.error(f"Failed to load PaddleOCR detector: {e}")
            self._detector_loaded = True
            self._detector = None

    @property
    def is_available(self) -> bool:
        """Whether the full OCR pipeline is ready (or can be loaded)."""
        return HAILO_AVAILABLE and self._rec_initialized

    @property
    def avg_latency_ms(self) -> float:
        """Average end-to-end OCR latency in milliseconds."""
        if not self._latency_history:
            return 0.0
        return sum(self._latency_history[-20:]) / len(self._latency_history[-20:])

    def read_text(self, frame: np.ndarray) -> List[TextResult]:
        """
        Run full OCR pipeline on a frame.
        
        Stage 1: Detect text regions (CPU, ~50-100ms)
        Stage 2: Recognize text in each region (Hailo NPU, ~8ms/region)
        
        Args:
            frame: BGR image from camera (any resolution)
            
        Returns:
            List of TextResult objects with recognized text, confidence, and bbox
        """
        if not self.is_available:
            logger.warning("OCR pipeline not available")
            return []

        start = time.perf_counter()
        results: List[TextResult] = []

        # ── Stage 1: Text Detection (CPU) ─────────────────────────────────
        self._lazy_load_detector()
        if self._detector is None:
            return []

        try:
            det_result = self._detector.ocr(frame, det=True, rec=False, cls=False)
        except Exception as e:
            logger.error(f"OCR detection failed: {e}")
            return []

        if not det_result or not det_result[0]:
            logger.debug("No text regions detected")
            return []

        # Extract bounding boxes from PaddleOCR detection output
        # Format: list of [4 corner points] — convert to x1,y1,x2,y2
        text_boxes = []
        for box_points in det_result[0][:self.max_text_regions]:
            if len(box_points) < 4:
                continue
            pts = np.array(box_points, dtype=np.float32)
            x1 = int(np.min(pts[:, 0]))
            y1 = int(np.min(pts[:, 1]))
            x2 = int(np.max(pts[:, 0]))
            y2 = int(np.max(pts[:, 1]))
            # Filter tiny boxes
            if (x2 - x1) < 5 or (y2 - y1) < 5:
                continue
            text_boxes.append((x1, y1, x2, y2))

        if not text_boxes:
            return []

        logger.debug(f"OCR: {len(text_boxes)} text regions detected")

        # ── Stage 2: Text Recognition (Hailo NPU) ────────────────────────
        for x1, y1, x2, y2 in text_boxes:
            # Crop text region from frame
            h, w = frame.shape[:2]
            cx1 = max(0, x1)
            cy1 = max(0, y1)
            cx2 = min(w, x2)
            cy2 = min(h, y2)
            crop = frame[cy1:cy2, cx1:cx2]

            if crop.size == 0:
                continue

            # Recognize text in this crop
            text, confidence = self._recognize_text(crop)

            if text and confidence >= self.confidence_threshold:
                results.append(TextResult(
                    text=text,
                    confidence=round(confidence, 3),
                    bbox=(x1, y1, x2, y2),
                ))

        elapsed_ms = (time.perf_counter() - start) * 1000
        self._latency_history.append(elapsed_ms)
        if len(self._latency_history) > 50:
            self._latency_history = self._latency_history[-25:]

        logger.info(
            f"OCR: {len(results)} text regions recognized in {elapsed_ms:.0f}ms"
        )
        return results

    def _recognize_text(self, crop: np.ndarray) -> Tuple[str, float]:
        """
        Recognize text in a single cropped text region using Hailo NPU.
        
        Args:
            crop: BGR image crop containing text
            
        Returns:
            (recognized_text, confidence) tuple
        """
        try:
            # Preprocess: resize to model input (48 x 320), keep aspect ratio
            h, w = crop.shape[:2]
            ratio = self.REC_HEIGHT / h
            new_w = min(int(w * ratio), self.REC_WIDTH)
            resized = cv2.resize(crop, (new_w, self.REC_HEIGHT), interpolation=cv2.INTER_LINEAR)

            # Convert BGR to RGB, normalize to [0, 1]
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            input_data = rgb.astype(np.float32) / 255.0

            # Pad to full width (320) with zeros
            padded = np.zeros(
                (self.REC_HEIGHT, self.REC_WIDTH, self.REC_CHANNELS),
                dtype=np.float32,
            )
            padded[:, :new_w, :] = input_data

            # Add batch dimension: (1, 48, 320, 3)
            batch = np.expand_dims(padded, axis=0)

            # Run Hailo inference
            input_params = InputVStreamParams.make(
                self._rec_network_group,
                format_type=FormatType.FLOAT32,
            )
            output_params = OutputVStreamParams.make(
                self._rec_network_group,
                format_type=FormatType.FLOAT32,
            )

            with self._rec_network_group.activate():
                input_dict = {self._rec_input_info[0].name: batch}
                raw_output = self._rec_network_group.infer(input_dict)

            # Extract output logits
            output_name = self._rec_output_info[0].name
            logits = raw_output[output_name]  # shape: (1, T, num_classes)
            logits = np.squeeze(logits, axis=0)  # (T, num_classes)

            # CTC greedy decode
            text, confidence = self._ctc_decode(logits)
            return text, confidence

        except Exception as e:
            logger.debug(f"OCR recognition failed for crop: {e}")
            return "", 0.0

    def _ctc_decode(self, logits: np.ndarray) -> Tuple[str, float]:
        """
        CTC greedy decoder for recognition output.
        
        Args:
            logits: (T, num_classes) raw logits from recognition model
            
        Returns:
            (decoded_text, average_confidence) tuple
        """
        # Softmax to get probabilities
        exp_logits = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
        probs = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)

        # Greedy: pick highest prob at each timestep
        indices = np.argmax(probs, axis=-1)  # (T,)
        max_probs = np.max(probs, axis=-1)  # (T,)

        # CTC collapse: remove blanks (index 0) and consecutive duplicates
        chars = []
        confidences = []
        prev_idx = -1

        for t in range(len(indices)):
            idx = int(indices[t])
            if idx == 0:
                # Blank token — reset prev to allow same char after blank
                prev_idx = -1
                continue
            if idx == prev_idx:
                # Consecutive duplicate — skip
                continue
            
            # Valid character
            char_idx = idx - 1  # Characters start at index 1 in model output
            if 0 <= char_idx < len(self._chars):
                chars.append(self._chars[char_idx])
                confidences.append(float(max_probs[t]))
            prev_idx = idx

        text = "".join(chars).strip()
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return text, avg_conf

    def format_for_speech(self, results: List[TextResult]) -> str:
        """
        Format OCR results for TTS output.
        
        Args:
            results: List of TextResult from read_text()
            
        Returns:
            Speech-ready string, e.g., "I can read: Exit, Floor 3, Push."
        """
        if not results:
            return ""

        # Deduplicate and filter
        seen = set()
        unique_texts = []
        for r in results:
            normalized = r.text.strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                unique_texts.append(normalized)

        if not unique_texts:
            return ""

        if len(unique_texts) == 1:
            return f"I can read: {unique_texts[0]}."
        elif len(unique_texts) == 2:
            return f"I can read: {unique_texts[0]} and {unique_texts[1]}."
        else:
            items = ", ".join(unique_texts[:-1])
            return f"I can read: {items}, and {unique_texts[-1]}."

    def cleanup(self):
        """Release Hailo and PaddleOCR resources."""
        try:
            if self._rec_network_group:
                self._rec_network_group = None
            if self._rec_vdevice:
                self._rec_vdevice = None
            self._rec_initialized = False
            self._detector = None
            self._detector_loaded = False
            logger.info("Hailo OCR pipeline cleaned up")
        except Exception as e:
            logger.warning(f"OCR cleanup error: {e}")
