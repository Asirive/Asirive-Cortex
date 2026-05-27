"""
ONNX Export

Export the trained PyTorch model to ONNX with static shapes for Hailo parsing.
Handles Mamba state I/O binding for streaming compatibility.

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

from training.models.cortex_local import CortexLocalModel

logger = logging.getLogger(__name__)


def export_to_onnx(
    checkpoint_path: str,
    output_path: str = "models/cortex_local/cortex_local.onnx",
    vocab_size: int = 32000,
    d_model: int = 512,
    n_layer: int = 12,
    d_state: int = 64,
    d_conv: int = 4,
    expand: int = 2,
    seq_len: int = 256,
):
    """
    Export CortexLocalModel to ONNX.

    Args:
        checkpoint_path: path to trained .pt checkpoint
        output_path: destination ONNX file
        seq_len: maximum sequence length to export (Hailo needs static shapes)
    """
    device = torch.device("cpu")
    model = CortexLocalModel(
        vocab_size=vocab_size,
        d_model=d_model,
        n_layer=n_layer,
        d_state=d_state,
        d_conv=d_conv,
        expand=expand,
    ).to(device)
    model.load_state_dict(torch.load(checkpoint_path, map_location=device))
    model.eval()

    # Dummy inputs
    dummy_video = torch.randn(1, 3, 224, 224)
    dummy_audio = torch.randn(1, 1, 80, 100)
    dummy_tokens = torch.randint(0, vocab_size, (1, seq_len))
    dummy_conv = torch.zeros(n_layer, 1, d_model, d_conv)
    dummy_ssm = torch.zeros(n_layer, 1, d_model, d_state)

    # Wrap model to accept tuple and return dict as flat tensors for ONNX
    class WrappedModel(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, video, audio, tokens, conv_state, ssm_state):
            out = self.inner(
                video=video,
                audio=audio,
                text_tokens=tokens,
                conv_state=[conv_state[i] for i in range(conv_state.size(0))],
                ssm_state=[ssm_state[i] for i in range(ssm_state.size(0))],
            )
            # Stack lists back to tensors for ONNX compatibility
            next_conv = torch.stack(out["next_conv_state"], dim=0)
            next_ssm = torch.stack(out["next_ssm_state"], dim=0)
            return (
                out["logits"],
                out["mode_logits"],
                out["tool_logits"],
                next_conv,
                next_ssm,
            )

    wrapped = WrappedModel(model)
    wrapped.eval()

    torch.onnx.export(
        wrapped,
        (dummy_video, dummy_audio, dummy_tokens, dummy_conv, dummy_ssm),
        output_path,
        input_names=["video", "audio", "tokens", "conv_state", "ssm_state"],
        output_names=["logits", "mode_logits", "tool_logits", "next_conv", "next_ssm"],
        dynamic_axes={
            "tokens": {1: "seq_len"},
            "logits": {1: "seq_len"},
        },
        opset_version=17,
        do_constant_folding=True,
    )
    logger.info(f"ONNX exported to {output_path}")


if __name__ == "__main__":
    export_to_onnx(
        checkpoint_path="outputs/stage5/ckpt_int8_final.pt",
        output_path="models/cortex_local/cortex_local.onnx",
    )
