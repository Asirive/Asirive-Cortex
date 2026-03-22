"""
Layer 3: Intent Router - The "Brain" of Project Cortex

Word-level intent classification. Routes voice commands to the correct AI layer.

Routing Logic (priority order):
- Layer 3 (Guide): Navigation, bus, memory, spatial audio — needs specific action
- Layer 1 (Reflex): Object detection, counting, identification — fast local YOLO
- Layer 2 (Thinker): Everything else — Gemini handles open-ended queries
- Ignore: Filler, noise, STT hallucinations

Key design: Layer 2 (Gemini) is the DEFAULT fallback, NOT Layer 1.
Gemini can handle any question. Layer 1 only handles explicit detection requests.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import logging
import re
from typing import Dict, Any, Set

logger = logging.getLogger(__name__)

class IntentRouter:
    """
    Word-level intent classifier. Extracts words from input text,
    checks for keyword hits per layer, and routes accordingly.
    
    Default fallback: Layer 2 (Gemini) — not Layer 1.
    """

    # Filler phrases that should NOT trigger any layer processing.
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

    # Known Whisper hallucination strings — reject these outright
    HALLUCINATION_STRINGS: Set[str] = {
        "voice command for a navigation assistant",
        "thank you for watching",
        "thanks for watching",
        "please subscribe",
        "subscribe to my channel",
        "like and subscribe",
        "see you in the next video",
        "bye bye",
        "you",
    }

    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager

        # ===============================================================
        # LAYER 3: Navigation, bus, memory, spatial audio
        # These are ACTION commands that need specific system handlers
        # ===============================================================
        # Phrase patterns (checked as substrings in text)
        self._l3_phrases = [
            "where am i", "take me to", "go to", "navigate to",
            "guide me to", "lead me to", "point me to",
            "how do i get to", "directions to",
            "start navigation", "stop navigation", "cancel navigation",
            "resume navigation", "pause navigation",
            "next bus", "bus arrival", "bus stop", "what bus", "which bus",
            "remember this", "save this", "memorize this", "store this",
            "what do you remember", "list memories", "show saved",
            "where is the", "where's the", "where are the",
            "which direction", "which way",
            "where is my", "find my", "show me my", "locate my",
        ]
        # Word stems (any word starting with these → L3 candidate)
        self._l3_stems = {"navigat", "route"}
        # Exact word hits (individual words that signal L3)
        self._l3_words = {"navigate", "navigation", "directions", "bus", "gps"}

        # ===============================================================
        # LAYER 1: Object detection (fast, local YOLO)
        # ONLY for explicit "what do you see" / counting / identification
        # ===============================================================
        self._l1_phrases = [
            "what do you see", "what u see", "what can you see",
            "what you see", "what do u see",
            "what's in front", "what's ahead", "whats in front", "whats ahead",
            "what is this", "what's this", "whats this",
            "list objects", "what objects", "any objects",
            "is there a", "do you see a", "do you see any",
            "how many", "count the", "spot a",
            "objects around me", "things around me",
            "show me objects",
        ]
        # Exact word hits — single-word commands that clearly mean detection
        self._l1_words = {"look", "identify", "detect", "count", "scan", "stop"}

        # ===============================================================
        # LAYER 2: Gemini (deep analysis, OCR, conversation, anything else)
        # This is the DEFAULT — if nothing else matches, Gemini handles it
        # ===============================================================
        # Explicit L2 phrases (these FORCE Gemini even if L1 words also appear)
        self._l2_phrases = [
            "describe the scene", "describe the room", "describe everything",
            "describe the area", "full description", "complete description",
            "analyze the scene", "what's happening", "explain what's happening",
            "read this", "read text", "read that", "read the",
            "what does it say", "what's written", "what is written",
            "can you read", "scan text",
            "tell me about", "explain this",
            "is this safe", "should i", "can i",
            "what kind of place", "what kind of room",
        ]
        # Exact word hits that force L2
        self._l2_words = {"describe", "explain", "analyze", "read"}

    def _clean(self, text: str) -> str:
        """Strip punctuation and normalize whitespace."""
        return re.sub(r'[^\w\s]', '', text.lower().strip())

    def _extract_words(self, cleaned: str) -> set:
        """Get the set of words from cleaned text."""
        return set(cleaned.split())

    def is_filler(self, text: str) -> bool:
        """Check if text is filler / noise / hallucination."""
        cleaned = self._clean(text)

        # Very short (< 2 chars) is always filler
        if len(cleaned) < 2:
            return True

        # Reject known Whisper hallucinations
        if cleaned in self.HALLUCINATION_STRINGS:
            return True

        # Exact filler phrase match
        if cleaned in self.FILLER_PHRASES:
            return True

        words = cleaned.split()

        # Single word: only valid if it's a recognized command word
        if len(words) == 1:
            word = words[0]
            command_words = (self._l1_words | self._l2_words | self._l3_words
                            | {"stop", "help", "quiet", "cancel"})
            if word not in command_words:
                return True

        # All filler words
        filler_words = {
            "um", "uh", "hmm", "hm", "ah", "oh", "eh", "mm", "like",
            "so", "well", "yeah", "yes", "no", "ok", "okay", "and",
            "the", "a", "an", "i", "is", "it", "that", "this", "just",
        }
        meaningful = [w for w in words if w not in filler_words]
        if len(meaningful) == 0:
            return True

        return False

    def _is_negated_nav(self, text: str) -> bool:
        """Check if navigation intent is negated (e.g. 'I don't want to go')."""
        negation_patterns = [
            "don't want to go", "dont want to go",
            "don't go to", "dont go to",
            "don't navigate", "dont navigate",
            "don't take me", "dont take me",
            "don't want to navigate", "dont want to navigate",
            "no i don't", "no i dont",
            "not go to", "not navigate to",
            "don't want directions", "dont want directions",
            "don't need directions", "dont need directions",
            "cancel", "never mind", "nevermind",
        ]
        for pattern in negation_patterns:
            if pattern in text:
                return True
        return False

    def _has_phrase(self, text: str, phrases: list) -> bool:
        """Check if any phrase is a substring of text."""
        for phrase in phrases:
            if phrase in text:
                return True
        return False

    def _has_word(self, words: set, keywords: set) -> bool:
        """Check if any word is in the keyword set."""
        return bool(words & keywords)

    def _has_stem(self, words: set, stems: set) -> bool:
        """Check if any word starts with any of the stems."""
        for word in words:
            for stem in stems:
                if word.startswith(stem):
                    return True
        return False

    def route(self, text: str) -> str:
        """
        Route a voice command to the appropriate layer.
        
        Priority order:
        1. Filler/hallucination → "ignore"
        2. Layer 3 phrase/word match → "layer3" (navigation/bus/memory)
        3. Layer 2 phrase/word match → "layer2" (Gemini analysis/OCR)
        4. Layer 1 phrase/word match → "layer1" (YOLO detection)
        5. Default → "layer2" (Gemini handles everything else)
        """
        cleaned = self._clean(text)
        text_lower = text.lower().strip()
        words = self._extract_words(cleaned)

        # Phase 0: Reject filler/noise/hallucinations
        if self.is_filler(text):
            logger.debug(f"[ROUTER] Filler/noise, ignoring: '{text}'")
            return "ignore"

        # Phase 1: Layer 3 (Navigation/Bus/Memory) — most specific actions
        if self._has_phrase(text_lower, self._l3_phrases) or \
           self._has_word(words, self._l3_words) or \
           self._has_stem(words, self._l3_stems):
            # Check negation — "I don't want to go", "don't navigate" etc.
            if self._is_negated_nav(text_lower):
                logger.info(f"🎯 [ROUTER] → Layer 2 (negated nav): '{text[:60]}'")
                return "layer2"
            # But check if L2 phrase also matches — L2 phrases take priority
            # e.g. "describe the scene at the bus stop" → L2 not L3
            if not self._has_phrase(text_lower, self._l2_phrases):
                logger.info(f"🎯 [ROUTER] → Layer 3 (Guide): '{text[:60]}'")
                return "layer3"

        # Phase 2: Layer 2 (Gemini) — explicit analysis/OCR/describe commands
        if self._has_phrase(text_lower, self._l2_phrases) or \
           self._has_word(words, self._l2_words):
            logger.info(f"🎯 [ROUTER] → Layer 2 (Thinker): '{text[:60]}'")
            return "layer2"

        # Phase 3: Layer 1 (YOLO detection) — explicit detection commands only
        if self._has_phrase(text_lower, self._l1_phrases) or \
           self._has_word(words, self._l1_words):
            logger.info(f"🎯 [ROUTER] → Layer 1 (Reflex): '{text[:60]}'")
            return "layer1"

        # Phase 4: DEFAULT → Layer 2 (Gemini)
        # Gemini can handle any question — conversational, knowledge, ambiguous
        logger.info(f"🎯 [ROUTER] → Layer 2 (default/Gemini): '{text[:60]}'")
        return "layer2"
    
    def get_recommended_mode(self, query: str, current_detections: str = "") -> str:
        """
        Recommend YOLOE detection mode based on query intent.
        """
        query_lower = query.lower().strip()
        
        # PERSONAL QUERIES → VISUAL PROMPTS
        personal_patterns = [
            "where's my", "where is my", "find my", "show me my",
            "locate my", "guide me to my", "where are my"
        ]
        
        for pattern in personal_patterns:
            if pattern in query_lower:
                return "VISUAL_PROMPTS"
        
        # DISCOVERY QUERIES → PROMPT-FREE
        discovery_patterns = [
            "everything", "all objects", "scan", "describe scene",
            "what's around", "show me everything", "full scan",
            "complete scan", "scan area", "scan the"
        ]
        
        for pattern in discovery_patterns:
            if pattern in query_lower:
                return "PROMPT_FREE"
        
        # LEARNING/TARGETED QUERIES → TEXT PROMPTS (DEFAULT)
        learning_patterns = [
            "what", "identify", "tell me", "is there", "do you see",
            "can you see", "look for", "find a", "count"
        ]
        
        for pattern in learning_patterns:
            if pattern in query_lower:
                return "TEXT_PROMPTS"
        
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
            "enable_code_execution": False,  # Agentic Vision (Gemini code execution)
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
            
            # Hardcoded code execution routing:
            # - Reading/OCR = Agentic (code execution ON) — needs structured text parsing
            # - Describe = Agentic (code execution ON) — benefits from analysis
            # - Safety = Fast (code execution OFF) — needs instant response
            if result["query_type"] in ("analysis_ocr", "analysis_describe"):
                result["enable_code_execution"] = True
        
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
                   f"CodeExec={result['enable_code_execution']}, Type={result['query_type']}")
        
        return result
