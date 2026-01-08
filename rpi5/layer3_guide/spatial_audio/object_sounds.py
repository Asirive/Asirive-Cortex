"""
Project-Cortex v2.0 - Object Sound Mapper

Maps detected object classes to distinct audio signatures.
Each object type has a unique sound to help users distinguish
between different objects in their environment.

Sound Categories:
- Furniture: Chair, table, couch, bed
- People: Person, crowd
- Vehicles: Car, bicycle, motorcycle
- Navigation: Door, stairs, elevator
- Animals: Dog, cat, bird
- Electronics: Phone, laptop, TV

Author: Haziq (@IRSPlays)
"""

import os
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import logging

logger = logging.getLogger("ObjectSounds")

# Try to import PyOpenAL
OPENAL_AVAILABLE = False
try:
    from openal import Source, Buffer
    OPENAL_AVAILABLE = True
except ImportError:
    pass


@dataclass
class SoundProfile:
    """Audio profile for an object class."""
    sound_file: str               # Path to sound file
    volume: float = 0.7           # Default volume (0.0 - 1.0)
    pitch: float = 1.0            # Pitch modifier
    loop: bool = True             # Whether to loop continuously
    priority: int = 5             # Priority (1=highest, 10=lowest)
    category: str = "general"     # Sound category


# Default sound mappings (relative to assets/sounds/)
DEFAULT_SOUND_MAP: Dict[str, SoundProfile] = {
    # === PEOPLE ===
    "person": SoundProfile(
        sound_file="objects/person.wav",
        volume=0.6,
        priority=3,
        category="people"
    ),
    
    # === FURNITURE ===
    "chair": SoundProfile(
        sound_file="objects/furniture.wav",
        volume=0.5,
        priority=6,
        category="furniture"
    ),
    "couch": SoundProfile(
        sound_file="objects/furniture.wav",
        volume=0.5,
        priority=6,
        category="furniture"
    ),
    "bed": SoundProfile(
        sound_file="objects/furniture.wav",
        volume=0.5,
        priority=6,
        category="furniture"
    ),
    "dining table": SoundProfile(
        sound_file="objects/furniture.wav",
        volume=0.5,
        priority=6,
        category="furniture"
    ),
    "toilet": SoundProfile(
        sound_file="objects/furniture.wav",
        volume=0.5,
        priority=5,
        category="furniture"
    ),
    
    # === VEHICLES ===
    "car": SoundProfile(
        sound_file="objects/vehicle.wav",
        volume=0.8,
        priority=1,  # High priority - safety
        category="vehicle"
    ),
    "truck": SoundProfile(
        sound_file="objects/vehicle.wav",
        volume=0.9,
        priority=1,
        category="vehicle"
    ),
    "bus": SoundProfile(
        sound_file="objects/vehicle.wav",
        volume=0.9,
        priority=1,
        category="vehicle"
    ),
    "motorcycle": SoundProfile(
        sound_file="objects/vehicle.wav",
        volume=0.8,
        pitch=1.1,
        priority=1,
        category="vehicle"
    ),
    "bicycle": SoundProfile(
        sound_file="objects/bicycle.wav",
        volume=0.6,
        priority=2,
        category="vehicle"
    ),
    
    # === NAVIGATION ===
    "door": SoundProfile(
        sound_file="objects/door.wav",
        volume=0.6,
        priority=4,
        category="navigation"
    ),
    "stairs": SoundProfile(
        sound_file="objects/stairs.wav",
        volume=0.7,
        priority=2,  # Safety hazard
        category="navigation"
    ),
    "traffic light": SoundProfile(
        sound_file="objects/traffic.wav",
        volume=0.7,
        priority=2,
        category="navigation"
    ),
    "stop sign": SoundProfile(
        sound_file="objects/traffic.wav",
        volume=0.7,
        priority=2,
        category="navigation"
    ),
    
    # === ANIMALS ===
    "dog": SoundProfile(
        sound_file="objects/animal.wav",
        volume=0.6,
        priority=4,
        category="animal"
    ),
    "cat": SoundProfile(
        sound_file="objects/animal.wav",
        volume=0.5,
        pitch=1.2,
        priority=5,
        category="animal"
    ),
    "bird": SoundProfile(
        sound_file="objects/animal.wav",
        volume=0.4,
        pitch=1.5,
        priority=7,
        category="animal"
    ),
    
    # === ELECTRONICS ===
    "cell phone": SoundProfile(
        sound_file="objects/electronic.wav",
        volume=0.5,
        priority=6,
        category="electronic"
    ),
    "laptop": SoundProfile(
        sound_file="objects/electronic.wav",
        volume=0.5,
        priority=6,
        category="electronic"
    ),
    "tv": SoundProfile(
        sound_file="objects/electronic.wav",
        volume=0.5,
        priority=6,
        category="electronic"
    ),
    "remote": SoundProfile(
        sound_file="objects/electronic.wav",
        volume=0.4,
        priority=8,
        category="electronic"
    ),
    
    # === COMMON OBJECTS ===
    "bottle": SoundProfile(
        sound_file="objects/object.wav",
        volume=0.4,
        priority=8,
        category="object"
    ),
    "cup": SoundProfile(
        sound_file="objects/object.wav",
        volume=0.4,
        priority=8,
        category="object"
    ),
    "backpack": SoundProfile(
        sound_file="objects/object.wav",
        volume=0.5,
        priority=7,
        category="object"
    ),
    "umbrella": SoundProfile(
        sound_file="objects/object.wav",
        volume=0.5,
        priority=7,
        category="object"
    ),
    "suitcase": SoundProfile(
        sound_file="objects/object.wav",
        volume=0.5,
        priority=6,
        category="object"
    ),
    "book": SoundProfile(
        sound_file="objects/object.wav",
        volume=0.3,
        priority=9,
        category="object"
    ),
}


