"""
Stereo Camera Handler
=====================

WITMOTION 400W stereo camera capture. The 400W is a passive stereo
camera — two synchronized image sensors on a 65mm baseline — that
exposes BOTH lenses as ONE side-by-side MJPG stream on Linux (no
separate per-lens V4L2 node — `/dev/video1` is a metadata node, not
a video stream). We request the 3840×1080 binocular mode and split
each captured frame into LEFT and RIGHT halves in software.

Why two lenses with no SGBM:
- LEFT cam (rotated 270°): upright 1080×1920 PORTRAIT (9:16) for the
  safety pipeline (YOLO + Hailo). Portrait gives more vertical pixels,
  which improves both overhead-hazard detection (signs, branches) and
  low-hazard detection (curbs, stairs).
- RIGHT cam (rotated 180°): upright 1920×1080 LANDSCAPE (16:9) for
  Gemini Live video context. Landscape is what Gemini's multimodal
  encoder is trained on; better spatial reasoning.

It does NOT output depth on its own; that requires stereo matching
(cv2.StereoSGBM), which is intentionally NOT in this handler. Depth
comes from the existing Hailo monocular pipeline on the LEFT frame.

Usage:
    cam = StereoCameraHandler(
        device_id=0,
        left_rotation_deg=270, right_rotation_deg=180,
        fps=30, fourcc="MJPG",
    )
    cam.start()
    left, lseq = cam.get_left_frame_with_seq()        # 1080×1920 portrait
    right, rseq = cam.get_right_frame_with_seq()      # 1920×1080 landscape
    cam.stop()

Author: Haziq (@IRSPlays) + AI Implementer
Project: Cortex v2.0 — YIA 2026
Date: June 2026
"""

import logging
import subprocess
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class StereoSyncError(Exception):
    """Raised when the stereo pair's timestamps diverge beyond tolerance."""


