"""
ProjectCortex RPi5 AI Wearable System

This package contains all 4 AI layers:
- Layer 0: Guardian (Safety-Critical YOLO Detection)
- Layer 1: Learner (Adaptive YOLOE Detection)
- Layer 2: Thinker (Gemini Live API Conversational AI)
- Layer 3: Guide (Navigation and Spatial Audio)
- Layer 4: Memory (SQLite + Supabase Storage)

Usage:
    from rpi5 import CortexSystem
    system = CortexSystem()
    system.start()

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

__version__ = "2.0.0"
__author__ = "Haziq (@IRSPlays)"

# Core exports
from rpi5.main import CortexSystem, load_config
from rpi5.config.config import get_config

__all__ = [
    "CortexSystem",
    "load_config",
    "get_config",
    "__version__",
    "__author__",
]
