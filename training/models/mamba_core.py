"""
Mamba-2 Fusion Core

State-space model decoder for multimodal token fusion.
Uses Mamba-2 for linear-time attention-equivalent quality with constant memory.
State is managed externally (CPU) for streaming inference compatibility.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Optional, Tuple, List

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

_MAMBA_AVAILABLE = False
try:
    from mamba_ssm import Mamba2
    _MAMBA_AVAILABLE = True
except ImportError:
    logger.warning("mamba_ssm not installed. Fusion core will use stub.")


class MambaFusionCore(nn.Module):
    """
    Mamba-2 decoder with external state management.

    Input:  [B, L, d_model] multimodal token embeddings
    Output: [B, L, d_model] hidden states + updated conv/ssm states
    """

    def __init__(
        self,
        d_model: int = 512,
        d_state: int = 64,
        d_conv: int = 4,
        expand: int = 2,
        n_layer: int = 12,
        dropout: float = 0.0,
    ):
        super().__init__()
        self.d_model = d_model
        self.n_layer = n_layer
        self.d_conv = d_conv
        self.d_state = d_state

        if _MAMBA_AVAILABLE:
            self.layers = nn.ModuleList([
                nn.ModuleDict({
                    "norm": nn.RMSNorm(d_model),
                    "mamba": Mamba2(
                        d_model=d_model,
                        d_state=d_state,
                        d_conv=d_conv,
                        expand=expand,
                        dropout=dropout,
                    ),
                })
                for _ in range(n_layer)
            ])
        else:
            logger.warning("Using stub Mamba layers.")
            self.layers = nn.ModuleList([
                nn.ModuleDict({
                    "norm": nn.LayerNorm(d_model),
                    "mamba": _StubMamba(d_model),
                })
                for _ in range(n_layer)
            ])

        self.norm_f = nn.RMSNorm(d_model) if _MAMBA_AVAILABLE else nn.LayerNorm(d_model)

    def forward(
        self,
        x: torch.Tensor,
        conv_state: Optional[List[torch.Tensor]] = None,
        ssm_state: Optional[List[torch.Tensor]] = None,
    ) -> Tuple[torch.Tensor, List[torch.Tensor], List[torch.Tensor]]:
        """
        Args:
            x:          [B, L, d_model] token embeddings
            conv_state: list of [B, d_model, d_conv] per layer (or None)
            ssm_state:  list of [B, d_model, d_state] per layer (or None)
        Returns:
            hidden:      [B, L, d_model]
            next_conv:   list of [B, d_model, d_conv]
            next_ssm:    list of [B, d_model, d_state]
        """
        next_conv_state: List[torch.Tensor] = []
        next_ssm_state: List[torch.Tensor] = []

        for i, layer in enumerate(self.layers):
            x = layer["norm"](x)
            cs = conv_state[i] if conv_state is not None else None
            ss = ssm_state[i] if ssm_state is not None else None

            if _MAMBA_AVAILABLE:
                # Mamba2.step returns (out, next_conv, next_ssm)
                x, cs_out, ss_out = layer["mamba"].step(x, conv_state=cs, ssm_state=ss)
            else:
                x, cs_out, ss_out = layer["mamba"](x, cs, ss)

            next_conv_state.append(cs_out)
            next_ssm_state.append(ss_out)

        x = self.norm_f(x)
        return x, next_conv_state, next_ssm_state

    def init_states(self, batch_size: int, device: torch.device) -> Tuple[List[torch.Tensor], List[torch.Tensor]]:
        """Initialize empty states for a new sequence."""
        conv_state = [
            torch.zeros(batch_size, self.d_model, self.d_conv, device=device)
            for _ in range(self.n_layer)
        ]
        ssm_state = [
            torch.zeros(batch_size, self.d_model, self.d_state, device=device)
            for _ in range(self.n_layer)
        ]
        return conv_state, ssm_state


class _StubMamba(nn.Module):
    """Placeholder for environments without mamba_ssm."""

    def __init__(self, d_model: int):
        super().__init__()
        self.linear = nn.Linear(d_model, d_model)

    def forward(self, x, conv_state=None, ssm_state=None):
        out = self.linear(x)
        B = x.shape[0]
        next_conv = torch.zeros(B, x.shape[-1], 4, device=x.device) if conv_state is None else conv_state
        next_ssm = torch.zeros(B, x.shape[-1], 64, device=x.device) if ssm_state is None else ssm_state
        return out, next_conv, next_ssm
