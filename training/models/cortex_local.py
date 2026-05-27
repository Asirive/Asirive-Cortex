"""
CortexLocal Full Model Assembly

Assembles vision tower, audio tower, text embedder, Mamba-2 fusion core,
and output heads into the complete multimodal model.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Dict, Optional, Tuple, List

import torch
import torch.nn as nn
import torch.nn.functional as F

from training.models.vision_tower import VisionTower
from training.models.audio_tower import AudioTower
from training.models.mamba_core import MambaFusionCore
from training.models.heads import OutputHeads

logger = logging.getLogger(__name__)


class CortexLocalModel(nn.Module):
    """
    End-to-end multimodal model: (video, audio, text) -> (text, mode, tool)
    """

    def __init__(
        self,
        vocab_size: int = 32000,
        d_model: int = 512,
        n_layer: int = 12,
        d_state: int = 64,
        d_conv: int = 4,
        expand: int = 2,
        num_tools: int = 14,
        freeze_vision: bool = False,
        freeze_audio: bool = False,
    ):
        super().__init__()
        self.d_model = d_model
        self.n_layer = n_layer

        # Encoders
        self.vision_tower = VisionTower(proj_dim=d_model, freeze_backbone=freeze_vision)
        self.audio_tower = AudioTower(proj_dim=d_model, freeze_backbone=freeze_audio)
        self.text_embedder = nn.Embedding(vocab_size, d_model)

        # Fusion core
        self.fusion_core = MambaFusionCore(
            d_model=d_model,
            d_state=d_state,
            d_conv=d_conv,
            expand=expand,
            n_layer=n_layer,
        )

        # Heads
        self.heads = OutputHeads(
            d_model=d_model,
            vocab_size=vocab_size,
            num_modes=4,
            num_tools=num_tools,
        )

    def forward(
        self,
        video: Optional[torch.Tensor] = None,
        audio: Optional[torch.Tensor] = None,
        text_tokens: Optional[torch.Tensor] = None,
        conv_state: Optional[List[torch.Tensor]] = None,
        ssm_state: Optional[List[torch.Tensor]] = None,
    ) -> Dict[str, torch.Tensor]:
        """
        Args:
            video:       [B, 3, 224, 224] or None
            audio:       [B, 1, 80, 100] or None
            text_tokens: [B, L_text] or None
            conv_state:  list of [B, d_model, d_conv] or None
            ssm_state:   list of [B, d_model, d_state] or None
        Returns:
            dict with logits, mode_logits, tool_logits, next_conv, next_ssm
        """
        tokens = []

        if video is not None:
            vis_tokens = self.vision_tower(video)  # [B, 196, d_model]
            tokens.append(vis_tokens)

        if audio is not None:
            aud_tokens = self.audio_tower(audio)   # [B, 3, d_model]
            tokens.append(aud_tokens)

        if text_tokens is not None:
            txt_tokens = self.text_embedder(text_tokens)  # [B, L_text, d_model]
            tokens.append(txt_tokens)

        if not tokens:
            raise ValueError("At least one of video, audio, or text_tokens must be provided.")

        # Concatenate all tokens along sequence dimension
        fused = torch.cat(tokens, dim=1)  # [B, L_total, d_model]

        # Fusion core
        hidden, next_conv, next_ssm = self.fusion_core(fused, conv_state, ssm_state)

        # Output heads
        outputs = self.heads(hidden)
        outputs["next_conv_state"] = next_conv
        outputs["next_ssm_state"] = next_ssm

        return outputs

    def init_states(self, batch_size: int, device: torch.device) -> Tuple[List[torch.Tensor], List[torch.Tensor]]:
        """Initialize empty recurrent states."""
        return self.fusion_core.init_states(batch_size, device)

    def count_parameters(self) -> int:
        """Return total trainable parameter count."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
