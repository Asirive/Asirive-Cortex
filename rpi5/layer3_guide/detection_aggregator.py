"""
Detection Aggregator for Voice Output
======================================

Combines duplicate YOLO detections into human-readable text.
Example: ["box", "box", "box", "person"] -> "3 boxes and 1 person"

Supports both Layer 0 (YOLO NCNN) and Layer 1 (YOLOE) detections.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
Date: January 27, 2026
"""

import logging
from typing import List, Dict, Any, Optional
from collections import Counter

logger = logging.getLogger(__name__)


# =============================================================================
# Pluralization Rules
# =============================================================================

# Irregular plurals
IRREGULAR_PLURALS = {
    "person": "people",
    "man": "men",
    "woman": "women",
    "child": "children",
    "foot": "feet",
    "tooth": "teeth",
    "mouse": "mice",
    "goose": "geese",
    "ox": "oxen",
    "leaf": "leaves",
    "life": "lives",
    "knife": "knives",
    "wife": "wives",
    "shelf": "shelves",
    "cactus": "cacti",
    "focus": "foci",
    "fungus": "fungi",
    "nucleus": "nuclei",
    "syllabus": "syllabi",
    "analysis": "analyses",
    "basis": "bases",
    "crisis": "crises",
    "diagnosis": "diagnoses",
    "thesis": "theses",
}

# Words that don't change in plural
UNCOUNTABLE = {
    "sheep", "deer", "fish", "species", "aircraft", "series",
    "scissors", "pants", "glasses", "jeans", "shorts", "clothes",
    "furniture", "luggage", "equipment", "information", "knowledge",
    "rice", "bread", "water", "coffee", "tea", "milk", "juice",
    "traffic", "weather", "news", "advice", "homework", "research"
}


def pluralize(word: str, count: int = 2) -> str:
    """
    Convert a singular noun to plural form.
    
    Args:
        word: Singular noun
        count: Number of items (returns singular if 1)
        
    Returns:
        Pluralized word
    """
    if count == 1:
        return word
    
    word_lower = word.lower()
    
    # Check uncountable
    if word_lower in UNCOUNTABLE:
        return word
    
    # Check irregular
    if word_lower in IRREGULAR_PLURALS:
        plural = IRREGULAR_PLURALS[word_lower]
        # Preserve original case
        if word[0].isupper():
            return plural.capitalize()
        return plural
    
    # Apply regular rules
    if word_lower.endswith(('s', 'ss', 'sh', 'ch', 'x', 'z')):
        return word + 'es'
    elif word_lower.endswith('y') and len(word) > 1 and word[-2].lower() not in 'aeiou':
        return word[:-1] + 'ies'
    elif word_lower.endswith('o') and word[-2].lower() not in 'aeiou':
        # Words ending in consonant + o usually add -es
        return word + 'es'
    elif word_lower.endswith('f'):
        return word[:-1] + 'ves'
    elif word_lower.endswith('fe'):
        return word[:-2] + 'ves'
    else:
        return word + 's'


# =============================================================================
# Detection Aggregation
# =============================================================================

