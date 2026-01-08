"""
WebSocket Message Protocol for ProjectCortex

Defines message types and structures for communication between:
- RPi5 (Cortex) → Laptop (Dashboard)
- Laptop (Dashboard) → RPi5 (Cortex)

Message Format (JSON):
{
    "type": "MESSAGE_TYPE",
    "timestamp": "ISO-8601 timestamp",
    "data": { ... message-specific fields ... }
}

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

from enum import Enum
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from datetime import datetime
import json


class MessageType(Enum):
    """WebSocket message types"""

    # Upstream (RPi5 → Laptop)
    METRICS = "METRICS"              # System metrics (FPS, RAM, CPU, battery)
    DETECTIONS = "DETECTIONS"        # Object detections from Layer 0/1
    VIDEO_FRAME = "VIDEO_FRAME"      # Camera frame (base64 encoded)
    GPS_IMU = "GPS_IMU"            # GPS and IMU data
    AUDIO_EVENT = "AUDIO_EVENT"     # Audio transcription events
    MEMORY_EVENT = "MEMORY_EVENT"   # Memory manager events
    STATUS = "STATUS"               # Connection/status updates

    # Downstream (Laptop → RPi5)
    COMMAND = "COMMAND"             # Control commands
    NAVIGATION = "NAVIGATION"       # Navigation commands
    SPATIAL_AUDIO = "SPATIAL_AUDIO" # Spatial audio configuration
    CONFIG = "CONFIG"               # Configuration updates

    # Bidirectional
    PING = "PING"
    PONG = "PONG"
    ERROR = "ERROR"


@dataclass
class BaseMessage:
    """Base message class"""
    type: str
    timestamp: str
    data: Dict[str, Any]

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> 'BaseMessage':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls(**data)


# ============================================================================
# UPSTREAM MESSAGES (RPi5 → Laptop)
# ============================================================================

@dataclass
class MetricsMessage(BaseMessage):
    """System metrics message"""
    data: Dict[str, Any]  # {
        # "fps": 30.0,
        # "ram_mb": 2048,
        # "ram_percent": 52.3,
        # "cpu_percent": 45.2,
        # "battery_percent": 85,
        # "temperature": 42.5,
        # "active_layers": ["layer0", "layer1", "layer2"],
        # "current_mode": "TEXT_PROMPTS"
    # }


@dataclass
class DetectionMessage(BaseMessage):
    """Object detection message"""
    data: Dict[str, Any]  # {
        # "layer": "guardian" | "learner",
        # "class_name": "person",
        # "confidence": 0.92,
        # "bbox": [x1, y1, x2, y2],
        # "bbox_area": 0.12
    # }


@dataclass
class VideoFrameMessage(BaseMessage):
    """Video frame message"""
    data: Dict[str, Any]  # {
        # "frame": "base64_encoded_jpeg",
        # "width": 640,
        # "height": 480,
        # "timestamp": "ISO-8601",
        # "frame_number": 1234
    # }


@dataclass
class GPSIMUMessage(BaseMessage):
    """GPS and IMU data message"""
    data: Dict[str, Any]  # {
        # "latitude": 1.3521,
        # "longitude": 103.8198,
        # "altitude": 15.0,
        # "speed": 0.0,
        # "acceleration": [0.01, -0.02, 9.81],
        # "gyroscope": [0.1, 0.2, 0.3],
        # "compass": 45.0
    # }


@dataclass
class AudioEventMessage(BaseMessage):
    """Audio transcription event message"""
    data: Dict[str, Any]  # {
        # "event": "transcription" | "tts_playback",
        # "text": "what do you see",
        # "layer": "layer1" | "layer2" | "layer3",
        # "confidence": 0.95
    # }


@dataclass
class MemoryEventMessage(BaseMessage):
    """Memory manager event message"""
    data: Dict[str, Any]  # {
        # "event": "sync_complete" | "sync_failed" | "queue_full",
        # "local_rows": 100,
        # "synced_rows": 95,
        # "upload_queue": 5,
        # "error": "error message (if any)"
    # }


@dataclass
class StatusMessage(BaseMessage):
    """Connection/status update message"""
    data: Dict[str, Any]  # {
        # "status": "connected" | "disconnected" | "error",
        # "message": "Human-readable status message",
        # "device_id": "rpi5-cortex-001"
    # }


# ============================================================================
# DOWNSTREAM MESSAGES (Laptop → RPi5)
# ============================================================================

@dataclass
class CommandMessage(BaseMessage):
    """Control command message"""
    data: Dict[str, Any]  # {
        # "command": "start" | "stop" | "pause" | "resume" | "shutdown",
        # "params": {}  # Optional command parameters
    # }


@dataclass
class NavigationMessage(BaseMessage):
    """Navigation command message"""
    data: Dict[str, Any]  # {
        # "action": "set_destination" | "cancel" | "get_route",
        # "destination": {"lat": 1.35, "lon": 103.82, "name": "Home"}
    # }


@dataclass
class SpatialAudioMessage(BaseMessage):
    """Spatial audio configuration message"""
    data: Dict[str, Any]  # {
        # "enabled": true,
        # "max_distance": 10.0,  # meters
        # "volume_curve": "linear" | "exponential"
    # }


@dataclass
class ConfigMessage(BaseMessage):
    """Configuration update message"""
    data: Dict[str, Any]  # {
        # "section": "layer0" | "layer1" | "layer2" | "layer3",
        # "config": {"confidence": 0.5, "mode": "TEXT_PROMPTS"}
    # }


# ============================================================================
# BIDIRECTIONAL MESSAGES
# ============================================================================

@dataclass
class PingMessage(BaseMessage):
    """Ping message for connection health check"""
    data: Dict[str, Any]  # {
        # "timestamp": "ISO-8601 timestamp"
    # }


@dataclass
class PongMessage(BaseMessage):
    """Pong response to ping"""
    data: Dict[str, Any]  # {
        # "ping_timestamp": "ISO-8601 timestamp from ping",
        # "pong_timestamp": "ISO-8601 timestamp of pong"
    # }


@dataclass
class ErrorMessage(BaseMessage):
    """Error message"""
    data: Dict[str, Any]  # {
        # "error_type": "connection" | "processing" | "validation",
        # "error_code": "ERR_001",
        # "message": "Human-readable error message",
        # "details": {}  # Optional error details
    # }


# ============================================================================
# MESSAGE FACTORY
# ============================================================================

def create_message(message_type: MessageType, data: Dict[str, Any]) -> BaseMessage:
    """Create a message of the specified type"""
    timestamp = datetime.utcnow().isoformat() + "Z"

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

    message_class = message_classes.get(message_type, BaseMessage)
    return message_class(type=message_type.value, timestamp=timestamp, data=data)


def parse_message(json_str: str) -> Optional[BaseMessage]:
    """Parse JSON string into message object"""
    try:
        data = json.loads(json_str)
        message_type = data.get("type")

        # Map message type string to enum
        try:
            msg_type = MessageType(message_type)
        except ValueError:
            # Unknown message type, return base message
            return BaseMessage(**data)

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

        message_class = message_classes.get(msg_type, BaseMessage)
        return message_class(**data)

    except Exception as e:
        print(f"Error parsing message: {e}")
        return None


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

if __name__ == "__main__":
    # Example: Create metrics message
    metrics = create_message(
        MessageType.METRICS,
        {
            "fps": 30.0,
            "ram_mb": 2048,
            "ram_percent": 52.3,
            "cpu_percent": 45.2,
            "battery_percent": 85
        }
    )

    print("Metrics Message:")
    print(metrics.to_json())
    print()

    # Example: Parse message
    parsed = parse_message(metrics.to_json())
    print("Parsed Message:")
    print(f"Type: {parsed.type}")
    print(f"Timestamp: {parsed.timestamp}")
    print(f"Data: {parsed.data}")
