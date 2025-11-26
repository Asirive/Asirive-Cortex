"""
Project-Cortex v2.0 - Object Tracker

Manages multiple audio sources for simultaneously detected objects.
Tracks objects across frames, handles source lifecycle, and limits
concurrent sources to prevent audio overload.

Features:
- Object persistence across frames
- Smooth position interpolation
- Source limit management (priority-based)
- Stale object cleanup

Author: Haziq (@IRSPlays)
"""

import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import OrderedDict
import logging

logger = logging.getLogger("ObjectTracker")

# Try to import PyOpenAL
OPENAL_AVAILABLE = False
try:
    from openal import Source, Buffer
    OPENAL_AVAILABLE = True
except ImportError:
    pass

from .position_calculator import PositionCalculator, Position3D
from .object_sounds import ObjectSoundMapper, SoundProfile


@dataclass
class TrackedObject:
    """Information about a tracked object with audio source."""
    object_id: str
    object_class: str
    position: Position3D
    source: Optional[Any] = None  # OpenAL Source
    confidence: float = 0.0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    frame_count: int = 0
    priority: int = 5
    is_active: bool = True
    
    def age(self) -> float:
        """Get age since first detection in seconds."""
        return time.time() - self.first_seen
    
    def staleness(self) -> float:
        """Get time since last update in seconds."""
        return time.time() - self.last_seen


@dataclass
class Detection:
    """YOLO detection input structure."""
    object_id: str
    class_name: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)


