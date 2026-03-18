"""
Scene Change Detector — Triggers Gemini Narration on Meaningful Changes

Decides WHEN Gemini should speak proactively based on:
- New object classes appearing in YOLO detections
- Significant depth changes (entered a room, reached a wall)
- Navigation events (reached waypoint, mode changed)
- Silence duration (haven't spoken in a while during navigation)

Author: Haziq (@IRSPlays)
Date: March 11, 2026
"""

import logging
import time
from collections import deque
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class SceneChangeDetector:
    """
    Determines when the scene has changed enough to warrant
    Gemini speaking proactively (unprompted).
    
    Usage:
        detector = SceneChangeDetector()
        
        # Called each frame with YOLO detections
        if detector.should_narrate(detections, depth_info, nav_context):
            # Send frame to Gemini for narration
            await gemini.send_video_frame(frame)
    """

    def __init__(
        self,
        class_memory_seconds: float = 5.0,
        depth_change_threshold: float = 0.3,
        silence_timeout_navigating: float = 120.0,
        silence_timeout_idle: float = 60.0,
        cooldown_seconds: float = 5.0,
        cooldown_navigating: float = 15.0,
        min_new_classes: int = 1,
    ):
        """
        Args:
            class_memory_seconds: How long to remember seen classes
            depth_change_threshold: Fraction change in avg depth to trigger (0.3 = 30%)
            silence_timeout_navigating: Seconds of silence before speaking while navigating
            silence_timeout_idle: Seconds of silence before speaking while idle
            cooldown_seconds: Minimum seconds between narration triggers (idle)
            cooldown_navigating: Minimum seconds between narration triggers (navigating)
            min_new_classes: Minimum new classes to trigger narration
        """
        self.class_memory_seconds = class_memory_seconds
        self.depth_change_threshold = depth_change_threshold
        self.silence_timeout_navigating = silence_timeout_navigating
        self.silence_timeout_idle = silence_timeout_idle
        self.cooldown_seconds = cooldown_seconds
        self.cooldown_navigating = cooldown_navigating
        self.min_new_classes = min_new_classes

        # State
        self._recent_classes: deque = deque()  # (timestamp, class_name)
        self._last_avg_depth: Optional[float] = None
        self._last_narration_time: float = 0.0
        self._last_speech_time: float = time.time()  # Track any speech output
        self._last_trigger_reason: str = ""

    def should_narrate(
        self,
        detections: List[Dict[str, Any]],
        avg_depth: Optional[float] = None,
        nav_event: Optional[str] = None,
        is_navigating: bool = False,
    ) -> bool:
        """
        Decide whether Gemini should narrate now.
        
        Args:
            detections: YOLO detection dicts with 'class' or 'class_name' keys
            avg_depth: Average depth in meters from Hailo (None if unavailable)
            nav_event: Navigation event string (e.g., "waypoint_reached", "mode_changed")
            is_navigating: Whether user is actively navigating
            
        Returns:
            True if Gemini should speak proactively
        """
        now = time.time()

        # Enforce cooldown (shorter during navigation)
        cooldown = self.cooldown_navigating if is_navigating else self.cooldown_seconds
        if now - self._last_narration_time < cooldown:
            return False

        # Check each trigger condition
        reason = self._check_triggers(detections, avg_depth, nav_event, is_navigating, now)
        if reason:
            self._last_narration_time = now
            self._last_trigger_reason = reason
            logger.debug(f"Scene change trigger: {reason}")
            return True

        return False

    def _check_triggers(
        self,
        detections: List[Dict[str, Any]],
        avg_depth: Optional[float],
        nav_event: Optional[str],
        is_navigating: bool,
        now: float,
    ) -> Optional[str]:
        """Check all trigger conditions. Returns reason string or None."""

        # 1. Navigation event (highest priority)
        if nav_event:
            return f"nav_event:{nav_event}"

        # 2. New object classes appeared
        current_classes = set()
        for d in detections:
            cls = d.get("class_name") or d.get("class", "")
            if cls:
                current_classes.add(cls.lower())

        # Prune old entries from memory
        cutoff = now - self.class_memory_seconds
        while self._recent_classes and self._recent_classes[0][0] < cutoff:
            self._recent_classes.popleft()

        recent_set = {cls for _, cls in self._recent_classes}
        new_classes = current_classes - recent_set

        # Update memory with current classes
        for cls in current_classes:
            self._recent_classes.append((now, cls))

        # Filter out very common classes that change frequently
        boring_classes = {"person"}  # People come and go — not worth narrating each time
        interesting_new = new_classes - boring_classes
        if len(interesting_new) >= self.min_new_classes:
            return f"new_classes:{','.join(interesting_new)}"

        # Multiple new people are interesting though
        if "person" in new_classes and len(current_classes) > len(recent_set) + 2:
            return "many_new_objects"

        # 3. Significant depth change
        if avg_depth is not None and self._last_avg_depth is not None:
            if self._last_avg_depth > 0:
                change = abs(avg_depth - self._last_avg_depth) / self._last_avg_depth
                if change > self.depth_change_threshold:
                    self._last_avg_depth = avg_depth
                    return f"depth_change:{change:.0%}"
        if avg_depth is not None:
            self._last_avg_depth = avg_depth

        # 4. Silence timeout
        silence_duration = now - self._last_speech_time
        timeout = self.silence_timeout_navigating if is_navigating else self.silence_timeout_idle
        if silence_duration > timeout:
            self._last_speech_time = now  # Reset to avoid re-triggering immediately
            return f"silence:{silence_duration:.0f}s"

        return None

    def record_speech(self):
        """Record that speech just occurred (resets silence timer)."""
        self._last_speech_time = time.time()

    def get_last_trigger(self) -> str:
        """Get the reason for the last narration trigger."""
        return self._last_trigger_reason

    def reset(self):
        """Reset all state."""
        self._recent_classes.clear()
        self._last_avg_depth = None
        self._last_narration_time = 0.0
        self._last_speech_time = time.time()
        self._last_trigger_reason = ""
