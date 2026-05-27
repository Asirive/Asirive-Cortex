"""
Inference Engine Abstraction

Wraps ONNXRuntime (CPU) or Hailo (NPU) inference backends.
Provides a unified interface for the CortexLocal runtime.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Optional, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

_ONNX_AVAILABLE = False
try:
    import onnxruntime as ort
    _ONNX_AVAILABLE = True
except ImportError:
    logger.warning("onnxruntime not installed. ONNX backend unavailable.")

_HAILO_AVAILABLE = False
try:
    from hailo_platform import VDevice, InferModel
    _HAILO_AVAILABLE = True
except ImportError:
    logger.warning("hailo_platform not installed. Hailo backend unavailable.")


class InferenceEngine:
    """
    Unified inference backend for CortexLocal.

    Supports:
    - onnxruntime (CPU / ARM)
    - Hailo NPU (when available)
    """

    def __init__(self, config: dict, vdevice=None):
        self.config = config
        self.backend = config.get("inference", {}).get("backend", "onnx")
        self.vdevice = vdevice
        self.session = None
        self.infer_model = None
        self._loaded = False

        # TODO: load tokenizer (SmolLM2 / custom)
        self.tokenizer = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self):
        """Load model weights and initialize backend."""
        if self.backend == "onnx":
            self._load_onnx()
        elif self.backend == "hailo":
            self._load_hailo()
        else:
            raise ValueError(f"Unknown backend: {self.backend}")
        self._loaded = True
        logger.info(f"InferenceEngine loaded with backend={self.backend}")

    def unload(self):
        """Release resources."""
        self.session = None
        self.infer_model = None
        self._loaded = False

    def _load_onnx(self):
        if not _ONNX_AVAILABLE:
            raise RuntimeError("onnxruntime not installed.")
        path = self.config["model"]["onnx_path"]
        providers = self.config.get("inference", {}).get("providers", ["CPUExecutionProvider"])
        self.session = ort.InferenceSession(path, providers=providers)
        logger.info(f"ONNX session loaded: {path}")

    def _load_hailo(self):
        if not _HAILO_AVAILABLE:
            raise RuntimeError("hailo_platform not installed.")
        path = self.config["model"]["hef_path"]
        vdev = self.vdevice
        if vdev is None:
            vdev = VDevice()
        self.infer_model = InferModel(vdev, path)
        logger.info(f"Hailo infer model loaded: {path}")

    def run(
        self,
        video: Optional[np.ndarray] = None,
        audio: Optional[np.ndarray] = None,
        tokens: Optional[np.ndarray] = None,
        conv_state: Optional[np.ndarray] = None,
        ssm_state: Optional[np.ndarray] = None,
    ) -> Dict[str, np.ndarray]:
        """
        Run one inference step.

        Args:
            video: [3, 224, 224] or None
            audio: [1, 80, 100] or None
            tokens: [L] token IDs
            conv_state: [n_layer, d_model, d_conv]
            ssm_state: [n_layer, d_model, d_state]
        Returns:
            dict with logits, mode_logits, tool_logits, next_conv, next_ssm
        """
        if self.backend == "onnx":
            return self._run_onnx(video, audio, tokens, conv_state, ssm_state)
        elif self.backend == "hailo":
            return self._run_hailo(video, audio, tokens, conv_state, ssm_state)
        else:
            raise RuntimeError("Backend not loaded.")

    def _run_onnx(self, video, audio, tokens, conv_state, ssm_state):
        # Add batch dimension if missing
        def _add_batch(x):
            return x[np.newaxis, ...] if x is not None and x.ndim < 3 else x

        inputs = {
            "video": _add_batch(video) if video is not None else np.zeros((1, 3, 224, 224), dtype=np.float32),
            "audio": _add_batch(audio) if audio is not None else np.zeros((1, 1, 80, 100), dtype=np.float32),
            "tokens": tokens.astype(np.int64)[np.newaxis, ...] if tokens is not None else np.zeros((1, 1), dtype=np.int64),
            "conv_state": conv_state.astype(np.float32) if conv_state is not None else np.zeros((12, 1, 512, 4), dtype=np.float32),
            "ssm_state": ssm_state.astype(np.float32) if ssm_state is not None else np.zeros((12, 1, 512, 64), dtype=np.float32),
        }
        logits, mode_logits, tool_logits, next_conv, next_ssm = self.session.run(None, inputs)
        return {
            "logits": logits,
            "mode_logits": mode_logits,
            "tool_logits": tool_logits,
            "next_conv": next_conv,
            "next_ssm": next_ssm,
        }

    def _run_hailo(self, video, audio, tokens, conv_state, ssm_state):
        # TODO: implement Hailo tensor binding
        logger.warning("Hailo run not yet implemented.")
        return self._run_onnx(video, audio, tokens, conv_state, ssm_state)

    def tokenize(self, text: str) -> np.ndarray:
        """Encode text to token IDs."""
        # TODO: implement with tokenizer
        return np.array([0], dtype=np.int64)

    def detokenize(self, token_ids: List[int]) -> str:
        """Decode token IDs to text."""
        # TODO: implement with tokenizer
        return ""
