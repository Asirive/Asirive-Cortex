"""
Project-Cortex v2.0 - Audio Beacon System

Provides continuous directional audio guidance to help visually impaired users
navigate toward a target object. The beacon emits rhythmic "ping" sounds from
the target's 3D position, with the ping rate increasing as the user approaches.

Features:
- Spatial pings from target direction
- Distance-based ping rate (closer = faster)
- Success chime when target is reached
- Configurable sound profiles

Author: Haziq (@IRSPlays)
"""

import os
import time
import threading
from typing import Optional, Tuple, Callable
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger("AudioBeacon")

# Try to import PyOpenAL
OPENAL_AVAILABLE = False
try:
    from openal import Source, Buffer
    OPENAL_AVAILABLE = True
except ImportError:
    pass


class BeaconState(Enum):
    """Beacon operational states."""
    INACTIVE = "inactive"
    SEARCHING = "searching"  # Target not yet detected
    TRACKING = "tracking"    # Actively guiding to target
    REACHED = "reached"      # Target has been reached


@dataclass
class BeaconConfig:
    """Configuration for beacon behavior."""
    # Ping rates at different distances (Hz)
    ping_rate_far: float = 1.0        # > 5m
    ping_rate_medium: float = 2.0      # 2-5m
    ping_rate_close: float = 4.0       # 1-2m
    ping_rate_very_close: float = 8.0  # < 1m
    
    # Distance thresholds (meters)
    threshold_far: float = 5.0
    threshold_medium: float = 2.0
    threshold_close: float = 1.0
    threshold_reached: float = 0.5
    
    # Volume settings
    min_volume: float = 0.3
    max_volume: float = 1.0
    
    # Pitch variation (higher when closer)
    pitch_far: float = 0.9
    pitch_close: float = 1.2


