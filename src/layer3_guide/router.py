"""
Layer 3: Intent Router - The "Brain" of Project Cortex

This module analyzes user voice commands (transcribed by Whisper)
and routes them to the appropriate AI layer.

Routing Logic:
- Layer 1 (Reflex): Immediate safety, object identification ("What is this?", "Watch out")
- Layer 2 (Thinker): Deep analysis, reading text, detailed description ("Describe scene", "Read text")
- Layer 3 (Guide): Navigation, memory, location ("Where am I?", "Take me to...")

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import logging
from typing import Tuple, Dict, Any

logger = logging.getLogger(__name__)

class IntentRouter:
    """
    Decides which AI layer should handle a user command.
    """
    
    def __init__(self):
        self.layer1_keywords = [
            "what is this", "what's this", "what do you see", "look", 
            "watch out", "stop", "careful", "hazard", "obstacle",
            "in front", "ahead"
        ]
        
        self.layer2_keywords = [
            "describe", "detail", "explain", "analyze", 
            "read", "text", "sign", "label", "writing",
            "what does it say", "scan"
        ]
        
        self.layer3_keywords = [
            "where am i", "location", "gps", "navigate", 
            "go to", "take me", "direction", "route", 
            "remember", "memory", "save"
        ]

    def route(self, text: str) -> str:
        """
        Determine the target layer based on text content.
        
        Args:
            text: Transcribed user command
            
        Returns:
            "layer1", "layer2", or "layer3"
        """
        text = text.lower().strip()
        
        # Check Layer 3 (Navigation/Memory)
        if any(k in text for k in self.layer3_keywords):
            return "layer3"
            
        # Check Layer 2 (Deep Analysis/Reading)
        if any(k in text for k in self.layer2_keywords):
            return "layer2"
            
        # Check Layer 1 (Reflex/Simple ID)
        if any(k in text for k in self.layer1_keywords):
            return "layer1"
            
        # Default to Layer 2 if ambiguous (safest bet for general queries)
        return "layer2"

    def get_layer_description(self, layer: str) -> str:
        if layer == "layer1":
            return "Layer 1: Reflex (Local YOLO)"
        elif layer == "layer2":
            return "Layer 2: Thinker (Gemini Vision)"
        elif layer == "layer3":
            return "Layer 3: Guide (Navigation/Memory)"
        return "Unknown Layer"
