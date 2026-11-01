"""
Layer 1: Detection Aggregator - Merges Guardian + Learner Detections

This module combines detections from:
- Layer 0 (Guardian): YOLO11x static safety detection (80 classes)
- Layer 1 (Learner): YOLOE-11m adaptive context detection (15-100 classes)

Into a single unified response with:
- Deduplication (keeps higher confidence)
- Priority sorting (safety classes first)
- <5ms overhead (negligible latency impact)

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: December 30, 2025
"""

import logging
from typing import List, Dict, Set

logger = logging.getLogger(__name__)


class DetectionAggregator:
    """
    Combines Layer 0 (Guardian) + Layer 1 (Learner) detections
    into a single unified response for TTS output.
    """
    
    # Safety-critical classes get PRIORITY in response ordering
    PRIORITY_CLASSES: Set[str] = {
        # People & Animals (highest priority)
        'person', 'people', 'child', 'baby',
        'dog', 'cat', 'bird', 'horse',
        
        # Vehicles (collision hazards)
        'car', 'motorcycle', 'bus', 'truck',
        'bicycle', 'train', 'airplane',
        
        # Infrastructure hazards
        'stairs', 'curb', 'pole', 'fire hydrant',
        'stop sign', 'traffic light',
        
        # Sharp/dangerous objects
        'knife', 'scissors', 'fork'
    }
    
    def __init__(self):
        """Initialize detection aggregator."""
        logger.info("✅ DetectionAggregator initialized")
    
    def merge_detections(
        self,
        guardian_detections: List[str],
        learner_detections: List[str],
        deduplicate: bool = True
    ) -> str:
        """
        Merge and format detections from both layers.
        
        Args:
            guardian_detections: Layer 0 detections ["person (0.87)", "car (0.92)"]
            learner_detections: Layer 1 detections ["fire extinguisher (0.75)"]
            deduplicate: Remove duplicate classes, keep higher confidence
            
        Returns:
            Formatted string: "person, car, fire extinguisher"
            
        Example:
            >>> aggregator = DetectionAggregator()
            >>> guardian = ["person (0.87)", "car (0.92)"]
            >>> learner = ["fire extinguisher (0.75)", "person (0.65)"]
            >>> aggregator.merge_detections(guardian, learner)
            "person, car, fire extinguisher"  # person appears once (guardian's 0.87 kept)
        """
        # Parse detections into structured format
        guardian_objs = self._parse_detections(guardian_detections, source='guardian')
        learner_objs = self._parse_detections(learner_detections, source='learner')
        
        # Combine detections
        all_objs = guardian_objs + learner_objs
        
        if not all_objs:
            return ""
        
        # Deduplicate if requested
        if deduplicate:
            all_objs = self._deduplicate(all_objs)
        
        # Sort: Priority classes first, then by confidence
        sorted_objs = self._sort_by_priority(all_objs)
        
        # Format output (class names only, no confidence scores)
        class_names = [obj['name'] for obj in sorted_objs]
        
        # Log composition details
        logger.debug(f"🔀 [Aggregator] Merged {len(guardian_objs)} guardian + {len(learner_objs)} learner → {len(sorted_objs)} final")
        
        return ", ".join(class_names)
    
    def _parse_detections(self, detections: List[str], source: str) -> List[Dict]:
        """
        Parse 'object (confidence)' strings into structured data.
        
        Args:
            detections: List of detection strings ["person (0.87)", "car (0.92)"]
            source: Detection source ('guardian' or 'learner')
            
        Returns:
            List of detection dicts with name, confidence, source
        """
        result = []
        
        for det in detections:
            if not det or det == "nothing":
                continue
            
            try:
                # Parse "object_name (confidence)" format
                if "(" in det and ")" in det:
                    name_part, conf_part = det.rsplit("(", 1)
                    name = name_part.strip()
                    conf_str = conf_part.rstrip(")")
                    confidence = float(conf_str)
                    
                    result.append({
                        'name': name,
                        'confidence': confidence,
                        'source': source
                    })
                else:
                    # No confidence score, assume high confidence
                    result.append({
                        'name': det.strip(),
                        'confidence': 0.9,
                        'source': source
                    })
            except (ValueError, IndexError) as e:
                logger.warning(f"⚠️ Failed to parse detection '{det}': {e}")
                continue
        
        return result
    
    def _deduplicate(self, objects: List[Dict]) -> List[Dict]:
        """
        Remove duplicate classes, keeping the detection with higher confidence.
        
        Args:
            objects: List of detection dicts
            
        Returns:
            Deduplicated list (one entry per unique class name)
            
        Example:
            Guardian sees "person (0.87)", Learner sees "person (0.65)"
            → Keep Guardian's "person (0.87)"
        """
        seen = {}
        
        for obj in objects:
            name = obj['name']
            
            if name not in seen:
                seen[name] = obj
            elif obj['confidence'] > seen[name]['confidence']:
                # Replace with higher confidence detection
                logger.debug(f"🔄 [Dedup] Replacing {name} ({seen[name]['confidence']:.2f}) with ({obj['confidence']:.2f})")
                seen[name] = obj
        
        return list(seen.values())
    
    def _sort_by_priority(self, objects: List[Dict]) -> List[Dict]:
        """
        Sort detections: Safety classes first, then by confidence.
        
        Args:
            objects: List of detection dicts
            
        Returns:
            Sorted list (priority classes first, then high confidence)
        """
        # Separate into priority and non-priority
        priority_objs = []
        other_objs = []
        
        for obj in objects:
            if obj['name'].lower() in self.PRIORITY_CLASSES:
                priority_objs.append(obj)
            else:
                other_objs.append(obj)
        
        # Sort each group by confidence (descending)
        priority_objs.sort(key=lambda x: x['confidence'], reverse=True)
        other_objs.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Priority classes first
        result = priority_objs + other_objs
        
        if priority_objs:
            logger.debug(f"⚠️ [Priority] Safety classes detected: {[o['name'] for o in priority_objs]}")
        
        return result
    
    def get_priority_alerts(self, guardian_detections: List[str], learner_detections: List[str]) -> List[str]:
        """
        Extract only priority/safety-critical detections for immediate alerts.
        
        Args:
            guardian_detections: Layer 0 detections
            learner_detections: Layer 1 detections
            
        Returns:
            List of priority class names (e.g., ["person", "car"])
        """
        all_objs = self._parse_detections(guardian_detections, 'guardian')
        all_objs += self._parse_detections(learner_detections, 'learner')
        
        # Filter for priority classes only
        priority_objs = [
            obj for obj in all_objs 
            if obj['name'].lower() in self.PRIORITY_CLASSES
        ]
        
        # Deduplicate
        priority_objs = self._deduplicate(priority_objs)
        
        # Sort by confidence
        priority_objs.sort(key=lambda x: x['confidence'], reverse=True)
        
        return [obj['name'] for obj in priority_objs]
