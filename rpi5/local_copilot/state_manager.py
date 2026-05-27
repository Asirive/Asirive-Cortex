"""
State Manager

Manages Mamba-2 recurrent states on the CPU between inference steps.
States are NOT part of the model graph to enable infinite streaming context.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)


class StateManager:
    """
    CPU-side state cache for Mamba-2 streaming inference.

    Maintains:
    - conv_state: [n_layer, d_model, d_conv]
    - ssm_state:  [n_layer, d_model, d_state]
    """

    def __init__(self, n_layer: int = 12, d_model: int = 512, d_state: int = 64, d_conv: int = 4):
        self.n_layer = n_layer
        self.d_model = d_model
        self.d_state = d_state
        self.d_conv = d_conv
        self._conv_state: np.ndarray = np.zeros((n_layer, 1, d_model, d_conv), dtype=np.float32)
        self._ssm_state: np.ndarray = np.zeros((n_layer, 1, d_model, d_state), dtype=np.float32)

    def get_states(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return current states for feeding into inference engine."""
        return self._conv_state.copy(), self._ssm_state.copy()

    def set_states(self, conv_state: np.ndarray, ssm_state: np.ndarray):
        """Update states from inference engine outputs."""
        self._conv_state = conv_state.copy()
        self._ssm_state = ssm_state.copy()

    def reset(self):
        """Zero out all states (e.g., on turn boundary or mode switch)."""
        self._conv_state.fill(0.0)
        self._ssm_state.fill(0.0)
        logger.debug("StateManager reset.")

    def save_to_disk(self, path: str):
        """Persist states for warm restart across reboots."""
        np.savez(path, conv=self._conv_state, ssm=self._ssm_state)
        logger.info(f"States saved to {path}")

    def load_from_disk(self, path: str):
        """Restore states from disk."""
        data = np.load(path)
        self._conv_state = data["conv"]
        self._ssm_state = data["ssm"]
        logger.info(f"States loaded from {path}")
