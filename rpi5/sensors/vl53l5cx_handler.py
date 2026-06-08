"""
VL53L5CX ToF Depth Sensor Handler
==================================

8×8 multi-zone Time-of-Flight depth sensor for close-range obstacle detection.
Mounts on the glasses bridge, pointing slightly downward (~10°).

Produces directional hazards (wall, drop-off, stairs) compatible with
SafetyMonitor.process_frame(). Replaces Hailo monocular depth for
close-range alerts (<2m), freeing the Hailo NPU for YOLO-only inference.

Hardware:
- VL53L5CX breakout (I2C, 3.3V)
- RPi5 GPIO: SDA=Pin3(GPIO2), SCL=Pin5(GPIO3), VCC=Pin1(3.3V), GND=Pin6

Software:
- Try/except import of official `vl53l5cx` Python driver
- Falls back to mock/simulation mode if driver unavailable
- 8×8 grid analyzed into left/center/right + ground hazards

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — IVP 2026
Date: May 2026
"""

import logging
import time
import threading
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hazard types compatible with SafetyMonitor (mirrors hailo_depth.py)
# ---------------------------------------------------------------------------

class HazardType(Enum):
    WALL = "wall"
    STAIRS_DOWN = "stairs_down"
    STAIRS_UP = "stairs_up"
    CURB = "curb"
    DROPOFF = "dropoff"
    APPROACHING_OBJECT = "approaching_object"


class HazardSeverity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Hazard:
    type: HazardType
    severity: HazardSeverity
    direction: str              # "left", "ahead", "right", "below"
    distance: float             # Approximate metres
    confidence: float           # 0.0 - 1.0
    bbox_region: Tuple[int, int, int, int] = (0, 0, 0, 0)  # unused for ToF


# ---------------------------------------------------------------------------
# VL53L5CX Handler
# ---------------------------------------------------------------------------

