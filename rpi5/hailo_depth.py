"""
Hailo 8L Depth Estimation & Hazard Detection

Uses fast_depth model on Hailo-8L NPU for real-time monocular depth estimation.
Analyzes depth maps to detect hazards: walls, stairs, curbs, drop-offs, and
approaching objects not caught by YOLO detection layers.

Hardware: Hailo-8L NPU (M.2 HAT on RPi5)
Model: fast_depth — 224x224x3 input, 1.35M params, ~299 FPS on Hailo-8L
Output: 224x224 relative/inverse depth map

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ─── Hailo Runtime Import (graceful degradation) ────────────────────────────
try:
    from hailo_platform import (
        HEF,
        VDevice,
        HailoStreamInterface,
        ConfigureParams,
        InputVStreamParams,
        OutputVStreamParams,
        FormatType,
        HailoSchedulingAlgorithm,
    )
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
        scale_factor: float = 1.0,
        min_distance: float = 0.3,
        max_distance: float = 20.0,
        wall_threshold: float = 1.5,
        stair_gradient_threshold: float = 0.3,
        dropoff_threshold: float = 3.0,
        approach_rate_threshold: float = 0.1,
        alert_cooldown: float = 3.0,
    ):
        """
        Initialize Hailo depth estimator.
        
        Args:
            hef_path: Path to fast_depth.hef model file
            scale_factor: Calibration factor for relative-to-metric depth conversion
            min_distance: Minimum distance clamp (meters)
            max_distance: Maximum distance clamp (meters)
            wall_threshold: Distance (m) below which a surface is flagged as wall
            stair_gradient_threshold: Depth gradient magnitude for stair/curb detection
            dropoff_threshold: Depth ratio for drop-off detection
            approach_rate_threshold: Per-frame depth decrease rate for approaching objects
            alert_cooldown: Seconds between repeated alerts of the same type
        """
        self.hef_path = hef_path
        self.scale_factor = scale_factor
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.wall_threshold = wall_threshold
        self.stair_gradient_threshold = stair_gradient_threshold
        self.dropoff_threshold = dropoff_threshold
        self.approach_rate_threshold = approach_rate_threshold
        self.alert_cooldown = alert_cooldown

        # Hailo resources
        self._vdevice = None
        self._network_group = None
        self._input_vstreams = None
        self._output_vstreams = None
        self._input_vstream_info = None
        self._output_vstream_info = None

        # Model dimensions (fast_depth)
        self.input_height = 224
        self.input_width = 224
        self.input_channels = 3

        # State
        self._prev_depth_map: Optional[np.ndarray] = None
        self._latency_history: List[float] = []
        self._alert_timestamps: Dict[str, float] = {}  # type -> last alert time
        self._is_initialized = False

        # Initialize if Hailo is available
        if HAILO_AVAILABLE:
            self._initialize()

    def _initialize(self):
        """Load HEF and configure Hailo device."""
        try:
            logger.info(f"Loading Hailo depth model: {self.hef_path}")
            
            # Load the HEF
            self._hef = HEF(self.hef_path)
            
            # Create virtual device
            self._vdevice = VDevice()
            
            # Configure network group
            configure_params = ConfigureParams.create_from_hef(
                hef=self._hef,
                interface=HailoStreamInterface.PCIe
            )
            self._network_group = self._vdevice.configure(self._hef, configure_params)[0]
            
            # Get stream info
            self._input_vstream_info = self._hef.get_input_vstream_infos()
            self._output_vstream_info = self._hef.get_output_vstream_infos()
            
            # Log model info
            for info in self._input_vstream_info:
                logger.info(f"  Input: {info.name}, shape={info.shape}, format={info.format}")
            for info in self._output_vstream_info:
                logger.info(f"  Output: {info.name}, shape={info.shape}, format={info.format}")
            
            self._is_initialized = True
            logger.info("Hailo depth estimator initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Hailo depth: {e}")
            self._is_initialized = False

    @property
    def is_available(self) -> bool:
        """Whether the depth estimator is ready to use."""
        return HAILO_AVAILABLE and self._is_initialized

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
            224x224 depth map (float32, higher values = closer),
            or None if inference fails
        """
        if not self.is_available:
            return None

        start = time.perf_counter()

        try:
            # Preprocess: resize to 224x224 and normalize
            import cv2
            resized = cv2.resize(frame, (self.input_width, self.input_height),
                                 interpolation=cv2.INTER_LINEAR)
            
            # Convert BGR to RGB, normalize to [0, 1] float32
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            input_data = rgb.astype(np.float32) / 255.0
            
            # Add batch dimension: (1, 224, 224, 3)
            input_data = np.expand_dims(input_data, axis=0)

            # Run inference
            input_params = InputVStreamParams.make(
                self._network_group,
                format_type=FormatType.FLOAT32
            )
            output_params = OutputVStreamParams.make(
                self._network_group,
                format_type=FormatType.FLOAT32
            )

            with self._network_group.activate():
                input_dict = {self._input_vstream_info[0].name: input_data}
                
                # Infer
                raw_output = self._network_group.infer(input_dict)
            
            # Extract depth map from output
            output_name = self._output_vstream_info[0].name
            depth_map = raw_output[output_name]
            
            # Remove batch dimension and squeeze to 2D
            depth_map = np.squeeze(depth_map)
            
            # fast_depth outputs inverse depth — higher = closer
            # Ensure it's float32 and positive
            depth_map = depth_map.astype(np.float32)
            depth_map = np.maximum(depth_map, 1e-6)

            elapsed_ms = (time.perf_counter() - start) * 1000
            self._latency_history.append(elapsed_ms)
            if len(self._latency_history) > 100:
                self._latency_history = self._latency_history[-50:]

            logger.debug(f"Depth inference: {elapsed_ms:.1f}ms")
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
            depth_map: 224x224 depth map from estimate()
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

        # Convert inverse depth to metric distance
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
        
        Detects:
        - Walls: Large uniform close-depth regions
        - Stairs down: Horizontal depth discontinuities (depth increases going down)
        - Stairs up: Depth decreases going down the frame
        - Curbs/steps: Single depth discontinuity at floor level
        - Drop-offs: Sudden depth increase in floor area
        - Approaching objects: Temporal depth decrease not covered by YOLO detections
        
        Args:
            depth_map: 224x224 depth map from estimate()
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

        # Convert inverse depth to distance map for analysis
        dist_map = self.scale_factor / (depth_map + 1e-6)
        dist_map = np.clip(dist_map, self.min_distance, self.max_distance)

        # ── 1. Wall detection ────────────────────────────────────────────
        hazards.extend(self._detect_walls(dist_map, dh, dw, now))

        # ── 2. Stairs / curb / step detection ────────────────────────────
        hazards.extend(self._detect_stairs_and_curbs(depth_map, dist_map, dh, dw, now))

        # ── 3. Drop-off detection ────────────────────────────────────────
        hazards.extend(self._detect_dropoff(depth_map, dist_map, dh, dw, now))

        # ── 4. Approaching object detection (temporal) ───────────────────
        if self._prev_depth_map is not None:
            hazards.extend(
                self._detect_approaching(depth_map, detections, frame_shape, dh, dw, now)
            )

        # Store for next frame comparison
        self._prev_depth_map = depth_map.copy()

        # Sort by severity (highest first)
        hazards.sort(key=lambda h: h.severity_rank, reverse=True)

        if hazards:
            logger.info(f"Hazards detected: {[(h.type.value, h.severity.value, f'{h.distance:.1f}m') for h in hazards]}")

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
        
        regions = [
            ("left", int(dw * 0.0), int(dw * 0.33)),
            ("ahead", int(dw * 0.25), int(dw * 0.75)),
            ("right", int(dw * 0.67), int(dw * 1.0)),
        ]

        for direction, x1, x2 in regions:
            # Analyze upper 70% of frame (walls are vertical, not floor)
            strip = dist_map[:int(dh * 0.7), x1:x2]
            if strip.size == 0:
                continue

            close_pixels = (strip < self.wall_threshold).sum()
            total_pixels = strip.size
            close_ratio = close_pixels / total_pixels

            if close_ratio > 0.60:
                median_dist = float(np.median(strip[strip < self.wall_threshold]))
                
                # Severity based on distance
                if median_dist < 0.8:
                    severity = HazardSeverity.CRITICAL
                elif median_dist < 1.2:
                    severity = HazardSeverity.WARNING
                else:
                    severity = HazardSeverity.INFO

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

        # Analyze bottom 40% of depth map (floor region)
        floor_start = int(dh * 0.6)
        floor_region = depth_map[floor_start:, :]

        if floor_region.shape[0] < 5:
            return hazards

        # Compute vertical gradient (how depth changes going down the image)
        # Positive gradient = depth increases going down = step-down / descending
        # Negative gradient = depth decreases going down = step-up / ascending
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
        mid_band = depth_map[int(dh * 0.6):int(dh * 0.7), center_start:center_end]
        # Bottom band (85-95% of frame height)
        bottom_band = depth_map[int(dh * 0.85):int(dh * 0.95), center_start:center_end]

        if mid_band.size == 0 or bottom_band.size == 0:
            return hazards

        mid_median = float(np.median(mid_band))
        bottom_median = float(np.median(bottom_band))

        # For inverse depth: drop-off means bottom has LOWER values (farther away)
        # Ratio: mid / bottom — high ratio means bottom is much farther
        if bottom_median > 1e-6:
            depth_ratio = mid_median / bottom_median
        else:
            depth_ratio = 0

        if depth_ratio > self.dropoff_threshold:
            # Ground falls away — drop-off detected
            drop_distance = self.scale_factor / (mid_median + 1e-6)
            drop_distance = max(self.min_distance, min(drop_distance, self.max_distance))

            severity = HazardSeverity.CRITICAL if drop_distance < 2.0 else HazardSeverity.WARNING

            hazards.append(Hazard(
                type=HazardType.DROPOFF,
                severity=severity,
                direction="ahead",
                distance=round(drop_distance, 2),
                confidence=round(min(1.0, depth_ratio / (self.dropoff_threshold * 2)), 2),
                bbox_region=(center_start, int(dh * 0.6), center_end, dh)
            ))
            self._mark_alerted("dropoff", now)

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
        Detect objects approaching the user that YOLO layers may have missed.
        
        Compares current depth map with previous frame's depth map.
        Regions with significant depth increase (closer) that don't overlap
        with existing YOLO detections are flagged.
        """
        hazards = []
        
        if self._is_on_cooldown("approaching_object", now):
            return hazards

        prev = self._prev_depth_map
        if prev is None or prev.shape != depth_map.shape:
            return hazards

        # Compute frame-over-frame depth change
        # For inverse depth: increase = object getting closer
        depth_diff = depth_map - prev

        # Only care about significant increases (approaching)
        approach_mask = depth_diff > self.approach_rate_threshold

        # Create exclusion mask for existing YOLO detections
        if detections and frame_shape:
            h, w = frame_shape[:2]
            exclusion = np.zeros((dh, dw), dtype=bool)
            for det in detections:
                bbox = det.get('bbox', det.get('bbox_normalized', []))
                if len(bbox) < 4:
                    continue
                # Map bbox to depth map coordinates
                x1 = int(bbox[0] / w * dw) if bbox[0] > 1 else int(bbox[0] * dw)
                y1 = int(bbox[1] / h * dh) if bbox[1] > 1 else int(bbox[1] * dh)
                x2 = int(bbox[2] / w * dw) if bbox[2] > 1 else int(bbox[2] * dw)
                y2 = int(bbox[3] / h * dh) if bbox[3] > 1 else int(bbox[3] * dh)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(dw, x2), min(dh, y2)
                # Add padding around detections
                pad = 5
                exclusion[max(0, y1-pad):min(dh, y2+pad), max(0, x1-pad):min(dw, x2+pad)] = True
            
            # Exclude already-detected regions
            approach_mask = approach_mask & ~exclusion

        # Check if any significant approaching region remains
        approach_ratio = approach_mask.sum() / approach_mask.size
        
        if approach_ratio > 0.03:  # At least 3% of frame is approaching
            # Find the centroid of the approaching region
            approaching_pixels = np.where(approach_mask)
            if len(approaching_pixels[0]) > 0:
                cy = int(np.mean(approaching_pixels[0]))
                cx = int(np.mean(approaching_pixels[1]))

                # Determine direction
                if cx < dw * 0.33:
                    direction = "left"
                elif cx > dw * 0.67:
                    direction = "right"
                else:
                    direction = "ahead"

                # Get distance
                dist = self.scale_factor / (float(depth_map[cy, cx]) + 1e-6)
                dist = max(self.min_distance, min(dist, self.max_distance))

                severity = HazardSeverity.WARNING if dist < 3.0 else HazardSeverity.INFO

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
                        int(np.max(approaching_pixels[0]))
                    )
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

    def cleanup(self):
        """Release Hailo device resources."""
        try:
            if self._network_group:
                self._network_group = None
            if self._vdevice:
                self._vdevice = None
            self._is_initialized = False
            logger.info("Hailo depth estimator cleaned up")
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
