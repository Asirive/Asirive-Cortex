"""
Audio Tower - Lightweight Mel-CNN

Encodes ambient audio (mel-spectrogram) into patch tokens for fusion.
Pretrained on AudioSet for environmental sound classification.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Optional

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


class AudioTower(nn.Module):
    """
    Audio encoder producing token embeddings from mel spectrogram.

    Input:  [B, 1, 80, 100] mel spectrogram (1 second @ 16kHz)
    Output: [B, 3, proj_dim] audio tokens
    """

    def __init__(
        self,
        in_channels: int = 1,
        channels: list = [32, 64, 128],
        kernels: list = [3, 3, 3],
        strides: list = [[2, 2], [2, 2], [2, 1]],
        proj_dim: int = 512,
        freeze_backbone: bool = False,
    ):
        super().__init__()
        self.proj_dim = proj_dim

        layers = []
        prev_c = in_channels
        for c, k, s in zip(channels, kernels, strides):
            layers.append(nn.Conv2d(prev_c, c, k, stride=s, padding=k // 2))
            layers.append(nn.BatchNorm2d(c))
            layers.append(nn.ReLU(inplace=True))
            prev_c = c
        self.conv = nn.Sequential(*layers)

        self.pool = nn.AdaptiveAvgPool2d((3, 1))  # Collapse spatial -> 3 tokens
        self.proj = nn.Linear(prev_c, proj_dim)

        if freeze_backbone:
            for param in self.conv.parameters():
                param.requires_grad = False
            logger.info("Audio backbone frozen.")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: [B, 1, 80, 100] mel spectrogram
        Returns:
            [B, 3, proj_dim] audio tokens
        """
        x = self.conv(x)            # [B, 128, H', W']
        x = self.pool(x).squeeze(-1)  # [B, 128, 3]
        x = x.permute(0, 2, 1)      # [B, 3, 128]
        x = self.proj(x)            # [B, 3, proj_dim]
        return x

    def get_dummy_input(self, batch_size: int = 1) -> torch.Tensor:
        """Return dummy input for tracing/export."""
        return torch.randn(batch_size, 1, 80, 100)