class ObjectSoundMapper:
    """
    Maps object classes to distinct audio signatures.
    
    Provides unique sounds for different object types to help
    users distinguish between objects in their environment.
    
    Example:
        mapper = ObjectSoundMapper()
        
        # Get sound for a detected object
        sound_file = mapper.get_sound("chair")
        
        # Play sound at position
        mapper.play_object_sound("person", position=(-0.5, 0, -2.0))
        
        # Get all sounds for a category
        furniture_sounds = mapper.get_sounds_by_category("furniture")
    """
    
    def __init__(
        self,
        assets_path: Optional[str] = None,
        custom_sounds: Optional[Dict[str, SoundProfile]] = None,
        default_sound: str = "objects/generic.wav"
    ):
        """
        Initialize the Object Sound Mapper.
        
        Args:
            assets_path: Path to sound assets directory
            custom_sounds: Custom sound mappings to add/override
            default_sound: Default sound for unknown objects
        """
        # Determine assets path
        if assets_path:
            self.assets_path = Path(assets_path)
        else:
            self.assets_path = Path(__file__).parent.parent.parent.parent / "assets" / "sounds"
        
        self.default_sound = default_sound
        
        # Sound mappings
        self._sound_map: Dict[str, SoundProfile] = DEFAULT_SOUND_MAP.copy()
        
        # Add custom sounds
        if custom_sounds:
            self._sound_map.update(custom_sounds)
        
        # Audio buffer cache
        self._buffer_cache: Dict[str, Buffer] = {}
        
        # Active sources (for cleanup)
        self._active_sources: List[Source] = []
        
        # Category index
        self._categories: Dict[str, List[str]] = {}
        self._build_category_index()
    
    def _build_category_index(self) -> None:
        """Build index of objects by category."""
        self._categories.clear()
        
        for obj_class, profile in self._sound_map.items():
            category = profile.category
            if category not in self._categories:
                self._categories[category] = []
            self._categories[category].append(obj_class)
    
    def get_sound(self, object_class: str) -> Optional[str]:
        """
        Get the sound file path for an object class.
        
        Args:
            object_class: Class name from YOLO detection
            
        Returns:
            Full path to sound file, or None if not found
        """
        object_class = object_class.lower().strip()
        
        if object_class in self._sound_map:
            profile = self._sound_map[object_class]
            sound_path = self.assets_path / profile.sound_file
            if sound_path.exists():
                return str(sound_path)
        
        # Try default sound
        default_path = self.assets_path / self.default_sound
        if default_path.exists():
            return str(default_path)
        
        return None
    
    def get_profile(self, object_class: str) -> Optional[SoundProfile]:
        """
        Get the full sound profile for an object class.
        
        Args:
            object_class: Class name from YOLO detection
            
        Returns:
            SoundProfile or None if not found
        """
        object_class = object_class.lower().strip()
        return self._sound_map.get(object_class)
    
    def play_object_sound(
        self,
        object_class: str,
        position: Tuple[float, float, float],
        volume_override: Optional[float] = None,
        loop: Optional[bool] = None
    ) -> Optional[Source]:
        """
        Play the sound for an object at a 3D position.
        
        Args:
            object_class: Class name
            position: 3D position (x, y, z)
            volume_override: Override default volume
            loop: Override default loop setting
            
        Returns:
            Audio Source if created, None otherwise
        """
        if not OPENAL_AVAILABLE:
            return None
        
        sound_file = self.get_sound(object_class)
        if not sound_file:
            logger.debug(f"No sound found for object class: {object_class}")
            return None
        
        profile = self.get_profile(object_class) or SoundProfile(
            sound_file=self.default_sound
        )
        
        try:
            # Load buffer (cached)
            buffer = self._load_buffer(sound_file)
            if not buffer:
                return None
            
            # Create source
            source = Source(buffer)
            source.set_position(position)
            source.set_gain(volume_override if volume_override is not None else profile.volume)
            source.set_pitch(profile.pitch)
            source.set_looping(loop if loop is not None else profile.loop)
            
            # Set distance attenuation
            source.set_reference_distance(1.0)
            source.set_rolloff_factor(1.0)
            source.set_max_distance(15.0)
            
            source.play()
            
            # Track for cleanup
            self._active_sources.append(source)
            
            return source
            
        except Exception as e:
            logger.error(f"Failed to play object sound: {e}")
            return None
    
    def _load_buffer(self, sound_file: str) -> Optional[Buffer]:
        """Load audio buffer with caching."""
        if sound_file in self._buffer_cache:
            return self._buffer_cache[sound_file]
        
        if not OPENAL_AVAILABLE:
            return None
        
        try:
            buffer = Buffer(sound_file)
            self._buffer_cache[sound_file] = buffer
            return buffer
        except Exception as e:
            logger.error(f"Failed to load audio file {sound_file}: {e}")
            return None
    
    def get_sounds_by_category(self, category: str) -> List[str]:
        """
        Get all object classes in a category.
        
        Args:
            category: Category name (furniture, vehicle, etc.)
            
        Returns:
            List of object class names
        """
        return self._categories.get(category, [])
    
    def get_categories(self) -> List[str]:
        """Get all available categories."""
        return list(self._categories.keys())
    
    def add_sound(
        self,
        object_class: str,
        sound_file: str,
        volume: float = 0.7,
        pitch: float = 1.0,
        loop: bool = True,
        priority: int = 5,
        category: str = "custom"
    ) -> None:
        """
        Add or update a sound mapping.
        
        Args:
            object_class: Class name to map
            sound_file: Relative path to sound file
            volume: Default volume (0.0 - 1.0)
            pitch: Pitch modifier
            loop: Whether to loop
            priority: Priority level
            category: Category name
        """
        self._sound_map[object_class.lower()] = SoundProfile(
            sound_file=sound_file,
            volume=volume,
            pitch=pitch,
            loop=loop,
            priority=priority,
            category=category
        )
        self._build_category_index()
    
    def remove_sound(self, object_class: str) -> bool:
        """
        Remove a sound mapping.
        
        Args:
            object_class: Class name to remove
            
        Returns:
            True if removed, False if not found
        """
        object_class = object_class.lower()
        if object_class in self._sound_map:
            del self._sound_map[object_class]
            self._build_category_index()
            return True
        return False
    
    def get_priority_objects(self, max_priority: int = 3) -> List[str]:
        """
        Get high-priority object classes (safety-critical).
        
        Args:
            max_priority: Maximum priority value (1 = highest)
            
        Returns:
            List of high-priority object class names
        """
        return [
            obj_class for obj_class, profile in self._sound_map.items()
            if profile.priority <= max_priority
        ]
    
    def stop_all(self) -> None:
        """Stop all active sound sources."""
        for source in self._active_sources:
            try:
                source.stop()
            except:
                pass
        self._active_sources.clear()
    
    def cleanup_finished(self) -> int:
        """
        Remove finished sources from tracking.
        
        Returns:
            Number of sources cleaned up
        """
        if not OPENAL_AVAILABLE:
            return 0
        
        cleaned = 0
        still_active = []
        
        for source in self._active_sources:
            try:
                # Check if source is still playing
                # OpenAL source state: 0=initial, 1=playing, 2=paused, 3=stopped
                if source.get_state() == 0x1012:  # AL_PLAYING
                    still_active.append(source)
                else:
                    cleaned += 1
            except:
                cleaned += 1
        
        self._active_sources = still_active
        return cleaned
    
    def get_stats(self) -> Dict:
        """Get mapper statistics."""
        return {
            "total_mappings": len(self._sound_map),
            "categories": len(self._categories),
            "cached_buffers": len(self._buffer_cache),
            "active_sources": len(self._active_sources),
            "high_priority_objects": self.get_priority_objects(),
        }


# ============================================================================
# Standalone Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Object Sound Mapper Test")
    print("=" * 60)
    
    mapper = ObjectSoundMapper()
    
    print(f"\nOpenAL available: {OPENAL_AVAILABLE}")
    print(f"Assets path: {mapper.assets_path}")
    
    print(f"\nStats: {mapper.get_stats()}")
    
    print("\n--- Categories ---")
    for category in mapper.get_categories():
        objects = mapper.get_sounds_by_category(category)
        print(f"  {category}: {', '.join(objects)}")
    
    print("\n--- High Priority Objects (Safety) ---")
    high_priority = mapper.get_priority_objects(max_priority=2)
    print(f"  {', '.join(high_priority)}")
    
    print("\n--- Sound Lookups ---")
    test_classes = ["person", "car", "chair", "dog", "unknown_object"]
    
    for obj_class in test_classes:
        sound = mapper.get_sound(obj_class)
        profile = mapper.get_profile(obj_class)
        
        if profile:
            print(f"  {obj_class}:")
            print(f"    Sound: {sound}")
            print(f"    Volume: {profile.volume}, Priority: {profile.priority}")
        else:
            print(f"  {obj_class}: Using default sound")
    
    print("\n✅ Test complete")
