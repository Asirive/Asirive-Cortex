"""
Layer 3: Detection Router - Smart Routing Based on Detection Confidence & Context

This module routes YOLO/YOLOE detection results to the appropriate response layer.
It implements context-aware logic to provide intelligent escalation when needed.

Routing Logic:
- High confidence (>0.75): Direct TTS announcement via Layer 1
- Medium confidence (0.3-0.75): Escalate to Layer 2 for context
- Low/No detection (<0.3): Ask Layer 2 for full scene analysis
- Object overload (>10 objects): Suggest Layer 2 for overview
- Repeated queries (3x): Auto-escalate to Layer 2

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from collections import deque
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class DetectionRouter:
    """
    Routes detection results to appropriate response layer with context-awareness.
    
    Features:
    - Confidence-based routing (high conf → direct, low conf → escalate)
    - Object overload detection (>10 objects → suggest Layer 2)
    - Repeated query escalation (3x same query → auto Layer 2)
    - Escalation pattern learning (learns which queries need Layer 2)
    """
    
    # Safety-critical classes (always trigger Layer 0 haptic feedback)
    SAFETY_CLASSES = [
        'person', 'car', 'truck', 'bus', 'motorcycle', 'bicycle',
        'traffic light', 'stop sign', 'stairs', 'dog', 'cat',
        'fire hydrant', 'bench', 'potted plant'
    ]
    
    # Confidence thresholds
    HIGH_CONF_THRESHOLD = 0.75  # Direct announcement
    LOW_CONF_THRESHOLD = 0.30   # Below this = escalate to Layer 2
    
    # Object overload threshold
    OBJECT_OVERLOAD_THRESHOLD = 10  # >10 objects = suggest Layer 2
    
    # Query history size
    QUERY_HISTORY_SIZE = 10
    
    # Escalation pattern file
    ESCALATION_PATTERNS_PATH = "memory/escalation_patterns.json"
    
    def __init__(self):
        """Initialize detection router with pattern learning capability."""
        self.query_history = deque(maxlen=self.QUERY_HISTORY_SIZE)
        self.escalation_patterns = self._load_escalation_patterns()
        
        logger.info("🧭 Detection Router initialized")
        logger.info(f"   High confidence threshold: {self.HIGH_CONF_THRESHOLD}")
        logger.info(f"   Low confidence threshold: {self.LOW_CONF_THRESHOLD}")
        logger.info(f"   Object overload threshold: {self.OBJECT_OVERLOAD_THRESHOLD}")
    
    def _load_escalation_patterns(self) -> Dict[str, Any]:
        """Load escalation patterns from memory (Phase 2 learning)."""
        path = Path(self.ESCALATION_PATTERNS_PATH)
        
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    patterns = json.load(f)
                logger.info(f"✅ Loaded {len(patterns.get('query_patterns', {}))} learned escalation patterns")
                return patterns
            except Exception as e:
                logger.warning(f"⚠️ Failed to load escalation patterns: {e}")
        
        # Default structure
        return {
            "query_patterns": {},  # "what kind of [object]": "layer2"
            "object_escalations": {},  # "plant": 12 (escalated 12 times)
            "learned_prompts": []  # Objects learned from Gemini
        }
    
    def _save_escalation_patterns(self):
        """Save escalation patterns to memory (Phase 2 learning)."""
        path = Path(self.ESCALATION_PATTERNS_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.escalation_patterns, f, indent=2, ensure_ascii=False)
            logger.debug("💾 Escalation patterns saved")
        except Exception as e:
            logger.error(f"❌ Failed to save escalation patterns: {e}")
    
    def fuzzy_match(self, text1: str, text2: str) -> float:
        """Calculate similarity between two queries."""
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
    
    def route_detection(
        self,
        guardian_detections: List[Dict[str, Any]],
        learner_detections: List[Dict[str, Any]],
        user_query: str
    ) -> Dict[str, Any]:
        """
        Route detections to appropriate response layer with context-awareness.
        
        Args:
            guardian_detections: Layer 0 (Guardian) safety detections
            learner_detections: Layer 1 (Learner) adaptive detections
            user_query: User's voice command (transcribed)
            
        Returns:
            Routing decision dictionary:
            {
                'layer': 'layer1_direct' | 'layer2_assist' | 'layer1_with_suggestion',
                'message': str,  # TTS message to speak
                'suggestion': Optional[str],  # Suggested follow-up query
                'reason': str,  # Why this routing was chosen
                'confidence': float,  # Average confidence of detections
                'detections': List[Dict]  # Filtered detections
            }
        """
        query_lower = user_query.lower().strip()
        
        # Add to query history
        self.query_history.append(query_lower)
        
        # ================================================================
        # PHASE 2: Check if query pattern should auto-escalate to Layer 2
        # ================================================================
        learned_layer = self.escalation_patterns.get('query_patterns', {}).get(query_lower)
        if learned_layer == 'layer2':
            logger.info(f"🎓 Learned pattern: '{user_query}' → Direct to Layer 2")
            return {
                'layer': 'layer2_assist',
                'message': f"Let me analyze that in detail...",
                'suggestion': None,
                'reason': 'learned_escalation',
                'confidence': 0.0,
                'detections': []
            }
        
        # ================================================================
        # PHASE 1: Check for repeated queries (3x same query)
        # ================================================================
        similar_queries = [q for q in self.query_history if self.fuzzy_match(query_lower, q) > 0.8]
        if len(similar_queries) >= 3:
            logger.info(f"🔄 Repeated query detected (x{len(similar_queries)}) → Escalating to Layer 2")
            
            # Learn this pattern for future
            self.escalation_patterns['query_patterns'][query_lower] = 'layer2'
            self._save_escalation_patterns()
            
            return {
                'layer': 'layer2_assist',
                'message': "Let me get a closer look with my advanced vision...",
                'suggestion': None,
                'reason': 'repeated_query',
                'confidence': 0.0,
                'detections': []
            }
        
        # ================================================================
        # Combine all detections (Guardian + Learner)
        # ================================================================
        all_detections = guardian_detections + learner_detections
        
        if not all_detections:
            # No detections → Ask Layer 2 for help
            return {
                'layer': 'layer2_assist',
                'message': f"I don't see any clear objects. Let me analyze the scene...",
                'suggestion': None,
                'reason': 'no_detections',
                'confidence': 0.0,
                'detections': []
            }
        
        # ================================================================
        # Calculate average confidence
        # ================================================================
        avg_confidence = sum(d.get('confidence', 0.0) for d in all_detections) / len(all_detections)
        
        # ================================================================
        # PHASE 1: Check for object overload (>10 objects)
        # ================================================================
        if len(all_detections) >= self.OBJECT_OVERLOAD_THRESHOLD:
            logger.info(f"📊 Object overload detected ({len(all_detections)} objects) → Suggesting Layer 2")
            
            # Get top 5 objects by confidence
            top_objects = sorted(all_detections, key=lambda x: x.get('confidence', 0.0), reverse=True)[:5]
            object_list = ", ".join([d['class_name'] for d in top_objects])
            
            return {
                'layer': 'layer1_with_suggestion',
                'message': f"I see {len(all_detections)} objects including {object_list}. Say 'describe the scene' for a better overview.",
                'suggestion': 'describe the scene',
                'reason': 'object_overload',
                'confidence': avg_confidence,
                'detections': all_detections
            }
        
        # ================================================================
        # Confidence-based routing
        # ================================================================
        if avg_confidence >= self.HIGH_CONF_THRESHOLD:
            # High confidence → Direct TTS announcement (Layer 1)
            object_list = ", ".join([
                f"{d['class_name']} ({d['confidence']:.0%})" 
                for d in sorted(all_detections, key=lambda x: x.get('confidence', 0.0), reverse=True)
            ])
            
            return {
                'layer': 'layer1_direct',
                'message': f"I see {object_list}",
                'suggestion': None,
                'reason': 'high_confidence',
                'confidence': avg_confidence,
                'detections': all_detections
            }
        
        elif avg_confidence >= self.LOW_CONF_THRESHOLD:
            # Medium confidence → Escalate to Layer 2 for context
            logger.info(f"🤔 Medium confidence ({avg_confidence:.2%}) → Escalating to Layer 2")
            
            # Track escalations for learning (Phase 2)
            for det in all_detections:
                class_name = det['class_name']
                self.escalation_patterns['object_escalations'][class_name] = \
                    self.escalation_patterns['object_escalations'].get(class_name, 0) + 1
            
            self._save_escalation_patterns()
            
            return {
                'layer': 'layer2_assist',
                'message': f"I see something but I'm not certain. Let me analyze it more carefully...",
                'suggestion': None,
                'reason': 'medium_confidence',
                'confidence': avg_confidence,
                'detections': all_detections
            }
        
        else:
            # Low confidence → Ask Layer 2 for full analysis
            return {
                'layer': 'layer2_assist',
                'message': f"I'm having trouble identifying objects. Let me use my advanced vision...",
                'suggestion': None,
                'reason': 'low_confidence',
                'confidence': avg_confidence,
                'detections': all_detections
            }
    
    def record_gemini_learning(self, gemini_response: str, original_detections: List[Dict[str, Any]]):
        """
        Record when Gemini identifies objects that YOLOE missed.
        This helps build adaptive prompts for Layer 1 (Phase 2 learning).
        
        Args:
            gemini_response: Gemini's scene description
            original_detections: What Layer 1 detected (before Gemini)
        """
        # Extract object names from Gemini response (simple NLP)
        # This is a simplified version - can be enhanced with proper NLP
        gemini_objects = []
        
        # Common object patterns in Gemini responses
        object_indicators = ["a ", "an ", "the ", "some ", "several "]
        words = gemini_response.lower().split()
        
        for i, word in enumerate(words):
            if any(word.startswith(ind) for ind in object_indicators):
                if i + 1 < len(words):
                    potential_object = words[i + 1].strip('.,!?')
                    
                    # Check if YOLOE didn't detect it
                    detected_classes = [d['class_name'].lower() for d in original_detections]
                    if potential_object not in detected_classes and len(potential_object) > 2:
                        gemini_objects.append(potential_object)
        
        # Track learned objects
        if gemini_objects:
            logger.info(f"🎓 Gemini identified new objects: {gemini_objects}")
            for obj in gemini_objects:
                if obj not in self.escalation_patterns['learned_prompts']:
                    self.escalation_patterns['learned_prompts'].append(obj)
            
            self._save_escalation_patterns()
    
    def get_escalation_stats(self) -> Dict[str, Any]:
        """Get statistics about escalation patterns (for debugging)."""
        patterns = self.escalation_patterns
        return {
            'learned_query_patterns': len(patterns.get('query_patterns', {})),
            'object_escalations': patterns.get('object_escalations', {}),
            'learned_prompts_count': len(patterns.get('learned_prompts', [])),
            'query_history_size': len(self.query_history)
        }


# Example usage (for testing):
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize router
    router = DetectionRouter()
    
    # Test case 1: High confidence detections
    print("\n=== Test 1: High Confidence ===")
    guardian = [{'class_name': 'person', 'confidence': 0.92}]
    learner = [{'class_name': 'laptop', 'confidence': 0.88}]
    result = router.route_detection(guardian, learner, "what do you see")
    print(f"Layer: {result['layer']}")
    print(f"Message: {result['message']}")
    print(f"Reason: {result['reason']}")
    
    # Test case 2: Object overload
    print("\n=== Test 2: Object Overload ===")
    many_objects = [{'class_name': f'object{i}', 'confidence': 0.8} for i in range(15)]
    result = router.route_detection([], many_objects, "what do you see")
    print(f"Layer: {result['layer']}")
    print(f"Message: {result['message']}")
    print(f"Suggestion: {result['suggestion']}")
    
    # Test case 3: Repeated query
    print("\n=== Test 3: Repeated Query ===")
    for i in range(3):
        result = router.route_detection(
            [{'class_name': 'plant', 'confidence': 0.5}],
            [],
            "what kind of plant is this"
        )
    print(f"Layer: {result['layer']}")
    print(f"Message: {result['message']}")
    print(f"Reason: {result['reason']}")
    
    # Test case 4: Low confidence
    print("\n=== Test 4: Low Confidence ===")
    low_conf = [{'class_name': 'unknown', 'confidence': 0.25}]
    result = router.route_detection([], low_conf, "what is this")
    print(f"Layer: {result['layer']}")
    print(f"Message: {result['message']}")
    
    # Show escalation stats
    print("\n=== Escalation Stats ===")
    stats = router.get_escalation_stats()
    for key, value in stats.items():
        print(f"{key}: {value}")
