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
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

class IntentRouter:
    """
    Decides which AI layer should handle a user command.
    Uses fuzzy matching to handle variations (e.g., 'what u see', 'what do you see').
    """
    
    def __init__(self):
        # Layer 1: Object detection patterns (YOLO)
        self.layer1_patterns = [
            "what is this", "what's this", "whats this",
            "what do you see", "what u see", "what you see", 
            "what do u see", "what can you see",
            "look", "watch out", "stop", "careful", 
            "hazard", "obstacle", "in front", "ahead",
            "identify", "detect", "count"
        ]
        
        # Layer 2: Deep analysis patterns (Gemini Vision)
        self.layer2_patterns = [
            "describe", "describe the scene", "describe what you see",
            "detail", "explain", "explain what you see", 
            "explain what ur seeing", "analyze", 
            "read", "read text", "text", "sign", "label", "writing",
            "what does it say", "scan", "tell me about",
            "what am i looking at", "what is in the picture"
        ]
        
        # Layer 3: Navigation + SPATIAL AUDIO patterns
        # This layer handles: GPS/location, navigation, AND object localization with 3D audio
        self.layer3_patterns = [
            # Location & GPS
            "where am i", "location", "gps", 
            # Navigation
            "navigate", "go to", "take me", "direction", "route",
            # Memory
            "remember", "memory", "save",
            # SPATIAL AUDIO: Object localization queries (NEW!)
            "where is", "where are", "where's", "locate", "find the",
            "guide me to", "lead me to", "point me to",
            "which direction", "which way", "how do i get to",
            "is there a", "can you find", "help me find"
        ]
        
        self.fuzzy_threshold = 0.7  # 70% similarity required

    def fuzzy_match(self, text: str, pattern: str) -> float:
        """
        Calculate fuzzy match score between text and pattern.
        
        Args:
            text: User query (lowercase)
            pattern: Reference pattern (lowercase)
            
        Returns:
            Similarity score (0.0 to 1.0)
        """
        # Check if pattern is substring (exact match gets priority)
        if pattern in text:
            return 1.0
        
        # Use SequenceMatcher for fuzzy comparison
        return SequenceMatcher(None, text, pattern).ratio()
    
    def route(self, text: str) -> str:
        """
        Determine the target layer based on text content using fuzzy matching + keyword priority.
        
        Uses a two-phase approach:
        1. First check for HIGH-PRIORITY keywords that force a specific layer
        2. Then use fuzzy matching for ambiguous queries
        
        Args:
            text: Transcribed user command
            
        Returns:
            "layer1", "layer2", or "layer3"
        """
        text = text.lower().strip()
        
        # =================================================================
        # PHASE 1: KEYWORD PRIORITY OVERRIDE
        # If query contains strong Layer 2 indicators, force Layer 2
        # This prevents "Explain to me what u see" from going to Layer 1
        # =================================================================
        layer2_priority_keywords = ["explain", "describe", "detail", "analyze", "tell me about", "read this", "what does it say"]
        
        # Layer 3 priority: Navigation + SPATIAL AUDIO localization
        layer3_priority_keywords = [
            # Navigation/GPS
            "where am i", "navigate", "take me to", "go to", "remember this", "save this",
            # SPATIAL AUDIO: Object localization (triggers 3D audio response)
            "where is the", "where's the", "where are the", "locate the", "find the",
            "guide me to the", "lead me to the", "point me to the",
            "which direction is the", "which way is the", "how do i get to the"
        ]
        
        # Check for Layer 2 priority keywords FIRST (before fuzzy matching)
        for kw in layer2_priority_keywords:
            if kw in text:
                logger.debug(f"🎯 Layer 2 priority keyword found: '{kw}' → Forcing Layer 2")
                return "layer2"
        
        # Check for Layer 3 priority keywords
        for kw in layer3_priority_keywords:
            if kw in text:
                logger.debug(f"🎯 Layer 3 priority keyword found: '{kw}' → Forcing Layer 3")
                return "layer3"
        
        # =================================================================
        # PHASE 2: FUZZY MATCHING (for ambiguous queries without priority keywords)
        # =================================================================
        layer1_score = max([self.fuzzy_match(text, p) for p in self.layer1_patterns])
        layer2_score = max([self.fuzzy_match(text, p) for p in self.layer2_patterns])
        layer3_score = max([self.fuzzy_match(text, p) for p in self.layer3_patterns])
        
        # Log fuzzy scores for debugging
        logger.debug(f"Fuzzy scores: L1={layer1_score:.2f}, L2={layer2_score:.2f}, L3={layer3_score:.2f}")
        
        # Route to highest scoring layer (must exceed threshold)
        if layer3_score >= self.fuzzy_threshold and layer3_score >= max(layer1_score, layer2_score):
            return "layer3"
        elif layer2_score >= layer1_score and layer2_score >= self.fuzzy_threshold:
            return "layer2"
        elif layer1_score >= self.fuzzy_threshold:
            return "layer1"
        
        # Default to Layer 2 if no clear match (safest for general queries)
        logger.debug(f"No clear match (all scores < {self.fuzzy_threshold}), defaulting to Layer 2")
        return "layer2"

    def get_layer_description(self, layer: str) -> str:
        if layer == "layer1":
            return "Layer 1: Reflex (Local YOLO)"
        elif layer == "layer2":
            return "Layer 2: Thinker (Gemini Vision)"
        elif layer == "layer3":
            return "Layer 3: Guide (Navigation/Spatial Audio)"
        return "Unknown Layer"
