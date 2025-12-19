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

🎧 ACCESSIBILITY COMFORT FEATURES (Based on Research):
======================================================
Insights from:
- Microsoft Soundscape (open-source blind navigation app)
- Sonification Handbook (academic audio accessibility guidelines)
- OpenAL-Soft HRTF research for listener fatigue reduction

Key comfort principles implemented:
1. INTERVAL PINGS vs continuous sounds (reduces fatigue)
2. EARCONS (abstract tones) vs auditory icons (real sounds) - configurable
3. VOLUME RAMPING - gradual volume changes, not abrupt
4. REST PERIODS - don't sonify everything constantly
5. CONFIGURABLE INTENSITY LEVELS - Low/Medium/High modes
6. START/END MELODIES - optional intro/outro for beacons
7. PROXIMITY AUTO-MUTE - silences when very close (prevents overwhelm)

Author: Haziq (@IRSPlays)
"""

import os
import threading
import time
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from pathlib import Path
import logging
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SpatialAudio")

# Try to import PyOpenAL
OPENAL_AVAILABLE = False
try:
    from openal import oalInit, oalQuit, oalGetListener, oalGetDevice
    from openal import Listener, Source, Buffer, WaveFile
    from openal import alDistanceModel, AL_INVERSE_DISTANCE_CLAMPED
    from openal.alc import alcGetString, ALC_DEVICE_SPECIFIER
    OPENAL_AVAILABLE = True
    logger.info("✅ PyOpenAL loaded successfully")
except ImportError as e:
    logger.warning(f"⚠️ PyOpenAL not available: {e}")
    logger.warning("   Install with: pip install PyOpenAL")

# Import local modules
from .position_calculator import PositionCalculator, Position3D
from .sound_generator import ProceduralSoundGenerator, get_sound_generator


# ============================================================================
# COMFORT CONFIGURATION SYSTEM
# ============================================================================

class ComfortMode(Enum):
    """
    Preset comfort modes for different user preferences.
    Based on Microsoft Soundscape research and user feedback.
    """
    GENTLE = "gentle"       # Minimal sounds, longer intervals, lower volume
    BALANCED = "balanced"   # Default mode - moderate audio feedback
    INFORMATIVE = "informative"  # More frequent updates, detailed feedback


@dataclass
class ComfortSettings:
    """
    Comprehensive comfort settings for accessible spatial audio.
    
    These settings address common discomfort issues:
    - Audio fatigue from continuous sounds
    - Overwhelming sensory input
    - Jarring/abrupt sound transitions
    - Inappropriate volume levels
    
    Research sources:
    - Microsoft Soundscape beacon design
    - Sonification Handbook (Hermann et al.)
    - OpenAL-Soft HRTF fatigue studies
    """
    
    # === Volume & Intensity ===
    master_volume: float = 0.6        # Overall volume (0.0 - 1.0)
    beacon_volume: float = 0.5        # Beacon ping volume
    proximity_volume: float = 0.4     # Proximity alert volume
    object_volume: float = 0.7        # Per-object tracking volume (increased for better audibility)
    
    # === Beacon Timing (Interval Pings vs Continuous) ===
    # Key insight: Continuous sounds cause fatigue, interval pings don't
    use_interval_pings: bool = True   # True = pings at intervals, False = continuous
    beacon_interval_far_ms: int = 2000    # Ping interval when far (>5m)
    beacon_interval_mid_ms: int = 1000    # Ping interval when mid (2-5m)
    beacon_interval_near_ms: int = 500    # Ping interval when near (1-2m)
    beacon_interval_close_ms: int = 200   # Ping interval when very close (<1m)
    
    # === Start/End Melodies (from Soundscape) ===
    play_beacon_start_melody: bool = True   # Play a short "beacon activated" sound
    play_beacon_end_melody: bool = True     # Play "destination reached" sound
    
    # === Volume Ramping (Prevent Jarring Transitions) ===
    enable_volume_ramping: bool = True   # Gradual volume changes
    ramp_duration_ms: int = 200          # Time to ramp up/down volume
    
    # === Proximity Auto-Mute ===
    # Soundscape auto-mutes beacon when very close to prevent overwhelming
    proximity_auto_mute: bool = True
    proximity_mute_distance_m: float = 0.5  # Distance to auto-mute beacon
    
    # === Rest Periods (Don't Sonify Everything) ===
    max_simultaneous_objects: int = 3    # Limit concurrent audio sources
    object_sound_cooldown_ms: int = 3000  # Min time between new object sounds
    
    # === Earcon Style (Abstract Tones vs Real Sounds) ===
    # Earcons (abstract) are less fatiguing for extended use
    use_earcons: bool = True      # True = abstract tones, False = real sounds
    earcon_style: str = "gentle"  # Options: "gentle", "clear", "bright"
    
    # === Pitch & Frequency Mapping ===
    # Intuitive: higher pitch = closer (not arbitrary)
    pitch_distance_mapping: bool = True  # Higher pitch when closer
    min_pitch: float = 0.8               # Pitch when far
    max_pitch: float = 1.3               # Pitch when close
    
    # === Stereo Spread / Crossfeed ===
    # OpenAL-Soft research: reducing stereo spread reduces fatigue
    stereo_spread: float = 0.7    # 0.0 = mono, 1.0 = full stereo (0.7 recommended)
    
    @classmethod
    def from_mode(cls, mode: ComfortMode) -> "ComfortSettings":
        """Create settings from a preset mode."""
        if mode == ComfortMode.GENTLE:
            return cls(
                master_volume=0.4,
                beacon_volume=0.35,
                proximity_volume=0.3,
                object_volume=0.5,
                beacon_interval_far_ms=3000,
                beacon_interval_mid_ms=2000,
                beacon_interval_near_ms=1000,
                beacon_interval_close_ms=400,
                max_simultaneous_objects=2,
                object_sound_cooldown_ms=5000,
                earcon_style="gentle",
                stereo_spread=0.6,
            )
        elif mode == ComfortMode.INFORMATIVE:
            return cls(
                master_volume=0.7,
                beacon_volume=0.6,
                proximity_volume=0.5,
                object_volume=0.8,
                beacon_interval_far_ms=1500,
                beacon_interval_mid_ms=800,
                beacon_interval_near_ms=400,
                beacon_interval_close_ms=150,
                max_simultaneous_objects=5,
                object_sound_cooldown_ms=2000,
                earcon_style="clear",
                stereo_spread=0.9,
            )
        else:  # BALANCED (default)
            return cls()  # Default values


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
    # NEW: Per-object ping timing (closer objects ping faster)
    last_ping_time: float = 0.0
    ping_interval_ms: float = 1000.0  # Will be calculated based on distance


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
        enable_hrtf: bool = True,
        comfort_mode: ComfortMode = ComfortMode.BALANCED,
        comfort_settings: Optional[ComfortSettings] = None
    ):
        """
        Initialize the Spatial Audio Manager.
        
        Args:
            config_path: Path to YAML configuration file (optional)
            frame_width: Camera frame width in pixels
            frame_height: Camera frame height in pixels
            max_sources: Maximum concurrent audio sources
            enable_hrtf: Enable HRTF for binaural audio
            comfort_mode: Preset comfort mode (GENTLE, BALANCED, INFORMATIVE)
            comfort_settings: Custom comfort settings (overrides mode)
        """
        self.config_path = config_path
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.max_sources = max_sources
        self.enable_hrtf = enable_hrtf
        
        # Comfort settings (use custom or from mode)
        if comfort_settings is not None:
            self.comfort = comfort_settings
        else:
            self.comfort = ComfortSettings.from_mode(comfort_mode)
        
        # Override max_sources from comfort settings
        self.max_sources = min(max_sources, self.comfort.max_simultaneous_objects)
        
        # State
        self._initialized = False
        self._running = False
        self._lock = threading.Lock()
        
        # OpenAL context
        self._device = None
        self._context = None
        
        # Position calculator with spatial width for HRTF
        # spatial_width_meters controls how wide the sound field is
        # CRITICAL: Higher values = MORE perceivable left/right separation
        # Research suggests 4-6m width provides best HRTF perception
        self.position_calc = PositionCalculator(
            frame_width=frame_width,
            frame_height=frame_height,
            spatial_width_meters=5.0  # Objects at screen edges will be ±2.5m left/right
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
        self._alert_source = None  # Reusable alert source to prevent memory leak
        
        # Beacon interval timing state (for interval pings)
        self._last_beacon_ping_time = 0.0
        self._beacon_ping_interval_ms = self.comfort.beacon_interval_far_ms
        
        # Object sound cooldown tracking
        self._last_object_sound_times: Dict[str, float] = {}
        
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
            # OpenAL-Soft will use HRTF automatically if available for headphones
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
                logger.debug("Distance model set to INVERSE_DISTANCE_CLAMPED")
            except Exception as dm_err:
                logger.warning(f"⚠️ Could not set distance model: {dm_err}")
            
            # CRITICAL: Set listener at origin, facing -Z (forward in OpenAL)
            # Listener orientation: (forward_x, forward_y, forward_z, up_x, up_y, up_z)
            # Default: facing -Z axis (into the screen), up is +Y
            listener = oalGetListener()
            listener.set_position((0, 0, 0))
            listener.set_orientation((0, 0, -1, 0, 1, 0))  # (forward_xyz, up_xyz)
            logger.debug("Listener set at origin (0,0,0), facing -Z, up +Y")
            
            self._initialized = True
            self._running = True
            
            logger.info("✅ Spatial Audio Manager started")
            logger.info(f"   🎧 HRTF enabled: {self.enable_hrtf}")
            logger.info(f"   📍 Spatial width: {self.position_calc.spatial_width_meters}m")
            logger.info(f"   🔊 Max sources: {self.max_sources}")
            logger.info(f"   🎚️ Master volume: {self.comfort.master_volume}")
            
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
            
            # Stop and destroy all sources (CRITICAL: must destroy to free OpenAL memory)
            for source_info in self._sources.values():
                try:
                    source_info.source.stop()
                    source_info.source.destroy()
                except:
                    pass
            self._sources.clear()
            
            # Destroy alert source if exists
            if self._alert_source:
                try:
                    self._alert_source.stop()
                    self._alert_source.destroy()
                except:
                    pass
                self._alert_source = None
            
            # Clear buffer cache (buffers are destroyed by oalQuit)
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
                # Generate STABLE object ID from bbox center (not memory address!)
                # This ensures the same object across frames has the same ID
                cx = int((detection.bbox[0] + detection.bbox[2]) / 2 / 50) * 50  # Round to 50px grid
                cy = int((detection.bbox[1] + detection.bbox[3]) / 2 / 50) * 50
                object_id = detection.object_id or f"{detection.class_name}_{cx}_{cy}"
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
                    # EXISTING object - update position and ping interval
                    self._update_source_position(object_id, position)
                    # Debug: Show that we're UPDATING (not recreating)
                    logger.debug(f"📍 UPDATE {object_id}: dist={position.distance_meters:.1f}m")
                elif len(self._sources) < self.max_sources:
                    # NEW object - create audio source
                    self._create_source(object_id, detection.class_name, position)
                    logger.info(f"🆕 CREATE {object_id}: dist={position.distance_meters:.1f}m")
                
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
        """
        Create a new audio source for an object with comfort-aware settings.
        
        CRITICAL FOR HRTF SPATIALIZATION:
        - Source must be MONO (stereo bypasses HRTF)
        - Position must be in METERS for perceivable effect
        - Reference distance should be ~1.0m
        - Source position is set relative to listener at origin
        """
        if not OPENAL_AVAILABLE:
            return
        
        # Check object sound cooldown (rest period between new object sounds)
        current_time = time.time() * 1000  # Convert to ms
        if object_class in self._last_object_sound_times:
            elapsed = current_time - self._last_object_sound_times[object_class]
            if elapsed < self.comfort.object_sound_cooldown_ms:
                return  # Skip - still in cooldown
        
        try:
            # Get sound file for object class (MUST be MONO for HRTF!)
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
            
            # CRITICAL: Set 3D position FIRST before other properties
            # Position is now in METERS (e.g., x=-1.5 = 1.5 meters to the left)
            source.set_position(position.as_tuple())
            
            # IMPORTANT: Use interval pinging, NOT continuous looping!
            # Continuous sounds cause listener fatigue. Interval pings don't.
            # The ping rate is controlled by distance (closer = faster pings)
            source.set_looping(False)  # We manually trigger pings based on distance
            
            # Apply comfort settings: volume (stereo_spread is NOT a volume factor!)
            # stereo_spread is for optional crossfeed effects, not volume reduction
            effective_volume = (
                self.comfort.master_volume * 
                self.comfort.object_volume
            )
            source.set_gain(effective_volume)
            
            # CRITICAL: Distance attenuation for realistic 3D audio
            # reference_distance = distance at which gain is 1.0 (full volume)
            # rolloff_factor = how quickly volume decreases with distance
            # With inverse distance: gain = ref_dist / (ref_dist + rolloff * (dist - ref_dist))
            # HRTF RESEARCH: Use smaller ref_distance for more pronounced positioning
            source.set_reference_distance(0.5)  # Full volume at 0.5 meter (closer = better HRTF)
            source.set_rolloff_factor(1.5)      # Slightly faster rolloff for distance perception
            source.set_max_distance(12.0)       # Max attenuation distance
            
            # Apply pitch based on distance if enabled
            if self.comfort.pitch_distance_mapping and position.distance_meters:
                pitch = self._calculate_pitch_for_distance(position.distance_meters)
                source.set_pitch(pitch)
            
            # Calculate initial ping interval based on distance
            ping_interval = self._get_object_ping_interval(position.distance_meters)
            
            # Start playing immediately (first ping)
            source.play()
            
            # Update cooldown tracking
            self._last_object_sound_times[object_class] = current_time
            
            # Store source info with ping timing
            self._sources[object_id] = AudioSourceInfo(
                source=source,
                buffer=buffer,
                object_class=object_class,
                position=position,
                created_at=time.time(),
                last_updated=time.time(),
                last_ping_time=current_time,
                ping_interval_ms=ping_interval
            )
            
            logger.debug(f"🔊 Created 3D source for {object_class} at {position} (ping every {ping_interval}ms)")
            
        except Exception as e:
            logger.error(f"Failed to create audio source: {e}")
    
    def _get_object_ping_interval(self, distance_meters: Optional[float]) -> float:
        """
        Calculate ping interval for object sounds based on distance.
        
        CLOSER = FASTER PINGS (more urgent feedback)
        This matches user expectations: rapid beeping means close!
        
        Distance thresholds mirror beacon intervals from ComfortSettings.
        """
        if distance_meters is None:
            return 1500.0  # Default: moderate interval
        
        # Use same thresholds as beacon but slightly slower for objects
        # (objects are less urgent than navigation targets)
        # NOTE: Using <= for close thresholds to ensure boundary values get faster pings
        if distance_meters <= 0.5:
            return 150.0   # Very close: rapid pings (almost continuous)
        elif distance_meters <= 1.0:
            return 300.0   # Close: fast pings
        elif distance_meters <= 2.0:
            return 600.0   # Near: moderate pings
        elif distance_meters <= 4.0:
            return 1200.0  # Mid-range: slow pings
        else:
            return 2000.0  # Far: very slow pings
    
    def _calculate_pitch_for_distance(self, distance_meters: float) -> float:
        """
        Calculate pitch based on distance (intuitive: closer = higher pitch).
        
        This is more intuitive for users than arbitrary pitch changes.
        """
        # Map distance to pitch: 0m = max_pitch, 10m = min_pitch
        max_dist = 10.0
        normalized = min(distance_meters / max_dist, 1.0)  # 0.0 (close) to 1.0 (far)
        
        pitch_range = self.comfort.max_pitch - self.comfort.min_pitch
        pitch = self.comfort.max_pitch - (normalized * pitch_range)
        
        return pitch
    
    def _update_source_position(self, object_id: str, position: Position3D) -> None:
        """
        Update the position of an existing audio source.
        
        Also handles distance-based ping timing:
        - Recalculates ping interval based on new distance
        - Triggers ping if enough time has elapsed
        """
        if object_id not in self._sources:
            return
        
        source_info = self._sources[object_id]
        source_info.position = position
        source_info.last_updated = time.time()
        
        try:
            # Update 3D position
            source_info.source.set_position(position.as_tuple())
            
            # Recalculate ping interval based on distance
            # This makes pings faster as objects get closer!
            new_interval = self._get_object_ping_interval(position.distance_meters)
            source_info.ping_interval_ms = new_interval
            
            # Update pitch based on distance
            if self.comfort.pitch_distance_mapping and position.distance_meters:
                pitch = self._calculate_pitch_for_distance(position.distance_meters)
                source_info.source.set_pitch(pitch)
            
            # Check if it's time for the next ping
            current_time_ms = time.time() * 1000
            elapsed = current_time_ms - source_info.last_ping_time
            
            if elapsed >= source_info.ping_interval_ms:
                # Time for next ping - play the sound
                source_info.source.stop()  # Stop any ongoing playback
                source_info.source.play()  # Start new ping
                source_info.last_ping_time = current_time_ms
                
                # Debug: Log ping events so user can see rate changes
                dist = position.distance_meters or 0
                logger.debug(
                    f"🔔 PING: {source_info.object_class} "
                    f"dist={dist:.1f}m interval={source_info.ping_interval_ms:.0f}ms"
                )
                
        except Exception as e:
            logger.error(f"Failed to update source position: {e}")
    
    def _remove_source(self, object_id: str) -> None:
        """Remove an audio source when object leaves frame."""
        if object_id not in self._sources:
            return
        
        source_info = self._sources.pop(object_id)
        
        try:
            source_info.source.stop()
            # CRITICAL: Must call .destroy() to free OpenAL resources!
            source_info.source.destroy()
        except Exception as e:
            logger.debug(f"Error destroying source: {e}")
        
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
            # CRITICAL: Use SHORT sounds (100ms) for distinct, perceivable pings!
            # Previous 500ms was too long - overlapped with fast ping intervals,
            # making rate changes imperceptible to the user.
            # 100ms = crisp, identifiable "ping" that works with 150ms+ intervals
            # amplitude=0.8 for louder, more noticeable pings (was 0.4 default)
            wav_bytes = sound_gen.generate_object_tone(object_class, duration_ms=100, amplitude=0.8)
            
            # Save to temp file for OpenAL to load
            temp_path = self._get_temp_sound_path(f"object_{object_class.lower()}_ping_loud.wav")
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
        
        Features (based on Microsoft Soundscape research):
        - Interval pings instead of continuous sound (reduces fatigue)
        - Optional start melody for beacon activation
        - Volume and pitch adjusted by comfort settings
        
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
            self._last_beacon_ping_time = 0.0  # Force immediate first ping
            
            # Play start melody if enabled (from Soundscape pattern)
            if self.comfort.play_beacon_start_melody:
                self._play_beacon_melody("start")
            
            # Generate procedural beacon sound if no custom file provided
            if sound_file is None:
                sound_gen = get_sound_generator()
                try:
                    # Generate beacon ping based on earcon style
                    freq = {"gentle": 660, "clear": 880, "bright": 1100}.get(
                        self.comfort.earcon_style, 880
                    )
                    wav_bytes = sound_gen.generate_beacon_ping(frequency=freq, duration_ms=150)
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
                return True
            
            try:
                buffer = self._load_buffer(str(sound_file))
                if buffer:
                    self._beacon_source = Source(buffer)
                    # NOT looping - we'll manually trigger pings at intervals
                    self._beacon_source.set_looping(not self.comfort.use_interval_pings)
                    
                    # Apply comfort volume
                    effective_volume = self.comfort.master_volume * self.comfort.beacon_volume
                    self._beacon_source.set_gain(effective_volume)
                    
                    logger.info(f"🎯 Beacon activated for target: {target_class} (interval: {self.comfort.use_interval_pings})")
                    return True
            except Exception as e:
                logger.error(f"Failed to create beacon source: {e}")
            
            return False
    
    def _play_beacon_melody(self, melody_type: str) -> None:
        """
        Play beacon start/end melody.
        
        From Soundscape: short melodies help users know when beacon state changes
        """
        sound_gen = get_sound_generator()
        try:
            if melody_type == "start":
                # Rising melody (activation)
                wav_bytes = sound_gen.generate_beacon_ping(frequency=440, duration_ms=100)
            elif melody_type == "end":
                # Descending melody (destination reached)
                wav_bytes = sound_gen.generate_beacon_ping(frequency=660, duration_ms=150)
            else:
                return
            
            temp_path = self._get_temp_sound_path(f"melody_{melody_type}.wav")
            sound_gen.save_to_file(wav_bytes, temp_path)
            
            if os.path.exists(temp_path):
                buffer = self._load_buffer(temp_path)
                if buffer:
                    melody_source = Source(buffer)
                    melody_source.set_gain(self.comfort.master_volume * 0.5)
                    melody_source.play()
                    # Note: Not tracking this source, it plays once and OpenAL handles cleanup
        except Exception as e:
            logger.debug(f"Failed to play beacon melody: {e}")
    
    def _update_beacon_position(self, position: Position3D) -> None:
        """
        Update beacon position when target is detected.
        
        If using interval pings, only plays at calculated intervals based on distance.
        """
        if not self._beacon_source:
            return
        
        try:
            self._beacon_source.set_position(position.as_tuple())
            
            # Check for proximity auto-mute
            if (self.comfort.proximity_auto_mute and 
                position.distance_meters and 
                position.distance_meters < self.comfort.proximity_mute_distance_m):
                # Very close - stop beacon (from Soundscape pattern)
                if self.comfort.play_beacon_end_melody:
                    self._play_beacon_melody("end")
                self.stop_beacon()
                logger.info("🎯 Destination reached - beacon auto-muted")
                return
            
            # Handle interval pinging
            if self.comfort.use_interval_pings:
                current_time_ms = time.time() * 1000
                
                # Calculate interval based on distance
                if position.distance_meters:
                    self._beacon_ping_interval_ms = self._get_beacon_interval(position.distance_meters)
                
                # Check if it's time for next ping
                elapsed = current_time_ms - self._last_beacon_ping_time
                if elapsed >= self._beacon_ping_interval_ms:
                    # Play ping
                    if not self._beacon_source.get_state():  # Not already playing
                        # Apply pitch based on distance
                        if self.comfort.pitch_distance_mapping and position.distance_meters:
                            pitch = self._calculate_pitch_for_distance(position.distance_meters)
                            self._beacon_source.set_pitch(pitch)
                        
                        self._beacon_source.play()
                        self._last_beacon_ping_time = current_time_ms
            else:
                # Continuous mode - start playing if not already
                if not self._beacon_source.get_state():
                    self._beacon_source.play()
                
                # Apply pitch adjustment
                if self.comfort.pitch_distance_mapping and position.distance_meters:
                    pitch = self._calculate_pitch_for_distance(position.distance_meters)
                    self._beacon_source.set_pitch(pitch)
                
        except Exception as e:
            logger.error(f"Failed to update beacon position: {e}")
    
    def _get_beacon_interval(self, distance_meters: float) -> int:
        """
        Get beacon ping interval based on distance.
        
        Closer = faster pings (more urgent feedback).
        From Soundscape: intuitive mapping helps users understand distance.
        """
        if distance_meters < 1.0:
            return self.comfort.beacon_interval_close_ms
        elif distance_meters < 2.0:
            return self.comfort.beacon_interval_near_ms
        elif distance_meters < 5.0:
            return self.comfort.beacon_interval_mid_ms
        else:
            return self.comfort.beacon_interval_far_ms
    
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
        """
        Update proximity alert level based on closest obstacle.
        
        EMERGENCY ALERT: Triggers when object is very close (<0.5m).
        This is critical for safety - blind users need immediate warning!
        """
        distance = self._closest_obstacle_distance
        
        # Determine alert level based on distance thresholds
        if distance < 0.3:
            new_level = "emergency"  # NEW: Distinct emergency for very close objects
        elif distance < 0.7:
            new_level = "critical"
        elif distance < 1.2:
            new_level = "danger"
        elif distance < 2.0:
            new_level = "warning"
        elif distance < 3.5:
            new_level = "notice"
        else:
            new_level = "none"
        
        # Only trigger alert if level changed (prevents sound spam)
        if new_level != self._proximity_alert_level:
            self._proximity_alert_level = new_level
            self._play_proximity_alert(new_level)
            
            # Log emergency alerts prominently
            if new_level == "emergency":
                logger.warning(f"🚨 EMERGENCY: Object extremely close! ({distance:.2f}m)")
            elif new_level == "critical":
                logger.warning(f"⚠️ CRITICAL: Object very close! ({distance:.2f}m)")
    
    def _play_proximity_alert(self, level: str) -> None:
        """
        Play proximity alert sound for given level using procedural sounds.
        
        Uses comfort settings for volume control.
        EMERGENCY level bypasses comfort settings for safety!
        """
        if level == "none":
            return
        
        # Calculate effective volume with comfort settings
        # EMERGENCY alerts are louder for safety-critical feedback
        if level == "emergency":
            effective_volume = min(1.0, self.comfort.master_volume * 1.5)  # 50% louder
        elif level == "critical":
            effective_volume = self.comfort.master_volume * self.comfort.proximity_volume * 1.3
        else:
            effective_volume = self.comfort.master_volume * self.comfort.proximity_volume
        
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
                    # Reuse existing alert source or create new one
                    if hasattr(self, '_alert_source') and self._alert_source:
                        try:
                            self._alert_source.stop()
                            self._alert_source.destroy()
                        except:
                            pass
                    self._alert_source = Source(buffer)
                    self._alert_source.set_position((0, 0, -1))  # In front
                    self._alert_source.set_gain(effective_volume)
                    self._alert_source.play()
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
                        # Reuse existing alert source
                        if hasattr(self, '_alert_source') and self._alert_source:
                            try:
                                self._alert_source.stop()
                                self._alert_source.destroy()
                            except:
                                pass
                        self._alert_source = Source(buffer)
                        self._alert_source.set_position((0, 0, -1))  # In front
                        self._alert_source.set_gain(effective_volume)
                        self._alert_source.play()
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
    
    # ========== COMFORT CONFIGURATION ==========
    
    def set_comfort_mode(self, mode: ComfortMode) -> None:
        """
        Switch to a preset comfort mode.
        
        Args:
            mode: ComfortMode.GENTLE, BALANCED, or INFORMATIVE
        """
        self.comfort = ComfortSettings.from_mode(mode)
        self.max_sources = min(self.max_sources, self.comfort.max_simultaneous_objects)
        logger.info(f"🎛️ Switched to {mode.value} comfort mode")
    
    def set_master_volume(self, volume: float) -> None:
        """
        Set master volume (0.0 to 1.0).
        
        Args:
            volume: Volume level (0.0 = silent, 1.0 = full)
        """
        self.comfort.master_volume = max(0.0, min(1.0, volume))
        logger.info(f"🔊 Master volume set to {self.comfort.master_volume:.0%}")
    
    def set_beacon_interval_mode(self, use_intervals: bool) -> None:
        """
        Toggle between interval pings and continuous beacon.
        
        Args:
            use_intervals: True for interval pings (recommended), False for continuous
        """
        self.comfort.use_interval_pings = use_intervals
        mode_str = "interval pings" if use_intervals else "continuous"
        logger.info(f"🎯 Beacon mode set to {mode_str}")
    
    def set_stereo_spread(self, spread: float) -> None:
        """
        Set stereo spread for reduced listener fatigue.
        
        Lower values (0.5-0.7) are more comfortable for extended use.
        Higher values (0.8-1.0) provide more spatial precision.
        
        Args:
            spread: Stereo spread (0.0 = mono, 1.0 = full stereo)
        """
        self.comfort.stereo_spread = max(0.0, min(1.0, spread))
        logger.info(f"🎧 Stereo spread set to {self.comfort.stereo_spread:.0%}")
    
    def get_comfort_settings(self) -> Dict[str, Any]:
        """Get current comfort settings as a dictionary."""
        return {
            "master_volume": self.comfort.master_volume,
            "beacon_volume": self.comfort.beacon_volume,
            "proximity_volume": self.comfort.proximity_volume,
            "object_volume": self.comfort.object_volume,
            "use_interval_pings": self.comfort.use_interval_pings,
            "stereo_spread": self.comfort.stereo_spread,
            "earcon_style": self.comfort.earcon_style,
            "max_simultaneous_objects": self.comfort.max_simultaneous_objects,
            "proximity_auto_mute": self.comfort.proximity_auto_mute,
            "play_beacon_melodies": self.comfort.play_beacon_start_melody,
        }
    
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
            "beacon_ping_interval_ms": self._beacon_ping_interval_ms if self._beacon_active else None,
            "proximity_alert_level": self._proximity_alert_level,
            "closest_obstacle_meters": self._closest_obstacle_distance if self._closest_obstacle_distance != float('inf') else None,
            "listener_orientation": self._listener_orientation,
            "openal_available": OPENAL_AVAILABLE,
            "spatial_width_meters": self.position_calc.spatial_width_meters,
            "comfort_mode": {
                "master_volume": self.comfort.master_volume,
                "stereo_spread": self.comfort.stereo_spread,
                "use_interval_pings": self.comfort.use_interval_pings,
            },
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
    
    def test_spatial_positioning(self, duration_seconds: float = 10.0) -> None:
        """
        🧪 DEBUG: Test spatial audio positioning with a moving sound.
        
        This test creates a sound that pans from LEFT → CENTER → RIGHT
        so you can verify HRTF spatialization is working correctly.
        
        Put on headphones and run this test!
        
        Args:
            duration_seconds: How long to run the test
        """
        if not self._initialized:
            if not self.start():
                logger.error("Cannot test - failed to start audio system")
                return
        
        if not OPENAL_AVAILABLE:
            logger.error("Cannot test - PyOpenAL not available")
            return
        
        logger.info("=" * 60)
        logger.info("🎧 SPATIAL AUDIO POSITIONING TEST")
        logger.info("=" * 60)
        logger.info("Put on headphones! A sound will pan LEFT → CENTER → RIGHT")
        logger.info(f"Test duration: {duration_seconds} seconds")
        logger.info("")
        
        try:
            # Generate a test tone
            from .sound_generator import get_sound_generator
            sound_gen = get_sound_generator()
            wav_bytes = sound_gen.generate_beacon_ping(frequency=660, duration_ms=500)
            
            # Save to temp file
            import tempfile
            temp_path = tempfile.mktemp(suffix=".wav")
            with open(temp_path, 'wb') as f:
                f.write(wav_bytes)
            
            # Load buffer
            wave_file = WaveFile(temp_path)
            buffer = Buffer(wave_file)
            
            # Create source
            source = Source(buffer)
            source.set_looping(True)
            source.set_gain(self.comfort.master_volume * 0.7)
            
            # Distance settings (source is always at z=-2m in front)
            source.set_reference_distance(1.0)
            source.set_rolloff_factor(1.0)
            source.set_max_distance(15.0)
            
            # Start at LEFT position
            start_x = -1.5  # 1.5 meters to the left
            source.set_position((start_x, 0.0, -2.0))  # z=-2m means 2 meters in front
            source.play()
            
            logger.info(f"▶️ Sound started at LEFT (x={start_x}m, z=-2m)")
            
            # Animate position from left to right
            import time as timer
            start_time = timer.time()
            
            while timer.time() - start_time < duration_seconds:
                elapsed = timer.time() - start_time
                progress = elapsed / duration_seconds
                
                # Oscillate x from -1.5 to +1.5 meters
                x = -1.5 + (progress * 3.0)  # Moves from -1.5 to +1.5
                if x > 1.5:
                    x = 1.5  # Clamp at end
                
                source.set_position((x, 0.0, -2.0))
                
                # Log position periodically
                if int(elapsed * 2) % 2 == 0:  # Every 0.5 seconds
                    direction = "LEFT" if x < -0.5 else ("CENTER" if x < 0.5 else "RIGHT")
                    logger.info(f"   📍 Position: x={x:.2f}m ({direction})")
                
                timer.sleep(0.05)  # 50ms update rate
            
            # Cleanup
            source.stop()
            source.destroy()
            
            # Delete temp file
            try:
                os.unlink(temp_path)
            except:
                pass
            
            logger.info("")
            logger.info("✅ Spatial test complete!")
            logger.info("   Did you hear the sound move from LEFT to RIGHT?")
            logger.info("   If NOT, check:")
            logger.info("   1. Are you using headphones? (speakers won't work)")
            logger.info("   2. Is OpenAL-Soft installed with HRTF support?")
            logger.info("   3. Try enabling stereo-encoding=hrtf in alsoft.ini")
            
        except Exception as e:
            logger.error(f"Spatial test failed: {e}")
            import traceback
            traceback.print_exc()
    
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
            
            # Run spatial positioning test
            print("\n" + "=" * 60)
            print("🎧 SPATIAL AUDIO TEST - Put on headphones!")
            print("=" * 60)
            print("\nRunning spatial positioning test...")
            print("You should hear a sound pan from LEFT → CENTER → RIGHT\n")
            
            audio.test_spatial_positioning(duration_seconds=6.0)
            
            print("\n" + "-" * 60)
            print("Now testing object detection simulation...")
            print("-" * 60)
            
            # Simulate some detections
            print("\nSimulating detections at different positions...")
            
            # Object on the LEFT side of the screen
            test_detections = [
                Detection(
                    class_name="chair",
                    confidence=0.92,
                    bbox=(100, 200, 300, 600),  # Left side of 1920 width
                    object_id="chair_1"
                ),
            ]
            
            audio.update_detections(test_detections)
            print(f"  → Chair positioned at LEFT")
            print(f"  → Active objects: {audio.get_active_objects()}")
            
            time.sleep(2)
            
            # Object on the RIGHT side
            test_detections = [
                Detection(
                    class_name="person",
                    confidence=0.87,
                    bbox=(1400, 100, 1800, 900),  # Right side of 1920 width
                    object_id="person_1"
                ),
            ]
            
            audio.update_detections(test_detections)
            print(f"  → Person positioned at RIGHT")
            print(f"  → Active objects: {audio.get_active_objects()}")
            
            time.sleep(2)
            
            # Object in CENTER
            test_detections = [
                Detection(
                    class_name="door",
                    confidence=0.95,
                    bbox=(800, 100, 1100, 800),  # Center of 1920 width
                    object_id="door_1"
                ),
            ]
            
            audio.update_detections(test_detections)
            print(f"  → Door positioned at CENTER")
            print(f"  → Active objects: {audio.get_active_objects()}")
            
            time.sleep(2)
            
            print(f"\nStatus: {audio.get_status()}")
            
            audio.stop()
            print("\n✅ Test complete")
        else:
            print("❌ Failed to start audio system")
    else:
        print("\n⚠️ PyOpenAL not installed. Install with: pip install PyOpenAL")
        print("   The manager can still be instantiated, but audio features are disabled.")
