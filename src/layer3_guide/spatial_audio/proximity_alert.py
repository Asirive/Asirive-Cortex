"""
Project-Cortex v2.0 - Proximity Alert System

Distance-based warning system that alerts users to approaching obstacles.
Uses escalating audio warnings based on proximity thresholds.

Alert Levels:
- None: No obstacles within range (> 3m)
- Notice: Object detected (2-3m) - soft ambient sound
- Warning: Object approaching (1-2m) - pulse tone
- Danger: Object close (0.5-1m) - rapid beeping
- Critical: Imminent collision (< 0.5m) - alarm

Author: Haziq (@IRSPlays)
"""

import os
import time
import threading
from typing import Optional, Dict, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
import logging

logger = logging.getLogger("ProximityAlert")

# Try to import PyOpenAL
OPENAL_AVAILABLE = False
try:
    from openal import Source, Buffer
    OPENAL_AVAILABLE = True
except ImportError:
    pass


class AlertLevel(Enum):
    """Proximity alert levels in order of severity."""
    NONE = 0
    NOTICE = 1
    WARNING = 2
    DANGER = 3
    CRITICAL = 4
    
    def __gt__(self, other):
        return self.value > other.value
    
    def __lt__(self, other):
        return self.value < other.value


@dataclass
class AlertThresholds:
    """Distance thresholds for each alert level (in meters)."""
    notice: float = 3.0     # Soft awareness
    warning: float = 2.0    # Attention needed
    danger: float = 1.0     # Caution required
    critical: float = 0.5   # Immediate action
    
    def get_level_for_distance(self, distance: float) -> AlertLevel:
        """Get alert level for a given distance."""
        if distance < self.critical:
            return AlertLevel.CRITICAL
        elif distance < self.danger:
            return AlertLevel.DANGER
        elif distance < self.warning:
            return AlertLevel.WARNING
        elif distance < self.notice:
            return AlertLevel.NOTICE
        else:
            return AlertLevel.NONE


@dataclass
class AlertConfig:
    """Configuration for the proximity alert system."""
    # Distance thresholds
    thresholds: AlertThresholds = field(default_factory=AlertThresholds)
    
    # Repeat intervals for each level (seconds)
    repeat_intervals: Dict[AlertLevel, float] = field(default_factory=lambda: {
        AlertLevel.NONE: 0,       # No repeating
        AlertLevel.NOTICE: 3.0,   # Every 3 seconds
        AlertLevel.WARNING: 1.5,  # Every 1.5 seconds
        AlertLevel.DANGER: 0.5,   # Every 0.5 seconds
        AlertLevel.CRITICAL: 0.2, # Every 0.2 seconds (rapid)
    })
    
    # Volume levels
    volumes: Dict[AlertLevel, float] = field(default_factory=lambda: {
        AlertLevel.NONE: 0.0,
        AlertLevel.NOTICE: 0.3,
        AlertLevel.WARNING: 0.5,
        AlertLevel.DANGER: 0.8,
        AlertLevel.CRITICAL: 1.0,
    })
    
    # Whether to announce obstacle direction
    announce_direction: bool = True
    
    # Minimum time between level changes (debounce)
    level_change_debounce: float = 0.3
    
    # Enable haptic feedback (future)
    haptic_enabled: bool = False


@dataclass
class ObstacleInfo:
    """Information about a tracked obstacle."""
    object_id: str
    object_class: str
    position: Tuple[float, float, float]
    distance: float
    direction: str  # "left", "center", "right"
    last_updated: float


