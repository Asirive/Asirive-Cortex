"""
Hailo 8L Depth Estimation & Hazard Detection

Supports multiple depth models on Hailo-8L NPU:
- SCDepthV3: Metric depth output (meters directly), auto-detected input size
- fast_depth: Inverse depth output (requires scale_factor conversion)

Analyzes depth maps to detect hazards: walls, stairs, curbs, drop-offs, and
approaching objects not caught by YOLO detection layers.

Hardware: Hailo-8L NPU (M.2 HAT on RPi5)
Output: Depth map (metric or inverse depending on model)

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ─── Hailo Runtime Import (graceful degradation) ────────────────────────────
try:
    from hailo_platform import VDevice, FormatType, HailoSchedulingAlgorithm
    HAILO_AVAILABLE = True
    logger.info("Hailo RT imported successfully")
except ImportError:
    HAILO_AVAILABLE = False
    logger.warning("hailo_platform not available — depth estimation disabled")


# ─── Data Classes ────────────────────────────────────────────────────────────

class HazardType(Enum):
    """Types of depth-based hazards."""
    WALL = "wall"
    STAIRS_DOWN = "stairs_down"
    STAIRS_UP = "stairs_up"
    CURB = "curb"
    DROPOFF = "dropoff"
    APPROACHING_OBJECT = "approaching_object"
    # v2.1 additions — focus on what the cane can't detect
    OVERHANG = "overhang"           # Sign / branch / low ceiling above
    INCOMING_FAST = "incoming_fast"  # Frame-over-frame depth rate > threshold


class HazardSeverity(Enum):
    """Severity levels for hazard alerts."""
    CRITICAL = "critical"    # Immediate danger — vibrate hard + audio
    WARNING = "warning"      # Caution — vibrate medium + audio
    INFO = "info"            # Awareness — no alert unless queried


@dataclass
class Hazard:
    """A detected depth-based hazard."""
    type: HazardType
    severity: HazardSeverity
    direction: str              # "ahead", "left", "right", "below"
    distance: float             # Approximate meters
    confidence: float           # 0.0 - 1.0
    bbox_region: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x1, y1, x2, y2 in depth map coords

    @property
    def alert_key(self) -> str:
        """Key for audio alert lookup (maps to WAV filename)."""
        return f"{self.type.value}"

    @property
    def severity_rank(self) -> int:
        """Numerical rank for priority comparison."""
        return {"critical": 3, "warning": 2, "info": 1}[self.severity.value]


# ─── Depth Estimator ─────────────────────────────────────────────────────────

class HailoDepthEstimator:
    """
    Real-time depth estimation using fast_depth on Hailo-8L NPU.
    
    Provides:
    - Per-frame depth maps (~3ms inference)
    - Hazard detection (walls, stairs, curbs, drop-offs)
    - Approaching object detection (temporal tracking)
    - Per-detection distance enrichment for YOLO results
    """

    # Depth map regions for directional analysis
    # Frame divided into vertical thirds for left/center/right
    REGION_LEFT = (0, 0.33)
    REGION_CENTER = (0.33, 0.67)
    REGION_RIGHT = (0.67, 1.0)

    def __init__(
        self,
        hef_path: str,
        model_type: str = "scdepthv3",
        scale_factor: float = 1.0,
        min_distance: float = 0.3,
        max_distance: float = 20.0,
        wall_threshold: float = 2.5,
        stair_gradient_threshold: float = 0.04,
        dropoff_threshold: float = 2.0,
        approach_rate_threshold: float = 0.25,
        alert_cooldown: float = 0.5,
        # v2.1 additions — indoor-focused (cane handles ground, AI handles head-height)
        overhang_max_height_m: float = 1.5,        # overhead closer than this → alert
        overhang_min_width_pct: float = 15.0,      # min horizontal extent (% of frame)
        stairs_up_min_riser_m: float = 0.3,        # min step height to flag stairs-up
        incoming_fast_velocity_mps: float = 0.5,   # depth change threshold per frame
        incoming_fast_min_frames: int = 3,         # consecutive frames before alert
        vdevice=None,
    ):
        """
        Initialize Hailo depth estimator.

        Args:
            hef_path: Path to depth model HEF file
            model_type: "scdepthv3" (metric depth) or "fast_depth" (inverse depth)
            scale_factor: Calibration factor for inverse depth models (ignored for metric)
            min_distance: Minimum distance clamp (meters)
            max_distance: Maximum distance clamp (meters)
            wall_threshold: Distance (m) below which a surface is flagged as wall
            stair_gradient_threshold: Depth gradient magnitude for stair/curb detection
            dropoff_threshold: Depth ratio for drop-off detection
            approach_rate_threshold: Per-frame depth decrease rate for approaching objects
            alert_cooldown: Seconds between repeated alerts of the same type
            overhang_max_height_m: Indoor — max depth (m) to flag overhead hazard
            overhang_min_width_pct: Min width (% frame) for valid overhead region
            stairs_up_min_riser_m: Min step height to flag stairs-up
            incoming_fast_velocity_mps: Per-frame depth change (m) to flag approach
            incoming_fast_min_frames: Consecutive frames of approach before alerting
            vdevice: Shared Hailo VDevice (if None, creates its own — NOT recommended
                     if other modules also need the device)
        """
        self.hef_path = hef_path
        self.model_type = model_type
        self.scale_factor = scale_factor
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.wall_threshold = wall_threshold
        self.stair_gradient_threshold = stair_gradient_threshold
        self.dropoff_threshold = dropoff_threshold
        self.approach_rate_threshold = approach_rate_threshold
        self.alert_cooldown = alert_cooldown
        # v2.1 — indoor-focused thresholds
        self.overhang_max_height_m = overhang_max_height_m
        self.overhang_min_width_pct = overhang_min_width_pct
        self.stairs_up_min_riser_m = stairs_up_min_riser_m
        self.incoming_fast_velocity_mps = incoming_fast_velocity_mps
        self.incoming_fast_min_frames = incoming_fast_min_frames

        # Environment-aware defaults (outdoor)
        self._outdoor_wall_threshold = wall_threshold
        self._outdoor_alert_cooldown = alert_cooldown
        self._wall_close_ratio = 0.50  # indoor raises this to reduce false walls
        self._is_indoor = False

        # Hailo resources (modern create_infer_model API)
        self._vdevice = None
        self._owns_vdevice = False  # True if we created the VDevice ourselves
        self._external_vdevice = vdevice  # Shared VDevice from caller
        self._infer_model = None
        self._configured_cm = None          # Context manager from configure()
        self._configured_infer_model = None  # Entered context (actual usable object)

        # Model dimensions (auto-detected from HEF)
        self.input_height = 224
        self.input_width = 224
        self.input_channels = 3
        self.output_height = 224
        self.output_width = 224

        # State
        self._prev_depth_map: Optional[np.ndarray] = None
        self._latency_history: List[float] = []
        self._alert_timestamps: Dict[str, float] = {}  # type -> last alert time
        self._is_initialized = False
        # FPS tracking (read by main.py -> DashboardState -> TUI panel)
        self._depth_fps: float = 0.0
        self._depth_fps_window: List[float] = []  # recent inference durations
        self._last_depth_fps_update: float = 0.0

        # Initialize if Hailo is available
        if HAILO_AVAILABLE:
            self._initialize()

    def _initialize(self):
        """Load HEF and configure Hailo device using modern create_infer_model API."""
        try:
            logger.info(f"Loading Hailo depth model: {self.hef_path} (type={self.model_type})")
            
            # Validate HEF file exists
            if not Path(self.hef_path).exists():
                logger.error(f"❌ HEF file not found: {self.hef_path}")
                return
            
            # Use shared VDevice or create our own
            if self._external_vdevice is not None:
                self._vdevice = self._external_vdevice
                self._owns_vdevice = False
                logger.info("  Using shared Hailo VDevice")
            else:
                self._vdevice = VDevice()
                self._owns_vdevice = True
                logger.info("  Created dedicated Hailo VDevice")
            
            # Modern API: create_infer_model from HEF path
            self._infer_model = self._vdevice.create_infer_model(self.hef_path)
            # CRITICAL: set_batch_size must be called BEFORE configure().
            # HailoRT defaults the HEF's batch size to 0 if unset, which
            # causes "Input buffer size 0 is different than expected N"
            # at the first inference call. The official Hailo examples
            # (HailoInfer.__init__) call this with batch_size=1.
            self._infer_model.set_batch_size(1)
            self._infer_model.input().set_format_type(FormatType.FLOAT32)
            self._infer_model.output().set_format_type(FormatType.FLOAT32)
            
            # Auto-detect input/output shapes from HEF
            input_shape = self._infer_model.input().shape
            output_shape = self._infer_model.output().shape
            logger.info(f"  Input shape: {input_shape}")
            logger.info(f"  Output shape: {output_shape}")
            
            # Parse input shape (typically [batch, height, width, channels] or [height, width, channels])
            if len(input_shape) == 4:
                self.input_height = input_shape[1]
                self.input_width = input_shape[2]
                self.input_channels = input_shape[3]
            elif len(input_shape) == 3:
                self.input_height = input_shape[0]
                self.input_width = input_shape[1]
                self.input_channels = input_shape[2]
            
            # Parse output shape
            if len(output_shape) == 4:
                self.output_height = output_shape[1]
                self.output_width = output_shape[2]
            elif len(output_shape) == 3:
                self.output_height = output_shape[0]
                self.output_width = output_shape[1]
            elif len(output_shape) == 2:
                self.output_height = output_shape[0]
                self.output_width = output_shape[1]
            
            logger.info(f"  Auto-detected: input={self.input_height}x{self.input_width}x{self.input_channels}, "
                       f"output={self.output_height}x{self.output_width}")
            
            # Configure once, keep alive for all frames
            # configure() returns a context manager — must enter it
            self._configured_cm = self._infer_model.configure()
            self._configured_infer_model = self._configured_cm.__enter__()
            logger.info("  Configured InferModel (persistent, context entered)")

            # CRITICAL: must explicitly activate() before run/run_async — BUT
            # only when we own the VDevice. On a SHARED VDevice the
            # core-op scheduler is already running (e.g. for the OCR
            # pipeline) and calling ``activate()`` raises
            # "Manually activate a core-op is not allowed when the
            # core-op scheduler is active" (HAILO_INVALID_OPERATION(6)).
            # When sharing, the scheduler activates each model on
            # demand as inference is submitted, so we don't need to.
            if self._owns_vdevice:
                try:
                    self._configured_infer_model.activate()
                    logger.info("  ConfiguredInferModel activated (own VDevice)")
                except Exception as _e:
                    logger.error(f"ConfiguredInferModel.activate() failed: {_e}")
                    raise
            else:
                logger.info("  Skipping activate() — shared VDevice scheduler handles it")

            self._is_initialized = True
            logger.info(f"✅ Hailo depth estimator initialized ({self.model_type})")
            
        except Exception as e:
            logger.error(f"Failed to initialize Hailo depth: {e}")
            self._is_initialized = False

    @property
    def is_available(self) -> bool:
        """Whether the depth estimator is ready to use."""
        return HAILO_AVAILABLE and self._is_initialized

    def cleanup(self) -> None:
        """Release Hailo resources and exit configured model context."""
        if self._configured_infer_model is not None:
            try:
                self._configured_infer_model.deactivate()
            except Exception:
                pass
        if self._configured_cm is not None:
            try:
                self._configured_cm.__exit__(None, None, None)
            except Exception:
                pass
            self._configured_cm = None
            self._configured_infer_model = None
        if self._owns_vdevice and self._vdevice is not None:
            try:
                del self._vdevice
            except Exception:
                pass
            self._vdevice = None
        self._is_initialized = False
        logger.info("Hailo depth estimator cleaned up")

    @property
    def avg_latency_ms(self) -> float:
        """Average inference latency in milliseconds."""
        if not self._latency_history:
            return 0.0
        return sum(self._latency_history[-30:]) / len(self._latency_history[-30:])

    def estimate(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Run depth estimation on a single frame.
        
        Args:
            frame: BGR image from camera (any resolution)
            
        Returns:
            Depth map (float32):
            - SCDepthV3: metric depth in meters (higher = farther)
            - fast_depth: inverse depth (higher = closer)
            Returns None if inference fails.
        """
        if not self.is_available:
            return None

        start = time.perf_counter()

        try:
            # Preprocess: resize to model input size
            import cv2
            resized = cv2.resize(frame, (self.input_width, self.input_height),
                                 interpolation=cv2.INTER_LINEAR)
            
            # Convert BGR to RGB
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            
            # Normalize based on model type
            if self.model_type == "scdepthv3":
                # SCDepthV3 uses ImageNet normalization
                input_data = rgb.astype(np.float32) / 255.0
                mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
                std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
                input_data = (input_data - mean) / std
            else:
                # fast_depth uses simple [0, 1] normalization
                input_data = rgb.astype(np.float32) / 255.0
            
            # Ensure contiguous memory layout (required by Hailo bindings)
            input_data = np.ascontiguousarray(input_data)

            # Run inference using the validated HailoRT 4.x async pattern.
            #
            # The pre-allocated ``output_buffer`` we hand to
            # ``set_buffer()`` STAYS ZERO-FILLED after the call. The
            # real dequantized float32 result comes back through
            # ``bindings.output().get_buffer()`` — HailoRT allocates
            # a NEW host-side array for the dequantized result and
            # returns it from that accessor. (See hailo_depth research
            # notes — host-side format conversion bypasses the
            # user-provided buffer.)
            #
            # API requirements (HailoRT 4.x):
            #   - ``infer_model.configure()`` context manager (we did this)
            #   - ``configured.activate()`` BEFORE first run (we did this)
            #   - ``bindings`` argument to run_async MUST be a list
            #   - ``wait_for_async_ready()`` to avoid queue full
            #   - Buffers should be np.zeros / np.full, NOT np.empty
            #   - Retrieve result via ``bindings.output().get_buffer()``
            bindings = self._configured_infer_model.create_bindings()
            bindings.input().set_buffer(input_data)
            output_buffer = np.zeros(
                self._infer_model.output().shape, dtype=np.float32
            )
            bindings.output().set_buffer(output_buffer)

            # Don't pile up jobs faster than the NPU can drain them
            try:
                self._configured_infer_model.wait_for_async_ready(
                    timeout_ms=5000, frames_count=1
                )
            except Exception as _e:
                logger.debug(f"wait_for_async_ready: {_e}")

            _infer_done = threading.Event()
            _infer_result: Dict[str, object] = {}

            def _infer_callback(*args, **kwargs) -> None:
                # HailoRT 4.x callback receives completion_info as kwarg.
                # The bindings list isn't passed through; we recover the
                # result via the closure-captured bindings.
                try:
                    ci = kwargs.get('completion_info') or (
                        args[0] if args else None
                    )
                    if ci is not None and hasattr(ci, 'exception'):
                        exc = ci.exception()
                        if exc is not None:
                            _infer_result['error'] = str(exc)
                except Exception as _e:
                    logger.debug(f"infer_callback inner error: {_e}")
                finally:
                    _infer_done.set()

            try:
                # MUST pass [bindings] (list of one) — bare Bindings
                # throws "'Bindings' object is not iterable"
                self._configured_infer_model.run_async(
                    [bindings], _infer_callback
                )
            except Exception as _e:
                logger.error(f"infer_model.run_async submit failed: {_e}")
                return None

            if not _infer_done.wait(timeout=5.0):
                logger.error("Depth inference timed out after 5s")
                return None

            if 'error' in _infer_result:
                logger.error(
                    f"Depth inference callback reported error: "
                    f"{_infer_result['error']}"
                )
                return None

            # *** THE KEY FIX ***
            # The real dequantized float32 result is allocated by
            # HailoRT on the host side and exposed via
            # ``bindings.output().get_buffer()``. The buffer we passed
            # via ``set_buffer()`` is just a DMA target for the raw
            # quantized bytes; the dequantization step writes to a NEW
            # array we retrieve here.
            try:
                result = bindings.output().get_buffer()
            except Exception as _e:
                logger.error(f"Failed to get output buffer: {_e}")
                return None
            if result is None:
                logger.error("get_buffer() returned None")
                return None

            # result may be a list (one entry per output layer) or
            # a single ndarray — SCDepthV3 has 1 output so it's ndarray
            if isinstance(result, list):
                result = result[0]
            output_buffer = np.asarray(result)

            # ── SCDepthV3 ON HAILO-8L SIGN CONVENTION ──
            # The compiled SCDepthV3 HEF on Hailo-8L emits NEGATIVE
            # log-disparity values (typically -3 to -6 on indoor
            # scenes). Convention: LESS NEGATIVE = CLOSER. So:
            #   raw = -5.5 → 5.5 m (real depth)
            #   raw = -3.5 → 3.5 m (further)
            # Negate so the depth map handed to ALL downstream
            # consumers is in positive meters. Without this fix:
            #   - ``np.clip(depth_map, 0.3, 20.0)`` clipped every
            #     negative to 0.3, making _detect_walls think every
            #     pixel was a wall AND _detect_overhangs see no
            #     "protrusion" (because bottom strip was also 0.3,
            #     not far) → ZERO safety alerts.
            #   - ``classify_distance()`` returned wrong labels.
            if self.model_type == "scdepthv3":
                output_buffer = -output_buffer
            
            # Extract depth map from pre-allocated output buffer
            depth_map = output_buffer
            
            # Remove batch dimension and squeeze to 2D
            depth_map = np.squeeze(depth_map)
            
            # Ensure float32
            depth_map = depth_map.astype(np.float32)
            
            # Handle model-specific output format
            if self.model_type == "scdepthv3":
                # SCDepthV3 outputs metric depth directly (meters)
                # Clamp to valid range
                depth_map = np.clip(depth_map, self.min_distance, self.max_distance)
            else:
                # fast_depth outputs inverse depth — higher = closer
                # Ensure positive values
                depth_map = np.maximum(depth_map, 1e-6)

            elapsed_ms = (time.perf_counter() - start) * 1000
            self._latency_history.append(elapsed_ms)
            if len(self._latency_history) > 100:
                self._latency_history = self._latency_history[-50:]

            # FPS tracking — read by DashboardState (TUI panel).
            # Update at most every 1s; rolling 1s window.
            now = time.time()
            self._depth_fps_window.append(now)
            cutoff = now - 1.0
            self._depth_fps_window = [t for t in self._depth_fps_window if t >= cutoff]
            if now - self._last_depth_fps_update > 0.5:
                self._depth_fps = float(len(self._depth_fps_window))
                self._last_depth_fps_update = now

            logger.debug(f"Depth inference: {elapsed_ms:.1f}ms ({self.model_type})")
            return depth_map

        except Exception as e:
            logger.error(f"Depth estimation failed: {e}")
            return None

    def get_depth_at_bbox(
        self,
        depth_map: np.ndarray,
        bbox: List[float],
        frame_shape: Tuple[int, ...]
    ) -> float:
        """
        Get approximate distance at a detection bounding box center.
        
        Args:
            depth_map: Depth map from estimate()
            bbox: [x1, y1, x2, y2] in pixel coordinates of original frame
            frame_shape: Shape of original frame (H, W, C)
            
        Returns:
            Approximate distance in meters (clamped to min/max range)
        """
        if depth_map is None or len(bbox) < 4:
            return -1.0

        h, w = frame_shape[:2]
        dh, dw = depth_map.shape[:2]

        # Map bbox center to depth map coordinates
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        dx = int(cx / w * dw)
        dy = int(cy / h * dh)

        # Clamp to depth map bounds
        dx = max(0, min(dx, dw - 1))
        dy = max(0, min(dy, dh - 1))

        # Sample median depth in a 7x7 region around center (robust to noise)
        r = 3
        y1 = max(0, dy - r)
        y2 = min(dh, dy + r + 1)
        x1 = max(0, dx - r)
        x2 = min(dw, dx + r + 1)
        region = depth_map[y1:y2, x1:x2]
        median_depth = float(np.median(region))

        # Convert to metric distance based on model type
        if self.model_type == "scdepthv3":
            # SCDepthV3 outputs metric depth directly (meters)
            distance = median_depth
        else:
            # fast_depth outputs inverse depth — convert to meters
            distance = self.scale_factor / (median_depth + 1e-6)
        
        distance = max(self.min_distance, min(distance, self.max_distance))

        return round(distance, 2)

    def analyze_hazards(
        self,
        depth_map: np.ndarray,
        detections: Optional[List[Dict[str, Any]]] = None,
        frame_shape: Optional[Tuple[int, ...]] = None
    ) -> List[Hazard]:
        """
        Analyze depth map for environmental hazards.

        Indoor mode (user has a cane):
        - Cane handles walls, stairs-down, drop-offs, curbs → SKIP
        - Cane CAN'T detect: overhangs, stairs-UP, fast-incoming → ENABLE
        - Furniture from YOLO + depth (T2 silent static) still fires via SafetyMonitor

        Outdoor mode:
        - All current ground hazards (walls, stairs, drop-offs, curbs)
        - Plus overhangs (low tree branches), stairs-UP, fast-incoming

        Args:
            depth_map: Depth map from estimate()
            detections: Current YOLO detections (to exclude from approaching object check)
            frame_shape: Original frame shape for bbox mapping

        Returns:
            List of detected Hazard objects, sorted by severity (highest first)
        """
        if depth_map is None:
            return []

        hazards: List[Hazard] = []
        now = time.time()
        dh, dw = depth_map.shape[:2]

        # Convert to unified distance map (meters, higher = farther)
        if self.model_type == "scdepthv3":
            # SCDepthV3 already outputs metric depth
            dist_map = np.clip(depth_map, self.min_distance, self.max_distance)
        else:
            # fast_depth outputs inverse depth — convert to meters
            dist_map = self.scale_factor / (depth_map + 1e-6)
            dist_map = np.clip(dist_map, self.min_distance, self.max_distance)

        if self._is_indoor:
            # ── INDOOR: cane handles ground; AI handles head-height ──
            # 1. Overhead hazards (signs, low doorways, branches, low ceiling)
            hazards.extend(self._detect_overhangs(dist_map, dh, dw, now))
            # 2. Stairs going UP (the cane-missed trap)
            hazards.extend(self._detect_stairs_up(depth_map, dist_map, dh, dw, now))
            # 3. Fast incoming objects (running person, cart)
            hazards.extend(self._detect_incoming_fast(depth_map, dh, dw, now))
        else:
            # ── OUTDOOR: keep all current + add new ──
            # 1. Wall detection
            hazards.extend(self._detect_walls(dist_map, dh, dw, now))
            # 2. Stairs / curb / step detection (down + up)
            hazards.extend(self._detect_stairs_and_curbs(depth_map, dist_map, dh, dw, now))
            # 3. Drop-off detection
            hazards.extend(self._detect_dropoff(depth_map, dist_map, dh, dw, now))
            # 4. Overhead (low tree branches, awnings, signs)
            hazards.extend(self._detect_overhangs(dist_map, dh, dw, now))
            # 5. Stairs-UP (still useful outdoors — same trap)
            hazards.extend(self._detect_stairs_up(depth_map, dist_map, dh, dw, now))
            # 6. Fast incoming (vehicles, cyclists)
            if self._prev_depth_map is not None:
                hazards.extend(
                    self._detect_approaching(depth_map, detections, frame_shape, dh, dw, now)
                )

        # Store for next frame comparison
        self._prev_depth_map = depth_map.copy()

        # Sort by severity (highest first)
        hazards.sort(key=lambda h: h.severity_rank, reverse=True)

        if hazards:
            logger.debug(f"Hazards detected: {[(h.type.value, h.severity.value, f'{h.distance:.1f}m') for h in hazards]}")

        return hazards

    def _is_on_cooldown(self, hazard_type: str, now: float) -> bool:
        """Check if a hazard type is still in cooldown period."""
        last = self._alert_timestamps.get(hazard_type, 0)
        return (now - last) < self.alert_cooldown

    def _mark_alerted(self, hazard_type: str, now: float):
        """Record that an alert was issued for this hazard type."""
        self._alert_timestamps[hazard_type] = now

    def _detect_walls(
        self, dist_map: np.ndarray, dh: int, dw: int, now: float
    ) -> List[Hazard]:
        """
        Detect walls by finding large vertical regions at close, uniform depth.
        
        Analyzes left, center, and right thirds of the frame.
        A "wall" is flagged when >60% of pixels in a vertical strip are
        at similar close distance (< wall_threshold).
        """
        hazards = []
        
        # M3 fix: regions are now non-overlapping. The previous
        # boundaries [0, 0.33) / [0.25, 0.75) / [0.67, 1.0] overlapped
        # at [0.25, 0.33) and [0.67, 0.75), so a wall spanning the
        # center of the frame would fire BOTH "left" and "ahead"
        # (or "right" and "ahead") simultaneously.
        regions = [
            ("left", int(dw * 0.00), int(dw * 0.33)),
            ("ahead", int(dw * 0.33), int(dw * 0.67)),
            ("right", int(dw * 0.67), int(dw * 1.00)),
        ]

        for direction, x1, x2 in regions:
            # Analyze upper 70% of frame (walls are vertical, not floor)
            strip = dist_map[:int(dh * 0.7), x1:x2]
            if strip.size == 0:
                continue

            close_pixels = (strip < self.wall_threshold).sum()
            total_pixels = strip.size
            close_ratio = close_pixels / total_pixels

            if close_ratio > self._wall_close_ratio:
                median_dist = float(np.median(strip[strip < self.wall_threshold]))
                
                # Severity based on distance
                if median_dist < 1.0:
                    severity = HazardSeverity.CRITICAL
                else:
                    severity = HazardSeverity.WARNING

                hazard_key = f"wall_{direction}"
                if not self._is_on_cooldown(hazard_key, now):
                    hazards.append(Hazard(
                        type=HazardType.WALL,
                        severity=severity,
                        direction=direction,
                        distance=round(median_dist, 2),
                        confidence=round(close_ratio, 2),
                        bbox_region=(x1, 0, x2, int(dh * 0.7))
                    ))
                    if severity != HazardSeverity.INFO:
                        self._mark_alerted(hazard_key, now)

        return hazards

    # ── Environment classification ───────────────────────────────────

    def classify_environment(self, depth_map: np.ndarray) -> str:
        """
        Classify indoor vs outdoor using depth map statistics.
        
        Indoor: max depth < 6m AND < 15% of pixels see beyond 6m.
        
        Args:
            depth_map: Raw depth map from estimate().
            
        Returns 'indoor' or 'outdoor'.
        """
        # Convert to distance map (meters)
        if self.model_type == "scdepthv3":
            dist_map = np.clip(depth_map, self.min_distance, self.max_distance)
        else:
            dist_map = self.scale_factor / (depth_map + 1e-6)
            dist_map = np.clip(dist_map, self.min_distance, self.max_distance)

        max_depth = float(np.max(dist_map))
        far_pixels = (dist_map > 6.0).sum()
        far_ratio = far_pixels / max(dist_map.size, 1)

        if max_depth < 6.0 and far_ratio < 0.15:
            return "indoor"
        return "outdoor"

    def set_environment(self, indoor: bool):
        """Adjust wall detection thresholds for indoor vs outdoor."""
        if indoor == self._is_indoor:
            return  # no change
        self._is_indoor = indoor
        if indoor:
            self.wall_threshold = 0.8
            self.alert_cooldown = 2.0
            self._wall_close_ratio = 0.70
        else:
            self.wall_threshold = self._outdoor_wall_threshold
            self.alert_cooldown = self._outdoor_alert_cooldown
            self._wall_close_ratio = 0.50
        label = "INDOOR" if indoor else "OUTDOOR"
        logger.info(f"Environment → {label}: wall_threshold={self.wall_threshold}m, "
                    f"close_ratio>{self._wall_close_ratio}, cooldown={self.alert_cooldown}s")

    def _detect_stairs_and_curbs(
        self, depth_map: np.ndarray, dist_map: np.ndarray, dh: int, dw: int, now: float
    ) -> List[Hazard]:
        """
        Detect stairs, curbs, and steps by analyzing depth gradients in the
        bottom 40% of the frame (floor area).
        
        - Sharp positive vertical gradient = step down / stairs descending
        - Sharp negative vertical gradient = step up / stairs ascending
        - Single discontinuity = curb or single step
        - Multiple discontinuities = staircase
        """
        hazards = []
        
        if self._is_on_cooldown("stairs", now) and self._is_on_cooldown("curb", now):
            return hazards

        # Analyze bottom 40% — metric distance for linear gradients
        floor_start = int(dh * 0.6)
        floor_region = dist_map[floor_start:, :]

        if floor_region.shape[0] < 5:
            return hazards

        # Vertical gradient on metric distance map
        # Positive = distance increases going down = floor drops away = step-down
        # Negative = distance decreases going down = surface closer = step-up
        vertical_gradient = np.diff(floor_region, axis=0)

        # Analyze center strip (where user is walking)
        center_start = int(dw * 0.25)
        center_end = int(dw * 0.75)
        center_gradient = vertical_gradient[:, center_start:center_end]

        # Average gradient per row to smooth noise
        row_gradients = np.mean(np.abs(center_gradient), axis=1)

        # Find rows with sharp gradient changes (potential step edges)
        threshold = self.stair_gradient_threshold
        step_rows = np.where(row_gradients > threshold)[0]

        if len(step_rows) == 0:
            return hazards

        # Count distinct step edges (edges must be at least 3 rows apart)
        distinct_edges = []
        last_row = -10
        for row in step_rows:
            if row - last_row >= 3:
                distinct_edges.append(row)
                last_row = row

        # Get average distance at the step region
        step_y = floor_start + distinct_edges[0]
        step_dist = float(np.median(
            dist_map[max(0, step_y - 2):min(dh, step_y + 3), center_start:center_end]
        ))

        # Determine direction of depth change
        if len(distinct_edges) > 0:
            first_edge = distinct_edges[0]
            edge_gradient = np.mean(center_gradient[first_edge, :])

            if len(distinct_edges) >= 3:
                # Multiple edges = staircase
                if edge_gradient > 0:
                    hazard_type = HazardType.STAIRS_DOWN
                else:
                    hazard_type = HazardType.STAIRS_UP
                
                severity = HazardSeverity.CRITICAL if step_dist < 2.0 else HazardSeverity.WARNING
                
                if not self._is_on_cooldown("stairs", now):
                    hazards.append(Hazard(
                        type=hazard_type,
                        severity=severity,
                        direction="ahead",
                        distance=round(step_dist, 2),
                        confidence=round(min(1.0, len(distinct_edges) / 3.0), 2),
                        bbox_region=(center_start, floor_start, center_end, dh)
                    ))
                    self._mark_alerted("stairs", now)
            else:
                # 1-2 edges = curb or single step
                severity = HazardSeverity.WARNING if step_dist < 2.0 else HazardSeverity.INFO
                
                if not self._is_on_cooldown("curb", now):
                    hazards.append(Hazard(
                        type=HazardType.CURB,
                        severity=severity,
                        direction="ahead",
                        distance=round(step_dist, 2),
                        confidence=round(min(1.0, float(row_gradients[distinct_edges[0]]) / threshold), 2),
                        bbox_region=(center_start, floor_start, center_end, dh)
                    ))
                    self._mark_alerted("curb", now)

        return hazards

    def _detect_dropoff(
        self, depth_map: np.ndarray, dist_map: np.ndarray, dh: int, dw: int, now: float
    ) -> List[Hazard]:
        """
        Detect drop-offs / ledges where the ground falls away.
        
        Compares mid-frame floor depth with bottom-frame depth.
        If bottom is significantly farther (ratio > threshold), it's a drop-off.
        """
        hazards = []
        
        if self._is_on_cooldown("dropoff", now):
            return hazards

        center_start = int(dw * 0.25)
        center_end = int(dw * 0.75)

        # Mid-floor band (60-70% of frame height)
        mid_band = dist_map[int(dh * 0.6):int(dh * 0.7), center_start:center_end]
        # Bottom band (85-95% of frame height)
        bottom_band = dist_map[int(dh * 0.85):int(dh * 0.95), center_start:center_end]

        if mid_band.size == 0 or bottom_band.size == 0:
            return hazards

        mid_median = float(np.median(mid_band))
        bottom_median = float(np.median(bottom_band))

        # For both model types, dist_map is in meters (higher = farther)
        # Drop-off: bottom is much farther than mid (ratio > threshold)
        if mid_median > 1e-6:
            depth_ratio = bottom_median / mid_median
        else:
            depth_ratio = 0

        # C6 fix: the previous code ONLY detected the "cliff in front of me"
        # case (bottom >> mid). It systematically MISSED the cane-relevant
        # "top of stairs going down" case, where the user looks down at the
        # descending steps — the bottom band is CLOSER than the mid band
        # (mid_median > bottom_median → ratio < 1), so the cliff case never
        # fired. Detect both directions and use the larger depth-jump as the
        # drop distance.
        forward_cliff = depth_ratio > self.dropoff_threshold  # cliff in front
        top_of_stairs = (
            bottom_median > 1e-6
            and (mid_median / bottom_median) > self.dropoff_threshold
        )  # top of stairs, looking down
        detected = forward_cliff or top_of_stairs

        if detected:
            # Ground falls away — drop-off detected
            # Use the closer of the two bands as the "distance to the drop"
            # because that's the edge the user is about to step off.
            drop_distance = min(mid_median, bottom_median)

            severity = HazardSeverity.CRITICAL if drop_distance < 2.0 else HazardSeverity.WARNING

            # Confidence: bigger jump = higher confidence.
            jump = (
                depth_ratio if forward_cliff
                else (mid_median / bottom_median)
            )
            hazards.append(Hazard(
                type=HazardType.DROPOFF,
                severity=severity,
                direction="ahead",
                distance=round(drop_distance, 2),
                confidence=round(min(1.0, jump / (self.dropoff_threshold * 2)), 2),
                bbox_region=(center_start, int(dh * 0.6), center_end, dh)
            ))
            self._mark_alerted("dropoff", now)

        return hazards

    # ── v2.1 indoor-focused detectors ──────────────────────────────────

    def _detect_overhangs(
        self, dist_map: np.ndarray, dh: int, dw: int, now: float
    ) -> List[Hazard]:
        """
        Detect overhead hazards — things above head height the cane can't see.

        Analyzes the TOP 40% of the frame. Looks for wide regions where
        the median depth is significantly closer than the frame's overall
        median (i.e. something protruding down toward the user's head).

        Differentiates from a "low ceiling" vs "overhang" by checking the
        bottom 40% — if the bottom is FAR (open space below), it's an
        overhang. If the bottom is also close, it's just a small room.
        """
        if self._is_on_cooldown("overhang", now):
            return []

        hazards = []
        # Top 40% of frame = ceiling / sky / tree canopy
        top_start = int(dh * 0.05)  # skip very top edge (often noisy)
        top_end = int(dh * 0.45)
        top_strip = dist_map[top_start:top_end, :]

        if top_strip.size < 16:
            return hazards

        # Find columns where the median depth in the top strip is close
        # (column = vertical slice of the image)
        col_medians = np.median(top_strip, axis=0)
        close_cols = col_medians < self.overhang_max_height_m

        if not np.any(close_cols):
            return hazards

        # Find the longest run of consecutive close columns
        # (avoids triggering on single noise pixels)
        diffs = np.diff(close_cols.astype(int))
        starts = np.where(diffs == 1)[0] + 1
        ends = np.where(diffs == -1)[0] + 1
        if close_cols[0]:
            starts = np.concatenate([[0], starts])
        if close_cols[-1]:
            ends = np.concatenate([ends, [len(close_cols)]])

        if len(starts) == 0:
            return hazards

        run_lengths = ends - starts
        widest_start = starts[np.argmax(run_lengths)]
        widest_end = ends[np.argmax(run_lengths)]
        run_width_pct = 100.0 * (widest_end - widest_start) / dw

        if run_width_pct < self.overhang_min_width_pct:
            return hazards

        # Compute median depth of the overhanging region
        overhang_depth = float(np.median(top_strip[:, widest_start:widest_end]))

        # Differentiate: if bottom 40% of frame is far (open below), it's
        # an overhang like a sign or branch. If bottom is also close, it's
        # just a low-ceiling room (not as critical).
        bottom_strip = dist_map[int(dh * 0.7):, :]
        if bottom_strip.size < 16:
            return hazards
        bottom_median = float(np.median(bottom_strip))
        is_protrusion = bottom_median > 2.0  # open space below

        # Direction: map column range to left/center/right
        run_center = (widest_start + widest_end) / 2
        if run_center < dw * 0.33:
            direction = "left"
        elif run_center > dw * 0.67:
            direction = "right"
        else:
            direction = "ahead"

        # Severity: closer = worse. Critical if < 1.0m (about to hit head).
        if overhang_depth < 1.0:
            severity = HazardSeverity.CRITICAL
        elif overhang_depth < 1.5:
            severity = HazardSeverity.WARNING
        else:
            severity = HazardSeverity.INFO

        # Only fire on WARNING or worse (INFO would be too noisy)
        if severity == HazardSeverity.INFO:
            return hazards

        hazard_key = f"overhang_{direction}"
        if not self._is_on_cooldown(hazard_key, now):
            hazards.append(Hazard(
                type=HazardType.OVERHANG,
                severity=severity,
                direction=direction,
                distance=round(overhang_depth, 2),
                confidence=round(min(1.0, run_width_pct / 30.0), 2),
                bbox_region=(widest_start, top_start, widest_end, top_end),
            ))
            if severity != HazardSeverity.INFO:
                self._mark_alerted(hazard_key, now)
            if is_protrusion:
                logger.debug(
                    f"OVERHANG {direction} {overhang_depth:.2f}m "
                    f"(width={run_width_pct:.0f}%, open_below={bottom_median:.1f}m)"
                )

        return hazards

    def _detect_stairs_up(
        self, depth_map: np.ndarray, dist_map: np.ndarray,
        dh: int, dw: int, now: float
    ) -> List[Hazard]:
        """
        Detect stairs going UP — the cane-missed trap.

        Looks at the vertical depth gradient in the bottom 40% of the frame.
        For step-UP: the floor in the foreground is CLOSER than the floor
        just above it (negative vertical gradient). A step > 0.3m rising
        from foreground to mid-frame means "you're about to walk up".

        Mirrors the structure of _detect_stairs_and_curbs but ONLY for
        the up direction (down is handled by the cane).
        """
        if self._is_on_cooldown("stairs_up", now):
            return []

        hazards = []
        # Bottom 40% — where the floor is
        floor_start = int(dh * 0.6)
        floor_region = dist_map[floor_start:, :]

        if floor_region.shape[0] < 5:
            return hazards

        # Vertical gradient on metric distance map
        # Negative gradient = distance DECREASES going down = surface is
        # CLOSER toward the bottom = step UP (riser sticking up toward
        # the camera)
        vertical_gradient = np.diff(floor_region, axis=0)

        # Center strip (where user is walking)
        center_start = int(dw * 0.25)
        center_end = int(dw * 0.75)
        center_gradient = vertical_gradient[:, center_start:center_end]

        # Average gradient per row
        row_gradients = np.mean(center_gradient, axis=1)

        # For stairs UP, we're looking for a sharp NEGATIVE gradient
        # (distance goes from large → small as we go down the image).
        #
        # C5 fix: row_gradients is in METERS PER ROW of the depthmap
        # (dist_map is metric). A real 0.3m riser that spans ~5 rows
        # produces a per-row gradient of ~0.06m, NOT 0.3m. The previous
        # threshold of 0.3m meant the detector only fired on an
        # impossibly steep single-row step — the entire indoor
        # cane-invisible step-up detection was dead. Use the same
        # per-row threshold as the outdoor stairs detector
        # (self.stair_gradient_threshold).
        threshold = self.stair_gradient_threshold
        step_rows = np.where(row_gradients < -threshold)[0]

        if len(step_rows) == 0:
            return hazards

        # Cluster consecutive step rows
        distinct_edges = []
        last_row = -10
        for row in step_rows:
            if row - last_row >= 3:
                distinct_edges.append(row)
                last_row = row

        if len(distinct_edges) == 0:
            return hazards

        # Distance to the riser (where the step is)
        step_y = floor_start + distinct_edges[0]
        step_dist = float(np.median(
            dist_map[max(0, step_y - 2):min(dh, step_y + 3), center_start:center_end]
        ))

        # Severity: closer step = more critical
        if step_dist < 1.0:
            severity = HazardSeverity.CRITICAL
        elif step_dist < 2.0:
            severity = HazardSeverity.WARNING
        else:
            severity = HazardSeverity.INFO

        if severity == HazardSeverity.INFO:
            return hazards

        hazards.append(Hazard(
            type=HazardType.STAIRS_UP,
            severity=severity,
            direction="ahead",
            distance=round(step_dist, 2),
            confidence=round(min(1.0, abs(row_gradients[distinct_edges[0]]) / 0.5), 2),
            bbox_region=(center_start, floor_start, center_end, dh),
        ))
        self._mark_alerted("stairs_up", now)

        logger.debug(
            f"STAIRS_UP ahead {step_dist:.2f}m "
            f"(edges={len(distinct_edges)}, gradient={row_gradients[distinct_edges[0]]:.2f})"
        )
        return hazards

    def _detect_incoming_fast(
        self, depth_map: np.ndarray, dh: int, dw: int, now: float
    ) -> List[Hazard]:
        """
        Detect anything approaching FAST (indoor primary use case).

        Frame-over-frame depth rate. A region with sustained depth
        decrease > incoming_fast_velocity_mps is "something coming at me".

        Outdoor: handled by _detect_approaching (same algorithm, more
        generous thresholds and uses YOLO for vehicle verification).
        """
        if self._is_on_cooldown("incoming_fast", now):
            return []

        if self._prev_depth_map is None or self._prev_depth_map.shape != depth_map.shape:
            return []

        hazards = []

        # Depth DECREASE = object getting CLOSER
        # SCDepthV3 outputs metric depth (smaller = closer)
        depth_diff = self._prev_depth_map - depth_map
        # For inverse depth models, the math is inverted (we'd flip signs)
        if self.model_type != "scdepthv3":
            depth_diff = -depth_diff

        # Threshold for "approaching" this frame
        per_frame_threshold = self.incoming_fast_velocity_mps
        approach_mask = depth_diff > per_frame_threshold

        # Require a large enough region (avoid single-pixel noise)
        approach_ratio = approach_mask.sum() / approach_mask.size

        if approach_ratio < 0.10:  # At least 10% of frame is approaching
            return hazards

        # Find the centroid of the approaching region
        approaching_pixels = np.where(approach_mask)
        if len(approaching_pixels[0]) == 0:
            return hazards

        cx = int(np.mean(approaching_pixels[1]))

        # M2 fix: the centroid (cy) of the approaching region is
        # typically the floor (the largest connected region). The
        # actual person/object is in the UPPER portion. We restrict
        # the distance sample to the top half of the approach_mask
        # to avoid sampling the floor.
        top_half_mask = approach_mask[: dh // 2, :]
        top_pixels = np.where(top_half_mask)
        if len(top_pixels[0]) > 0:
            cy = int(np.mean(top_pixels[0]))
        else:
            cy = int(np.mean(approaching_pixels[0]))

        # Direction
        if cx < dw * 0.33:
            direction = "left"
        elif cx > dw * 0.67:
            direction = "right"
        else:
            direction = "ahead"

        # Distance to the approaching object — sample upper portion only
        dist = float(np.median(depth_map[
            max(0, cy - 5):min(dh, cy + 5),
            max(0, cx - 5):min(dw, cx + 5)
        ]))
        dist = max(self.min_distance, min(dist, self.max_distance))

        # Severity by distance
        if dist < 1.0:
            severity = HazardSeverity.CRITICAL
        elif dist < 2.0:
            severity = HazardSeverity.WARNING
        else:
            severity = HazardSeverity.INFO

        if severity == HazardSeverity.INFO:
            return hazards

        hazards.append(Hazard(
            type=HazardType.INCOMING_FAST,
            severity=severity,
            direction=direction,
            distance=round(dist, 2),
            confidence=round(min(1.0, approach_ratio / 0.2), 2),
            bbox_region=(
                int(np.min(approaching_pixels[1])),
                int(np.min(approaching_pixels[0])),
                int(np.max(approaching_pixels[1])),
                int(np.max(approaching_pixels[0])),
            ),
        ))
        self._mark_alerted("incoming_fast", now)

        logger.debug(
            f"INCOMING_FAST {direction} {dist:.2f}m (ratio={approach_ratio:.0%})"
        )
        return hazards

    def _detect_approaching(
        self,
        depth_map: np.ndarray,
        detections: Optional[List[Dict[str, Any]]],
        frame_shape: Optional[Tuple[int, ...]],
        dh: int, dw: int,
        now: float
    ) -> List[Hazard]:
        """
        Detect objects approaching the user (outdoor / vehicle case).

        Compares current depth map with previous frame. Regions with
        significant depth DECREASE (closer) that don't overlap with
        existing YOLO detections are flagged.

        Outdoor use only — indoor uses _detect_incoming_fast which has
        stricter thresholds. This method also excludes YOLO-detected
        regions to avoid double-alerting on tracked vehicles.
        """
        hazards = []

        if self._prev_depth_map is None or self._prev_depth_map.shape != depth_map.shape:
            return hazards

        # Depth DECREASE = object getting CLOSER
        # SCDepthV3 outputs metric depth (smaller = closer)
        depth_diff = self._prev_depth_map - depth_map
        if self.model_type != "scdepthv3":
            depth_diff = -depth_diff  # invert for inverse-depth models

        approach_mask = depth_diff > self.approach_rate_threshold

        # Exclude YOLO-detected regions (those are handled by SafetyMonitor Tier 3)
        if detections and frame_shape:
            h, w = frame_shape[:2]
            exclusion = np.zeros((dh, dw), dtype=bool)
            for det in detections:
                bbox = det.get('bbox', det.get('bbox_normalized', []))
                if len(bbox) < 4:
                    continue
                x1 = int(bbox[0] / w * dw) if bbox[0] > 1 else int(bbox[0] * dw)
                y1 = int(bbox[1] / h * dh) if bbox[1] > 1 else int(bbox[1] * dh)
                x2 = int(bbox[2] / w * dw) if bbox[2] > 1 else int(bbox[2] * dw)
                y2 = int(bbox[3] / h * dh) if bbox[3] > 1 else int(bbox[3] * dh)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(dw, x2), min(dh, y2)
                pad = 5
                exclusion[max(0, y1-pad):min(dh, y2+pad), max(0, x1-pad):min(dw, x2+pad)] = True
            approach_mask = approach_mask & ~exclusion

        # Check if any significant approaching region remains
        approach_ratio = approach_mask.sum() / approach_mask.size

        if approach_ratio > 0.08:
            approaching_pixels = np.where(approach_mask)
            if len(approaching_pixels[0]) > 0:
                cy = int(np.mean(approaching_pixels[0]))
                cx = int(np.mean(approaching_pixels[1]))

                if cx < dw * 0.33:
                    direction = "left"
                elif cx > dw * 0.67:
                    direction = "right"
                else:
                    direction = "ahead"

                # SCDepthV3 is metric; fast_depth is inverse
                if self.model_type == "scdepthv3":
                    dist = float(depth_map[cy, cx])
                else:
                    dist = self.scale_factor / (float(depth_map[cy, cx]) + 1e-6)
                dist = max(self.min_distance, min(dist, self.max_distance))

                severity = HazardSeverity.WARNING if dist < 3.0 else HazardSeverity.INFO

                if severity == HazardSeverity.INFO:
                    return hazards

                hazards.append(Hazard(
                    type=HazardType.APPROACHING_OBJECT,
                    severity=severity,
                    direction=direction,
                    distance=round(dist, 2),
                    confidence=round(min(1.0, approach_ratio / 0.1), 2),
                    bbox_region=(
                        int(np.min(approaching_pixels[1])),
                        int(np.min(approaching_pixels[0])),
                        int(np.max(approaching_pixels[1])),
                        int(np.max(approaching_pixels[0])),
                    ),
                ))
                self._mark_alerted("approaching_object", now)

        return hazards

    def classify_distance(self, distance_m: float) -> str:
        """
        Classify a distance into a human-readable zone.

        Args:
            distance_m: Distance in meters

        Returns:
            Zone string for speech output
        """
        if distance_m < 1.0:
            return "very close"
        elif distance_m < 3.0:
            return "nearby"
        elif distance_m < 8.0:
            return f"about {int(round(distance_m))} meters away"
        else:
            return "far away"

    # H30 fix: there used to be a SECOND `cleanup()` defined here
    # (at line 1216 in the previous version). It shadowed the proper
    # one at line 274 and called `_configured_infer_model.shutdown()`
    # — a method that doesn't exist on the HailoRT binding. Python
    # silently used the second definition, the configured model
    # context was never released, the VDevice was never freed, and
    # the next `init()` raised "device busy". The canonical
    # `cleanup()` at line 274 (using `__exit__` + `del _vdevice`) is
    # the only one we want. The orphaned duplicate is gone.
