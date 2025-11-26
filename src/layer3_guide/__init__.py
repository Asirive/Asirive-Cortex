"""
Layer 3: The Guide - Navigation, Audio, and User Interface

This module integrates GPS navigation, 3D spatial audio, TTS/STT,
and the caregiver web dashboard.

Key Features:
- GPS-based navigation
- 3D spatial audio via PyOpenAL (IMPLEMENTED)
- Text-to-Speech (Piper/Murf)
- Speech-to-Text (Whisper)
- Real-time web dashboard

Author: Haziq (@IRSPlays)
"""

import logging
from typing import Optional, Tuple, List, Dict, Any

logger = logging.getLogger(__name__)

# Import spatial audio components
try:
    from .spatial_audio import (
        SpatialAudioManager,
        PositionCalculator,
        AudioBeacon,
        ProximityAlertSystem,
        ObjectSoundMapper,
        ObjectTracker,
        bbox_to_3d_position,
        estimate_distance_meters,
    )
    from .spatial_audio.manager import Detection as AudioDetection
    SPATIAL_AUDIO_AVAILABLE = True
    logger.info("✅ Spatial Audio module loaded")
except ImportError as e:
    SPATIAL_AUDIO_AVAILABLE = False
    logger.warning(f"⚠️ Spatial Audio not available: {e}")


class Navigator:
    """
    Navigation and user interface system.
    
    This is the "guide" layer - integrating all outputs.
    Includes 3D spatial audio for navigation assistance.
    """
    
    def __init__(self, enable_spatial_audio: bool = True):
        """
        Initialize the navigation system.
        
        Args:
            enable_spatial_audio: Whether to enable 3D spatial audio
        """
        logger.info("🔧 Initializing Layer 3 (Guide)")
        
        # Spatial Audio System
        self.spatial_audio: Optional[SpatialAudioManager] = None
        self._spatial_audio_enabled = enable_spatial_audio and SPATIAL_AUDIO_AVAILABLE
        
        if self._spatial_audio_enabled:
            try:
                self.spatial_audio = SpatialAudioManager(
                    config_path="config/spatial_audio.yaml"
                )
                logger.info("✅ Spatial Audio Manager initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Spatial Audio: {e}")
                self.spatial_audio = None
        
        # TODO: Initialize other subsystems
        # self.gps = GPSModule()
        # self.tts = TTSEngine()
        # self.stt = STTEngine()
        
        logger.info("✅ Layer 3 initialized")
    
    def start(self) -> bool:
        """
        Start all Layer 3 subsystems.
        
        Returns:
            True if all systems started successfully
        """
        success = True
        
        # Start spatial audio
        if self.spatial_audio:
            if not self.spatial_audio.start():
                logger.error("Failed to start Spatial Audio")
                success = False
        
        return success
    
    def stop(self) -> None:
        """Stop all Layer 3 subsystems."""
        if self.spatial_audio:
            self.spatial_audio.stop()
        
        logger.info("🛑 Layer 3 stopped")
    
    def update_detections(self, detections: List[Dict[str, Any]]) -> None:
        """
        Update spatial audio with YOLO detections.
        
        Args:
            detections: List of detection dicts with keys:
                - class_name: str
                - confidence: float
                - bbox: (x1, y1, x2, y2)
                - object_id: str (optional)
        """
        if not self.spatial_audio:
            return
        
        # Convert to AudioDetection format
        audio_detections = []
        for det in detections:
            audio_detections.append(AudioDetection(
                class_name=det.get('class_name', 'unknown'),
                confidence=det.get('confidence', 0.0),
                bbox=tuple(det.get('bbox', (0, 0, 100, 100))),
                object_id=det.get('object_id')
            ))
        
        self.spatial_audio.update_detections(audio_detections)
    
    def start_navigation_beacon(self, target_class: str) -> bool:
        """
        Start audio beacon to guide user to target object.
        
        Args:
            target_class: Object class to navigate to (e.g., "chair", "door")
            
        Returns:
            True if beacon started successfully
        """
        if not self.spatial_audio:
            logger.warning("Spatial audio not available for beacon")
            return False
        
        return self.spatial_audio.start_beacon(target_class)
    
    def stop_navigation_beacon(self) -> None:
        """Stop the navigation beacon."""
        if self.spatial_audio:
            self.spatial_audio.stop_beacon()
        
    def speak(self, text: str, priority: str = "normal") -> None:
        """
        Convert text to speech and play.
        
        Args:
            text: Text to speak
            priority: 'high' for immediate, 'normal' for queued
        """
        # TODO: Implement TTS
        logger.info(f"🔊 Speaking: {text}")
        
    def play_spatial_audio(self, sound: str, direction: Tuple[float, float, float]) -> None:
        """
        Play 3D spatial audio cue.
        
        Args:
            sound: Sound identifier
            direction: (x, y, z) position vector
        """
        if not self.spatial_audio:
            return
        
        # Use object sound mapper to play sound at position
        if hasattr(self.spatial_audio, 'sound_mapper'):
            self.spatial_audio.sound_mapper.play_object_sound(
                sound, direction
            )
        
    def get_gps_location(self) -> Optional[Tuple[float, float]]:
        """
        Get current GPS coordinates.
        
        Returns:
            (latitude, longitude) or None if unavailable
        """
        # TODO: Implement GPS reading
        return None
        
    def cleanup(self) -> None:
        """Release resources."""
        logger.info("🧹 Cleaning up Layer 3")
