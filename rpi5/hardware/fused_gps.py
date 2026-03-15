"""
Fused GPS Handler - M8U Hardware + Phone Browser Fallback

Drop-in replacement for GPSHandler that fuses two GPS sources:
  1. NEO-M8U  (UART, primary — hardware GPS with UDR)
  2. Phone    (WebSocket, fallback — browser Geolocation API)

Selection logic:
  - M8U preferred when fix_quality > 0 AND satellites >= 4
  - Phone used as fallback when M8U has no fix
  - Logs which source is active on every switch

Exposes the EXACT same API as GPSHandler so it's a transparent swap.

Author: Haziq (@IRSPlays)
Date: January 2026
"""

import logging
import time
from typing import Optional, Tuple

from rpi5.hardware.gps_handler import GPSFix, GPSHandler
from rpi5.hardware.phone_gps import PhoneGPSReceiver

logger = logging.getLogger(__name__)


class FusedGPSHandler:
    """
    Fused GPS that transparently merges M8U hardware + phone browser GPS.

    API is identical to GPSHandler:
        start() → bool
        stop()
        get_fix()       → Optional[GPSFix]
        get_location()  → Optional[Tuple[float, float]]
        has_fix         (property)
        is_receiving    (property)

    Usage:
        fused = FusedGPSHandler(
            gps_handler=GPSHandler(port="/dev/ttyAMA0"),
            phone_gps_port=8766,
        )
        fused.start()
        fix = fused.get_fix()   # Best available source
        fused.stop()
    """

    def __init__(
        self,
        gps_handler: Optional[GPSHandler] = None,
        phone_gps_port: int = 8766,
        phone_gps_enabled: bool = True,
    ):
        self._hw = gps_handler  # Hardware M8U (can be None)
        self._phone = PhoneGPSReceiver(port=phone_gps_port) if phone_gps_enabled else None
        self._active_source: Optional[str] = None  # "m8u" | "phone" | None

    # ------------------------------------------------------------------
    # Public API  (matches GPSHandler exactly)
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start both GPS sources."""
        hw_ok = False
        phone_ok = False

        if self._hw:
            hw_ok = self._hw.start()
            if hw_ok:
                logger.info("📡 Fused GPS: M8U hardware started")

        if self._phone:
            phone_ok = self._phone.start()
            if phone_ok:
                logger.info("📱 Fused GPS: Phone GPS server started")

        return hw_ok or phone_ok

    def stop(self) -> None:
        """Stop both GPS sources."""
        if self._hw:
            self._hw.stop()
        if self._phone:
            self._phone.stop()
        logger.info("🛑 Fused GPS: stopped all sources")

    def get_fix(self) -> Optional[GPSFix]:
        """
        Get the best available GPS fix.

        Priority:
          1. M8U hardware (if fix_quality > 0 AND satellites >= 4)
          2. Phone GPS (fallback)
          3. None
        """
        # Try hardware first
        hw_fix = self._hw.get_fix() if self._hw else None
        if hw_fix and hw_fix.fix_quality > 0 and hw_fix.satellites >= 4:
            self._set_source("m8u")
            return hw_fix

        # Fallback to phone (accept any fix with valid coordinates)
        phone_fix = self._phone.get_fix() if self._phone else None
        if phone_fix and (phone_fix.latitude != 0.0 or phone_fix.longitude != 0.0):
            self._set_source("phone")
            return phone_fix

        # If hardware has any fix at all (even weak), use it
        if hw_fix and hw_fix.fix_quality > 0:
            self._set_source("m8u")
            return hw_fix

        self._set_source(None)
        return None

    def get_location(self) -> Optional[Tuple[float, float]]:
        """Get (latitude, longitude) from best available source."""
        fix = self.get_fix()
        if fix:
            return (fix.latitude, fix.longitude)
        return None

    @property
    def has_fix(self) -> bool:
        """True if any GPS source has a fix."""
        return self.get_fix() is not None

    @property
    def is_receiving(self) -> bool:
        """True if any GPS source is receiving data."""
        hw_rx = self._hw.is_receiving if self._hw else False
        phone_rx = (self._phone.is_connected if self._phone else False)
        return hw_rx or phone_rx

    @property
    def active_source(self) -> Optional[str]:
        """Currently active GPS source: 'm8u', 'phone', or None."""
        return self._active_source

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_source(self, source: Optional[str]) -> None:
        """Log when the active GPS source changes."""
        if source != self._active_source:
            old = self._active_source or "none"
            new = source or "none"
            if source:
                logger.info(f"📍 GPS source: {old} → {new}")
            else:
                logger.debug(f"📍 GPS source: {old} → {new}")
            self._active_source = source
