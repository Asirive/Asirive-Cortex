"""
Project-Cortex v2.0 - Spatial Audio Manager

Central orchestrator for all 3D spatial audio features.
Manages OpenAL context, audio sources, and coordinates all subsystems:
- Audio Beacons (navigation guidance)
- Proximity Alerts (distance warnings)
- Object Tracking (per-object sounds)

Uses PyOpenAL with HRTF (Head-Related Transfer Function) for binaural audio
that works with standard Bluetooth headphones.

⚠️ IMPORTANT: BODY-RELATIVE NAVIGATION ⚠️
=========================================
This system uses BODY-RELATIVE navigation, not head-tracking.
Users must TURN THEIR TORSO to center the sound, not just their head.

Author: Haziq (@IRSPlays)
"""

import os
import threading
import time
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SpatialAudio")

# Try to import PyOpenAL
OPENAL_AVAILABLE = False
try:
    from openal import oalInit, oalQuit, oalGetListener, oalGetDevice
    from openal import Listener, Source, Buffer, WaveFile
    from openal import alDistanceModel, AL_INVERSE_DISTANCE_CLAMPED
    from openal.alc import alcGetString, ALC_DEVICE_SPECIFIER, ALC_ALL_DEVICES_SPECIFIER
    OPENAL_AVAILABLE = True
    logger.info("✅ PyOpenAL loaded successfully")
except ImportError as e:
    logger.warning(f"⚠️ PyOpenAL not available: {e}")
    logger.warning("   Install with: pip install PyOpenAL")

# Import local modules
from .position_calculator import PositionCalculator, Position3D
from .sound_generator import ProceduralSoundGenerator, get_sound_generator


@dataclass
class Detection:
    """YOLO detection data structure."""
    class_name: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    object_id: Optional[str] = None  # For tracking across frames


@dataclass
class AudioSourceInfo:
    """Information about an active audio source."""
    source: Any  # OpenAL Source
    buffer: Any  # OpenAL Buffer
    object_class: str
    position: Position3D
    created_at: float
    last_updated: float


