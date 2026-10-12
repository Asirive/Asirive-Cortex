"""
Output Heads

Multi-task output heads for CortexLocal NAVIGATOR.

Outputs:
  - LM Head: text generation (verbal instructions)
  - Mode Head: <speak>, <silence>, <tool>, <navigate>, <alert>
  - Tool Head: which tool to call
  - NavAction Head: navigation primitive (forward, left, right, stop, etc.)
  - Distance Head: estimated distance to target/obstacle in meters
  - Landmark Head: landmark detection + naming
  - Safety Head: hazard probability and type

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Dict

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# Mode tokens
MODE_SPEAK = 0
MODE_SILENCE = 1
MODE_TOOL = 2
MODE_NAVIGATE = 3   # Emit navigation action + verbal guidance
MODE_ALERT = 4      # Safety-critical alert (override everything)
MODE_EOS = 5

# Navigation action primitives
NAV_ACTIONS = [
    "STOP",           # Stop immediately
    "FORWARD",        # Walk forward
    "LEFT",           # Turn left
    "RIGHT",          # Turn right
    "LEFT_SMALL",     # Nudge left
    "RIGHT_SMALL",    # Nudge right
    "TURN_AROUND",    # 180 degree turn
    "STEP_UP",        # Step up (curb, stair)
    "STEP_DOWN",      # Step down (curb, stair)
    "DUCK",           # Lower head (low branch)
    "WAIT",           # Wait for signal/person
    "REORIENT",       # Stop and reorient (lost)
]

# Safety hazard types
SAFETY_TYPES = [
    "NONE",
    "CURB",
    "STAIR_UP",
    "STAIR_DOWN",
    "OBSTACLE_LOW",      # Trip hazard
    "OBSTACLE_HEAD",     # Head strike
    "OBSTACLE_SIDE",     # Shoulder strike
    "VEHICLE_APPROACH",  # Car/bike/cycling
    "CROWD",             # Dense people
    "DROP_OFF",          # Edge with no railing
    "WET_FLOOR",
    "CONSTRUCTION",
]


class OutputHeads(nn.Module):
    """
    Navigation-focused multi-task output heads.
    """

    def __init__(
        self,
        d_model: int = 512,
        vocab_size: int = 32000,
        num_modes: int = 6,
        num_tools: int = 14,
        num_nav_actions: int = 12,
        num_safety_types: int = 12,
    ):
        super().__init__()
        self.vocab_size = vocab_size
        self.num_modes = num_modes
        self.num_tools = num_tools
        self.num_nav_actions = num_nav_actions
        self.num_safety_types = num_safety_types

        # Shared state representation (from last decoder token)
        self.state_proj = nn.Linear(d_model, d_model)

        # Text generation
        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)

        # Behavior mode
        self.mode_head = nn.Linear(d_model, num_modes)

        # Tool calling
        self.tool_head = nn.Linear(d_model, num_tools)

        # Navigation action (what to physically do)
        self.nav_action_head = nn.Linear(d_model, num_nav_actions)

        # Distance estimation (regression, meters)
        self.distance_head = nn.Sequential(
            nn.Linear(d_model, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
        )

        # Landmark detection (binary + classification)
        self.landmark_binary = nn.Linear(d_model, 1)  # landmark present?
        self.landmark_class = nn.Linear(d_model, 500)  # 500 common landmark types

        # Safety hazard detection
        self.safety_head = nn.Linear(d_model, num_safety_types)
        self.safety_distance = nn.Sequential(  # Distance to hazard
            nn.Linear(d_model, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(self, hidden: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Args:
            hidden: [B, L, d_model] decoder hidden states
        Returns:
            dict with all head outputs
        """
        # Language modeling over full sequence
        logits = self.lm_head(hidden)  # [B, L, vocab_size]

        # All other predictions from last token
        last_hidden = hidden[:, -1, :]  # [B, d_model]
        state = torch.relu(self.state_proj(last_hidden))

        mode_logits = self.mode_head(state)  # [B, num_modes]
        tool_logits = self.tool_head(state)   # [B, num_tools]
        nav_action_logits = self.nav_action_head(state)  # [B, num_nav_actions]
        distance = self.distance_head(state).squeeze(-1)  # [B], meters
        landmark_present = torch.sigmoid(self.landmark_binary(state)).squeeze(-1)  # [B]
        landmark_class_logits = self.landmark_class(state)  # [B, 500]
        safety_logits = self.safety_head(state)  # [B, num_safety_types]
        safety_dist = self.safety_distance(state).squeeze(-1)  # [B], meters to hazard

        return {
            "logits": logits,
            "mode_logits": mode_logits,
            "tool_logits": tool_logits,
            "nav_action_logits": nav_action_logits,
            "distance": distance,
            "landmark_present": landmark_present,
            "landmark_class_logits": landmark_class_logits,
            "safety_logits": safety_logits,
            "safety_distance": safety_dist,
        }
