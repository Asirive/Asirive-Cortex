"""
CortexLocal - Package Initialization

Exposes the main runtime class and helpers for integration into core/system.py.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

from tools.local_copilot.cortex_local import CortexLocal
from tools.local_copilot.inference_engine import InferenceEngine
from tools.local_copilot.state_manager import StateManager
from tools.local_copilot.tool_adapter import ToolAdapter

__all__ = ["CortexLocal", "InferenceEngine", "StateManager", "ToolAdapter"]
