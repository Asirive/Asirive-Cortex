"""
Shared API Module for Project Cortex

Provides unified WebSocket communication between RPi5 and Laptop.
"""
from .protocol import (
    MessageType,
    DetectionClass,
    BoundingBox,
    Detection,
    SystemMetrics,
    GPSData,
    IMUData,
    Command,
    BaseMessage,
    create_video_frame,
    create_metrics,
    create_detections,
    create_gps_imu,
    create_command,
    create_ping,
    create_pong,
    create_error,
    create_ack,
    parse_message,
    encode_frame,
    decode_frame,
)

from .base_client import (
    ClientConfig,
    AsyncWebSocketClient,
    SyncWebSocketClient,
)

from .base_server import (
    ServerConfig,
    ClientInfo,
    AsyncWebSocketServer,
    FastAPIWebSocketServer,
)

from .exceptions import (
    CortexException,
    ConnectionError,
    ConnectionTimeout,
    ConnectionRefused,
    DisconnectedError,
    ProtocolError,
    InvalidMessageError,
    UnknownMessageType,
    SerializationError,
    QueueFullError,
    RateLimitError,
    HeartbeatError,
    ConfigurationError,
    DeviceError,
    CameraError,
    AudioError,
    ModelError,
    InferenceError,
    ExportError,
    SyncError,
    SupabaseError,
    AuthenticationError,
)

__all__ = [
    # Protocol
    "MessageType",
    "DetectionClass",
    "BoundingBox",
    "Detection",
    "SystemMetrics",
    "GPSData",
    "IMUData",
    "Command",
    "BaseMessage",
    "create_video_frame",
    "create_metrics",
    "create_detections",
    "create_gps_imu",
    "create_command",
    "create_ping",
    "create_pong",
    "create_error",
    "create_ack",
    "parse_message",
    "encode_frame",
    "decode_frame",
    # Client
    "ClientConfig",
    "AsyncWebSocketClient",
    "SyncWebSocketClient",
    # Server
    "ServerConfig",
    "ClientInfo",
    "AsyncWebSocketServer",
    "FastAPIWebSocketServer",
    # Exceptions
    "CortexException",
    "ConnectionError",
    "ConnectionTimeout",
    "ConnectionRefused",
    "DisconnectedError",
    "ProtocolError",
    "InvalidMessageError",
    "UnknownMessageType",
    "SerializationError",
    "QueueFullError",
    "RateLimitError",
    "HeartbeatError",
    "ConfigurationError",
    "DeviceError",
    "CameraError",
    "AudioError",
    "ModelError",
    "InferenceError",
    "ExportError",
    "SyncError",
    "SupabaseError",
    "AuthenticationError",
]

__version__ = "2.0.0"
