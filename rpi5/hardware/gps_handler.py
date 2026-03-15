"""
GPS Handler - NEO-6M / GT-U7 UART Serial Reader

Reads NMEA sentences from a GPS module connected via UART and extracts
location (lat/lon), speed, heading, and fix quality.

HARDWARE:
- Module:  NEO-6M or GT-U7 GPS breakout
- RX pin:  GPIO 15 (UART RX, RPi5 Pin 10)  ← GPS TX
- TX pin:  GPIO 14 (UART TX, RPi5 Pin 8)   → GPS RX
- VCC:     3.3V (Pin 1)
- GND:     GND  (Pin 6)
- Device:  /dev/ttyAMA0 at 9600 baud

SETUP (RPi5):
    sudo raspi-config → Interface Options → Serial
        Login shell: No
        Hardware port: Yes
    pip install pyserial

Author: Haziq (@IRSPlays)
Date: January 2026
"""

import logging
import threading
import time
from typing import Optional, Tuple, NamedTuple

logger = logging.getLogger(__name__)

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    logger.info("ℹ️ pyserial not installed — GPS running in mock mode")


class GPSFix(NamedTuple):
    """Current GPS fix data."""
    latitude: float      # Decimal degrees (positive = North)
    longitude: float     # Decimal degrees (positive = East)
    altitude: float      # Metres above sea level (-1 if unknown)
    speed_kmh: float     # Ground speed in km/h
    heading: float       # True heading in degrees (0–360)
    fix_quality: int     # 0=no fix, 1=GPS, 2=DGPS
    satellites: int      # Number of satellites used


