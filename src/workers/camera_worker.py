"""
Camera Worker - Frame Capture and Distribution
===============================================

This worker is responsible for:
- Camera capture using Picamera2 (or OpenCV fallback)
- Pushing frames to SharedFrameBuffer
- FPS management and adaptive quality
- Motion detection for smart encoding

CPU Assignment: Core 3
Priority: HIGH (feeds all other workers)

Author: Project Cortex Team
Date: 2025
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from workers import BaseWorker, setup_worker_logging
from frame_queue import SharedFrameBuffer

# Try to import Picamera2 (RPi)
try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False

# Try to import OpenCV (fallback)
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


# ============================================================================
# CONSTANTS
# ============================================================================

# Default camera settings
DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 30

# Motion detection
MOTION_THRESHOLD = 0.02  # 2% pixel difference = motion


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class CameraStats:
    """Camera capture statistics."""
    frames_captured: int
    fps_actual: float
    fps_target: float
    motion_frames: int
    dropped_frames: int
    capture_latency_ms: float


# ============================================================================
# CAMERA WORKER
# ============================================================================

class CameraWorker(BaseWorker):
    """
    Camera capture worker.
    
    Runs on Core 3, captures frames and pushes to SharedFrameBuffer.
    Supports Picamera2 (RPi) and OpenCV (fallback).
    """
    
    def __init__(
        self,
        frame_buffer_name: str = "cortex_frames",
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        target_fps: int = DEFAULT_FPS,
        camera_id: int = 0,
        use_picamera: bool = True,
        log_level: int = logging.INFO
    ):
        """
        Initialize the camera worker.
        
        Args:
            frame_buffer_name: Name of shared frame buffer
            width: Frame width
            height: Frame height
            target_fps: Target capture FPS
            camera_id: Camera device ID (for OpenCV)
            use_picamera: Whether to prefer Picamera2
            log_level: Logging level
        """
        super().__init__(
            name="Camera",
            cpu_core=3,  # Dedicated core for camera I/O
            frame_buffer_name=frame_buffer_name,
            worker_id=3,  # Worker ID (not used for camera)
            log_level=log_level
        )
        
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.camera_id = camera_id
        self.use_picamera = use_picamera and PICAMERA_AVAILABLE
        
        # Will be set in setup()
        self.camera = None
        self.prev_frame = None
        
        # Stats
        self.frames_captured = 0
        self.motion_frames = 0
        self.dropped_frames = 0
        self.capture_start_time = 0.0
    
    def setup(self) -> None:
        """Initialize camera."""
        if self.use_picamera:
            self._setup_picamera()
        elif OPENCV_AVAILABLE:
            self._setup_opencv()
        else:
            self.logger.error("No camera backend available!")
            self.camera = None
    
    def _setup_picamera(self) -> None:
        """Set up Picamera2."""
        try:
            self.camera = Picamera2()
            
            # Configure camera
            config = self.camera.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"}
            )
            self.camera.configure(config)
            self.camera.start()
            
            self.logger.info(f"Picamera2 initialized: {self.width}x{self.height}")
            
        except Exception as e:
            self.logger.error(f"Picamera2 init failed: {e}")
            
            # Try OpenCV fallback
            if OPENCV_AVAILABLE:
                self.logger.info("Falling back to OpenCV")
                self._setup_opencv()
            else:
                self.camera = None
    
    def _setup_opencv(self) -> None:
        """Set up OpenCV camera."""
        try:
            self.camera = cv2.VideoCapture(self.camera_id)
            
            # Set resolution
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.camera.set(cv2.CAP_PROP_FPS, self.target_fps)
            
            if not self.camera.isOpened():
                raise RuntimeError("Failed to open camera")
            
            # Test read a frame to verify camera works
            ret, _ = self.camera.read()
            if not ret:
                self.logger.warning("Camera opened but cannot read frames, using mock mode")
                self.camera.release()
                self.camera = None
                return
            
            self.logger.info(f"OpenCV camera initialized: {self.width}x{self.height}")
            
        except Exception as e:
            self.logger.error(f"OpenCV camera init failed: {e}")
            self.camera = None
    
    def process_frame(self, frame, metadata) -> None:
        """
        Not used by CameraWorker (overrides _main_loop instead).
        
        Camera produces frames, doesn't process them.
        """
        pass  # Camera worker overrides _main_loop, not process_frame
    
    def _main_loop(self) -> None:
        """
        Override main loop for camera-specific capture.
        
        Camera doesn't process frames, it produces them.
        """
        self.capture_start_time = time.time()
        frame_interval = 1.0 / self.target_fps
        
        while not self._stop_event.is_set():
            loop_start = time.perf_counter()
            
            # Update heartbeat
            self._last_heartbeat.value = time.time()
            
            # Capture frame
            frame = self._capture_frame()
            
            if frame is not None:
                # Check for motion
                has_motion = self._detect_motion(frame)
                if has_motion:
                    self.motion_frames += 1
                
                # Push to buffer
                self.frame_buffer.push_frame(frame)
                self.frames_captured += 1
                
                # Update stats
                self._frames_processed.value = self.frames_captured
            else:
                self.dropped_frames += 1
            
            # Calculate actual FPS
            elapsed = time.perf_counter() - loop_start
            
            # Sleep to maintain target FPS
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    def _capture_frame(self) -> Optional[np.ndarray]:
        """
        Capture a single frame from the camera.
        
        Returns:
            NumPy array (H, W, 3) RGB or None on failure
        """
        if self.camera is None:
            return self._generate_test_frame()
        
        try:
            if self.use_picamera and PICAMERA_AVAILABLE:
                # Picamera2 returns RGB directly
                frame = self.camera.capture_array()
            elif OPENCV_AVAILABLE:
                ret, frame = self.camera.read()
                if not ret:
                    return None
                # Convert BGR to RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            else:
                return None
            
            # Ensure correct shape
            if frame.shape[:2] != (self.height, self.width):
                frame = cv2.resize(frame, (self.width, self.height))
            
            return frame
            
        except Exception as e:
            self.logger.error(f"Capture error: {e}")
            return None
    
    def _generate_test_frame(self) -> np.ndarray:
        """Generate a test frame (for testing without camera)."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        
        # Add timestamp text
        timestamp = time.strftime("%H:%M:%S")
        
        # Simple gradient for visual feedback
        frame[:, :, 0] = np.linspace(0, 255, self.width, dtype=np.uint8)  # Red gradient
        frame[:, :, 1] = np.linspace(0, 128, self.height, dtype=np.uint8)[:, np.newaxis]  # Green gradient
        
        # Add frame count
        frame_num = self.frames_captured % 256
        frame[10:20, 10:10+frame_num, 2] = 255  # Blue bar
        
        return frame
    
    def _detect_motion(self, frame: np.ndarray) -> bool:
        """
        Detect motion between current and previous frame.
        
        Args:
            frame: Current frame
            
        Returns:
            True if motion detected
        """
        if self.prev_frame is None:
            self.prev_frame = frame.copy()
            return False
        
        # Simple frame difference
        diff = np.abs(frame.astype(np.int16) - self.prev_frame.astype(np.int16))
        motion_ratio = np.mean(diff) / 255.0
        
        self.prev_frame = frame.copy()
        
        return motion_ratio > MOTION_THRESHOLD
    
    def get_camera_stats(self) -> CameraStats:
        """Get camera capture statistics."""
        elapsed = time.time() - self.capture_start_time if self.capture_start_time > 0 else 1.0
        actual_fps = self.frames_captured / elapsed if elapsed > 0 else 0.0
        
        return CameraStats(
            frames_captured=self.frames_captured,
            fps_actual=actual_fps,
            fps_target=self.target_fps,
            motion_frames=self.motion_frames,
            dropped_frames=self.dropped_frames,
            capture_latency_ms=1000.0 / actual_fps if actual_fps > 0 else 0.0
        )
    
    def cleanup(self) -> None:
        """Clean up camera resources."""
        if self.camera is not None:
            try:
                if self.use_picamera and PICAMERA_AVAILABLE:
                    self.camera.stop()
                    self.camera.close()
                elif OPENCV_AVAILABLE:
                    self.camera.release()
            except Exception as e:
                self.logger.error(f"Camera cleanup error: {e}")
        
        stats = self.get_camera_stats()
        self.logger.info(
            f"Camera cleanup: {stats.frames_captured} frames, "
            f"{stats.fps_actual:.1f} FPS, "
            f"{stats.dropped_frames} dropped"
        )


