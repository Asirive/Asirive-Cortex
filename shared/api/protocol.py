"""
Shared Protocol for Project Cortex - Message Types and Serialization

Defines unified message formats for communication between:
- RPi5 (client/wearable)
- Laptop (server/dashboard)

All messages are JSON-serializable dicts with:
- type: MessageType enum value
- timestamp: ISO format datetime
- data: message-specific payload
- device_id: source device identifier (optional for server->client)
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import json
import base64
import uuid


class MessageType(str, Enum):
    """Unified message types for RPi5 <-> Laptop communication."""

    # RPi5 -> Laptop (Upstream)
    VIDEO_FRAME = "VIDEO_FRAME"
    DETECTIONS = "DETECTIONS"
    METRICS = "METRICS"
    GPS_IMU = "GPS_IMU"
    AUDIO_EVENT = "AUDIO_EVENT"
    MEMORY_EVENT = "MEMORY_EVENT"
    STATUS = "STATUS"
    LAYER_RESPONSE = "LAYER_RESPONSE"

    # Laptop -> RPi5 (Downstream)
    COMMAND = "COMMAND"
    NAVIGATION = "NAVIGATION"
    SPATIAL_AUDIO = "SPATIAL_AUDIO"
    CONFIG = "CONFIG"

    # Bidirectional
    PING = "PING"
    PONG = "PONG"
    ERROR = "ERROR"

    # Connection management
    CONNECT = "CONNECT"
    DISCONNECT = "DISCONNECT"
    ACK = "ACK"


class DetectionClass(str, Enum):
    """Common detection classes for standardization."""
    PERSON = "person"
    VEHICLE = "vehicle"
    OBSTACLE = "obstacle"
    STAIRS = "stairs"
    DOOR = "door"
    CROSSWALK = "crosswalk"
    TRAFFIC_LIGHT = "traffic_light"
    SIGN = "sign"
    TEXT = "text"
    FACE = "face"
    UNKNOWN = "unknown"


@dataclass
class BoundingBox:
    """Normalized bounding box coordinates (0-1 range)."""
    x1: float
    y1: float
    x2: float
    y2: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "BoundingBox":
        return cls(
            x1=data["x1"],
            y1=data["y1"],
            x2=data["x2"],
            y2=data["y2"],
        )


@dataclass
class Detection:
    """Single object detection result."""
    class_name: str
    confidence: float
    bbox: BoundingBox
    layer: int  # 0=Guardian, 1=Learner
    track_id: Optional[str] = None
    mask: Optional[List[List[float]]] = None  # Segmentation mask

    def to_dict(self) -> Dict[str, Any]:
        return {
            "class_name": self.class_name,
            "confidence": self.confidence,
            "bbox": self.bbox.to_dict(),
            "layer": self.layer,
            "track_id": self.track_id,
            "mask": self.mask,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Detection":
        return cls(
            class_name=data["class_name"],
            confidence=data["confidence"],
            bbox=BoundingBox.from_dict(data["bbox"]),
            layer=data["layer"],
            track_id=data.get("track_id"),
            mask=data.get("mask"),
        )


@dataclass
class SystemMetrics:
    """System performance metrics."""
    fps: float
    cpu_percent: float
    ram_percent: float
    battery_percent: Optional[float] = None
    temperature: Optional[float] = None
    inference_time_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fps": self.fps,
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "battery_percent": self.battery_percent,
            "temperature": self.temperature,
            "inference_time_ms": self.inference_time_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemMetrics":
        return cls(
            fps=data["fps"],
            cpu_percent=data["cpu_percent"],
            ram_percent=data["ram_percent"],
            battery_percent=data.get("battery_percent"),
            temperature=data.get("temperature"),
            inference_time_ms=data.get("inference_time_ms"),
        )


@dataclass
class GPSData:
    """GPS coordinates."""
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    accuracy: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
            "accuracy": self.accuracy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GPSData":
        return cls(
            latitude=data["latitude"],
            longitude=data["longitude"],
            altitude=data.get("altitude"),
            accuracy=data.get("accuracy"),
        )


@dataclass
class IMUData:
    """IMU sensor data."""
    accelerometer: List[float]  # [x, y, z]
    gyroscope: List[float]  # [x, y, z]
    magnetometer: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accelerometer": self.accelerometer,
            "gyroscope": self.gyroscope,
            "magnetometer": self.magnetometer,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IMUData":
        return cls(
            accelerometer=data["accelerometer"],
            gyroscope=data["gyroscope"],
            magnetometer=data.get("magnetometer"),
        )


@dataclass
class Command:
    """Control command from laptop to RPi5."""
    action: str  # START_VIDEO, STOP_VIDEO, RESTART, etc.
    target_layer: Optional[int] = None  # 0-3 for layer-specific
    parameters: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "target_layer": self.target_layer,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Command":
        return cls(
            action=data["action"],
            target_layer=data.get("target_layer"),
            parameters=data.get("parameters"),
        )


@dataclass
class BaseMessage:
    """Base message structure for all communications."""
    type: MessageType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseMessage":
        """Create from dictionary."""
        return cls(
            type=MessageType(data["type"]),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            message_id=data.get("message_id", str(uuid.uuid4())),
            data=data.get("data", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "BaseMessage":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


# Convenience factory functions

def create_video_frame(
    device_id: str,
    frame_bytes: bytes,
    width: int,
    height: int,
    detections: Optional[List[Detection]] = None,
    quality: int = 80,
) -> BaseMessage:
    """Create a VIDEO_FRAME message."""
    # Compress and encode frame
    import cv2
    _, jpeg = cv2.imencode('.jpg', frame_bytes, [cv2.IMWRITE_JPEG_QUALITY, quality])
    encoded_frame = base64.b64encode(jpeg).decode('ascii')

    detection_data = [d.to_dict() for d in detections] if detections else []

    return BaseMessage(
        type=MessageType.VIDEO_FRAME,
        data={
            "device_id": device_id,
            "frame": encoded_frame,
            "width": width,
            "height": height,
            "detections": detection_data,
            "format": "jpeg",
        },
    )


def create_metrics(device_id: str, metrics: SystemMetrics) -> BaseMessage:
    """Create a METRICS message."""
    return BaseMessage(
        type=MessageType.METRICS,
        data={
            "device_id": device_id,
            **metrics.to_dict(),
        },
    )


def create_detections(
    device_id: str,
    detections: List[Detection],
    frame_timestamp: Optional[str] = None,
) -> BaseMessage:
    """Create a DETECTIONS message."""
    return BaseMessage(
        type=MessageType.DETECTIONS,
        data={
            "device_id": device_id,
            "detections": [d.to_dict() for d in detections],
            "frame_timestamp": frame_timestamp,
        },
    )


def create_gps_imu(
    device_id: str,
    gps: GPSData,
    imu: Optional[IMUData] = None,
) -> BaseMessage:
    """Create a GPS_IMU message."""
    data = {
        "device_id": device_id,
        "gps": gps.to_dict(),
    }
    if imu:
        data["imu"] = imu.to_dict()
    return BaseMessage(
        type=MessageType.GPS_IMU,
        data=data,
    )


def create_command(
    action: str,
    target_layer: Optional[int] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> BaseMessage:
    """Create a COMMAND message."""
    return BaseMessage(
        type=MessageType.COMMAND,
        data=Command(action, target_layer, parameters).to_dict(),
    )


def create_ping(device_id: str) -> BaseMessage:
    """Create a PING message."""
    return BaseMessage(
        type=MessageType.PING,
        data={"device_id": device_id},
    )


def create_pong(device_id: str, latency_ms: float) -> BaseMessage:
    """Create a PONG message (response to PING)."""
    return BaseMessage(
        type=MessageType.PONG,
        data={
            "device_id": device_id,
            "latency_ms": latency_ms,
        },
    )


def create_error(
    device_id: str,
    error_code: str,
    error_message: str,
    context: Optional[Dict[str, Any]] = None,
) -> BaseMessage:
    """Create an ERROR message."""
    return BaseMessage(
        type=MessageType.ERROR,
        data={
            "device_id": device_id,
            "error_code": error_code,
            "error_message": error_message,
            "context": context or {},
        },
    )


def create_ack(message_id: str, success: bool = True, details: Optional[Dict] = None) -> BaseMessage:
    """Create an ACK message (acknowledgment)."""
    return BaseMessage(
        type=MessageType.ACK,
        data={
            "original_message_id": message_id,
            "success": success,
            "details": details or {},
        },
    )


def parse_message(json_str: str) -> BaseMessage:
    """Parse a JSON message string into a BaseMessage."""
    return BaseMessage.from_json(json_str)


def encode_frame(frame_bytes: bytes, quality: int = 80) -> str:
    """Encode a frame to base64 JPEG string."""
    import cv2
    _, jpeg = cv2.imencode('.jpg', frame_bytes, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(jpeg).decode('ascii')


def decode_frame(encoded: str) -> bytes:
    """Decode a base64 JPEG string to bytes."""
    return base64.b64decode(encoded)