class ProximityAlertSystem:
    """
    Proximity-based warning system for obstacle detection.
    
    Monitors detected objects and triggers audio alerts when
    obstacles enter the danger zone around the user.
    
    Example:
        alerts = ProximityAlertSystem()
        alerts.start()
        
        # Update with closest obstacle
        alerts.update(distance=1.5, direction="left", object_class="chair")
        
        # Or update with multiple obstacles
        alerts.update_obstacles([
            {"distance": 1.5, "direction": "left", "class": "chair"},
            {"distance": 0.8, "direction": "center", "class": "person"},
        ])
        
        alerts.stop()
    """
    
    def __init__(
        self,
        config: Optional[AlertConfig] = None,
        sound_paths: Optional[Dict[AlertLevel, str]] = None,
        on_level_change: Optional[Callable[[AlertLevel, AlertLevel], None]] = None
    ):
        """
        Initialize the Proximity Alert System.
        
        Args:
            config: Alert configuration
            sound_paths: Dict mapping AlertLevel to sound file paths
            on_level_change: Callback when alert level changes (old, new)
        """
        self.config = config or AlertConfig()
        self.sound_paths = sound_paths or {}
        self.on_level_change = on_level_change
        
        # State
        self._current_level = AlertLevel.NONE
        self._previous_level = AlertLevel.NONE
        self._closest_distance = float('inf')
        self._closest_direction = "center"
        self._closest_class = None
        
        # Tracked obstacles
        self._obstacles: Dict[str, ObstacleInfo] = {}
        
        # Audio resources
        self._sound_buffers: Dict[AlertLevel, Buffer] = {}
        self._alert_source: Optional[Source] = None
        
        # Threading
        self._running = False
        self._alert_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Timing
        self._last_alert_time = 0.0
        self._last_level_change_time = 0.0
        
        # Load sounds
        self._load_sounds()
    
    def _load_sounds(self) -> None:
        """Load alert sound files into buffers."""
        if not OPENAL_AVAILABLE:
            return
        
        for level, path in self.sound_paths.items():
            if os.path.exists(path):
                try:
                    self._sound_buffers[level] = Buffer(path)
                    logger.debug(f"Loaded {level.name} sound: {path}")
                except Exception as e:
                    logger.error(f"Failed to load {level.name} sound: {e}")
    
    def start(self) -> None:
        """Start the proximity alert system."""
        if self._running:
            return
        
        self._running = True
        self._current_level = AlertLevel.NONE
        self._closest_distance = float('inf')
        
        # Start alert loop
        self._alert_thread = threading.Thread(target=self._alert_loop, daemon=True)
        self._alert_thread.start()
        
        logger.info("🚨 Proximity Alert System started")
    
    def stop(self) -> None:
        """Stop the proximity alert system."""
        self._running = False
        
        if self._alert_thread and self._alert_thread.is_alive():
            self._alert_thread.join(timeout=1.0)
        
        if self._alert_source:
            try:
                self._alert_source.stop()
            except:
                pass
            self._alert_source = None
        
        self._current_level = AlertLevel.NONE
        self._obstacles.clear()
        
        logger.info("🛑 Proximity Alert System stopped")
    
    def update(
        self,
        distance: float,
        direction: str = "center",
        object_class: Optional[str] = None,
        position: Optional[Tuple[float, float, float]] = None
    ) -> AlertLevel:
        """
        Update with closest obstacle information.
        
        Args:
            distance: Distance to obstacle in meters
            direction: Direction of obstacle ("left", "center", "right")
            object_class: Class of detected object
            position: 3D position of obstacle
            
        Returns:
            Current alert level
        """
        with self._lock:
            self._closest_distance = distance
            self._closest_direction = direction
            self._closest_class = object_class
            
            # Update alert level
            new_level = self.config.thresholds.get_level_for_distance(distance)
            self._update_level(new_level)
            
            return self._current_level
    
    def update_obstacles(self, obstacles: List[Dict]) -> AlertLevel:
        """
        Update with multiple obstacles and track the closest.
        
        Args:
            obstacles: List of dicts with keys:
                - object_id: Unique identifier
                - object_class: Class name
                - distance: Distance in meters
                - direction: "left", "center", or "right"
                - position: Optional (x, y, z) tuple
                
        Returns:
            Current alert level
        """
        current_time = time.time()
        
        with self._lock:
            # Update tracked obstacles
            seen_ids = set()
            
            for obs in obstacles:
                obj_id = obs.get('object_id', f"obs_{id(obs)}")
                seen_ids.add(obj_id)
                
                # Determine direction from position if not provided
                direction = obs.get('direction', 'center')
                if 'position' in obs and not obs.get('direction'):
                    x = obs['position'][0]
                    if x < -0.3:
                        direction = "left"
                    elif x > 0.3:
                        direction = "right"
                    else:
                        direction = "center"
                
                self._obstacles[obj_id] = ObstacleInfo(
                    object_id=obj_id,
                    object_class=obs.get('object_class', 'obstacle'),
                    position=obs.get('position', (0, 0, -obs['distance'])),
                    distance=obs['distance'],
                    direction=direction,
                    last_updated=current_time
                )
            
            # Remove stale obstacles (not seen in this update)
            stale_ids = set(self._obstacles.keys()) - seen_ids
            for stale_id in stale_ids:
                del self._obstacles[stale_id]
            
            # Find closest obstacle
            if self._obstacles:
                closest = min(self._obstacles.values(), key=lambda o: o.distance)
                self._closest_distance = closest.distance
                self._closest_direction = closest.direction
                self._closest_class = closest.object_class
            else:
                self._closest_distance = float('inf')
                self._closest_direction = "center"
                self._closest_class = None
            
            # Update alert level
            new_level = self.config.thresholds.get_level_for_distance(self._closest_distance)
            self._update_level(new_level)
            
            return self._current_level
    
    def _update_level(self, new_level: AlertLevel) -> None:
        """Update the alert level with debouncing."""
        current_time = time.time()
        
        # Debounce level changes (except for escalation to critical)
        if new_level != self._current_level:
            time_since_change = current_time - self._last_level_change_time
            
            # Always allow immediate escalation to CRITICAL
            if new_level == AlertLevel.CRITICAL:
                pass
            # Debounce other changes
            elif time_since_change < self.config.level_change_debounce:
                return
        
        if new_level != self._current_level:
            self._previous_level = self._current_level
            self._current_level = new_level
            self._last_level_change_time = current_time
            
            # Log level change
            if new_level > self._previous_level:
                logger.warning(f"⚠️ Alert level UP: {self._previous_level.name} → {new_level.name}")
            else:
                logger.info(f"✓ Alert level DOWN: {self._previous_level.name} → {new_level.name}")
            
            # Trigger callback
            if self.on_level_change:
                try:
                    self.on_level_change(self._previous_level, new_level)
                except Exception as e:
                    logger.error(f"Error in level change callback: {e}")
    
    def _alert_loop(self) -> None:
        """Background thread that plays alerts at appropriate intervals."""
        while self._running:
            with self._lock:
                current_level = self._current_level
                repeat_interval = self.config.repeat_intervals.get(current_level, 1.0)
            
            # Play alert if needed
            if current_level != AlertLevel.NONE:
                current_time = time.time()
                time_since_last = current_time - self._last_alert_time
                
                if time_since_last >= repeat_interval:
                    self._play_alert(current_level)
                    self._last_alert_time = current_time
            
            # Sleep a short interval
            time.sleep(0.05)
    
    def _play_alert(self, level: AlertLevel) -> None:
        """Play the alert sound for the given level."""
        if not OPENAL_AVAILABLE:
            return
        
        if level not in self._sound_buffers:
            # No sound loaded for this level, skip
            return
        
        try:
            buffer = self._sound_buffers[level]
            volume = self.config.volumes.get(level, 0.5)
            
            # Position sound based on obstacle direction
            if self._closest_direction == "left":
                position = (-0.5, 0, -1.0)
            elif self._closest_direction == "right":
                position = (0.5, 0, -1.0)
            else:
                position = (0, 0, -1.0)
            
            # Create and play source
            source = Source(buffer)
            source.set_position(position)
            source.set_gain(volume)
            source.play()
            
        except Exception as e:
            logger.error(f"Failed to play alert sound: {e}")
    
    def get_level(self) -> AlertLevel:
        """Get current alert level."""
        return self._current_level
    
    def get_closest_obstacle(self) -> Optional[Dict]:
        """Get information about the closest obstacle."""
        if self._closest_distance == float('inf'):
            return None
        
        return {
            "distance": self._closest_distance,
            "direction": self._closest_direction,
            "class": self._closest_class,
            "alert_level": self._current_level.name,
        }
    
    def get_all_obstacles(self) -> List[ObstacleInfo]:
        """Get all tracked obstacles."""
        return list(self._obstacles.values())
    
    def is_active(self) -> bool:
        """Check if alert system is running."""
        return self._running
    
    def set_thresholds(self, **kwargs) -> None:
        """
        Update distance thresholds.
        
        Args:
            notice: Notice threshold in meters
            warning: Warning threshold in meters
            danger: Danger threshold in meters
            critical: Critical threshold in meters
        """
        for key, value in kwargs.items():
            if hasattr(self.config.thresholds, key):
                setattr(self.config.thresholds, key, value)
    
    def mute(self) -> None:
        """Temporarily mute all alerts."""
        for level in self.config.volumes:
            self.config.volumes[level] = 0.0
    
    def unmute(self) -> None:
        """Restore default volume levels."""
        self.config.volumes = {
            AlertLevel.NONE: 0.0,
            AlertLevel.NOTICE: 0.3,
            AlertLevel.WARNING: 0.5,
            AlertLevel.DANGER: 0.8,
            AlertLevel.CRITICAL: 1.0,
        }


