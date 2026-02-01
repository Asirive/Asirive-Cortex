"""
Custom Exceptions for Project Cortex Shared API
"""


class CortexException(Exception):
    """Base exception for Project Cortex."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConnectionError(CortexException):
    """Connection-related errors."""
    def __init__(self, message: str = "Connection failed", details: dict = None):
        super().__init__(message, details)


class ConnectionTimeout(ConnectionError):
    """Connection timed out."""
    def __init__(self, timeout: float, details: dict = None):
        super().__init__(f"Connection timed out after {timeout}s", details)
        self.timeout = timeout


class ConnectionRefused(ConnectionError):
    """Connection was refused."""
    def __init__(self, host: str, port: int, details: dict = None):
        super().__init__(f"Connection refused to {host}:{port}", details)
        self.host = host
        self.port = port


class DisconnectedError(ConnectionError):
    """Disconnected unexpectedly."""
    def __init__(self, reason: str = "Unknown", details: dict = None):
        super().__init__(f"Disconnected: {reason}", details)
        self.reason = reason


class ProtocolError(CortexException):
    """Protocol/message errors."""
    def __init__(self, message: str, message_type: str = None, details: dict = None):
        super().__init__(message, details)
        self.message_type = message_type


class InvalidMessageError(ProtocolError):
    """Invalid message format."""
    def __init__(self, message: str, raw_data: str = None, details: dict = None):
        super().__init__(f"Invalid message: {message}", details=details)
        self.raw_data = raw_data


class UnknownMessageType(ProtocolError):
    """Unknown message type."""
    def __init__(self, message_type: str, details: dict = None):
        super().__init__(f"Unknown message type: {message_type}", message_type, details)
        self.message_type = message_type


class SerializationError(CortexException):
    """Serialization/deserialization errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, details)


class QueueFullError(CortexException):
    """Message queue is full."""
    def __init__(self, queue_size: int, details: dict = None):
        super().__init__(f"Message queue full (max: {queue_size})", details)
        self.queue_size = queue_size


class RateLimitError(CortexException):
    """Rate limit exceeded."""
    def __init__(self, client_id: str, limit: int, details: dict = None):
        super().__init__(f"Rate limit exceeded for {client_id} (limit: {limit}/s)", details)
        self.client_id = client_id
        self.limit = limit


class HeartbeatError(CortexException):
    """Heartbeat/PONG timeout."""
    def __init__(self, timeout: float, details: dict = None):
        super().__init__(f"Heartbeat timeout after {timeout}s", details)
        self.timeout = timeout


class ConfigurationError(CortexException):
    """Configuration errors."""
    def __init__(self, message: str, config_key: str = None, details: dict = None):
        super().__init__(message, details)
        self.config_key = config_key


class DeviceError(CortexException):
    """Device-related errors (camera, audio, etc.)."""
    def __init__(self, device: str, message: str, details: dict = None):
        super().__init__(f"{device}: {message}", details)
        self.device = device


class CameraError(DeviceError):
    """Camera errors."""
    def __init__(self, message: str, device_id: int = None, details: dict = None):
        device = f"Camera {device_id}" if device_id else "Camera"
        super().__init__(device, message, details)
        self.device_id = device_id


class AudioError(DeviceError):
    """Audio device errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__("Audio", message, details)


class ModelError(CortexException):
    """AI model errors."""
    def __init__(self, model: str, message: str, details: dict = None):
        super().__init__(f"{model}: {message}", details)
        self.model = model


class InferenceError(ModelError):
    """Model inference errors."""
    def __init__(self, model: str, message: str, details: dict = None):
        super().__init__(model, f"Inference failed: {message}", details)


class ExportError(ModelError):
    """Model export errors."""
    def __init__(self, model: str, message: str, details: dict = None):
        super().__init__(model, f"Export failed: {message}", details)


class SyncError(CortexException):
    """Synchronization errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, details)


class SupabaseError(CortexException):
    """Supabase/Cloud sync errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(f"Supabase: {message}", details)


class AuthenticationError(CortexException):
    """Authentication errors."""
    def __init__(self, message: str = "Authentication failed", details: dict = None):
        super().__init__(message, details)


# Alias for common name used in base_client.py
# CRITICAL FIX: Renamed to avoid shadowing Python's built-in TimeoutError
ConnectionTimeoutError = ConnectionTimeout
