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

Key Features:
- Audio Beacons: Continuous directional sounds for navigation guidance
- Proximity Alerts: Distance-based warning sounds
- Object Tracking: Unique sounds for different object classes
- Distance Estimation: Real-world distance from YOLO bounding boxes
- Procedural Sound Generation: No external WAV files needed

Usage:
    from src.layer3_guide.spatial_audio import SpatialAudioManager
    
    audio = SpatialAudioManager()
    audio.start()
    audio.update_detections(yolo_detections)
    audio.start_beacon("chair")  # Guide user to chair
"""

from .manager import SpatialAudioManager
from .position_calculator import PositionCalculator, bbox_to_3d_position, estimate_distance_meters
from .audio_beacon import AudioBeacon
from .proximity_alert import ProximityAlertSystem
from .object_sounds import ObjectSoundMapper
from .object_tracker import ObjectTracker
from .sound_generator import ProceduralSoundGenerator, get_sound_generator

__all__ = [
    'SpatialAudioManager',
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
