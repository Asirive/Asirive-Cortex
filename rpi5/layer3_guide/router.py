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
import re
from typing import Tuple, Dict, Any, Set
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

class IntentRouter:
    """
    Decides which AI layer should handle a user command.
    Uses fuzzy matching to handle variations (e.g., 'what u see', 'what do you see').
    """

    # Filler phrases that should NOT trigger any layer processing.
    # These are common STT artifacts, acknowledgements, and non-command utterances.
    FILLER_PHRASES: Set[str] = {
        # Acknowledgements
        "yeah", "yep", "yup", "yes", "no", "nope", "nah",
        "ok", "okay", "sure", "right", "alright", "got it",
        "cool", "nice", "great", "good", "fine", "perfect",
        # Greetings / farewells
        "hello", "hi", "hey", "bye", "goodbye", "see you",
        "good morning", "good night",
        # Filler sounds / hesitations
        "um", "uh", "uh huh", "hmm", "hm", "ah", "oh", "eh",
        "mm", "mmm", "mhm",
        # Polite / social
        "thanks", "thank you", "thanks for watching",
        "please", "sorry", "excuse me",
        # Conversational noise
        "i see", "oh well", "never mind", "you know",
        "i guess", "i think", "i mean", "well",
        "anyway", "so", "like", "whatever", "nothing",
        "that's it", "that's all", "done", "okay bye",
    }

    def __init__(self, memory_manager=None):
        """
        Initialize Intent Router.

        Args:
            memory_manager: HybridMemoryManager for cloud storage (optional)
        """
        # Memory manager (optional, for logging routing decisions)
        self.memory_manager = memory_manager

        # Layer 1 PRIORITY KEYWORDS: These force Layer 1 routing WITHOUT fuzzy matching
        # These are IMMEDIATE object listing queries that should be <150ms (not 1-2s cloud AI)
        self.layer1_priority_keywords = [
            "what do you see", "what u see", "what can you see",
            "what you see", "what do u see",
            "what's in front", "what's ahead", "whats in front", "whats ahead",
            "see", "look", "show me", "list objects", "what objects",
            "identify", "detect", "count", "how many"
        ]
        
        # Layer 1: Object detection patterns (YOLOE LEARNER) - USE FOR MOST QUERIES
        # This is the PRIMARY layer for object identification - fast, offline, adaptive
        self.layer1_patterns = [
            "what is this", "what's this", "whats this",
            "what do you see", "what u see", "what you see", 
            "what do u see", "what can you see",
            "look", "watch out", "stop", "careful", 
            "hazard", "obstacle", "in front", "ahead",
            "identify", "detect", "count", "list objects",
            "show me objects", "what objects", "any objects",
            # Object queries (YOLOE adaptive learning)
            "is there a", "do you see a", "can you see",
            "how many", "count the", "find a", "spot a",
            # Quick identification
            "what's in front", "what's ahead", "what's nearby",
            "objects around me", "things around me",
            # Memory recall (quick): "where is my [object]" - checks if visible
            "where is my", "find my", "show me my"
        ]
        
        # Layer 2: Deep analysis patterns (GEMINI 3 FLASH) - RESERVE FOR COMPLEX ANALYSIS ONLY
        # Only use when Layer 1 cannot provide sufficient context
        self.layer2_patterns = [
            "describe the entire scene", "describe the room", "describe the area",
            "describe everything", "full description", "complete description",
            "analyze", "analyze the scene", "what's happening",
            "explain what's happening", "context", "situation",
            # Text reading (OCR required)
            "read", "read text", "read this", "what does it say",
            "text", "sign", "label", "writing", "words",
            "what's written", "what is written", "can you read",
            "scan text", "read the", "read that",
            "letter", "menu", "price", "receipt",
            # Deep understanding (removed "what am i looking at" - too ambiguous)
            "tell me about", "explain this scene",
            "is this safe to", "should i", "can i",
            # Scene understanding
            "what kind of place", "what kind of room"
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

    def is_filler(self, text: str) -> bool:
        """
        Check if text is a non-command filler utterance that should be ignored.
        
        Strips punctuation and checks against known filler phrases.
        Single words that match a Layer priority keyword (e.g., "look", "stop")
        are NOT treated as filler — they are legitimate short commands.
        
        Args:
            text: User utterance (raw from STT)
            
        Returns:
            True if filler (should be ignored), False if potential command
        """
        # Strip punctuation and normalize
        cleaned = re.sub(r'[^\w\s]', '', text.lower().strip())
        
        # Very short text (< 2 chars after cleaning) is always filler
        if len(cleaned) < 2:
            return True
        
        # Check if it's a single word that matches a priority keyword — NOT filler
        # This protects legitimate commands like "look", "stop", "count", "identify"
        words = cleaned.split()
        if len(words) == 1:
            word = words[0]
            if word in {kw for kw in self.layer1_priority_keywords if ' ' not in kw}:
                return False
            # Also check Layer 2/3 single-word priority keywords
            if word in {"analyze", "navigate", "describe", "explain", "read"}:
                return False
        
        # Check against filler phrases (exact match after cleaning)
        if cleaned in self.FILLER_PHRASES:
            return True
        
        # Check if the entire utterance is just filler words combined
        filler_words = {
            "um", "uh", "hmm", "hm", "ah", "oh", "eh", "mm", "like",
            "so", "well", "yeah", "yes", "no", "ok", "okay", "and",
            "the", "a", "an", "i", "is", "it", "that", "this", "just",
        }
        meaningful_words = [w for w in words if w not in filler_words]
        if len(meaningful_words) == 0:
            return True
        
        return False

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
        # PHASE 0: FILLER FILTER — Reject non-command utterances
        # Prevents "yeah", "thanks for watching", "um" from defaulting to Layer 1
        # =================================================================
        if self.is_filler(text):
            logger.debug(f"[ROUTER] Filler detected, ignoring: '{text}'")
            return "ignore"
        
        # =================================================================
        # PHASE 1: KEYWORD PRIORITY OVERRIDE (CRITICAL FIX: CHECK MOST SPECIFIC FIRST)
        # Order matters! Check Layer 2/3 keywords BEFORE Layer 1 to prevent false matches.
        # Example: "explain what you see" should match "explain" (L2) not "what you see" (L1)
        # =================================================================
        
        # Layer 2 priority keywords (deep analysis, OCR, reasoning) - CHECK FIRST
        layer2_priority_keywords = [
            "describe the scene", "describe the room", "describe everything",
            "analyze", "read this", "read text", "read the", "read that",
            "what does it say", "what's written", "can you read",
            "explain", "explain what's happening", "is this safe", "should i"
        ]
        
        # Layer 3 priority: Navigation + SPATIAL AUDIO + Memory storage - CHECK SECOND
        layer3_priority_keywords = [
            # Navigation/GPS
            "where am i", "navigate", "take me to", "go to",
            # Memory storage: "remember this [object]"
            "remember this", "save this", "memorize this", "store this",
            "what do you remember", "list memories", "show saved",
            # SPATIAL AUDIO: Object localization (triggers 3D audio response)
            "where is the", "where's the", "where are the", "locate the", "find the",
            "guide me to the", "lead me to the", "point me to the",
            "which direction is the", "which way is the", "how do i get to the"
        ]
        
        # ✅ CRITICAL: Check Layer 2 priority keywords FIRST (most specific)
        for kw in layer2_priority_keywords:
            if kw in text:
                logger.info(f"🎯 [ROUTER] Layer 2 priority: '{kw}' → Forcing Layer 2 (Thinker)")
                # Log routing decision to memory manager
                if self.memory_manager:
                    self.memory_manager.store_detection({
                        'layer': 'router',
                        'class_name': 'layer2_routing',
                        'confidence': 1.0,
                        'bbox_area': 0.0,
                        'source': 'priority_keyword',
                        'detection_mode': f'keyword:{kw}'
                    })
                return "layer2"

        # ✅ Check Layer 3 priority keywords SECOND
        for kw in layer3_priority_keywords:
            if kw in text:
                logger.info(f"🎯 [ROUTER] Layer 3 priority: '{kw}' → Forcing Layer 3 (Guide)")
                # Log routing decision to memory manager
                if self.memory_manager:
                    self.memory_manager.store_detection({
                        'layer': 'router',
                        'class_name': 'layer3_routing',
                        'confidence': 1.0,
                        'bbox_area': 0.0,
                        'source': 'priority_keyword',
                        'detection_mode': f'keyword:{kw}'
                    })
                return "layer3"

        # ✅ Check Layer 1 priority keywords LAST (most general, fallback)
        for kw in self.layer1_priority_keywords:
            if kw in text:
                logger.info(f"🎯 [ROUTER] Layer 1 priority: '{kw}' → Forcing Layer 1 (Reflex)")
                # Log routing decision to memory manager
                if self.memory_manager:
                    self.memory_manager.store_detection({
                        'layer': 'router',
                        'class_name': 'layer1_routing',
                        'confidence': 1.0,
                        'bbox_area': 0.0,
                        'source': 'priority_keyword',
                        'detection_mode': f'keyword:{kw}'
                    })
                return "layer1"
        
        # =================================================================
        # PHASE 2: FUZZY MATCHING (for ambiguous queries without priority keywords)
        # =================================================================
        layer1_score = max([self.fuzzy_match(text, p) for p in self.layer1_patterns])
        layer2_score = max([self.fuzzy_match(text, p) for p in self.layer2_patterns])
        layer3_score = max([self.fuzzy_match(text, p) for p in self.layer3_patterns])
        
        # Log fuzzy scores for debugging
        logger.info(f"📊 [ROUTER] Fuzzy scores: L1={layer1_score:.2f}, L2={layer2_score:.2f}, L3={layer3_score:.2f} (threshold={self.fuzzy_threshold})")
        
        # Route to highest scoring layer (must exceed threshold)
        if layer3_score >= self.fuzzy_threshold and layer3_score >= max(layer1_score, layer2_score):
            logger.info(f"🎯 [ROUTER] Fuzzy match: Layer 3 (Navigation) - score={layer3_score:.2f}")
            # Log routing decision to memory manager
            if self.memory_manager:
                self.memory_manager.store_detection({
                    'layer': 'router',
                    'class_name': 'layer3_routing',
                    'confidence': float(layer3_score),
                    'bbox_area': 0.0,
                    'source': 'fuzzy_match',
                    'detection_mode': f'scores:L1={layer1_score:.2f},L2={layer2_score:.2f},L3={layer3_score:.2f}'
                })
            return "layer3"
        elif layer2_score >= layer1_score and layer2_score >= self.fuzzy_threshold:
            logger.info(f"🎯 [ROUTER] Fuzzy match: Layer 2 (Thinker) - score={layer2_score:.2f}")
            # Log routing decision to memory manager
            if self.memory_manager:
                self.memory_manager.store_detection({
                    'layer': 'router',
                    'class_name': 'layer2_routing',
                    'confidence': float(layer2_score),
                    'bbox_area': 0.0,
                    'source': 'fuzzy_match',
                    'detection_mode': f'scores:L1={layer1_score:.2f},L2={layer2_score:.2f},L3={layer3_score:.2f}'
                })
            return "layer2"
        elif layer1_score >= self.fuzzy_threshold:
            logger.info(f"🎯 [ROUTER] Fuzzy match: Layer 1 (Reflex) - score={layer1_score:.2f}")
            # Log routing decision to memory manager
            if self.memory_manager:
                self.memory_manager.store_detection({
                    'layer': 'router',
                    'class_name': 'layer1_routing',
                    'confidence': float(layer1_score),
                    'bbox_area': 0.0,
                    'source': 'fuzzy_match',
                    'detection_mode': f'scores:L1={layer1_score:.2f},L2={layer2_score:.2f},L3={layer3_score:.2f}'
                })
            return "layer1"

        # Default to Layer 1 if no clear match (faster, offline)
        logger.info(f"⚠️ [ROUTER] No clear match (all scores < {self.fuzzy_threshold}), defaulting to Layer 1 (offline fallback)")
        # Log routing decision to memory manager
        if self.memory_manager:
            self.memory_manager.store_detection({
                'layer': 'router',
                'class_name': 'layer1_routing',
                'confidence': 0.0,
                'bbox_area': 0.0,
                'source': 'default_fallback',
                'detection_mode': f'no_match:L1={layer1_score:.2f},L2={layer2_score:.2f},L3={layer3_score:.2f}'
            })
        return "layer1"
    
    def get_recommended_mode(self, query: str, current_detections: str = "") -> str:
        """
        Recommend YOLOE detection mode based on query intent.
        
        THREE DETECTION MODES:
        1. PROMPT_FREE: Discovery queries ("show me everything", "scan area")
           - Uses 4585+ built-in classes
           - Confidence: 0.3-0.6 (expected for zero-shot)
        
        2. TEXT_PROMPTS: Learning queries ("what do you see", "identify this")
           - Uses adaptive vocabulary (Gemini/Maps/Memory learned)
           - Confidence: 0.7-0.9 (higher due to context)
        
        3. VISUAL_PROMPTS: Personal queries ("where's my wallet", "find my keys")
           - Uses user-marked personal items
           - Confidence: 0.6-0.95 (highest for personal items)
        
        Args:
            query: User voice command (lowercase)
            current_detections: Current detections string (for context)
        
        Returns:
            Mode string: "PROMPT_FREE", "TEXT_PROMPTS", or "VISUAL_PROMPTS"
        """
        query_lower = query.lower().strip()
        
        # =================================================================
        # PATTERN 1: PERSONAL QUERIES → VISUAL PROMPTS
        # User asking about their specific items (requires memory recall)
        # =================================================================
        personal_patterns = [
            "where's my", "where is my", "find my", "show me my",
            "locate my", "guide me to my", "where are my"
        ]
        
        for pattern in personal_patterns:
            if pattern in query_lower:
                logger.debug(f"🎯 [MODE DETECTION] Personal query detected: '{pattern}' → VISUAL_PROMPTS")
                return "VISUAL_PROMPTS"
        
        # =================================================================
        # PATTERN 2: DISCOVERY QUERIES → PROMPT-FREE
        # User wants comprehensive scene scan (not targeted search)
        # =================================================================
        discovery_patterns = [
            "everything", "all objects", "scan", "describe scene",
            "what's around", "show me everything", "full scan",
            "complete scan", "scan area", "scan the"
        ]
        
        for pattern in discovery_patterns:
            if pattern in query_lower:
                logger.debug(f"🎯 [MODE DETECTION] Discovery query detected: '{pattern}' → PROMPT_FREE")
                return "PROMPT_FREE"
        
        # =================================================================
        # PATTERN 3: LEARNING/TARGETED QUERIES → TEXT PROMPTS (DEFAULT)
        # Standard object identification using adaptive vocabulary
        # =================================================================
        learning_patterns = [
            "what", "identify", "tell me", "is there", "do you see",
            "can you see", "look for", "find a", "count"
        ]
        
        for pattern in learning_patterns:
            if pattern in query_lower:
                logger.debug(f"🎯 [MODE DETECTION] Learning query detected: '{pattern}' → TEXT_PROMPTS")
                return "TEXT_PROMPTS"
        
        # Default: Use text prompts for ambiguous queries
        logger.debug(f"🎯 [MODE DETECTION] Ambiguous query → TEXT_PROMPTS (default)")
        return "TEXT_PROMPTS"

    def get_layer_description(self, layer: str) -> str:
        if layer == "layer1":
            return "Layer 1: Reflex (Local YOLO)"
        elif layer == "layer2":
            return "Layer 2: Thinker (Gemini Vision)"
        elif layer == "layer3":
            return "Layer 3: Guide (Navigation/Spatial Audio)"
        return "Unknown Layer"
    
    def route_with_flags(self, text: str) -> Dict[str, Any]:
        """
        Route a voice command and return detailed routing information.
        
        This method provides structured output for the voice pipeline,
        including flags for which systems to use.
        
        Args:
            text: Transcribed user command
            
        Returns:
            Dict with:
                - layer: Target layer ("layer1", "layer2", "layer3")
                - use_layer0: Use YOLO NCNN on RPi5 (always True for layer1)
                - use_layer1: Use YOLOE on Laptop via WebSocket
                - use_gemini: Use Gemini API (vision or TTS)
                - use_spatial_audio: Use 3D spatial audio for object localization
                - query_type: "detection", "analysis", "navigation", "memory"
                - description: Human-readable description
        """
        layer = self.route(text)
        text_lower = text.lower().strip()
        
        # Handle filler/ignored utterances — return immediately with all flags off
        if layer == "ignore":
            return {
                "layer": "ignore",
                "text": text,
                "use_layer0": False,
                "use_layer1": False,
                "use_gemini": False,
                "use_spatial_audio": False,
                "query_type": "filler",
                "description": "Ignored (filler/non-command)"
            }
        
        # Default flags
        result = {
            "layer": layer,
            "text": text,
            "use_layer0": False,  # YOLO NCNN on RPi5
            "use_layer1": False,  # YOLOE on Laptop
            "use_gemini": False,  # Gemini API
            "use_spatial_audio": False,  # 3D audio
            "query_type": "unknown",
            "description": self.get_layer_description(layer)
        }
        
        # =================================================================
        # Layer 1: Detection queries
        # =================================================================
        if layer == "layer1":
            result["use_layer0"] = True  # Always use local YOLO
            result["use_layer1"] = True  # Also use Laptop YOLOE for better accuracy
            result["query_type"] = "detection"
            
            # Check for specific detection sub-types
            if any(kw in text_lower for kw in ["what do you see", "what can you see", "what u see"]):
                result["query_type"] = "detection_full"
            elif any(kw in text_lower for kw in ["count", "how many"]):
                result["query_type"] = "detection_count"
            elif any(kw in text_lower for kw in ["identify", "what is this"]):
                result["query_type"] = "detection_identify"
        
        # =================================================================
        # Layer 2: Deep analysis queries (Gemini)
        # =================================================================
        elif layer == "layer2":
            result["use_gemini"] = True
            result["query_type"] = "analysis"
            
            # Check for specific analysis sub-types
            ocr_keywords = [
                "read", "text", "sign", "label", "writing", "words",
                "what does it say", "what's written", "what is written",
                "can you read", "scan text", "read the", "read that",
                "letter", "menu", "price", "receipt",
            ]
            if any(kw in text_lower for kw in ocr_keywords):
                result["query_type"] = "analysis_ocr"
            elif any(kw in text_lower for kw in ["describe", "explain", "tell me about"]):
                result["query_type"] = "analysis_describe"
            elif any(kw in text_lower for kw in ["is this safe", "should i", "can i"]):
                result["query_type"] = "analysis_safety"
        
        # =================================================================
        # Layer 3: Navigation and spatial audio
        # =================================================================
        elif layer == "layer3":
            result["query_type"] = "navigation"
            
            # Check for spatial audio queries (object localization)
            spatial_keywords = [
                "where is", "where's", "locate", "find the",
                "guide me to", "lead me to", "point me to",
                "which direction", "which way"
            ]
            
            if any(kw in text_lower for kw in spatial_keywords):
                result["use_spatial_audio"] = True
                result["use_layer0"] = True  # Need detection for object location
                result["use_layer1"] = True
                result["query_type"] = "navigation_spatial"
            
            # Check for memory queries
            memory_keywords = ["remember", "save", "memorize", "store", "memory"]
            if any(kw in text_lower for kw in memory_keywords):
                result["query_type"] = "memory"
            
            # Check for GPS/location queries
            location_keywords = ["where am i", "location", "gps", "navigate", "take me to"]
            if any(kw in text_lower for kw in location_keywords):
                result["query_type"] = "navigation_gps"
        
        logger.info(f"🎯 [ROUTER] Flags: L0={result['use_layer0']}, L1={result['use_layer1']}, "
                   f"Gemini={result['use_gemini']}, Spatial={result['use_spatial_audio']}, "
                   f"Type={result['query_type']}")
        
        return result
