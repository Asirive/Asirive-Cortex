"""
IMU Handler - BNO055 9-Axis Inertial Measurement Unit

Reads orientation, acceleration, gyroscope, and magnetometer data from
a BNO055 sensor via I2C. Uses the sensor's built-in fusion algorithm
to produce stable Euler angles and quaternions.

HARDWARE:
- Sensor: BNO055 (GY-BNO055 breakout or Adafruit BNO055)
- SDA:    GPIO 2 (I2C SDA, RPi5 Pin 3)
- SCL:    GPIO 3 (I2C SCL, RPi5 Pin 5)
- VCC:    3.3V (Pin 1)
- GND:    GND  (Pin 6)
- ADR/ADDR pin: GND → I2C address 0x28 (default)
                3.3V → I2C address 0x29

SETUP (RPi5):
    sudo raspi-config → Interface Options → I2C → Yes
    pip install adafruit-circuitpython-bno055 adafruit-blinka smbus2

QUICK TEST:
    i2cdetect -y 1   # Should show "28" at 0x28

Author: Haziq (@IRSPlays)
Date: January 2026
"""

import logging
import math
import threading
import time
from typing import Optional, NamedTuple

logger = logging.getLogger(__name__)

# Adafruit CircuitPython driver (preferred — handles sensor fusion mode setup)
try:
    import board
    import busio
    import adafruit_bno055
    BNO055_AVAILABLE = True
except ImportError:
    BNO055_AVAILABLE = False
    logger.info("ℹ️ adafruit-circuitpython-bno055 not installed — IMU in mock mode")


class IMUReading(NamedTuple):
    """A single IMU reading snapshot."""
    # Euler angles (degrees) from BNO055 internal fusion
    heading: float          # 0–360 degrees (compass heading)
    roll: float             # -180 to +180 degrees
    pitch: float            # -90  to +90  degrees
    # Quaternion (unit quaternion from sensor fusion)
    quat_w: float
    quat_x: float
    quat_y: float
    quat_z: float
    # Raw sensor data (SI units)
    accel_x: float          # m/s²
    accel_y: float          # m/s²
    accel_z: float          # m/s²
    gyro_x: float           # deg/s
    gyro_y: float           # deg/s
    gyro_z: float           # deg/s
    mag_x: float            # µT (microtesla)
    mag_y: float            # µT
    mag_z: float            # µT
    # Calibration status (0=uncalibrated … 3=fully calibrated)
    cal_system: int
    cal_gyro: int
    cal_accel: int
    cal_mag: int


# ── Axis-remap presets for different physical mountings ──
# Each preset is (x_remap, y_remap, z_remap, x_sign, y_sign, z_sign)
# where *_remap is AXIS_REMAP_X/Y/Z and *_sign is AXIS_REMAP_POSITIVE/NEGATIVE.
MOUNTING_PRESETS = {
    # Default: chip face-up, Y pointing forward
    "default": None,  # no remap needed
    # Right glasses temple: chip face-DOWN, connectors pointing RIGHT
    "right_temple_down": (1, 0, 2, 0, 0, 1),  # X<-Y+, Y<-X+, Z<-Z-
}