class AudioBeacon:
    """
    Directional audio beacon for navigation guidance.
    
    Emits rhythmic ping sounds from the target's 3D position.
    The ping rate and volume increase as the user gets closer.
    
    Example:
        beacon = AudioBeacon()
        beacon.start(target_position=(0.5, 0, -3.0))  # Target to the right
        
        # Update position as target moves
        beacon.update_position((0.3, 0, -2.0))
        
        # Stop when done
        beacon.stop()
    """
    
    def __init__(
        self,
        ping_sound_path: Optional[str] = None,
        success_sound_path: Optional[str] = None,
        config: Optional[BeaconConfig] = None,
        on_target_reached: Optional[Callable] = None
    ):
        """
        Initialize the Audio Beacon.
        
        Args:
            ping_sound_path: Path to ping sound file (WAV)
            success_sound_path: Path to success chime sound file (WAV)
            config: Beacon configuration (optional)
            on_target_reached: Callback when target is reached (optional)
        """
        self.ping_sound_path = ping_sound_path
        self.success_sound_path = success_sound_path
        self.config = config or BeaconConfig()
        self.on_target_reached = on_target_reached
        
        # State
        self._state = BeaconState.INACTIVE
        self._position: Optional[Tuple[float, float, float]] = None
        self._distance_meters: Optional[float] = None
        
        # Audio resources
        self._ping_source: Optional[Source] = None
        self._ping_buffer: Optional[Buffer] = None
        self._success_buffer: Optional[Buffer] = None
        
        # Ping thread
        self._ping_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        
        # Current ping parameters
        self._current_ping_rate = self.config.ping_rate_far
        self._current_volume = self.config.min_volume
        self._current_pitch = self.config.pitch_far
        
        # Load sounds if paths provided
        if ping_sound_path and os.path.exists(ping_sound_path):
            self._load_sounds()
    
    def _load_sounds(self) -> bool:
        """Load sound files into buffers."""
        if not OPENAL_AVAILABLE:
            logger.warning("OpenAL not available, beacon sounds disabled")
            return False
        
        try:
            if self.ping_sound_path and os.path.exists(self.ping_sound_path):
                self._ping_buffer = Buffer(self.ping_sound_path)
                logger.debug(f"Loaded ping sound: {self.ping_sound_path}")
            
            if self.success_sound_path and os.path.exists(self.success_sound_path):
                self._success_buffer = Buffer(self.success_sound_path)
                logger.debug(f"Loaded success sound: {self.success_sound_path}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to load beacon sounds: {e}")
            return False
    
    def start(
        self,
        target_position: Optional[Tuple[float, float, float]] = None,
        ping_sound_path: Optional[str] = None
    ) -> bool:
        """
        Start the audio beacon.
        
        Args:
            target_position: Initial (x, y, z) position of target
            ping_sound_path: Override ping sound file
            
        Returns:
            True if started successfully
        """
        if self._running:
            logger.warning("Beacon already running")
            return True
        
        # Update sound if provided
        if ping_sound_path:
            self.ping_sound_path = ping_sound_path
            self._load_sounds()
        
        # Initialize position
        self._position = target_position
        
        if target_position:
            self._state = BeaconState.TRACKING
            self._distance_meters = self._calculate_distance(target_position)
        else:
            self._state = BeaconState.SEARCHING
            self._distance_meters = None
        
        # Create source if we have audio
        if OPENAL_AVAILABLE and self._ping_buffer:
            try:
                self._ping_source = Source(self._ping_buffer)
                self._ping_source.set_looping(False)  # We control timing
                
                if target_position:
                    self._ping_source.set_position(target_position)
                    
            except Exception as e:
                logger.error(f"Failed to create beacon source: {e}")
        
        # Start ping thread
        self._running = True
        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._ping_thread.start()
        
        logger.info(f"🎯 Beacon started, state: {self._state.value}")
        return True
    
    def stop(self) -> None:
        """Stop the audio beacon."""
        self._running = False
        
        if self._ping_thread and self._ping_thread.is_alive():
            self._ping_thread.join(timeout=1.0)
        
        if self._ping_source:
            try:
                self._ping_source.stop()
            except:
                pass
            self._ping_source = None
        
        self._state = BeaconState.INACTIVE
        self._position = None
        self._distance_meters = None
        
        logger.info("🛑 Beacon stopped")
    
    def update_position(self, position: Tuple[float, float, float]) -> None:
        """
        Update the target's 3D position.
        
        Args:
            position: New (x, y, z) position
        """
        with self._lock:
            self._position = position
            self._distance_meters = self._calculate_distance(position)
            
            # Update state based on distance
            if self._distance_meters and self._distance_meters <= self.config.threshold_reached:
                if self._state != BeaconState.REACHED:
                    self._on_target_reached()
            elif self._state == BeaconState.SEARCHING:
                self._state = BeaconState.TRACKING
            
            # Update audio source position
            if self._ping_source:
                try:
                    self._ping_source.set_position(position)
                except:
                    pass
            
            # Update ping parameters based on distance
            self._update_ping_parameters()
    
    def update_distance(self, distance_meters: float) -> None:
        """
        Update the distance directly (if known from other source).
        
        Args:
            distance_meters: Distance to target in meters
        """
        with self._lock:
            self._distance_meters = distance_meters
            
            if distance_meters <= self.config.threshold_reached:
                if self._state != BeaconState.REACHED:
                    self._on_target_reached()
            
            self._update_ping_parameters()
    
    def _calculate_distance(self, position: Tuple[float, float, float]) -> float:
        """Calculate distance from listener (at origin) to position."""
        x, y, z = position
        return (x**2 + y**2 + z**2) ** 0.5
    
    def _update_ping_parameters(self) -> None:
        """Update ping rate, volume, and pitch based on current distance."""
        if self._distance_meters is None:
            return
        
        distance = self._distance_meters
        config = self.config
        
        # Determine ping rate based on distance
        if distance > config.threshold_far:
            self._current_ping_rate = config.ping_rate_far
            self._current_volume = config.min_volume
            self._current_pitch = config.pitch_far
        elif distance > config.threshold_medium:
            # Interpolate between far and medium
            t = (config.threshold_far - distance) / (config.threshold_far - config.threshold_medium)
            self._current_ping_rate = config.ping_rate_far + t * (config.ping_rate_medium - config.ping_rate_far)
            self._current_volume = config.min_volume + t * 0.2
            self._current_pitch = config.pitch_far + t * 0.1
        elif distance > config.threshold_close:
            # Interpolate between medium and close
            t = (config.threshold_medium - distance) / (config.threshold_medium - config.threshold_close)
            self._current_ping_rate = config.ping_rate_medium + t * (config.ping_rate_close - config.ping_rate_medium)
            self._current_volume = config.min_volume + 0.2 + t * 0.2
            self._current_pitch = config.pitch_far + 0.1 + t * 0.1
        else:
            # Very close - maximum urgency
            t = (config.threshold_close - distance) / (config.threshold_close - config.threshold_reached)
            self._current_ping_rate = config.ping_rate_close + t * (config.ping_rate_very_close - config.ping_rate_close)
            self._current_volume = min(config.max_volume, config.min_volume + 0.4 + t * 0.3)
            self._current_pitch = config.pitch_close
    
    def _ping_loop(self) -> None:
        """Background thread that emits pings at the current rate."""
        while self._running:
            # Calculate sleep time based on ping rate
            if self._current_ping_rate > 0:
                sleep_time = 1.0 / self._current_ping_rate
            else:
                sleep_time = 1.0
            
            # Emit ping if tracking
            if self._state == BeaconState.TRACKING and self._ping_source:
                self._emit_ping()
            
            # Sleep until next ping
            time.sleep(sleep_time)
    
    def _emit_ping(self) -> None:
        """Emit a single ping sound."""
        if not self._ping_source:
            return
        
        try:
            with self._lock:
                # Update source properties
                self._ping_source.set_gain(self._current_volume)
                self._ping_source.set_pitch(self._current_pitch)
                
                if self._position:
                    self._ping_source.set_position(self._position)
                
                # Play ping
                self._ping_source.play()
                
        except Exception as e:
            logger.error(f"Failed to emit ping: {e}")
    
    def _on_target_reached(self) -> None:
        """Handle target reached event."""
        self._state = BeaconState.REACHED
        logger.info("✅ Target reached!")
        
        # Play success sound
        if OPENAL_AVAILABLE and self._success_buffer:
            try:
                success_source = Source(self._success_buffer)
                success_source.set_position((0, 0, -0.5))  # In front
                success_source.play()
            except Exception as e:
                logger.error(f"Failed to play success sound: {e}")
        
        # Call callback if provided
        if self.on_target_reached:
            try:
                self.on_target_reached()
            except Exception as e:
                logger.error(f"Error in on_target_reached callback: {e}")
    
    def get_state(self) -> BeaconState:
        """Get current beacon state."""
        return self._state
    
    def get_distance(self) -> Optional[float]:
        """Get current distance to target in meters."""
        return self._distance_meters
    
    def get_position(self) -> Optional[Tuple[float, float, float]]:
        """Get current target position."""
        return self._position
    
    def get_ping_rate(self) -> float:
        """Get current ping rate in Hz."""
        return self._current_ping_rate
    
    def is_active(self) -> bool:
        """Check if beacon is actively running."""
        return self._running and self._state in (BeaconState.SEARCHING, BeaconState.TRACKING)