class VL53L5CXHandler:
    """
    Interface to the VL53L5CX 8×8 ToF sensor.

    Modes:
        - REAL:  Uses official vl53l5cx driver over I2C.
        - MOCK:  Simulates an 8×8 grid for development without hardware.

    Call update() in the main loop at ~15 Hz. It returns a list of Hazard
    objects ready for SafetyMonitor.process_frame(hazards=...).
    """

    # 8×8 zone mapping to direction (row-major, sensor native)
    # Rows 0-2 = upper (sky / overhead), 3-5 = center (ahead), 6-7 = lower (ground)
    # Cols 0-2 = left, 3-4 = center, 5-7 = right
    ZONE_DIRECTIONS = [
        ["left",  "left",  "left",  "ahead", "ahead", "right", "right", "right"],  # row 0
        ["left",  "left",  "left",  "ahead", "ahead", "right", "right", "right"],  # row 1
        ["left",  "left",  "left",  "ahead", "ahead", "right", "right", "right"],  # row 2
        ["left",  "left",  "left",  "ahead", "ahead", "right", "right", "right"],  # row 3
        ["left",  "left",  "left",  "ahead", "ahead", "right", "right", "right"],  # row 4
        ["left",  "left",  "left",  "ahead", "ahead", "right", "right", "right"],  # row 5
        ["left",  "left",  "left",  "ahead", "ahead", "right", "right", "right"],  # row 6
        ["left",  "left",  "left",  "ahead", "ahead", "right", "right", "right"],  # row 7
    ]

    # Distance thresholds (metres)
    WALL_THRESHOLD = 1.5          # Average distance below this = wall ahead
    WALL_CRITICAL = 0.6           # Below this = critical (collision imminent)
    DROPOFF_THRESHOLD = 0.3       # Bottom-row drop in distance = drop-off
    GROUND_MAX = 1.0              # If ground is >1.0m away, likely a drop/stair

    def __init__(
        self,
        i2c_bus: int = 1,
        i2c_address: int = 0x52,
        mock: bool = False,
        mock_scenario: str = "clear",  # "clear", "wall", "dropoff", "mixed"
    ):
        """
        Args:
            i2c_bus: RPi5 I2C bus (default 1).
            i2c_address: VL53L5CX I2C address (0x52 after initialization).
            mock: Force simulation mode (for development without hardware).
            mock_scenario: Which synthetic scene to generate in mock mode.
        """
        self._i2c_bus = i2c_bus
        self._i2c_address = i2c_address
        self._mock = mock
        self._mock_scenario = mock_scenario
        self._driver = None
        self._is_available = False
        self._lock = threading.Lock()

        # Latest depth grid (8×8, mm)
        self.depth_mm = np.full((8, 8), -1, dtype=np.int16)
        self._last_update = 0.0
        self._update_count = 0

        # Try to initialize real driver
        if not self._mock:
            self._init_real_driver()
        else:
            logger.info("🎭 VL53L5CX running in MOCK mode (scenario: %s)", mock_scenario)
            self._is_available = True

    # ------------------------------------------------------------------
    # Driver initialization
    # ------------------------------------------------------------------

    def _init_real_driver(self):
        """Attempt to load and initialize the official VL53L5CX driver."""
        try:
            # Official STM driver package (pip install vl53l5cx)
            import vl53l5cx
            logger.info("🔍 Initializing VL53L5CX on I2C bus %d, addr 0x%02x...",
                        self._i2c_bus, self._i2c_address)

            self._driver = vl53l5cx.VL53L5CX(
                i2c_bus=self._i2c_bus,
                i2c_address=self._i2c_address,
            )
            self._driver.init()
            self._driver.set_resolution(8 * 8)
            self._driver.set_ranging_frequency_hz(15)
            self._driver.start_ranging()

            self._is_available = True
            logger.info("✅ VL53L5CX initialized — 8×8 @ 15 Hz")

        except ImportError:
            logger.warning(
                "⚠️ vl53l5cx Python driver not installed. "
                "Install: pip install vl53l5cx\n"
                "Falling back to MOCK mode."
            )
            self._mock = True
            self._is_available = True

        except Exception as e:
            logger.error("❌ VL53L5CX init failed: %s", e)
            logger.warning("Falling back to MOCK mode.")
            self._mock = True
            self._is_available = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self) -> List[Hazard]:
        """
        Fetch latest 8×8 depth data and produce hazards.

        Returns:
            List of Hazard objects for SafetyMonitor.
        """
        with self._lock:
            if not self._is_available:
                return []

            if self._mock:
                self._mock_update()
            else:
                self._real_update()

            self._last_update = time.time()
            self._update_count += 1

            return self._analyze_grid()

    def get_depth_mm(self) -> np.ndarray:
        """Get the latest 8×8 depth grid in millimetres (-1 = invalid)."""
        with self._lock:
            return self.depth_mm.copy()

    @property
    def is_available(self) -> bool:
        """Return True if the sensor is initialized and ready."""
        return self._is_available

    @property
    def is_mock(self) -> bool:
        """Return True if running in mock/simulation mode (no real hardware).

        Callers should treat mock data as synthetic — never use it to
        short-circuit a more authoritative source (e.g. Hailo depth).
        """
        return bool(self._mock)

    def get_context_string(self) -> str:
        """Short status string for dashboard / logging."""
        with self._lock:
            valid = np.sum(self.depth_mm > 0)
            avg = float(np.mean(self.depth_mm[self.depth_mm > 0])) if valid else 0.0
            return f"[ToF] zones={valid}/64 avg={avg/1000:.2f}m"

    # ------------------------------------------------------------------
    # Real driver path
    # ------------------------------------------------------------------

    def _real_update(self):
        """Read from actual VL53L5CX sensor."""
        try:
            data = self._driver.get_data()
            # data.distance_mm is expected to be an 8×8 array or flat 64
            distances = np.array(data.distance_mm, dtype=np.int16).reshape(8, 8)
            # VL53L5CX returns 0 for invalid; map to -1 for consistency
            distances[distances == 0] = -1
            self.depth_mm = distances
        except Exception as e:
            logger.debug("VL53L5CX read error: %s", e)

    # ------------------------------------------------------------------
    # Mock driver path
    # ------------------------------------------------------------------

    def _mock_update(self):
        """Generate synthetic 8×8 depth data for development."""
        t = time.time()
        grid = np.full((8, 8), 4000, dtype=np.int16)  # default 4m clear

        if self._mock_scenario == "wall":
            # Wall closing in from ahead (center columns)
            for r in range(8):
                for c in range(3, 5):
                    grid[r, c] = int(600 + 200 * np.sin(t * 2))

        elif self._mock_scenario == "dropoff":
            # Ground falls away at bottom rows
            for r in range(6, 8):
                for c in range(8):
                    grid[r, c] = 5000  # out of range / no ground
            # Top rows still see ground at 0.8m
            for r in range(0, 5):
                for c in range(8):
                    grid[r, c] = 800

        elif self._mock_scenario == "mixed":
            # Left wall close, right side clear, center ahead moderate
            for r in range(8):
                for c in range(0, 2):
                    grid[r, c] = 500
                for c in range(5, 8):
                    grid[r, c] = 3500
                for c in range(2, 5):
                    grid[r, c] = 1500

        # Add noise
        noise = np.random.normal(0, 30, (8, 8)).astype(np.int16)
        grid = np.clip(grid + noise, 100, 8000).astype(np.int16)
        self.depth_mm = grid

    # ------------------------------------------------------------------
    # Grid analysis → Hazards
    # ------------------------------------------------------------------

    def _analyze_grid(self) -> List[Hazard]:
        """
        Convert 8×8 depth grid into directional hazards.

        Heuristics:
        - Center zones (cols 2-5, rows 2-5) averaged → "wall ahead"
        - Bottom zones (rows 6-7) averaged → "drop-off" if far / absent
        - Left/right asymmetry → "wall left" / "wall right"
        """
        grid = self.depth_mm
        hazards: List[Hazard] = []

        # Ignore invalid cells
        valid = grid > 0
        if not np.any(valid):
            return hazards

        # ── 1. Ground / Drop-off detection (bottom 2 rows) ──
        bottom = grid[6:8, :]
        bottom_valid = bottom[bottom > 0]
        if len(bottom_valid) > 0:
            bottom_avg = float(np.mean(bottom_valid))
            if bottom_avg > self.GROUND_MAX * 1000:
                # Ground is far away → likely stairs down or drop-off
                hazards.append(Hazard(
                    type=HazardType.DROPOFF,
                    severity=HazardSeverity.CRITICAL,
                    direction="ahead",
                    distance=bottom_avg / 1000.0,
                    confidence=0.85,
                ))
            elif bottom_avg < self.DROPOFF_THRESHOLD * 1000:
                # Unexpectedly close ground → possible curb / step up
                pass  # normal walking; don't alert

        # ── 2. Center "ahead" wall detection (rows 2-5, cols 2-5) ──
        center = grid[2:6, 2:6]
        center_valid = center[center > 0]
        if len(center_valid) >= 4:
            center_avg = float(np.mean(center_valid))
            center_min = float(np.min(center_valid))

            if center_min < self.WALL_CRITICAL * 1000:
                hazards.append(Hazard(
                    type=HazardType.WALL,
                    severity=HazardSeverity.CRITICAL,
                    direction="ahead",
                    distance=center_min / 1000.0,
                    confidence=0.9,
                ))
            elif center_avg < self.WALL_THRESHOLD * 1000:
                hazards.append(Hazard(
                    type=HazardType.WALL,
                    severity=HazardSeverity.WARNING,
                    direction="ahead",
                    distance=center_avg / 1000.0,
                    confidence=0.75,
                ))

        # ── 3. Left / Right wall detection ──
        left = grid[2:6, 0:2]
        right = grid[2:6, 6:8]
        left_valid = left[left > 0]
        right_valid = right[right > 0]

        if len(left_valid) >= 2:
            left_avg = float(np.mean(left_valid))
            if left_avg < self.WALL_THRESHOLD * 1000:
                hazards.append(Hazard(
                    type=HazardType.WALL,
                    severity=HazardSeverity.WARNING,
                    direction="left",
                    distance=left_avg / 1000.0,
                    confidence=0.7,
                ))

        if len(right_valid) >= 2:
            right_avg = float(np.mean(right_valid))
            if right_avg < self.WALL_THRESHOLD * 1000:
                hazards.append(Hazard(
                    type=HazardType.WALL,
                    severity=HazardSeverity.WARNING,
                    direction="right",
                    distance=right_avg / 1000.0,
                    confidence=0.7,
                ))

        return hazards

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def stop(self):
        """Stop ranging and release resources."""
        with self._lock:
            if self._driver:
                try:
                    self._driver.stop_ranging()
                    logger.info("⏹️ VL53L5CX ranging stopped")
                except Exception as e:
                    logger.debug("VL53L5CX stop error: %s", e)

    def __del__(self):
        self.stop()


# ---------------------------------------------------------------------------
# Example usage / self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    handler = VL53L5CXHandler(mock=True, mock_scenario="mixed")
    logger.info("Running 5-second mock test...")

    for _ in range(30):
        hazards = handler.update()
        ctx = handler.get_context_string()
        if hazards:
            for h in hazards:
                logger.info("  🚨 %s %s at %.1fm (conf=%.2f)",
                            h.severity.value.upper(), h.type.value,
                            h.distance, h.confidence)
        else:
            logger.info("  ✅ %s", ctx)
        time.sleep(0.166)  # ~6 Hz

    handler.stop()
    logger.info("Test complete.")