# ============================================================================
# Standalone Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Proximity Alert System Test")
    print("=" * 60)
    
    # Create alert system with default config
    config = AlertConfig()
    
    def on_level_change(old_level, new_level):
        print(f"  📢 Level changed: {old_level.name} → {new_level.name}")
    
    alerts = ProximityAlertSystem(config=config, on_level_change=on_level_change)
    
    print(f"\nOpenAL available: {OPENAL_AVAILABLE}")
    print(f"\nThresholds:")
    print(f"  Notice: < {config.thresholds.notice}m")
    print(f"  Warning: < {config.thresholds.warning}m")
    print(f"  Danger: < {config.thresholds.danger}m")
    print(f"  Critical: < {config.thresholds.critical}m")
    
    alerts.start()
    
    # Simulate approaching obstacle
    test_scenarios = [
        (5.0, "center", "Far away"),
        (2.5, "left", "Notice zone (left)"),
        (1.5, "center", "Warning zone"),
        (0.8, "right", "Danger zone (right)"),
        (0.3, "center", "Critical - collision imminent!"),
        (1.2, "center", "Backing away - danger"),
        (3.5, "center", "Safe distance"),
    ]
    
    print("\nSimulating obstacle approach/retreat:")
    
    for distance, direction, description in test_scenarios:
        level = alerts.update(distance, direction, "obstacle")
        
        closest = alerts.get_closest_obstacle()
        print(f"\n  {description}")
        print(f"    Distance: {distance}m, Direction: {direction}")
        print(f"    Alert Level: {level.name}")
        
        time.sleep(0.5)
    
    alerts.stop()
    print(f"\n✅ Test complete")