class DetectionAggregator:
    """
    Aggregates YOLO detections into human-readable descriptions.
    
    Combines duplicate class names and generates natural language output.
    """
    
    def __init__(
        self,
        min_confidence: float = 0.25,
        max_items_to_speak: int = 10,
        sort_by_count: bool = True
    ):
        """
        Initialize aggregator.
        
        Args:
            min_confidence: Minimum confidence threshold for detections
            max_items_to_speak: Maximum number of object types to include in output
            sort_by_count: If True, sort by count (highest first). If False, sort by confidence.
        """
        self.min_confidence = min_confidence
        self.max_items_to_speak = max_items_to_speak
        self.sort_by_count = sort_by_count
    
    def aggregate(
        self,
        detections: List[Dict[str, Any]],
        source_label: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Aggregate detections into counts by class name.
        
        Args:
            detections: List of detection dicts with 'class_name' and 'confidence' keys
            source_label: Optional label (e.g., "layer0", "layer1")
            
        Returns:
            Dict with:
                - counts: Dict[class_name, count]
                - total: Total number of detections
                - text: Human-readable string
                - items: List of (class_name, count) tuples sorted
        """
        # Filter by confidence
        filtered = [
            d for d in detections
            if d.get('confidence', 0) >= self.min_confidence
        ]
        
        # Count by class name
        class_names = [d.get('class_name', d.get('class', 'unknown')) for d in filtered]
        counts = Counter(class_names)
        
        # Sort
        if self.sort_by_count:
            # Sort by count descending, then alphabetically
            sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        else:
            # Sort by average confidence per class
            class_conf = {}
            for d in filtered:
                name = d.get('class_name', d.get('class', 'unknown'))
                if name not in class_conf:
                    class_conf[name] = []
                class_conf[name].append(d.get('confidence', 0))
            
            avg_conf = {name: sum(confs) / len(confs) for name, confs in class_conf.items()}
            sorted_items = sorted(counts.items(), key=lambda x: -avg_conf.get(x[0], 0))
        
        # Limit items
        limited_items = sorted_items[:self.max_items_to_speak]
        
        # Generate text
        text = self._generate_text(limited_items)
        
        return {
            "counts": dict(counts),
            "total": sum(counts.values()),
            "text": text,
            "items": limited_items,
            "source": source_label,
            "filtered_count": len(filtered),
            "original_count": len(detections)
        }
    
    def _generate_text(self, items: List[tuple]) -> str:
        """
        Generate human-readable text from (class_name, count) items.
        
        Examples:
            [(box, 3), (person, 1)] -> "3 boxes and 1 person"
            [(chair, 2)] -> "2 chairs"
            [] -> "nothing detected"
        """
        if not items:
            return "nothing detected"
        
        parts = []
        for class_name, count in items:
            plural_name = pluralize(class_name, count)
            parts.append(f"{count} {plural_name}")
        
        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        else:
            # "3 boxes, 2 chairs, and 1 person"
            return ", ".join(parts[:-1]) + f", and {parts[-1]}"
    
    def merge_layers(
        self,
        layer0_detections: List[Dict[str, Any]],
        layer1_detections: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Merge detections from Layer 0 (RPi5) and Layer 1 (Laptop).
        
        Combines counts and generates unified text output.
        
        Args:
            layer0_detections: Detections from YOLO NCNN on RPi5
            layer1_detections: Detections from YOLOE on Laptop
            
        Returns:
            Aggregated result with merged counts
        """
        # Aggregate each layer
        layer0_agg = self.aggregate(layer0_detections, "layer0")
        layer1_agg = self.aggregate(layer1_detections, "layer1")
        
        # Merge counts (take max for each class to avoid double-counting)
        merged_counts = Counter()
        
        for class_name, count in layer0_agg["counts"].items():
            merged_counts[class_name] = max(merged_counts[class_name], count)
        
        for class_name, count in layer1_agg["counts"].items():
            merged_counts[class_name] = max(merged_counts[class_name], count)
        
        # Sort merged
        if self.sort_by_count:
            sorted_items = sorted(merged_counts.items(), key=lambda x: (-x[1], x[0]))
        else:
            sorted_items = sorted(merged_counts.items(), key=lambda x: x[0])
        
        # Limit and generate text
        limited_items = sorted_items[:self.max_items_to_speak]
        text = self._generate_text(limited_items)
        
        return {
            "counts": dict(merged_counts),
            "total": sum(merged_counts.values()),
            "text": text,
            "items": limited_items,
            "layer0": layer0_agg,
            "layer1": layer1_agg,
            "source": "merged"
        }
    
    def format_for_speech(
        self,
        result: Dict[str, Any],
        prefix: str = "I see",
        include_total: bool = False
    ) -> str:
        """
        Format aggregation result for TTS output.
        
        Args:
            result: Result from aggregate() or merge_layers()
            prefix: Prefix phrase (e.g., "I see", "In front of you")
            include_total: If True, include total count
            
        Returns:
            Speech-ready string
        """
        if result["total"] == 0:
            return f"{prefix} nothing in the current view."
        
        text = result["text"]
        
        if include_total and result["total"] > 1:
            return f"{prefix} {result['total']} objects: {text}."
        else:
            return f"{prefix} {text}."


# =============================================================================
# Convenience Functions
# =============================================================================

def aggregate_detections(
    detections: List[Dict[str, Any]],
    min_confidence: float = 0.25
) -> str:
    """
    Quick aggregation for simple use cases.
    
    Args:
        detections: List of detection dicts
        min_confidence: Minimum confidence threshold
        
    Returns:
        Human-readable string (e.g., "3 boxes and 1 person")
    """
    aggregator = DetectionAggregator(min_confidence=min_confidence)
    result = aggregator.aggregate(detections)
    return result["text"]


def format_detections_for_speech(
    layer0_detections: List[Dict[str, Any]],
    layer1_detections: Optional[List[Dict[str, Any]]] = None,
    min_confidence: float = 0.25
) -> str:
    """
    Format detections from one or two layers for TTS.
    
    Args:
        layer0_detections: RPi5 YOLO NCNN detections
        layer1_detections: Optional Laptop YOLOE detections
        min_confidence: Minimum confidence threshold
        
    Returns:
        Speech-ready string
    """
    aggregator = DetectionAggregator(min_confidence=min_confidence)
    
    if layer1_detections:
        result = aggregator.merge_layers(layer0_detections, layer1_detections)
    else:
        result = aggregator.aggregate(layer0_detections, "layer0")
    
    return aggregator.format_for_speech(result)


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    # Test pluralization
    print("=== Pluralization Tests ===")
    test_words = ["box", "person", "child", "bus", "baby", "leaf", "sheep", "chair"]
    for word in test_words:
        print(f"  1 {word} -> 3 {pluralize(word, 3)}")
    
    # Test aggregation
    print("\n=== Aggregation Tests ===")
    
    test_detections = [
        {"class_name": "storage box", "confidence": 0.85},
        {"class_name": "storage box", "confidence": 0.78},
        {"class_name": "storage box", "confidence": 0.92},
        {"class_name": "person", "confidence": 0.95},
        {"class_name": "chair", "confidence": 0.67},
        {"class_name": "chair", "confidence": 0.71},
        {"class_name": "laptop", "confidence": 0.88},
        {"class_name": "mouse", "confidence": 0.15},  # Below threshold
    ]
    
    aggregator = DetectionAggregator()
    result = aggregator.aggregate(test_detections)
    
    print(f"  Input: {len(test_detections)} detections")
    print(f"  Filtered: {result['filtered_count']} (above {aggregator.min_confidence} confidence)")
    print(f"  Counts: {result['counts']}")
    print(f"  Text: {result['text']}")
    print(f"  Speech: {aggregator.format_for_speech(result)}")
    
    # Test layer merging
    print("\n=== Layer Merge Tests ===")
    
    layer0 = [
        {"class_name": "person", "confidence": 0.9},
        {"class_name": "chair", "confidence": 0.8},
    ]
    
    layer1 = [
        {"class_name": "person", "confidence": 0.85},
        {"class_name": "storage box", "confidence": 0.7},
        {"class_name": "storage box", "confidence": 0.75},
        {"class_name": "laptop", "confidence": 0.9},
    ]
    
    merged = aggregator.merge_layers(layer0, layer1)
    print(f"  Layer 0: {layer0}")
    print(f"  Layer 1: {layer1}")
    print(f"  Merged counts: {merged['counts']}")
    print(f"  Merged text: {merged['text']}")
    print(f"  Speech: {aggregator.format_for_speech(merged)}")