class StereoCameraHandler:
    """WITMOTION 400W dual-lens capture via side-by-side MJPG stream.

    The WITMOTION 400W is a passive stereo camera (65mm baseline). On
    Linux it exposes the two lenses as a single UVC MJPG stream where
    the left half is the LEFT lens and the right half is the RIGHT
    lens. We request 3840×1080 binocular mode and split each captured
    frame into LEFT (1920×1080) and RIGHT (1920×1080) halves, then
    apply per-lens rotation to land each lens upright in its target
    orientation.

    Attributes:
        device_id: /dev/videoN for the composite stream.
        fps: target frames per second.
        fourcc: V4L2 fourcc. MJPG recommended.
        left_rotation_deg, right_rotation_deg: rotation to apply to
            each half to land upright (270 → portrait, 180 → landscape).
        flip_v: flip vertical first (compensates upside-down mount).
    """

    BINOCULAR_WIDTH = 3840
    BINOCULAR_HEIGHT = 1080

    def __init__(
        self,
        device_id: int = 0,
        fps: int = 30,
        fourcc: str = "MJPG",
        left_rotation_deg: int = 270,
        right_rotation_deg: int = 180,
        flip_v: bool = True,
        sync_tolerance_ms: int = 50,
    ):
        self.device_id = device_id
        self.fps = fps
        self.fourcc = fourcc
        self.left_rotation_deg = left_rotation_deg
        self.right_rotation_deg = right_rotation_deg
        self.flip_v = flip_v
        self.sync_tolerance_ms = sync_tolerance_ms

        self._cap: Optional[cv2.VideoCapture] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._running = False

        # Thread-safe latest-frame storage per lens.
        self._lock_left = threading.Lock()
        self._latest_left: Optional[np.ndarray] = None
        self._left_seq = 0
        self._left_ts: float = 0.0

        self._lock_right = threading.Lock()
        self._latest_right: Optional[np.ndarray] = None
        self._right_seq = 0
        self._right_ts: float = 0.0

        # Resolved output shapes — set on first frame.
        self._left_shape: Optional[Tuple[int, int, int]] = None
        self._right_shape: Optional[Tuple[int, int, int]] = None

        logger.info(
            "📸 StereoCameraHandler created "
            "(/dev/video%d side-by-side %d×%d, LEFT=%d°, RIGHT=%d°, %d FPS, %s)",
            device_id,
            self.BINOCULAR_WIDTH, self.BINOCULAR_HEIGHT,
            left_rotation_deg, right_rotation_deg,
            fps, fourcc,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Open the composite V4L2 stream, request 3840×1080 MJPG, warm up,
        start the capture thread that splits LEFT/RIGHT per frame."""
        logger.info(
            "🎥 Opening WITMOTION 400W stereo (/dev/video%d, binocular %d×%d MJPG)...",
            self.device_id, self.BINOCULAR_WIDTH, self.BINOCULAR_HEIGHT,
        )
        cap = cv2.VideoCapture(self.device_id)
        if not cap.isOpened():
            logger.error("❌ Failed to open /dev/video%d", self.device_id)
            return False
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        except cv2.error as e:
            logger.warning("FOURCC set failed (%s) — using driver default", e)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.BINOCULAR_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.BINOCULAR_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, float(self.fps))
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        logger.info(
            "   Composite stream: %dx%d @ %.1f FPS (FourCC=%s)",
            actual_w, actual_h, actual_fps, self.fourcc,
        )
        # Some drivers lie about the requested size — fall back if so.
        if actual_w < self.BINOCULAR_WIDTH // 2 or actual_h < self.BINOCULAR_HEIGHT // 2:
            logger.warning(
                "Driver returned %dx%d — falling back to monocular single-lens mode",
                actual_w, actual_h,
            )
        self._cap = cap

        # Warm-up — discard a few frames so auto-exposure settles.
        for _ in range(5):
            cap.read()

        self._running = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="stereo-split",
            daemon=True,
        )
        self._capture_thread.start()
        logger.info("✅ Stereo capture thread started (splitting per frame)")
        return True

    def stop(self):
        """Stop the capture thread and release the camera."""
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("⏹️ Stereo camera stopped")

    # ------------------------------------------------------------------
    # Frame retrieval — LEFT (portrait, safety)
    # ------------------------------------------------------------------

    def get_left_frame(self) -> Optional[np.ndarray]:
        """Get the latest LEFT frame (thread-safe copy). 1080×1920 portrait."""
        with self._lock_left:
            if self._latest_left is not None:
                return self._latest_left.copy()
        return None

    def get_frame(self) -> Optional[np.ndarray]:
        """Backward-compat shim: returns the latest LEFT frame.

        Existing camera paths in main.py (and other modules) call
        `self.camera.get_frame()` expecting the primary (safety) lens.
        For the stereo handler that is the LEFT lens. RIGHT is fetched
        explicitly via `get_right_frame()`.
        """
        return self.get_left_frame()

    def get_left_frame_with_seq(
        self,
        last_seq: Optional[int] = None,
    ) -> Tuple[Optional[np.ndarray], int]:
        """Like `get_left_frame()` but also returns the frame sequence
        number. If `last_seq == current_seq`, returns (None, seq) so the
        caller can skip processing without polling."""
        with self._lock_left:
            seq = self._left_seq
            if last_seq is not None and seq == last_seq:
                return None, seq
            if self._latest_left is not None:
                return self._latest_left.copy(), seq
            return None, seq

    def get_frame_with_seq(
        self,
        last_seq: Optional[int] = None,
    ) -> Tuple[Optional[np.ndarray], int]:
        """Backward-compat shim: returns (LEFT frame, LEFT seq).

        Existing main.py code calls `self.camera.get_frame_with_seq(...)`
        and expects the primary (safety) lens, which for the stereo
        handler is the LEFT lens. RIGHT is fetched explicitly via
        `get_right_frame_with_seq()`.
        """
        return self.get_left_frame_with_seq(last_seq)

    # ------------------------------------------------------------------
    # Frame retrieval — RIGHT (landscape, Gemini)
    # ------------------------------------------------------------------

    def get_right_frame(self) -> Optional[np.ndarray]:
        """Get the latest RIGHT frame (thread-safe copy). 1920×1080 landscape."""
        with self._lock_right:
            if self._latest_right is not None:
                return self._latest_right.copy()
        return None

    def get_right_frame_with_seq(
        self,
        last_seq: Optional[int] = None,
    ) -> Tuple[Optional[np.ndarray], int]:
        """Same as `get_left_frame_with_seq` but for the RIGHT lens."""
        with self._lock_right:
            seq = self._right_seq
            if last_seq is not None and seq == last_seq:
                return None, seq
            if self._latest_right is not None:
                return self._latest_right.copy(), seq
            return None, seq

    # ------------------------------------------------------------------
    # Stereo pair (for future SGBM cross-check)
    # ------------------------------------------------------------------

    def get_stereo_pair(
        self,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Return (left, right) frames whose capture timestamps differ by
        ≤ `sync_tolerance_ms`. Returns (None, None) if either lens is
        missing or the pair is stale. Today's Phase B doesn't require
        strict sync (LEFT and RIGHT are read independently), but this
        API is here for the Phase C SGBM cross-check."""
        with self._lock_left:
            left = self._latest_left.copy() if self._latest_left is not None else None
            lts = self._left_ts
        with self._lock_right:
            right = self._latest_right.copy() if self._latest_right is not None else None
            rts = self._right_ts
        if left is None or right is None:
            return None, None
        if abs(lts - rts) * 1000.0 > self.sync_tolerance_ms:
            logger.debug(
                "Stereo pair stale: Δt=%.1fms (tolerance=%dms)",
                abs(lts - rts) * 1000.0, self.sync_tolerance_ms,
            )
            return None, None
        return left, right

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def left_shape(self) -> Optional[Tuple[int, int, int]]:
        return self._left_shape

    @property
    def right_shape(self) -> Optional[Tuple[int, int, int]]:
        return self._right_shape

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _capture_loop(self):
        """Background thread: read composite frames, split LEFT/RIGHT,
        apply per-lens rotation, cache both halves atomically."""
        sleep_s = 1.0 / max(self.fps, 1)
        while self._running:
            cap = self._cap  # snapshot — stop() can null mid-iteration
            if cap is None or not cap.isOpened():
                time.sleep(0.005)
                continue
            try:
                ret, frame = cap.read()
            except cv2.error as e:
                logger.debug("Stereo read error (recoverable): %s", e)
                time.sleep(0.01)
                continue
            except Exception as e:
                logger.warning("Stereo unexpected read error: %s", e)
                time.sleep(0.01)
                continue
            if not ret or frame is None:
                # Clear stale frames so callers see "no frame", not frozen.
                with self._lock_left:
                    self._latest_left = None
                with self._lock_right:
                    self._latest_right = None
                time.sleep(0.005)
                continue

            # Split into LEFT/RIGHT halves. If the driver gave us a
            # monocular single-lens frame (e.g. 1920×1080), treat the
            # whole frame as both lenses — caller will see duplicate
            # content but no exception. Binocular mode is the default.
            h, w = frame.shape[:2]
            try:
                if w >= 2 * self.BINOCULAR_HEIGHT and w >= 2 * h:
                    # Side-by-side composite: split horizontally.
                    mid = w // 2
                    raw_left = frame[:, :mid]
                    raw_right = frame[:, mid:]
                else:
                    # Monocular fallback — same content for both.
                    raw_left = frame
                    raw_right = frame
            except Exception as e:
                logger.warning("Stereo split failed: %s — skipping frame", e)
                time.sleep(0.005)
                continue

            # Apply per-lens rotation. Both lenses share the same
            # capture timestamp since they came from the same frame.
            try:
                left_rot = self._apply_rotation(raw_left, self.left_rotation_deg)
            except Exception as e:
                logger.warning("LEFT rotation failed: %s — keeping raw", e)
                left_rot = raw_left
            try:
                right_rot = self._apply_rotation(raw_right, self.right_rotation_deg)
            except Exception as e:
                logger.warning("RIGHT rotation failed: %s — keeping raw", e)
                right_rot = raw_right

            ts = time.monotonic()
            with self._lock_left:
                self._latest_left = left_rot
                self._left_seq += 1
                self._left_ts = ts
                if self._left_shape is None:
                    self._left_shape = left_rot.shape
            with self._lock_right:
                self._latest_right = right_rot
                self._right_seq += 1
                self._right_ts = ts
                if self._right_shape is None:
                    self._right_shape = right_rot.shape

            time.sleep(sleep_s)

    def _apply_rotation(self, frame: np.ndarray, rotation_deg: int) -> np.ndarray:
        """Apply flip-v + rotation to land the lens upright."""
        if self.flip_v:
            frame = cv2.flip(frame, 0)
        if rotation_deg == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if rotation_deg == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if rotation_deg == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _v4l2_present(device_idx: int) -> bool:
    """Quick check: does /dev/videoN exist?"""
    import os
    return os.path.exists(f"/dev/video{device_idx}")


def _probe_uvc_vid_pid() -> Optional[str]:
    """Return the first WITMOTION USB ID from lsusb, or None."""
    try:
        out = subprocess.check_output(["lsusb"], text=True, timeout=3)
        for line in out.splitlines():
            if "WitMotion" in line or "WITMOTION" in line or "WIT" in line.upper():
                return line.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("🎥 StereoCameraHandler self-test")
    logger.info("USB probe: %s", _probe_uvc_vid_pid() or "(WITMOTION not detected in lsusb)")
    logger.info("/dev/video0: %s", _v4l2_present(0))

    cam = StereoCameraHandler(
        device_id=0,
        fps=30, fourcc="MJPG",
        left_rotation_deg=270, right_rotation_deg=180,
    )
    if not cam.start():
        logger.error("Camera failed to start. Check USB / V4L2 permissions.")
        raise SystemExit(1)

    logger.info("Capturing 30 frames per lens...")
    last_l, last_r = -1, -1
    for i in range(30):
        left, lseq = cam.get_left_frame_with_seq(last_l)
        right, rseq = cam.get_right_frame_with_seq(last_r)
        if left is not None:
            last_l = lseq
            logger.info("  LEFT  frame %d: %s", lseq, left.shape)
        if right is not None:
            last_r = rseq
            logger.info("  RIGHT frame %d: %s", rseq, right.shape)
        time.sleep(0.1)

    cam.stop()
    logger.info("✅ Self-test complete")