class ObjectTracker:
    """
    Manages audio sources for multiple detected objects.
    
    Tracks objects across frames, creates/updates/destroys audio sources,
    and ensures we don't exceed the maximum source limit.
    
    Example:
        tracker = ObjectTracker(max_sources=5)
        tracker.start()
        
        # Each frame, update with detections
        detections = [
            Detection("person_1", "person", 0.9, (100, 200, 300, 600)),
            Detection("chair_1", "chair", 0.85, (800, 300, 1000, 500)),
        ]
        tracker.update(detections)
        
        # Get currently tracked objects
        tracked = tracker.get_tracked_objects()
        
        tracker.stop()
    """
    
    def __init__(
        self,
        max_sources: int = 5,
        stale_timeout: float = 1.0,
        position_calculator: Optional[PositionCalculator] = None,
        sound_mapper: Optional[ObjectSoundMapper] = None,
        smoothing_alpha: float = 0.3
    ):
        """
        Initialize the Object Tracker.
        
        Args:
            max_sources: Maximum concurrent audio sources
            stale_timeout: Seconds before removing undetected objects
            position_calculator: Position calculator instance
            sound_mapper: Object sound mapper instance
            smoothing_alpha: Position smoothing factor (0-1)
        """
        self.max_sources = max_sources
        self.stale_timeout = stale_timeout
        self.smoothing_alpha = smoothing_alpha
        
        # Dependencies
        self.position_calc = position_calculator or PositionCalculator()
        self.sound_mapper = sound_mapper or ObjectSoundMapper()
        
        # Tracked objects (ordered by recency)
        self._objects: OrderedDict[str, TrackedObject] = OrderedDict()
        
        # Audio buffer cache
        self._buffer_cache: Dict[str, Buffer] = {}
        
        # State
        self._running = False
        self._frame_count = 0
    
    def start(self) -> None:
        """Start the object tracker."""
        self._running = True
        self._objects.clear()
        self._frame_count = 0
        logger.info("🎯 Object Tracker started")
    
    def stop(self) -> None:
        """Stop the tracker and clean up all sources."""
        self._running = False
        
        for obj in self._objects.values():
            self._destroy_source(obj)
        
        self._objects.clear()
        self._buffer_cache.clear()
        
        logger.info("🛑 Object Tracker stopped")
    
    def update(self, detections: List[Detection]) -> List[TrackedObject]:
        """
        Update tracker with new detections.
        
        Args:
            detections: List of Detection objects from YOLO
            
        Returns:
            List of currently tracked objects
        """
        if not self._running:
            return []
        
        self._frame_count += 1
        current_time = time.time()
        detected_ids = set()
        
        # Process each detection
        for det in detections:
            detected_ids.add(det.object_id)
            
            # Calculate 3D position
            position = self.position_calc.bbox_to_3d(
                det.bbox,
                object_class=det.class_name,
                object_id=det.object_id,
                apply_smoothing=True
            )
            
            # Get object priority
            profile = self.sound_mapper.get_profile(det.class_name)
            priority = profile.priority if profile else 5
            
            if det.object_id in self._objects:
                # Update existing object
                self._update_object(det.object_id, det, position, priority)
            else:
                # Create new tracked object
                self._create_object(det, position, priority)
        
        # Handle stale objects
        stale_ids = []
        for obj_id, obj in self._objects.items():
            if obj_id not in detected_ids:
                if obj.staleness() > self.stale_timeout:
                    stale_ids.append(obj_id)
                else:
                    obj.is_active = False
        
        # Remove stale objects
        for obj_id in stale_ids:
            self._remove_object(obj_id)
        
        # Enforce source limit
        self._enforce_source_limit()
        
        return list(self._objects.values())
    
    def _create_object(
        self,
        detection: Detection,
        position: Position3D,
        priority: int
    ) -> TrackedObject:
        """Create a new tracked object."""
        current_time = time.time()
        
        obj = TrackedObject(
            object_id=detection.object_id,
            object_class=detection.class_name,
            position=position,
            confidence=detection.confidence,
            first_seen=current_time,
            last_seen=current_time,
            frame_count=1,
            priority=priority,
            is_active=True
        )
        
        # Create audio source if under limit
        if len(self._get_active_sources()) < self.max_sources:
            self._create_source(obj)
        
        self._objects[detection.object_id] = obj
        
        logger.debug(f"Created object: {detection.class_name} at {position}")
        return obj
    
    def _update_object(
        self,
        object_id: str,
        detection: Detection,
        position: Position3D,
        priority: int
    ) -> None:
        """Update an existing tracked object."""
        obj = self._objects[object_id]
        
        obj.position = position
        obj.confidence = detection.confidence
        obj.last_seen = time.time()
        obj.frame_count += 1
        obj.priority = priority
        obj.is_active = True
        
        # Move to end of ordered dict (most recent)
        self._objects.move_to_end(object_id)
        
        # Update source position
        if obj.source:
            try:
                obj.source.set_position(position.as_tuple())
            except Exception as e:
                logger.error(f"Failed to update source position: {e}")
    
    def _remove_object(self, object_id: str) -> None:
        """Remove a tracked object and its audio source."""
        if object_id not in self._objects:
            return
        
        obj = self._objects.pop(object_id)
        self._destroy_source(obj)
        self.position_calc.clear_object_history(object_id)
        
        logger.debug(f"Removed object: {obj.object_class}")
    
    def _create_source(self, obj: TrackedObject) -> bool:
        """Create an audio source for a tracked object."""
        if not OPENAL_AVAILABLE:
            return False
        
        sound_file = self.sound_mapper.get_sound(obj.object_class)
        if not sound_file:
            return False
        
        profile = self.sound_mapper.get_profile(obj.object_class)
        
        try:
            # Load buffer (cached)
            if sound_file not in self._buffer_cache:
                self._buffer_cache[sound_file] = Buffer(sound_file)
            buffer = self._buffer_cache[sound_file]
            
            # Create source
            source = Source(buffer)
            source.set_position(obj.position.as_tuple())
            source.set_looping(profile.loop if profile else True)
            source.set_gain(profile.volume if profile else 0.7)
            source.set_pitch(profile.pitch if profile else 1.0)
            
            # Distance attenuation
            source.set_reference_distance(1.0)
            source.set_rolloff_factor(1.0)
            source.set_max_distance(15.0)
            
            source.play()
            obj.source = source
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to create audio source: {e}")
            return False
    
    def _destroy_source(self, obj: TrackedObject) -> None:
        """Destroy an object's audio source."""
        if obj.source:
            try:
                obj.source.stop()
            except:
                pass
            obj.source = None
    
    def _get_active_sources(self) -> List[TrackedObject]:
        """Get objects that have active audio sources."""
        return [obj for obj in self._objects.values() if obj.source is not None]
    
    def _enforce_source_limit(self) -> None:
        """Ensure we don't exceed the maximum source limit."""
        active = self._get_active_sources()
        
        if len(active) <= self.max_sources:
            return
        
        # Sort by priority (lower = higher priority) and staleness
        active.sort(key=lambda o: (o.priority, o.staleness()))
        
        # Remove sources from lowest priority objects
        to_remove = len(active) - self.max_sources
        for obj in active[-to_remove:]:
            self._destroy_source(obj)
            logger.debug(f"Removed source for low-priority: {obj.object_class}")
        
        # Check if any high-priority objects need sources
        for obj in self._objects.values():
            if obj.source is None and obj.is_active:
                if len(self._get_active_sources()) < self.max_sources:
                    self._create_source(obj)
    
    def get_tracked_objects(self) -> List[TrackedObject]:
        """Get all currently tracked objects."""
        return list(self._objects.values())
    
    def get_active_objects(self) -> List[TrackedObject]:
        """Get objects detected in the current frame."""
        return [obj for obj in self._objects.values() if obj.is_active]
    
    def get_object(self, object_id: str) -> Optional[TrackedObject]:
        """Get a specific tracked object by ID."""
        return self._objects.get(object_id)
    
    def get_closest_object(self) -> Optional[TrackedObject]:
        """Get the closest tracked object."""
        if not self._objects:
            return None
        
        return min(
            self._objects.values(),
            key=lambda o: o.position.distance_meters or float('inf')
        )
    
    def get_objects_by_class(self, class_name: str) -> List[TrackedObject]:
        """Get all tracked objects of a specific class."""
        class_name = class_name.lower()
        return [
            obj for obj in self._objects.values()
            if obj.object_class.lower() == class_name
        ]
    
    def set_max_sources(self, max_sources: int) -> None:
        """Update the maximum source limit."""
        self.max_sources = max_sources
        self._enforce_source_limit()
    
    def mute_class(self, class_name: str) -> int:
        """
        Mute all objects of a specific class.
        
        Args:
            class_name: Class to mute
            
        Returns:
            Number of objects muted
        """
        count = 0
        class_name = class_name.lower()
        
        for obj in self._objects.values():
            if obj.object_class.lower() == class_name and obj.source:
                try:
                    obj.source.set_gain(0.0)
                    count += 1
                except:
                    pass
        
        return count
    
    def unmute_class(self, class_name: str) -> int:
        """
        Unmute all objects of a specific class.
        
        Args:
            class_name: Class to unmute
            
        Returns:
            Number of objects unmuted
        """
        count = 0
        class_name = class_name.lower()
        
        for obj in self._objects.values():
            if obj.object_class.lower() == class_name and obj.source:
                profile = self.sound_mapper.get_profile(obj.object_class)
                volume = profile.volume if profile else 0.7
                try:
                    obj.source.set_gain(volume)
                    count += 1
                except:
                    pass
        
        return count
    
    def get_stats(self) -> Dict:
        """Get tracker statistics."""
        active_sources = self._get_active_sources()
        
        return {
            "total_tracked": len(self._objects),
            "active_objects": len(self.get_active_objects()),
            "active_sources": len(active_sources),
            "max_sources": self.max_sources,
            "frame_count": self._frame_count,
            "cached_buffers": len(self._buffer_cache),
            "running": self._running,
        }


