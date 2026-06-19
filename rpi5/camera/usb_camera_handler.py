"""
USB Camera Handler
==================

OpenCV-based camera capture for USB UVC cameras.
Replaces picamera2 / CSI path in `main.py` for IVP glasses-mounted setup.

Supports:
- Any UVC-compliant USB camera (plug & play)
- Configurable resolution and FPS
- Threaded frame capture to decouple I/O from processing
- Frame rotation / flip for mounting orientation
- Always-latest-frame semantics (drop stale frames when behind)

Usage:
    cam = USBCameraHandler(device_id=0, resolution=(640, 480), fps=30)
    cam.start()
    frame, seq = cam.get_frame_with_seq()  # or cam.get_frame()
    cam.stop()

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — IVP 2026
Date: May 2026
"""

import logging
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class USBCameraHandler:
    """
    Threaded USB camera capture via OpenCV VideoCapture.

    Design:
    - Background capture thread reads frames continuously.
    - Main loop calls get_frame() to grab the latest frame.
    - If processing lags, stale frames are silently overwritten.
    """

    def __init__(
        self,
        device_id: int = 0,
        resolution: Tuple[int, int] = (640, 480),
        fps: int = 30,
        rotation: int = 0,          # 0, 90, 180, 270 (clockwise)
        flip_h: bool = False,
        flip_v: bool = False,
        fourcc: str = "MJPG",       # MJPG usually most reliable on USB2
    ):
        """
        Args:
            device_id: /dev/video{N} index (0, 1, ...).
            resolution: Capture resolution (width, height).
            fps: Target frame rate.
            rotation: Rotate frame clockwise by N degrees.
            flip_h: Horizontal flip.
            flip_v: Vertical flip.
            fourcc: OpenCV FourCC codec. MJPG recommended for USB2 bandwidth.
        """
        self.device_id = device_id
        self.resolution = resolution
        self.fps = fps
        self.rotation = rotation
        self.flip_h = flip_h
        self.flip_v = flip_v
        self.fourcc = fourcc

        self._cap: Optional[cv2.VideoCapture] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._running = False

        # Thread-safe frame storage
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_frame_seq = 0

        logger.info("📸 USBCameraHandler created (dev=%d, %dx%d@%d)",
                    device_id, resolution[0], resolution[1], fps)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Open the camera and start the capture thread."""
        logger.info("🎥 Opening USB camera /dev/video%d...", self.device_id)
        self._cap = cv2.VideoCapture(self.device_id)

        if not self._cap.isOpened():
            logger.error("❌ Failed to open /dev/video%d", self.device_id)
            self._cap = None
            return False

        # Apply requested settings
        self._cap.set(cv2.CAP_PROP_FOURCC,
                      cv2.VideoWriter_fourcc(*self.fourcc))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, self.fps)

        # Log actual settings (camera may adjust them)
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self._cap.get(cv2.CAP_PROP_FPS)
        logger.info("   Actual: %dx%d @ %.1f FPS (FourCC=%s)",
                    actual_w, actual_h, actual_fps, self.fourcc)

        # Warm-up: discard a few frames so auto-exposure settles
        for _ in range(5):
            self._cap.read()

        self._running = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="usb-capture",
            daemon=True,
        )
        self._capture_thread.start()
        logger.info("✅ USB camera capture thread started")
        return True

    def stop(self):
        """Stop capture thread and release camera."""
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("⏹️ USB camera stopped")

    # ------------------------------------------------------------------
    # Frame retrieval
    # ------------------------------------------------------------------

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest frame (thread-safe copy)."""
        with self._frame_lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
        return None

    def get_frame_with_seq(
        self,
        last_seq: Optional[int] = None,
    ) -> Tuple[Optional[np.ndarray], int]:
        """
        Get latest frame and its sequence number.

        If last_seq == current_seq, returns (None, seq) to signal
        "no new frame since last call" — caller should skip processing.
        """
        with self._frame_lock:
            seq = self._latest_frame_seq
            if last_seq is not None and seq == last_seq:
                return None, seq
            if self._latest_frame is not None:
                return self._latest_frame.copy(), seq
            return None, seq

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _capture_loop(self):
        """Background thread: continuously read frames from USB camera."""
        while self._running:
            cap = self._cap
            # H7 fix: snapshot _cap on every iteration. stop() can null
            # _cap between our check and the next read(); without
            # re-snapshotting we'd dereference None on .read() and the
            # capture thread would die hard (sometimes segfaulting the
            # process on repeated start/stop in self-test).
            if cap is None or not cap.isOpened():
                time.sleep(0.005)
                continue
            try:
                ret, frame = cap.read()
            except cv2.error as e:
                # OpenCV can raise if the device disappears mid-read.
                logger.debug("USB camera read error (recoverable): %s", e)
                time.sleep(0.01)
                continue
            except Exception as e:
                logger.warning("USB camera unexpected read error: %s", e)
                time.sleep(0.01)
                continue
            if not ret or frame is None:
                time.sleep(0.001)
                continue

            frame = self._apply_transforms(frame)

            with self._frame_lock:
                self._latest_frame = frame
                self._latest_frame_seq += 1

            # Throttle to roughly target FPS
            time.sleep(1.0 / self.fps)

    def _apply_transforms(self, frame: np.ndarray) -> np.ndarray:
        """Apply rotation and flips."""
        if self.flip_h:
            frame = cv2.flip(frame, 1)
        if self.flip_v:
            frame = cv2.flip(frame, 0)
        if self.rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    cam = USBCameraHandler(device_id=0, resolution=(640, 480), fps=30)
    if cam.start():
        logger.info("Capturing 30 frames...")
        for i in range(30):
            frame, seq = cam.get_frame_with_seq()
            if frame is not None:
                logger.info("  Frame %d: %s", seq, frame.shape)
            time.sleep(0.1)
        cam.stop()
    else:
        logger.error("Camera failed to start. Check /dev/video0 exists.")
