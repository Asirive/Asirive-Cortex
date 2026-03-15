"""
Hailo 8L OCR Pipeline — Two-Stage Text Recognition

Stage 1: CPU-based text detection via OpenCV morphological ops (zero dependencies)
Stage 2: Hailo NPU text recognition via paddle_ocr_v3_recognition.hef (91 FPS)

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
    from hailo_platform import VDevice, FormatType
    HAILO_AVAILABLE = True
except ImportError:
    HAILO_AVAILABLE = False
    logger.warning("hailo_platform not available — Hailo OCR recognition disabled")


# ─── Character Dictionary ────────────────────────────────────────────────────
# PaddleOCR v3 recognition model character set for CTC decoding.
# Index 0 = CTC blank token. Characters follow ASCII order starting from '0'.
PADDLE_OCR_CHARS = (
    "0123456789"                    # idx 1-10  (ASCII 48-57)
    ":;<=>?@"                       # idx 11-17 (ASCII 58-64)
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"    # idx 18-43 (ASCII 65-90)
    "[\\]^_`"                       # idx 44-49 (ASCII 91-96)
    "abcdefghijklmnopqrstuvwxyz"    # idx 50-75 (ASCII 97-122)
    "{|}~"                          # idx 76-79 (ASCII 123-126)
    " !\"#$%&'()*+,-./"            # idx 80-95 (ASCII 32-47)
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
    
    Stage 1 (CPU): OpenCV morphological text detection — finds text bounding boxes
    Stage 2 (NPU): Hailo recognition via paddle_ocr_v3_recognition.hef — reads text
    
    Features:
    - Zero external dependencies for text detection (pure OpenCV)
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
        vdevice=None,
    ):
        """
        Initialize the OCR pipeline.
        
        Args:
            recognition_hef_path: Path to PaddleOCR v3 recognition HEF
            confidence_threshold: Minimum confidence for recognized text
            max_text_regions: Maximum text regions to process per frame
            vdevice: Shared Hailo VDevice (if None, creates its own — will fail
                     if another module already holds the device)
        """
        self.recognition_hef_path = recognition_hef_path
        self.confidence_threshold = confidence_threshold
        self.max_text_regions = max_text_regions

        # OpenCV text detector (lazy-loaded)
        self._detector = None
        self._detector_loaded = False
        self._east_net = None  # OpenCV EAST text detector (optional, better accuracy)

        # Hailo recognition model (modern create_infer_model API)
        self._rec_vdevice = None
        self._rec_owns_vdevice = False  # True if we created the VDevice ourselves
        self._external_vdevice = vdevice  # Shared VDevice from caller
        self._rec_infer_model = None
        self._rec_configured_model = None
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
        """Load Hailo recognition HEF using modern create_infer_model API."""
        try:
            hef_path = Path(self.recognition_hef_path)
            if not hef_path.exists():
                logger.warning(f"OCR recognition HEF not found: {hef_path}")
                return

            logger.info(f"Loading Hailo OCR recognition model: {hef_path}")

            # Use shared VDevice or create our own
            if self._external_vdevice is not None:
                self._rec_vdevice = self._external_vdevice
                self._rec_owns_vdevice = False
                logger.info("  OCR using shared Hailo VDevice")
            else:
                self._rec_vdevice = VDevice()
                self._rec_owns_vdevice = True
                logger.info("  OCR created dedicated Hailo VDevice")

            # Modern API: create_infer_model from HEF path
            self._rec_infer_model = self._rec_vdevice.create_infer_model(str(hef_path))
            self._rec_infer_model.input().set_format_type(FormatType.FLOAT32)
            self._rec_infer_model.output().set_format_type(FormatType.FLOAT32)

            logger.info(f"  OCR Input: shape={self._rec_infer_model.input().shape}")
            logger.info(f"  OCR Output: shape={self._rec_infer_model.output().shape}")

            # Configure once, keep alive for all calls
            self._rec_configured_model = self._rec_infer_model.configure()
            logger.info("  OCR ConfiguredInferModel ready (persistent)")

            self._rec_initialized = True
            logger.info("Hailo OCR recognition model initialized")

        except Exception as e:
            logger.error(f"Failed to initialize Hailo OCR recognition: {e}")
            self._rec_initialized = False

    def _lazy_load_detector(self):
        """
        Initialize text detection using OpenCV morphological approach.

        Zero external dependencies — uses adaptive thresholding, dilation,
        and contour analysis to find text-like regions. Fast (~5-15ms on RPi5).
        """
        if self._detector_loaded:
            return

        logger.info("Text detector ready (OpenCV morphological, zero-dep)")
        self._detector = True  # Flag that detector is ready
        self._detector_loaded = True

    def _detect_text_regions(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detect text regions using OpenCV morphological operations.

        Pipeline:
        1. Convert to grayscale
        2. Apply MSER (Maximally Stable Extremal Regions) for character candidates
        3. Group nearby regions into text lines via dilation
        4. Filter by aspect ratio and size

        Args:
            frame: BGR image

        Returns:
            List of (x1, y1, x2, y2) bounding boxes around text regions
        """
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Approach: adaptive threshold + morphological grouping
        # This works well for clear signage, labels, and printed text
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 15, 8
        )

        # Dilate to merge nearby characters into text lines
        # Horizontal kernel groups characters in a line
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        dilated = cv2.dilate(binary, kernel_h, iterations=2)

        # Find contours of text regions
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        text_boxes = []
        min_area = (h * w) * 0.0005  # Min 0.05% of frame
        max_area = (h * w) * 0.5     # Max 50% of frame

        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh

            if area < min_area or area > max_area:
                continue

            # Text regions are typically wider than tall
            aspect = bw / max(bh, 1)
            if aspect < 1.2 or aspect > 30:
                continue

            # Min height to avoid noise
            if bh < 10:
                continue

            # Add padding
            pad = 4
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w, x + bw + pad)
            y2 = min(h, y + bh + pad)
            text_boxes.append((x1, y1, x2, y2))

        # Sort by y-position (top to bottom), then x (left to right)
        text_boxes.sort(key=lambda b: (b[1] // 30, b[0]))

        return text_boxes[:self.max_text_regions]

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

        # ── Stage 1: Text Detection (CPU, OpenCV morphological) ───────────
        self._lazy_load_detector()
        if self._detector is None:
            return []

        text_boxes = self._detect_text_regions(frame)

        if not text_boxes:
            logger.debug("No text regions detected")
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

            # Convert BGR to RGB, normalize to [-1, 1] (PaddleOCR v3 standard)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            input_data = (rgb.astype(np.float32) / 255.0 - 0.5) / 0.5

            # Pad to full width (320) with -1.0 (normalized black)
            padded = np.full(
                (self.REC_HEIGHT, self.REC_WIDTH, self.REC_CHANNELS),
                -1.0,
                dtype=np.float32,
            )
            padded[:, :new_w, :] = input_data

            # Add batch dimension: (1, 48, 320, 3)
            batch = np.expand_dims(padded, axis=0)

            # Run Hailo inference using modern bindings API
            bindings = self._rec_configured_model.create_bindings()
            bindings.input().set_buffer(batch)
            output_buffer = np.empty(self._rec_infer_model.output().shape, dtype=np.float32)
            bindings.output().set_buffer(output_buffer)
            self._rec_configured_model.run([bindings], 5000)

            # Extract output logits
            logits = output_buffer  # shape: (1, T, num_classes) or (T, num_classes)
            if logits.ndim == 3:
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
            logits: (T, num_classes) — may be raw logits OR post-softmax probs
            
        Returns:
            (decoded_text, average_confidence) tuple
        """
        # Check if output is already post-softmax (all values in [0,1] and rows sum to ~1)
        row_sums = np.sum(logits, axis=-1)
        if np.allclose(row_sums, 1.0, atol=0.1):
            probs = logits  # Already softmax
        else:
            # Apply softmax
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
        """Release Hailo resources."""
        try:
            # Release configured model
            if self._rec_configured_model:
                try:
                    self._rec_configured_model.shutdown()
                except Exception as e:
                    logger.debug(f"OCR ConfiguredInferModel shutdown error (non-fatal): {e}")
                self._rec_configured_model = None
            self._rec_infer_model = None
            # Only release VDevice if we created it ourselves
            if self._rec_owns_vdevice and self._rec_vdevice:
                self._rec_vdevice = None
            self._rec_initialized = False
            self._detector = None
            self._detector_loaded = False
            logger.info("Hailo OCR pipeline cleaned up")
        except Exception as e:
            logger.warning(f"OCR cleanup error: {e}")