# ============================================================================
# Standalone Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Object Tracker Test")
    print("=" * 60)
    
    tracker = ObjectTracker(max_sources=3)
    
    print(f"\nOpenAL available: {OPENAL_AVAILABLE}")
    print(f"Max sources: {tracker.max_sources}")
    
    tracker.start()
    
    # Simulate detections over multiple frames
    frames = [
        # Frame 1: Two objects
        [
            Detection("person_1", "person", 0.9, (100, 200, 300, 600)),
            Detection("chair_1", "chair", 0.85, (800, 300, 1000, 500)),
        ],
        # Frame 2: Same objects, slightly moved
        [
            Detection("person_1", "person", 0.92, (110, 190, 310, 610)),
            Detection("chair_1", "chair", 0.87, (810, 310, 1010, 510)),
        ],
        # Frame 3: New object, one leaves
        [
            Detection("person_1", "person", 0.88, (120, 180, 320, 620)),
            Detection("car_1", "car", 0.95, (1400, 100, 1800, 400)),
        ],
        # Frame 4: All objects
        [
            Detection("person_1", "person", 0.91, (130, 170, 330, 630)),
            Detection("chair_1", "chair", 0.80, (820, 320, 1020, 520)),
            Detection("car_1", "car", 0.93, (1350, 110, 1750, 410)),
            Detection("dog_1", "dog", 0.75, (500, 400, 600, 550)),
        ],
    ]
    
    print("\nSimulating frames:")
    
    for i, detections in enumerate(frames):
        print(f"\n--- Frame {i + 1} ---")
        print(f"  Detections: {[d.class_name for d in detections]}")
        
        tracked = tracker.update(detections)
        stats = tracker.get_stats()
        
        print(f"  Tracked: {stats['total_tracked']}")
        print(f"  Active sources: {stats['active_sources']}/{stats['max_sources']}")
        
        for obj in tracked:
            status = "🔊" if obj.source else "🔇"
            print(f"    {status} {obj.object_class}: {obj.position}, priority={obj.priority}")
        
        time.sleep(0.3)
    
    # Wait for stale timeout
    print(f"\nWaiting for stale timeout ({tracker.stale_timeout}s)...")
    time.sleep(tracker.stale_timeout + 0.5)
    
    # Empty frame to trigger cleanup
    tracker.update([])
    
    print(f"\nAfter cleanup: {tracker.get_stats()}")
    
    tracker.stop()
    print("\n✅ Test complete")
