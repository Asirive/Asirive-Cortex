"""
GGUF Export (llama.cpp fallback)

Convert the ONNX or PyTorch model to GGUF for CPU inference on RPi5
via llama.cpp or similar runtime.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
import sys
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


def export_to_gguf(
    checkpoint_path: str,
    output_path: str = "models/cortex_local/cortex_local.gguf",
    vocab_size: int = 32000,
    d_model: int = 512,
    n_layer: int = 12,
):
    """
    Export to GGUF for llama.cpp CPU inference.

    NOTE: This is a placeholder. Actual GGUF conversion requires:
    - Either converting the Mamba-2 weights to a llama.cpp-compatible format
    - Or using a custom inference engine (onnxruntime with Mamba state management)

    For now, we recommend onnxruntime CPU as the primary fallback path.
    GGUF is only useful if we switch the core to a standard Transformer.
    """
    logger.warning("GGUF export is a placeholder. Use ONNX + onnxruntime for now.")
    # TODO: implement with gguf-py or llama.cpp conversion tools if needed
    pass


if __name__ == "__main__":
    export_to_gguf(
        checkpoint_path="outputs/stage5/ckpt_int8_final.pt",
        output_path="models/cortex_local/cortex_local.gguf",
    )