class GPSHandler:
    """
    NMEA GPS reader with background polling thread.

    Reads $GPRMC and $GPGGA sentences from a serial GPS module.
    Provides thread-safe access to the latest position data.

    Usage:
        gps = GPSHandler(port="/dev/ttyAMA0")
        gps.start()
        fix = gps.get_fix()
        if fix:
            print(f"Lat {fix.latitude}, Lon {fix.longitude}")
        gps.stop()
    """

    def __init__(
        self,
        port: str = "/dev/ttyAMA0",
        baudrate: int = 9600,
        timeout: float = 1.0,
        enabled: bool = True,
    ):
        """
        Initialise GPS handler.

        Args:
            port:     Serial device path (e.g. /dev/ttyAMA0)
            baudrate: Baud rate — NEO-6M default is 9600
            timeout:  Serial read timeout in seconds
            enabled:  Set False to disable (mock mode for laptop dev)
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._enabled = enabled and SERIAL_AVAILABLE

        self._serial: Optional["serial.Serial"] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Latest parsed fix (None until first valid sentence)
        self._fix: Optional[GPSFix] = None
        self._receiving = False  # True once any NMEA sentence is seen

        if not self._enabled:
            logger.info("ℹ️ GPS Handler in MOCK mode")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Open serial port and start background reader thread.

        Returns:
            True if started successfully, False otherwise.
        """
        if not self._enabled:
            logger.info("📍 GPS mock mode — start() is a no-op")
            return True

        try:
            self._serial = serial.Serial(
                self._port,
                baudrate=self._baudrate,
                timeout=self._timeout,
            )
            self._running = True
            self._thread = threading.Thread(
                target=self._reader_loop, daemon=True, name="gps-reader"
            )
            self._thread.start()
            logger.info(f"✅ GPS started on {self._port} @ {self._baudrate} baud")
            return True
        except Exception as exc:
            logger.error(f"❌ GPS failed to open {self._port}: {exc}")
            self._enabled = False
            return False

    def stop(self) -> None:
        """Stop the reader thread and close the serial port."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        logger.info("🛑 GPS stopped")

    def get_fix(self) -> Optional[GPSFix]:
        """
        Return the latest GPS fix, or None if no fix yet.

        Thread-safe.
        """
        with self._lock:
            return self._fix

    def get_location(self) -> Optional[Tuple[float, float]]:
        """
        Convenience method — returns (latitude, longitude) or None.

        Compatible with the Navigator.get_gps_location() stub.
        """
        fix = self.get_fix()
        if fix and fix.fix_quality > 0:
            return (fix.latitude, fix.longitude)
        return None

    @property
    def has_fix(self) -> bool:
        """True when a valid GPS fix is available."""
        fix = self.get_fix()
        return fix is not None and fix.fix_quality > 0

    @property
    def is_receiving(self) -> bool:
        """True when NMEA sentences are being received (even without fix)."""
        return self._receiving

    # ------------------------------------------------------------------
    # Background reader loop
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        """Background thread: continuously read NMEA lines and parse them."""
        logger.debug("GPS reader thread started")
        while self._running:
            try:
                raw = self._serial.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="replace").strip()
                if line.startswith("$"):
                    if not self._receiving:
                        self._receiving = True
                        logger.info("📡 GPS module is transmitting NMEA data")
                    self._parse_nmea(line)
            except serial.SerialException as exc:
                logger.error(f"❌ GPS serial error: {exc}")
                time.sleep(1.0)
            except Exception as exc:
                logger.debug(f"GPS parse error: {exc}")
        logger.debug("GPS reader thread stopped")

    # ------------------------------------------------------------------
    # NMEA parsing
    # ------------------------------------------------------------------

    def _parse_nmea(self, sentence: str) -> None:
        """Parse a single NMEA sentence and update internal fix state."""
        # Validate checksum
        if not self._checksum_ok(sentence):
            return

        parts = sentence.split(",")
        msg_type = parts[0].lstrip("$")

        try:
            if msg_type in ("GPRMC", "GNRMC"):
                self._parse_rmc(parts)
            elif msg_type in ("GPGGA", "GNGGA"):
                self._parse_gga(parts)
        except (IndexError, ValueError) as exc:
            logger.debug(f"NMEA parse error in {msg_type}: {exc}")

    def _parse_rmc(self, parts: list) -> None:
        """
        Parse $GPRMC — Recommended Minimum Specific GPS Data.
        Fields: time, status, lat, N/S, lon, E/W, speed(knots), course, date, ...
        """
        status = parts[2]  # A = active (valid), V = void (no fix)
        if status != "A":
            return  # No valid fix yet

        lat = self._nmea_to_decimal(parts[3], parts[4])
        lon = self._nmea_to_decimal(parts[5], parts[6])
        speed_knots = float(parts[7]) if parts[7] else 0.0
        heading = float(parts[8]) if parts[8] else 0.0

        with self._lock:
            old = self._fix
            self._fix = GPSFix(
                latitude=lat,
                longitude=lon,
                altitude=old.altitude if old else -1.0,
                speed_kmh=speed_knots * 1.852,
                heading=heading,
                fix_quality=old.fix_quality if old else 1,
                satellites=old.satellites if old else 0,
            )
        logger.debug(f"📍 GPS RMC: lat={lat:.6f}, lon={lon:.6f}, spd={speed_knots:.1f}kn")

    def _parse_gga(self, parts: list) -> None:
        """
        Parse $GPGGA — Global Positioning System Fix Data.
        Fields: time, lat, N/S, lon, E/W, fix_quality, satellites, hdop, altitude, ...
        """
        fix_quality = int(parts[6]) if parts[6] else 0
        satellites = int(parts[7]) if parts[7] else 0
        altitude = float(parts[9]) if parts[9] else -1.0

        if fix_quality == 0:
            logger.debug("📍 GPS GGA: no fix")
            with self._lock:
                if self._fix:
                    # Keep position but downgrade quality
                    self._fix = self._fix._replace(
                        fix_quality=0, satellites=satellites
                    )
            return

        lat = self._nmea_to_decimal(parts[2], parts[3])
        lon = self._nmea_to_decimal(parts[4], parts[5])

        with self._lock:
            old = self._fix
            self._fix = GPSFix(
                latitude=lat,
                longitude=lon,
                altitude=altitude,
                speed_kmh=old.speed_kmh if old else 0.0,
                heading=old.heading if old else 0.0,
                fix_quality=fix_quality,
                satellites=satellites,
            )
        logger.debug(
            f"📍 GPS GGA: lat={lat:.6f}, lon={lon:.6f}, alt={altitude:.1f}m, "
            f"qual={fix_quality}, sats={satellites}"
        )

    @staticmethod
    def _nmea_to_decimal(raw: str, direction: str) -> float:
        """
        Convert NMEA lat/lon format (DDDMM.MMMM) to decimal degrees.

        Args:
            raw:       e.g. "4807.038" (DDDMM.MMMM)
            direction: "N", "S", "E", or "W"

        Returns:
            Decimal degrees, negative for South/West.
        """
        if not raw:
            return 0.0
        dot = raw.index(".")
        degrees = float(raw[: dot - 2])
        minutes = float(raw[dot - 2:])
        decimal = degrees + minutes / 60.0
        if direction in ("S", "W"):
            decimal = -decimal
        return decimal

    @staticmethod
    def _checksum_ok(sentence: str) -> bool:
        """Validate NMEA sentence checksum."""
        try:
            if "*" not in sentence:
                return True  # No checksum field — accept anyway
            data, checksum_hex = sentence[1:].rsplit("*", 1)
            expected = int(checksum_hex[:2], 16)
            computed = 0
            for char in data:
                computed ^= ord(char)
            return computed == expected
        except (ValueError, IndexError):
            return False