# ============================================================================
# STANDALONE TESTING
# ============================================================================

def test_camera_worker():
    """Test camera worker in standalone mode."""
    print("=" * 60)
    print("Testing Camera Worker")
    print("=" * 60)
    
    # Create test frame buffer
    buffer = SharedFrameBuffer.create(name="test_camera")
    
    # Create worker (use test mode - no real camera)
    worker = CameraWorker(
        frame_buffer_name="test_camera",
        width=640,
        height=480,
        target_fps=30,
        use_picamera=False,  # Force test mode
        log_level=logging.DEBUG
    )
    
    # Start worker
    worker.start(write_index=buffer.write_index, slot_locks=buffer.slot_locks)
    
    # Wait for ready
    if not worker.wait_ready(timeout=10):
        print("Worker failed to start!")
        worker.stop()
        buffer.close()
        buffer.unlink()
        return
    
    print("Worker ready, capturing frames...")
    
    # Let it run for a few seconds
    time.sleep(3)
    
    # Print stats
    stats = worker.get_camera_stats()
    print(f"Camera stats: {stats}")
    print(f"Buffer stats: {buffer.get_stats()}")
    
    # Read latest frame
    slot = buffer.get_latest_frame()
    if slot:
        print(f"Latest frame: sequence={slot.metadata.sequence}, shape={slot.frame.shape}")
    
    # Stop worker
    worker.stop()
    
    # Cleanup
    buffer.close()
    buffer.unlink()
    
    print("Test complete!")


if __name__ == "__main__":
    test_camera_worker()
