"""
Output Heads

LM head for text generation, mode head for behavior classification,
and tool head for offline tool calling.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Dict

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# Mode token indices (must match tokenizer special tokens)
MODE_SPEAK = 0
MODE_SILENCE = 1
MODE_TOOL = 2
MODE_EOS = 3


class OutputHeads(nn.Module):
    """
    Multi-task output heads for CortexLocal.

    Input:  [B, L, d_model] decoder hidden states
    Output: dict of logits for language modeling, mode prediction, and tool selection
    """

    def __init__(
        self,
        d_model: int = 512,
        vocab_size: int = 32000,
        num_modes: int = 4,
        num_tools: int = 14,
    ):
        super().__init__()
        self.vocab_size = vocab_size
        self.num_modes = num_modes
        self.num_tools = num_tools

        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)
        self.mode_head = nn.Linear(d_model, num_modes, bias=True)
        self.tool_head = nn.Linear(d_model, num_tools, bias=True)

    def forward(self, hidden: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Args:
            hidden: [B, L, d_model]
        Returns:
            dict with keys:
                - logits:       [B, L, vocab_size]
                - mode_logits:  [B, num_modes]
                - tool_logits:  [B, num_tools]
        """
        # Language modeling over full sequence
        logits = self.lm_head(hidden)  # [B, L, vocab_size]

        # Mode and tool predictions from last token
        last_hidden = hidden[:, -1, :]  # [B, d_model]
        mode_logits = self.mode_head(last_hidden)  # [B, num_modes]
        tool_logits = self.tool_head(last_hidden)   # [B, num_tools]

        return {
            "logits": logits,
            "mode_logits": mode_logits,
            "tool_logits": tool_logits,
        }