class IMUHandler:
    """
    BNO055 9-axis IMU reader with background polling thread.

    Operates the BNO055 in NDOF (Nine Degrees Of Freedom) mode which
    uses the sensor's internal Kalman-filter fusion to produce stable
    orientation data.

    Usage:
        imu = IMUHandler(i2c_address=0x29, mounting='right_temple_down')
        imu.start()
        reading = imu.get_reading()
        if reading:
            print(f"Heading: {reading.heading:.1f}°")
        imu.stop()
    """

    # Thresholds for event detection
    FALL_ACCEL_THRESHOLD = 2.0   # m/s² total acceleration (free-fall is ~0)
    IMPACT_ACCEL_THRESHOLD = 25.0  # m/s² (sudden impact)

    def __init__(
        self,
        i2c_address: int = 0x28,
        poll_hz: float = 25.0,
        enabled: bool = True,
        mounting: str = "default",
    ):
        """
        Initialise IMU handler.

        Args:
            i2c_address: I2C address of BNO055 (0x28 default, 0x29 if ADR pin high)
            poll_hz:     Polling frequency in Hz (BNO055 outputs up to 100Hz)
            enabled:     Set False to disable (mock mode for laptop dev)
            mounting:    Physical mounting preset ('default' or 'right_temple_down')
        """
        self._address = i2c_address
        self._poll_interval = 1.0 / poll_hz
        self._enabled = enabled and BNO055_AVAILABLE
        self._mounting = mounting

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._reading: Optional[IMUReading] = None

        # Event callbacks (optional)
        self.on_fall_detected = None       # callable() — called on free-fall
        self.on_impact_detected = None     # callable(accel_mag: float)
        self._start_time = 0.0             # suppress false falls during init

        self._sensor = None  # adafruit_bno055.BNO055_I2C instance

        if not self._enabled:
            logger.info("ℹ️ IMU Handler in MOCK mode")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Initialise I2C, put sensor in NDOF mode, start polling thread.

        Returns:
            True on success, False on failure.
        """
        if not self._enabled:
            logger.info("🧭 IMU mock mode — start() is a no-op")
            return True

        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self._sensor = adafruit_bno055.BNO055_I2C(i2c, address=self._address)

            # Apply axis remap for physical mounting BEFORE switching to NDOF
            preset = MOUNTING_PRESETS.get(self._mounting)
            if preset:
                self._sensor.mode = adafruit_bno055.CONFIG_MODE
                time.sleep(0.025)  # BNO055 needs 19ms to switch modes
                # H8 fix: the Adafruit library's `axis_remap` setter
                # now type-checks for the AXIS_REMAP_CONFIG namedtuple
                # in current releases. Passing a raw 6-tuple silently
                # raised inside the setter, the exception was caught
                # by our outer try/except, and _enabled was flipped
                # to False — the glasses-mounted IMU has never worked.
                # Wrap the preset in the namedtuple the library expects.
                if hasattr(adafruit_bno055, "AXIS_REMAP_CONFIG"):
                    self._sensor.axis_remap = adafruit_bno055.AXIS_REMAP_CONFIG(*preset)
                else:
                    # Older library versions accept a plain tuple.
                    self._sensor.axis_remap = preset
                logger.info(f"🧭 Axis remap applied for '{self._mounting}' mounting")

            self._sensor.mode = adafruit_bno055.NDOF_MODE
            logger.info(
                f"✅ BNO055 initialised at I2C 0x{self._address:02X} "
                f"(NDOF mode, {1/self._poll_interval:.0f}Hz, mount={self._mounting})"
            )
        except Exception as exc:
            logger.error(f"❌ BNO055 init failed: {exc}")
            self._enabled = False
            return False

        self._running = True
        self._start_time = time.time()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="imu-poller"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop the polling thread and release I2C resources."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        # Release I2C bus if the driver exposes deinit
        if self._sensor is not None:
            try:
                if hasattr(self._sensor, 'i2c_device') and hasattr(self._sensor.i2c_device, 'i2c'):
                    self._sensor.i2c_device.i2c.deinit()
            except Exception:
                pass  # Best-effort cleanup
            self._sensor = None
        logger.info("🛑 IMU stopped")

    def get_reading(self) -> Optional[IMUReading]:
        """
        Return the most recent IMU reading. Thread-safe.

        Returns:
            IMUReading namedtuple, or None if no data yet.
        """
        with self._lock:
            return self._reading

    def get_heading(self) -> Optional[float]:
        """
        Convenience: return magnetic heading in degrees (0–360).

        Returns None if no data or sensor not calibrated.
        """
        r = self.get_reading()
        if r and r.cal_mag >= 1:  # At least partial magnetometer calibration
            return r.heading
        return None

    def set_gyro_only(self) -> bool:
        """
        Switch BNO055 to gyro-only mode (no magnetometer).
        
        Use indoors where metal structures cause magnetic interference.
        Heading will drift over time but avoids false readings.
        Returns True on success.
        """
        if not self._sensor or not self._enabled:
            return False
        try:
            self._sensor.mode = adafruit_bno055.GYROONLY_MODE
            logger.info("🧭 IMU switched to GYRO-ONLY mode (indoor)")
            return True
        except Exception as e:
            logger.warning(f"Failed to set gyro-only mode: {e}")
            return False

    def set_ndof_mode(self) -> bool:
        """
        Switch BNO055 back to NDOF mode (full 9-axis fusion).
        
        Use outdoors where magnetometer readings are reliable.
        Returns True on success.
        """
        if not self._sensor or not self._enabled:
            return False
        try:
            self._sensor.mode = adafruit_bno055.NDOF_MODE
            logger.info("🧭 IMU switched to NDOF mode (outdoor)")
            return True
        except Exception as e:
            logger.warning(f"Failed to set NDOF mode: {e}")
            return False

    @property
    def is_calibrated(self) -> bool:
        """True when system calibration is ≥ 2 (good)."""
        r = self.get_reading()
        return r is not None and r.cal_system >= 2

    # ------------------------------------------------------------------
    # Background polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Continuously poll sensor at configured frequency."""
        logger.debug("IMU polling thread started")
        _imu_err_count = 0
        # H9 fix: previous code did a flat 0.5s sleep on every error
        # and never recovered fast — persistent I2C glitches would
        # permanently drop the poll rate to ~2Hz and fall detection
        # became useless. Use exponential backoff that decays back
        # to the configured poll_interval on consecutive successes.
        backoff = 0.0
        while self._running:
            try:
                self._read_sensor()
                if _imu_err_count > 0:
                    logger.info(
                        f"IMU recovered after {_imu_err_count} errors"
                    )
                _imu_err_count = 0
                backoff = 0.0  # Reset on success
            except Exception as exc:
                _imu_err_count += 1
                if _imu_err_count <= 3 or _imu_err_count % 50 == 0:
                    logger.warning(f"IMU read error (#{_imu_err_count}): {exc}")
                # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, ... capped
                # at 0.5s. This gives the I2C bus room to settle without
                # permanently throttling the loop.
                backoff = min(0.5, max(0.1, 0.1 * (2 ** min(_imu_err_count, 4))))
            # Sleep for the configured poll interval, plus any error
            # backoff. The backoff is added (not substituted) so we
            # still respect the 25Hz target on success.
            time.sleep(self._poll_interval + backoff)
        logger.debug("IMU polling thread stopped")

    def _read_sensor(self) -> None:
        """Read one sample from the BNO055 and store it."""
        # Euler angles — may be None if sensor hasn't fused yet
        euler = self._sensor.euler         # (heading, roll, pitch) in degrees
        quat = self._sensor.quaternion     # (w, x, y, z) unit quaternion
        accel = self._sensor.acceleration  # (x, y, z) m/s²
        gyro = self._sensor.gyro           # (x, y, z) deg/s
        mag = self._sensor.magnetic        # (x, y, z) µT
        cal = self._sensor.calibration_status  # (sys, gyro, accel, mag) 0–3

        # Guard: any read can return None before sensor warms up
        heading = euler[0] if euler and euler[0] is not None else 0.0
        roll    = euler[1] if euler and euler[1] is not None else 0.0
        pitch   = euler[2] if euler and euler[2] is not None else 0.0

        qw = quat[0] if quat and quat[0] is not None else 1.0
        qx = quat[1] if quat and quat[1] is not None else 0.0
        qy = quat[2] if quat and quat[2] is not None else 0.0
        qz = quat[3] if quat and quat[3] is not None else 0.0

        ax = accel[0] if accel and accel[0] is not None else 0.0
        ay = accel[1] if accel and accel[1] is not None else 0.0
        az = accel[2] if accel and accel[2] is not None else 0.0

        gx = gyro[0] if gyro and gyro[0] is not None else 0.0
        gy = gyro[1] if gyro and gyro[1] is not None else 0.0
        gz = gyro[2] if gyro and gyro[2] is not None else 0.0

        mx = mag[0] if mag and mag[0] is not None else 0.0
        my = mag[1] if mag and mag[1] is not None else 0.0
        mz = mag[2] if mag and mag[2] is not None else 0.0

        cal_sys, cal_gyro, cal_accel, cal_mag = cal if cal else (0, 0, 0, 0)

        reading = IMUReading(
            heading=heading, roll=roll, pitch=pitch,
            quat_w=qw, quat_x=qx, quat_y=qy, quat_z=qz,
            accel_x=ax, accel_y=ay, accel_z=az,
            gyro_x=gx, gyro_y=gy, gyro_z=gz,
            mag_x=mx, mag_y=my, mag_z=mz,
            cal_system=cal_sys, cal_gyro=cal_gyro,
            cal_accel=cal_accel, cal_mag=cal_mag,
        )

        with self._lock:
            self._reading = reading

        self._check_events(ax, ay, az)

    def _check_events(self, ax: float, ay: float, az: float) -> None:
        """Detect fall / impact events and fire callbacks."""
        # Skip first 5s after start — sensor reads zeros during calibration
        if time.time() - self._start_time < 5.0:
            return

        # M58 fix: previous guard only skipped the exact (0,0,0) tuple.
        # A real I2C error (Errno 121) can return near-zero on all axes
        # (e.g. (0.001, 0.0, -0.0007)) which still passed the check and
        # produced false "free-fall" events. Use a strict band that
        # covers sensor-internal noise + a small epsilon for floating
        # point fuzz, and a sanity-check that magnitude is plausible.
        EPS = 0.5  # m/s² — anything under this is sensor noise, not motion
        if -EPS < ax < EPS and -EPS < ay < EPS and -EPS < az < EPS:
            return

        total = math.sqrt(ax * ax + ay * ay + az * az)
        # Plausibility check: BNO055 accel magnitude should be in
        # [~7 m/s² true free-fall + 0, ~30 m/s² hard impact] under
        # normal use. Values outside that band are bogus.
        if total < 0.5 or total > 50.0:
            return

        if total < self.FALL_ACCEL_THRESHOLD and self.on_fall_detected:
            try:
                self.on_fall_detected()
            except Exception as exc:
                logger.error(f"on_fall_detected callback error: {exc}")

        if total > self.IMPACT_ACCEL_THRESHOLD and self.on_impact_detected:
            try:
                self.on_impact_detected(total)
            except Exception as exc:
                logger.error(f"on_impact_detected callback error: {exc}")