# ============================================================================
# Standalone Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Audio Beacon Test")
    print("=" * 60)
    
    # Test beacon configuration
    config = BeaconConfig()
    print(f"\nDefault configuration:")
    print(f"  Ping rate far: {config.ping_rate_far} Hz")
    print(f"  Ping rate close: {config.ping_rate_very_close} Hz")
    print(f"  Threshold reached: {config.threshold_reached}m")
    
    # Create beacon (without sounds for testing)
    beacon = AudioBeacon(config=config)
    
    print(f"\nOpenAL available: {OPENAL_AVAILABLE}")
    print(f"Initial state: {beacon.get_state().value}")
    
    # Simulate tracking
    print("\nSimulating approach to target...")
    
    test_positions = [
        ((0.5, 0, -8.0), "Far right, 8m away"),
        ((0.3, 0, -4.0), "Slightly right, 4m away"),
        ((0.1, 0, -2.0), "Almost center, 2m away"),
        ((0.0, 0, -1.0), "Center, 1m away"),
        ((0.0, 0, -0.3), "Center, very close"),
    ]
    
    beacon.start()
    
    for position, description in test_positions:
        beacon.update_position(position)
        
        print(f"\n  {description}")
        print(f"    Position: {position}")
        print(f"    Distance: {beacon.get_distance():.2f}m" if beacon.get_distance() else "    Distance: N/A")
        print(f"    Ping rate: {beacon.get_ping_rate():.1f} Hz")
        print(f"    State: {beacon.get_state().value}")
        
        time.sleep(0.5)
    
    beacon.stop()
    print(f"\nFinal state: {beacon.get_state().value}")
    print("\n✅ Test complete")
