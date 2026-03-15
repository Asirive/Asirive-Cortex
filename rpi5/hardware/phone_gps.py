"""
Phone GPS Receiver - Browser Geolocation → WebSocket → RPi5

Runs a lightweight WebSocket server that receives GPS coordinates from
a phone's browser (Geolocation API).  The phone connects by opening
http://<rpi5-ip>:8766/gps in any mobile browser.

Data flows:
    Phone Browser → WebSocket JSON → PhoneGPSReceiver → GPSFix

Author: Haziq (@IRSPlays)
Date: January 2026
"""

import asyncio
import json
import logging
import os
import ssl
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import websockets
    import websockets.server
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("⚠️ websockets not installed — phone GPS unavailable")

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logger.info("ℹ️ aiohttp not installed — phone GPS HTML served via websockets only")

# Re-use the same GPSFix NamedTuple from gps_handler
from rpi5.hardware.gps_handler import GPSFix


class PhoneGPSReceiver:
    """
    WebSocket server that receives GPS from a phone browser.

    The phone opens a simple HTML page that uses navigator.geolocation
    and streams {lat, lng, alt, speed, heading, accuracy} at ~1 Hz.

    Usage:
        receiver = PhoneGPSReceiver(port=8766)
        receiver.start()
        fix = receiver.get_fix()    # Returns Optional[GPSFix]
        receiver.stop()
    """

    # How old a fix can be before we consider it stale (seconds)
    STALE_THRESHOLD = 10.0

    def __init__(self, port: int = 8766):
        self._port = port
        self._lock = threading.Lock()
        self._fix: Optional[GPSFix] = None
        self._last_update: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected_phones: int = 0

        # Path to the HTML file served to phones
        self._html_path = Path(__file__).parent.parent / "static" / "phone_gps.html"

        # SSL cert directory (auto-generated self-signed)
        self._cert_dir = Path(__file__).parent.parent / "config" / "ssl"
        self._cert_file = self._cert_dir / "phone_gps.pem"
        self._key_file = self._cert_dir / "phone_gps-key.pem"

    # ------------------------------------------------------------------
    # Public API  (mirrors GPSHandler interface)
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start the WebSocket server in a background thread."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("📱 Phone GPS: websockets not installed, skipping")
            return False

        if self._running:
            return True

        self._running = True
        self._thread = threading.Thread(
            target=self._run_server,
            name="phone-gps-server",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"📱 Phone GPS server starting on port {self._port}")
        return True

    def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("📱 Phone GPS server stopped")

    def get_fix(self) -> Optional[GPSFix]:
        """Get the latest GPS fix from the phone, or None if stale/missing."""
        with self._lock:
            if self._fix is None:
                return None
            age = time.monotonic() - self._last_update
            if age > self.STALE_THRESHOLD:
                return None
            return self._fix

    @property
    def has_fix(self) -> bool:
        """True if we have a recent phone GPS fix."""
        return self.get_fix() is not None

    @property
    def is_connected(self) -> bool:
        """True if at least one phone is connected."""
        return self._connected_phones > 0

    # ------------------------------------------------------------------
    # Internal — WebSocket server
    # ------------------------------------------------------------------

    def _run_server(self) -> None:
        """Entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            logger.error(f"📱 Phone GPS server error: {e}")
        finally:
            self._loop.close()

    def _ensure_ssl_cert(self) -> Optional[ssl.SSLContext]:
        """Generate a self-signed SSL cert if needed. Returns SSLContext or None."""
        try:
            self._cert_dir.mkdir(parents=True, exist_ok=True)

            if not self._cert_file.exists() or not self._key_file.exists():
                logger.info("📱 Generating self-signed SSL cert for phone GPS...")
                subprocess.run(
                    [
                        "openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-keyout", str(self._key_file),
                        "-out", str(self._cert_file),
                        "-days", "3650", "-nodes",
                        "-subj", "/CN=CortexGPS",
                    ],
                    check=True,
                    capture_output=True,
                )
                logger.info("📱 SSL cert generated")

            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(self._cert_file), str(self._key_file))
            return ctx
        except (subprocess.CalledProcessError, FileNotFoundError, ssl.SSLError) as e:
            logger.warning(f"📱 SSL setup failed, falling back to HTTP: {e}")
            return None

    async def _serve(self) -> None:
        """Run the WebSocket + HTTP server (HTTPS if openssl available)."""
        ssl_ctx = self._ensure_ssl_cert()
        proto = "wss" if ssl_ctx else "ws"

        async with websockets.server.serve(
            self._handle_ws,
            "0.0.0.0",
            self._port,
            process_request=self._serve_html,
            ssl=ssl_ctx,
            ping_interval=20,
            ping_timeout=10,
        ):
            logger.info(f"📱 Phone GPS: listening on {proto}://0.0.0.0:{self._port}")
            logger.info(f"📱 Open https://<rpi5-ip>:{self._port}/gps on your phone")
            while self._running:
                await asyncio.sleep(0.5)

    async def _serve_html(self, path, request_headers):
        """Serve the GPS HTML page on GET /gps."""
        if path == "/gps" or path == "/gps/":
            try:
                html = self._html_path.read_text(encoding="utf-8")
                return (200, [("Content-Type", "text/html; charset=utf-8")], html.encode())
            except FileNotFoundError:
                return (404, [], b"phone_gps.html not found")
        # Return None to let WebSocket handle the connection
        return None

    async def _handle_ws(self, websocket):
        """Handle a single phone WebSocket connection."""
        self._connected_phones += 1
        remote = websocket.remote_address
        logger.info(f"📱 Phone GPS connected: {remote}")
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    self._update_fix(data)
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.debug(f"📱 Bad GPS data from phone: {e}")
        except Exception as e:
            logger.debug(f"📱 Phone GPS disconnected: {remote} ({e})")
        finally:
            self._connected_phones = max(0, self._connected_phones - 1)
            logger.info(f"📱 Phone GPS disconnected: {remote}")

    def _update_fix(self, data: dict) -> None:
        """Parse phone GPS JSON and update the fix."""
        lat = float(data["lat"])
        lng = float(data["lng"])
        alt = float(data.get("alt", -1) or -1)
        speed_ms = float(data.get("speed", 0) or 0)
        heading = float(data.get("heading", 0) or 0)
        accuracy = float(data.get("accuracy", 999) or 999)

        speed_kmh = speed_ms * 3.6  # m/s → km/h

        # Map accuracy to a pseudo fix_quality
        # <10m → quality 2 (excellent), <30m → quality 1, else 0
        if accuracy < 10:
            fix_quality = 2
        elif accuracy < 30:
            fix_quality = 1
        else:
            fix_quality = 0

        with self._lock:
            self._fix = GPSFix(
                latitude=lat,
                longitude=lng,
                altitude=alt,
                speed_kmh=speed_kmh,
                heading=heading,
                fix_quality=fix_quality,
                satellites=0,  # Browser doesn't report sat count
            )
            self._last_update = time.monotonic()

        logger.debug(
            f"📱 Phone GPS: lat={lat:.6f}, lng={lng:.6f}, "
            f"acc={accuracy:.0f}m, speed={speed_kmh:.1f}km/h"
        )
