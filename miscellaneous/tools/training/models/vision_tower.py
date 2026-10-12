"""
Vision Tower - MobileCLIP-S2 Wrapper

Wraps Apple's MobileCLIP vision encoder for use in CortexLocal.
Outputs patch-level embeddings projected to the fusion core dimension.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Optional

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# TODO: Install mobileclip package: pip install mobileclip
# Fallback: use timm or torchvision if mobileclip unavailable
_MOBILECLIP_AVAILABLE = False
try:
    from mobileclip import create_model_and_transforms
    _MOBILECLIP_AVAILABLE = True
except ImportError:
    logger.warning("mobileclip not installed. Vision tower will use stub.")


class VisionTower(nn.Module):
    """
    Vision encoder producing patch embeddings.

    Input:  [B, 3, 224, 224] RGB images
    Output: [B, 196, proj_dim] patch tokens (no CLS)
    """

    def __init__(
        self,
        model_name: str = "mobileclip_s2",
        proj_dim: int = 512,
        freeze_backbone: bool = False,
    ):
        super().__init__()
        self.proj_dim = proj_dim

        if _MOBILECLIP_AVAILABLE:
            self.model, _, _ = create_model_and_transforms(
                model_name, pretrained=True
            )
            # MobileCLIP image encoder output hidden dim varies by variant.
            # S2 uses 384-dim patch tokens.
            self.backbone = self.model.image_encoder
            backbone_dim = 384  # S2 specific; parameterize if using other variants
        else:
            # Stub: shallow ConvNet for fast prototyping without mobileclip install
            logger.warning("Using stub vision tower. Install mobileclip for real model.")
            self.backbone = _StubVisionBackbone()
            backbone_dim = 384

        self.proj = nn.Linear(backbone_dim, proj_dim)

        if freeze_backbone:
            for param in self.backbone.parameters():
                param.requires_grad = False
            logger.info("Vision backbone frozen.")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: [B, 3, 224, 224] RGB normalized to [0,1] or ImageNet stats
        Returns:
            [B, 196, proj_dim] patch embeddings
        """
        # MobileCLIP image encoder returns features dict or tensor depending on API
        # TODO: verify exact API and adjust
        feats = self.backbone(x, return_all_features=True)  # [B, 196, backbone_dim]
        feats = self.proj(feats)  # [B, 196, proj_dim]
        return feats

    def get_dummy_input(self, batch_size: int = 1) -> torch.Tensor:
        """Return dummy input for tracing/export."""
        return torch.randn(batch_size, 3, 224, 224)


class _StubVisionBackbone(nn.Module):
    """Placeholder ConvNet for environments without mobileclip."""

    def __init__(self, out_dim: int = 384):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(3, 32, 3, stride=2, padding=1),   # 112
            nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1),  # 56
            nn.ReLU(),
            nn.Conv2d(64, 128, 3, stride=2, padding=1), # 28
            nn.ReLU(),
            nn.Conv2d(128, 256, 3, stride=2, padding=1),# 14
            nn.ReLU(),
            nn.Conv2d(256, out_dim, 3, stride=1, padding=1), # 14
            nn.ReLU(),
        )
        self.pool = nn.AdaptiveAvgPool2d((14, 14))

    def forward(self, x, return_all_features: bool = True):
        x = self.conv(x)
        x = self.pool(x)
        # Reshape to [B, 196, out_dim]
        B, C, H, W = x.shape
        return x.view(B, C, H * W).permute(0, 2, 1)