class SpatialAudioManager:
    """
    Central controller for 3D spatial audio navigation.
    
    Manages:
    - OpenAL context initialization with HRTF
    - Audio source lifecycle (create, update, destroy)
    - Integration with YOLO detections
    - Beacon navigation system
    - Proximity alerts
    - Per-object audio signatures
    
    Example:
        audio = SpatialAudioManager()
        audio.start()
        
        # Update with YOLO detections each frame
        audio.update_detections(detections)
        
        # Start navigation beacon to target
        audio.start_beacon("chair")
        
        # Clean up
        audio.stop()
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        frame_width: int = 1920,
        frame_height: int = 1080,
        max_sources: int = 5,
        enable_hrtf: bool = True
    ):
        """
        Initialize the Spatial Audio Manager.
        
        Args:
            config_path: Path to YAML configuration file (optional)
            frame_width: Camera frame width in pixels
            frame_height: Camera frame height in pixels
            max_sources: Maximum concurrent audio sources
            enable_hrtf: Enable HRTF for binaural audio
        """
        self.config_path = config_path
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.max_sources = max_sources
        self.enable_hrtf = enable_hrtf
        
        # State
        self._initialized = False
        self._running = False
        self._lock = threading.Lock()
        
        # OpenAL context
        self._device = None
        self._context = None
        
        # Position calculator
        self.position_calc = PositionCalculator(
            frame_width=frame_width,
            frame_height=frame_height
        )
        
        # Active audio sources (object_id → AudioSourceInfo)
        self._sources: Dict[str, AudioSourceInfo] = {}
        
        # Beacon state
        self._beacon_active = False
        self._beacon_target_class: Optional[str] = None
        self._beacon_source: Optional[Any] = None
        
        # Proximity alert state
        self._closest_obstacle_distance = float('inf')
        self._proximity_alert_level = "none"
        
        # Audio assets path
        self._assets_path = Path(__file__).parent.parent.parent.parent / "assets" / "sounds"
        
        # Loaded buffers cache (sound_file → Buffer)
        self._buffer_cache: Dict[str, Any] = {}
        
        # Listener orientation (yaw, pitch, roll in degrees)
        self._listener_orientation = (0.0, 0.0, 0.0)
        
        # Load configuration if provided
        if config_path and os.path.exists(config_path):
            self._load_config(config_path)
    
    def _load_config(self, config_path: str) -> None:
        """Load configuration from YAML file."""
        try:
            import yaml
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Apply configuration
            if 'position' in config:
                pos_cfg = config['position']
                self.frame_width = pos_cfg.get('frame_width', self.frame_width)
                self.frame_height = pos_cfg.get('frame_height', self.frame_height)
                self.position_calc = PositionCalculator(
                    frame_width=self.frame_width,
                    frame_height=self.frame_height,
                    min_distance=pos_cfg.get('min_distance', 0.5),
                    max_distance=pos_cfg.get('max_distance', 10.0),
                    focal_length_pixels=pos_cfg.get('focal_length', 1500)
                )
            
            if 'audio' in config:
                audio_cfg = config['audio']
                self.max_sources = audio_cfg.get('max_sources', self.max_sources)
            
            logger.info(f"✅ Loaded configuration from {config_path}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load config: {e}")
    
    def start(self) -> bool:
        """
        Initialize OpenAL and start the audio system.
        
        Returns:
            True if started successfully, False otherwise
        """
        if self._initialized:
            logger.warning("Audio system already initialized")
            return True
        
        if not OPENAL_AVAILABLE:
            logger.error("❌ Cannot start: PyOpenAL not installed")
            return False
        
        try:
            # Initialize OpenAL
            # oalInit initializes the default device and creates a context
            oalInit()
            self._initialized = True
            
            # Log which audio device is being used
            try:
                device = oalGetDevice()
                if device:
                    device_name = alcGetString(device, ALC_DEVICE_SPECIFIER)
                    if device_name:
                        device_name = device_name.decode('utf-8') if isinstance(device_name, bytes) else device_name
                        logger.info(f"🔊 Spatial Audio Device: {device_name}")
                    else:
                        logger.info("🔊 Spatial Audio Device: (default system device)")
            except Exception as dev_err:
                logger.debug(f"Could not query device name: {dev_err}")
            
            # Set distance model for realistic attenuation
            # INVERSE_DISTANCE_CLAMPED: volume = ref_dist / (ref_dist + rolloff * (dist - ref_dist))
            try:
                alDistanceModel(AL_INVERSE_DISTANCE_CLAMPED)
            except Exception as dm_err:
                logger.warning(f"⚠️ Could not set distance model: {dm_err}")
            
            # Set listener at origin, facing -Z (forward)
            listener = oalGetListener()
            listener.set_position((0, 0, 0))
            listener.set_orientation((0, 0, -1, 0, 1, 0))  # (forward_xyz, up_xyz)
            
            self._initialized = True
            self._running = True
            
            logger.info("✅ Spatial Audio Manager started")
            logger.info(f"   HRTF enabled: {self.enable_hrtf}")
            logger.info(f"   Max sources: {self.max_sources}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize OpenAL: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the audio system and clean up resources."""
        if not self._initialized:
            return
        
        with self._lock:
            self._running = False
            
            # Stop beacon
            self.stop_beacon()
            
            # Stop all sources
            for source_info in self._sources.values():
                try:
                    source_info.source.stop()
                except:
                    pass
            self._sources.clear()
            
            # Clear buffer cache
            self._buffer_cache.clear()
            
            # Close OpenAL
            if OPENAL_AVAILABLE:
                try:
                    oalQuit()
                except:
                    pass
            
            self._initialized = False
            logger.info("🛑 Spatial Audio Manager stopped")
    
    def update_detections(self, detections: List[Detection]) -> None:
        """
        Update audio sources based on YOLO detections.
        
        Creates, updates, or removes audio sources to match current detections.
        
        Args:
            detections: List of Detection objects from YOLO
        """
        if not self._running:
            return
        
        with self._lock:
            current_time = time.time()
            detected_ids = set()
            
            # Update closest obstacle distance for proximity alerts
            self._closest_obstacle_distance = float('inf')
            
            for detection in detections:
                # Generate object ID if not provided
                object_id = detection.object_id or f"{detection.class_name}_{id(detection)}"
                detected_ids.add(object_id)
                
                # Convert bbox to 3D position
                position = self.position_calc.bbox_to_3d(
                    detection.bbox,
                    object_class=detection.class_name,
                    object_id=object_id
                )
                
                # Track closest obstacle
                if position.distance_meters and position.distance_meters < self._closest_obstacle_distance:
                    self._closest_obstacle_distance = position.distance_meters
                
                # Update or create audio source
                if object_id in self._sources:
                    self._update_source_position(object_id, position)
                elif len(self._sources) < self.max_sources:
                    self._create_source(object_id, detection.class_name, position)
                
                # Update beacon if tracking this object
                if (self._beacon_active and 
                    self._beacon_target_class and 
                    detection.class_name.lower() == self._beacon_target_class.lower()):
                    self._update_beacon_position(position)
            
            # Remove sources for objects no longer detected
            stale_ids = set(self._sources.keys()) - detected_ids
            for stale_id in stale_ids:
                self._remove_source(stale_id)
            
            # Update proximity alert level
            self._update_proximity_alert()
    
    def _create_source(self, object_id: str, object_class: str, position: Position3D) -> None:
        """Create a new audio source for an object."""
        if not OPENAL_AVAILABLE:
            return
        
        try:
            # Get sound file for object class
            sound_file = self._get_sound_for_class(object_class)
            
            if not sound_file or not os.path.exists(sound_file):
                logger.debug(f"No sound file for class '{object_class}'")
                return
            
            # Load buffer (cached)
            buffer = self._load_buffer(sound_file)
            if buffer is None:
                return
            
            # Create source
            source = Source(buffer)
            source.set_position(position.as_tuple())
            source.set_looping(True)
            
            # Set distance attenuation properties
            source.set_reference_distance(1.0)
            source.set_rolloff_factor(1.0)
            source.set_max_distance(15.0)
            
            # Start playing
            source.play()
            
            # Store source info
            self._sources[object_id] = AudioSourceInfo(
                source=source,
                buffer=buffer,
                object_class=object_class,
                position=position,
                created_at=time.time(),
                last_updated=time.time()
            )
            
            logger.debug(f"Created source for {object_class} at {position}")
            
        except Exception as e:
            logger.error(f"Failed to create audio source: {e}")
    
    def _update_source_position(self, object_id: str, position: Position3D) -> None:
        """Update the position of an existing audio source."""
        if object_id not in self._sources:
            return
        
        source_info = self._sources[object_id]
        source_info.position = position
        source_info.last_updated = time.time()
        
        try:
            source_info.source.set_position(position.as_tuple())
        except Exception as e:
            logger.error(f"Failed to update source position: {e}")
    
    def _remove_source(self, object_id: str) -> None:
        """Remove an audio source when object leaves frame."""
        if object_id not in self._sources:
            return
        
        source_info = self._sources.pop(object_id)
        
        try:
            source_info.source.stop()
        except:
            pass
        
        # Clear position history
        self.position_calc.clear_object_history(object_id)
        
        logger.debug(f"Removed source for {source_info.object_class}")
    
    def _load_buffer(self, sound_file: str) -> Optional[Any]:
        """Load an audio file into a buffer (with caching)."""
        if sound_file in self._buffer_cache:
            return self._buffer_cache[sound_file]
        
        if not OPENAL_AVAILABLE:
            return None
        
        try:
            # PyOpenAL's Buffer expects a WaveFile object (with .channels, .frequency, .buffer attributes)
            # NOT a string path directly!
            wave_file = WaveFile(sound_file)
            buffer = Buffer(wave_file)
            self._buffer_cache[sound_file] = buffer
            return buffer
        except Exception as e:
            logger.error(f"Failed to load audio file {sound_file}: {e}")
            return None
    
    def _get_sound_for_class(self, object_class: str) -> Optional[str]:
        """
        Get the sound file path for an object class.
        
        Uses PROCEDURAL SOUND GENERATION - no external WAV files needed!
        Generates unique frequency-based tones for each object class.
        """
        # Use procedural sound generator
        sound_gen = get_sound_generator()
        
        try:
            # Generate procedural sound bytes for this object class
            wav_bytes = sound_gen.generate_object_tone(object_class, duration_ms=500)
            
            # Save to temp file for OpenAL to load
            temp_path = self._get_temp_sound_path(f"object_{object_class.lower()}.wav")
            sound_gen.save_to_file(wav_bytes, temp_path)
            
            logger.debug(f"Using procedural sound for '{object_class}'")
            return temp_path
        except Exception as e:
            logger.warning(f"Failed to generate procedural sound: {e}")
        
        # Fallback: Try loading from assets if they exist
        sound_map = {
            "person": "objects/person.wav",
            "chair": "objects/furniture.wav",
            "car": "objects/vehicle.wav",
            "bicycle": "objects/bicycle.wav",
            "door": "objects/door.wav",
            "stairs": "objects/stairs.wav",
        }
        
        object_class_lower = object_class.lower()
        
        if object_class_lower in sound_map:
            sound_path = self._assets_path / sound_map[object_class_lower]
            if sound_path.exists():
                return str(sound_path)
        
        # Try default sound
        default_path = self._assets_path / "objects" / "generic.wav"
        if default_path.exists():
            return str(default_path)
        
        return None
    
    def _get_temp_sound_path(self, filename: str) -> str:
        """Get path for temporary sound file."""
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "cortex_audio"
        temp_dir.mkdir(exist_ok=True)
        return str(temp_dir / filename)
    
    # ========== BEACON SYSTEM ==========
    
    def start_beacon(self, target_class: str, sound_file: Optional[str] = None) -> bool:
        """
        Start an audio beacon to guide user to target object.
        
        Args:
            target_class: Class name of target object (e.g., "chair")
            sound_file: Custom sound file path (optional)
            
        Returns:
            True if beacon started, False if failed
        """
        if not self._running:
            logger.warning("Cannot start beacon: audio system not running")
            return False
        
        with self._lock:
            # Stop existing beacon
            self.stop_beacon()
            
            self._beacon_target_class = target_class.lower()
            self._beacon_active = True
            
            # Generate procedural beacon sound if no custom file provided
            if sound_file is None:
                sound_gen = get_sound_generator()
                try:
                    # Generate beacon ping and save to temp file
                    wav_bytes = sound_gen.generate_beacon_ping(frequency=880, duration_ms=150)
                    sound_file = self._get_temp_sound_path("beacon_ping.wav")
                    sound_gen.save_to_file(wav_bytes, sound_file)
                except Exception as e:
                    logger.warning(f"Failed to generate beacon sound: {e}")
                    sound_file = None
            
            # Fallback to asset file
            if sound_file is None or not os.path.exists(sound_file):
                sound_file = self._assets_path / "beacons" / "ping.wav"
            
            if not os.path.exists(str(sound_file)):
                logger.warning(f"Beacon sound not found: {sound_file}")
                # Will play when target is detected and sound is available
                return True
            
            try:
                buffer = self._load_buffer(str(sound_file))
                if buffer:
                    self._beacon_source = Source(buffer)
                    self._beacon_source.set_looping(True)
                    # Position will be set when target is detected
                    logger.info(f"🎯 Beacon activated for target: {target_class}")
                    return True
            except Exception as e:
                logger.error(f"Failed to create beacon source: {e}")
            
            return False
    
    def _update_beacon_position(self, position: Position3D) -> None:
        """Update beacon position when target is detected."""
        if not self._beacon_source:
            return
        
        try:
            self._beacon_source.set_position(position.as_tuple())
            
            # Start playing if not already
            if not self._beacon_source.get_state():
                self._beacon_source.play()
            
            # Adjust ping rate based on distance
            if position.distance_meters:
                self._adjust_beacon_rate(position.distance_meters)
                
        except Exception as e:
            logger.error(f"Failed to update beacon position: {e}")
    
    def _adjust_beacon_rate(self, distance_meters: float) -> None:
        """Adjust beacon ping rate based on distance (closer = faster)."""
        # This would require using a pulsing sound or modulating gain
        # For now, we just adjust the pitch slightly
        if not self._beacon_source:
            return
        
        try:
            # Closer = higher pitch (subtle effect)
            if distance_meters < 1.0:
                pitch = 1.2
            elif distance_meters < 2.0:
                pitch = 1.1
            elif distance_meters < 5.0:
                pitch = 1.0
            else:
                pitch = 0.9
            
            self._beacon_source.set_pitch(pitch)
        except:
            pass
    
    def stop_beacon(self) -> None:
        """Stop the navigation beacon."""
        self._beacon_active = False
        self._beacon_target_class = None
        
        if self._beacon_source:
            try:
                self._beacon_source.stop()
            except:
                pass
            self._beacon_source = None
        
        logger.info("🛑 Beacon deactivated")
    
    # ========== PROXIMITY ALERTS ==========
    
    def _update_proximity_alert(self) -> None:
        """Update proximity alert level based on closest obstacle."""
        distance = self._closest_obstacle_distance
        
        if distance < 0.5:
            new_level = "critical"
        elif distance < 1.0:
            new_level = "danger"
        elif distance < 2.0:
            new_level = "warning"
        elif distance < 3.0:
            new_level = "notice"
        else:
            new_level = "none"
        
        if new_level != self._proximity_alert_level:
            self._proximity_alert_level = new_level
            self._play_proximity_alert(new_level)
    
    def _play_proximity_alert(self, level: str) -> None:
        """Play proximity alert sound for given level using procedural sounds."""
        if level == "none":
            return
        
        # First try procedural sound generation
        sound_gen = get_sound_generator()
        try:
            # generate_proximity_alert takes level string, not distance
            wav_bytes = sound_gen.generate_proximity_alert(level)
            
            # Save to temp file
            sound_path = self._get_temp_sound_path(f"proximity_{level}.wav")
            sound_gen.save_to_file(wav_bytes, sound_path)
            
            if os.path.exists(sound_path):
                buffer = self._load_buffer(sound_path)
                if buffer:
                    alert_source = Source(buffer)
                    alert_source.set_position((0, 0, -1))  # In front
                    alert_source.play()
                    return
        except Exception as e:
            logger.warning(f"Failed to generate proximity alert: {e}")
        
        # Fallback to asset files
        sound_map = {
            "notice": "alerts/notice.wav",
            "warning": "alerts/warning.wav",
            "danger": "alerts/danger.wav",
            "critical": "alerts/critical.wav",
        }
        
        if level in sound_map:
            sound_path = self._assets_path / sound_map[level]
            if sound_path.exists():
                try:
                    buffer = self._load_buffer(str(sound_path))
                    if buffer:
                        alert_source = Source(buffer)
                        alert_source.set_position((0, 0, -1))  # In front
                        alert_source.play()
                except Exception as e:
                    logger.error(f"Failed to play proximity alert: {e}")
    
    # ========== LISTENER ORIENTATION ==========
    
    def set_listener_orientation(self, yaw: float, pitch: float, roll: float = 0.0) -> None:
        """
        Update listener orientation based on head tracking.
        
        Args:
            yaw: Rotation around Y axis (left/right) in degrees
            pitch: Rotation around X axis (up/down) in degrees
            roll: Rotation around Z axis (tilt) in degrees
        """
        self._listener_orientation = (yaw, pitch, roll)
        
        if not OPENAL_AVAILABLE or not self._initialized:
            return
        
        try:
            import math
            
            # Convert to radians
            yaw_rad = math.radians(yaw)
            pitch_rad = math.radians(pitch)
            
            # Calculate forward vector
            forward_x = math.sin(yaw_rad) * math.cos(pitch_rad)
            forward_y = math.sin(pitch_rad)
            forward_z = -math.cos(yaw_rad) * math.cos(pitch_rad)
            
            # Up vector (simplified, ignoring roll for now)
            up_x = 0
            up_y = 1
            up_z = 0
            
            listener = oalGetListener()
            listener.set_orientation((forward_x, forward_y, forward_z, up_x, up_y, up_z))
            
        except Exception as e:
            logger.error(f"Failed to update listener orientation: {e}")
    
    # ========== STATUS & STATS ==========
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the audio system."""
        return {
            "initialized": self._initialized,
            "running": self._running,
            "active_sources": len(self._sources),
            "max_sources": self.max_sources,
            "beacon_active": self._beacon_active,
            "beacon_target": self._beacon_target_class,
            "proximity_alert_level": self._proximity_alert_level,
            "closest_obstacle_meters": self._closest_obstacle_distance if self._closest_obstacle_distance != float('inf') else None,
            "listener_orientation": self._listener_orientation,
            "openal_available": OPENAL_AVAILABLE,
        }
    
    def get_active_objects(self) -> List[Dict[str, Any]]:
        """Get list of currently tracked objects with audio sources."""
        return [
            {
                "object_id": obj_id,
                "class_name": info.object_class,
                "position": info.position.as_tuple(),
                "distance_meters": info.position.distance_meters,
            }
            for obj_id, info in self._sources.items()
        ]
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False


# ============================================================================
# Demo / Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Project-Cortex Spatial Audio Manager Test")
    print("=" * 60)
    
    # Create manager
    audio = SpatialAudioManager()
    
    print(f"\nOpenAL Available: {OPENAL_AVAILABLE}")
    print(f"Status: {audio.get_status()}")
    
    if OPENAL_AVAILABLE:
        print("\nStarting audio system...")
        if audio.start():
            print("✅ Audio system started")
            
            # Simulate some detections
            print("\nSimulating detections...")
            
            test_detections = [
                Detection(
                    class_name="chair",
                    confidence=0.92,
                    bbox=(100, 200, 300, 600),
                    object_id="chair_1"
                ),
                Detection(
                    class_name="person",
                    confidence=0.87,
                    bbox=(1400, 100, 1800, 900),
                    object_id="person_1"
                ),
            ]
            
            audio.update_detections(test_detections)
            
            print(f"\nActive objects: {audio.get_active_objects()}")
            print(f"Status: {audio.get_status()}")
            
            # Test beacon
            print("\nStarting beacon for 'chair'...")
            audio.start_beacon("chair")
            
            time.sleep(0.5)
            print(f"Status: {audio.get_status()}")
            
            audio.stop()
            print("\n✅ Test complete")
        else:
            print("❌ Failed to start audio system")
    else:
        print("\n⚠️ PyOpenAL not installed. Install with: pip install PyOpenAL")
        print("   The manager can still be instantiated, but audio features are disabled.")
