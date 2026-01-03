"""
WebSocket Communication Protocol - RPi ↔ Laptop Server

Defines the message format and protocol for communication between the RPi wearable
and the laptop server. All messages are JSON-encoded.

Message Types:
1. METRICS: System performance data (FPS, latency, RAM, battery)
2. DETECTIONS: YOLO detection results (Guardian + Learner)
3. VIDEO_FRAME: Camera frame (JPEG-encoded)
4. GPS_IMU: Location and orientation data
5. AUDIO_EVENT: Voice commands, TTS status
6. COMMAND: Commands from laptop to RPi (navigate, remember, etc.)

Author: Haziq (@IRSPlays)
Date: January 3, 2026
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime


class MessageType(str, Enum):
    """WebSocket message types."""
    # RPi → Laptop (Upstream)
    METRICS = "metrics"
    DETECTIONS = "detections"
    VIDEO_FRAME = "video_frame"
    GPS_IMU = "gps_imu"
    AUDIO_EVENT = "audio_event"
    MEMORY_EVENT = "memory_event"
    STATUS = "status"
    
    # Laptop → RPi (Downstream)
    COMMAND = "command"
    NAVIGATION = "navigation"
    SPATIAL_AUDIO = "spatial_audio"
    CONFIG = "config"
    
    # Bidirectional
    PING = "ping"
    PONG = "pong"
    ERROR = "error"


class BaseMessage(BaseModel):
    """Base class for all WebSocket messages."""
    type: MessageType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    device_id: Optional[str] = None  # RPi device identifier


# === UPSTREAM MESSAGES (RPi → Laptop) ===

class MetricsMessage(BaseMessage):
    """System performance metrics."""
    type: MessageType = MessageType.METRICS
    fps: float = Field(description="Current video processing FPS")
    latency_ms: float = Field(description="End-to-end latency in milliseconds")
    ram_usage_gb: float = Field(description="RAM usage in GB")
    ram_total_gb: float = Field(default=4.0, description="Total RAM in GB")
    cpu_usage_percent: float = Field(description="CPU usage percentage")
    temperature_celsius: Optional[float] = Field(default=None, description="CPU temperature")
    battery_percent: Optional[float] = Field(default=None, description="Battery level (0-100)")
    active_layer: str = Field(description="Currently active AI layer (layer1, layer2, layer3)")


class DetectionMessage(BaseMessage):
    """Object detection results."""
    type: MessageType = MessageType.DETECTIONS
    guardian_detections: List[str] = Field(description="Layer 0 safety detections (YOLO11x)")
    learner_detections: List[str] = Field(description="Layer 1 adaptive detections (YOLOE)")
    merged_detections: str = Field(description="Combined detection string")
    detection_count: int = Field(description="Total number of objects detected")
    yoloe_mode: str = Field(description="YOLOE mode: prompt_free, text_prompts, visual_prompts")
    confidence_threshold: float = Field(default=0.5, description="Detection confidence threshold")


class VideoFrameMessage(BaseMessage):
    """Camera video frame."""
    type: MessageType = MessageType.VIDEO_FRAME
    frame_data: str = Field(description="Base64-encoded JPEG frame")
    width: int = Field(description="Frame width in pixels")
    height: int = Field(description="Frame height in pixels")
    format: str = Field(default="jpeg", description="Image format")
    quality: int = Field(default=90, description="JPEG quality (0-100)")


class GPSIMUMessage(BaseMessage):
    """GPS and IMU sensor data."""
    type: MessageType = MessageType.GPS_IMU
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    accuracy: Optional[float] = None
    heading: Optional[float] = Field(default=None, description="Compass heading in degrees")
    pitch: Optional[float] = Field(default=None, description="IMU pitch in degrees")
    roll: Optional[float] = Field(default=None, description="IMU roll in degrees")
    yaw: Optional[float] = Field(default=None, description="IMU yaw in degrees")


class AudioEventMessage(BaseMessage):
    """Voice command and TTS events."""
    type: MessageType = MessageType.AUDIO_EVENT
    event: str = Field(description="Event type: voice_start, voice_end, tts_start, tts_end, interrupt")
    text: Optional[str] = Field(default=None, description="Transcribed text or TTS content")
    duration_ms: Optional[float] = Field(default=None, description="Event duration")
    confidence: Optional[float] = Field(default=None, description="Transcription confidence")


class MemoryEventMessage(BaseMessage):
    """Memory storage/recall events."""
    type: MessageType = MessageType.MEMORY_EVENT
    event: str = Field(description="Event type: store, recall, list")
    object_name: Optional[str] = None
    memory_id: Optional[str] = None
    success: bool = True
    message: Optional[str] = None


class StatusMessage(BaseMessage):
    """System status updates."""
    type: MessageType = MessageType.STATUS
    status: str = Field(description="Status message")
    level: str = Field(default="info", description="Severity: info, warning, error")
    component: Optional[str] = Field(default=None, description="Component name (yolo, whisper, etc.)")


# === DOWNSTREAM MESSAGES (Laptop → RPi) ===

class CommandMessage(BaseMessage):
    """Commands from laptop to RPi."""
    type: MessageType = MessageType.COMMAND
    command: str = Field(description="Command type: navigate, remember, recall, switch_mode")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Command parameters")


class NavigationMessage(BaseMessage):
    """Navigation guidance."""
    type: MessageType = MessageType.NAVIGATION
    target_lat: float
    target_lon: float
    distance_meters: float
    bearing_degrees: float
    waypoints: Optional[List[Dict[str, float]]] = None


class SpatialAudioMessage(BaseMessage):
    """3D spatial audio targets."""
    type: MessageType = MessageType.SPATIAL_AUDIO
    object_name: str
    azimuth_degrees: float = Field(description="Horizontal angle (-180 to 180)")
    elevation_degrees: float = Field(description="Vertical angle (-90 to 90)")
    distance_meters: float = Field(description="Distance to object")


class ConfigMessage(BaseMessage):
    """Configuration updates."""
    type: MessageType = MessageType.CONFIG
    settings: Dict[str, Any] = Field(description="Configuration key-value pairs")


# === BIDIRECTIONAL MESSAGES ===

class PingMessage(BaseMessage):
    """Heartbeat ping."""
    type: MessageType = MessageType.PING
    sequence: int = Field(description="Ping sequence number")


class PongMessage(BaseModel):
    """Heartbeat pong response."""
    type: MessageType = MessageType.PONG
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    sequence: int = Field(description="Ping sequence number being acknowledged")


class ErrorMessage(BaseMessage):
    """Error notification."""
    type: MessageType = MessageType.ERROR
    error_code: str
    error_message: str
    traceback: Optional[str] = None


# === PROTOCOL UTILITIES ===

def create_message(msg_type: MessageType, **kwargs) -> BaseMessage:
    """Factory function to create protocol messages."""
    message_classes = {
        MessageType.METRICS: MetricsMessage,
        MessageType.DETECTIONS: DetectionMessage,
        MessageType.VIDEO_FRAME: VideoFrameMessage,
        MessageType.GPS_IMU: GPSIMUMessage,
        MessageType.AUDIO_EVENT: AudioEventMessage,
        MessageType.MEMORY_EVENT: MemoryEventMessage,
        MessageType.STATUS: StatusMessage,
        MessageType.COMMAND: CommandMessage,
        MessageType.NAVIGATION: NavigationMessage,
        MessageType.SPATIAL_AUDIO: SpatialAudioMessage,
        MessageType.CONFIG: ConfigMessage,
        MessageType.PING: PingMessage,
        MessageType.PONG: PongMessage,
        MessageType.ERROR: ErrorMessage,
    }
    
    msg_class = message_classes.get(msg_type)
    if msg_class is None:
        raise ValueError(f"Unknown message type: {msg_type}")
    
    return msg_class(**kwargs)


def parse_message(json_data: dict) -> BaseMessage:
    """Parse JSON data into the appropriate message object."""
    msg_type = json_data.get("type")
    if not msg_type:
        raise ValueError("Message missing 'type' field")
    
    return create_message(MessageType(msg_type), **json_data)


# === PROTOCOL VERSION ===
PROTOCOL_VERSION = "2.0.0"
