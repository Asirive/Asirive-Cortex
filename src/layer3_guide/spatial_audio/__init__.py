"""
Project-Cortex v2.0 - 3D Spatial Audio Navigation System

This module provides binaural 3D audio navigation for visually impaired users.
Uses PyOpenAL with HRTF (Head-Related Transfer Function) for realistic spatial audio
that works with standard Bluetooth headphones.

⚠️ IMPORTANT: BODY-RELATIVE NAVIGATION ⚠️
=========================================
This system uses BODY-RELATIVE navigation, not head-tracking.
Users must TURN THEIR TORSO to center the sound, not just their head.

When demonstrating to judges:
"This device uses Body-Relative Navigation. You must turn your torso 
to center the sound, not just your head."

🎧 ACCESSIBILITY COMFORT FEATURES:
=================================
Based on research from Microsoft Soundscape, Sonification Handbook, and 
OpenAL-Soft HRTF studies, this module includes configurable comfort settings:

- ComfortMode.GENTLE: Minimal sounds, longer intervals (for sensitive users)
- ComfortMode.BALANCED: Default moderate feedback (recommended)
- ComfortMode.INFORMATIVE: Frequent updates, detailed feedback (power users)

Key accessibility features:
- INTERVAL PINGS instead of continuous sounds (reduces fatigue)
- EARCONS (abstract tones) for less overwhelming audio
- PROXIMITY AUTO-MUTE when very close to destination
- CONFIGURABLE VOLUME levels for all audio types
- STEREO SPREAD control for headphone comfort
- START/END MELODIES for clear state changes

Key Features:
- Audio Beacons: Configurable directional sounds for navigation guidance
- Proximity Alerts: Distance-based warning sounds with volume control
- Object Tracking: Unique sounds for different object classes
- Distance Estimation: Real-world distance from YOLO bounding boxes
- Procedural Sound Generation: No external WAV files needed

Usage:
    from src.layer3_guide.spatial_audio import SpatialAudioManager, ComfortMode
    
    # Default balanced mode
    audio = SpatialAudioManager()
    
    # Or with gentle mode for sensitive users
    audio = SpatialAudioManager(comfort_mode=ComfortMode.GENTLE)
    
    audio.start()
    audio.update_detections(yolo_detections)
    audio.start_beacon("chair")  # Guide user to chair
    
    # Adjust comfort at runtime
    audio.set_master_volume(0.5)
    audio.set_comfort_mode(ComfortMode.GENTLE)
"""

from .manager import SpatialAudioManager, ComfortMode, ComfortSettings
from .position_calculator import PositionCalculator, bbox_to_3d_position, estimate_distance_meters
from .audio_beacon import AudioBeacon
from .proximity_alert import ProximityAlertSystem
from .object_sounds import ObjectSoundMapper
from .object_tracker import ObjectTracker
from .sound_generator import ProceduralSoundGenerator, get_sound_generator

__all__ = [
    'SpatialAudioManager',
    'ComfortMode',
    'ComfortSettings',
    'PositionCalculator',
    'bbox_to_3d_position',
    'estimate_distance_meters',
    'AudioBeacon',
    'ProximityAlertSystem',
    'ObjectSoundMapper',
    'ObjectTracker',
    'ProceduralSoundGenerator',
    'get_sound_generator',
]

# Body-Relative Navigation Notice
NAVIGATION_NOTICE = """
╔══════════════════════════════════════════════════════════════════╗
║  ⚠️  BODY-RELATIVE NAVIGATION  ⚠️                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  This device uses Body-Relative Navigation.                      ║
║  You must TURN YOUR TORSO to center the sound,                  ║
║  not just your head.                                             ║
║                                                                  ║
║  The camera is mounted on your chest/torso, so sounds           ║
║  are positioned relative to where your body is facing.          ║
╚══════════════════════════════════════════════════════════════════╝
"""

def print_navigation_notice():
    """Print the body-relative navigation notice to console."""
    print(NAVIGATION_NOTICE)

__version__ = "1.0.0"
__author__ = "Haziq (@IRSPlays)"
