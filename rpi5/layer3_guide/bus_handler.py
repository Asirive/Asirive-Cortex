"""
Bus Handler — LTA DataMall API + YOLO Bus Detection

Provides bus arrival announcements via LTA DataMall API and
visual bus detection via YOLO. Designed for Singapore public
transport system.

Phase 1 scope:
- LTA API bus arrival queries
- Nearest bus stop lookup (SQLite)
- Voice announcements of arrivals
- YOLO "bus" class detection (approaching notification)

Phase 2 (deferred):
- Door detection, queue handling, temporal voting OCR

Author: Haziq (@IRSPlays)
Date: March 11, 2026
"""

import asyncio
import json
import logging
import math
import sqlite3
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =====================================================
# DATA TYPES
# =====================================================

class BusStopMode(Enum):
    """Bus stop handler state."""
    INACTIVE = "inactive"
    MONITORING = "monitoring"       # Near bus stop, checking arrivals
    BUS_APPROACHING = "approaching" # YOLO sees a bus


@dataclass
class BusStop:
    """A Singapore bus stop."""
    code: str           # e.g., "01012"
    description: str    # e.g., "Hotel & Towers"
    road_name: str      # e.g., "Victoria St"
    latitude: float
    longitude: float


@dataclass
class BusArrival:
    """A single bus arrival estimate."""
    service_no: str     # e.g., "23"
    operator: str       # e.g., "SBST"
    eta_minutes: int    # Minutes until arrival (-1 if no estimate)
    load: str           # "SEA" (seats), "SDA" (standing), "LSD" (limited)
    bus_type: str       # "SD" (single deck), "DD" (double deck), "BD" (bendy)


# =====================================================
# GEO MATH (shared with navigation_engine)
# =====================================================

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two GPS coordinates."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# =====================================================
# BUS HANDLER
# =====================================================

class BusHandler:
    """
    Bus arrival monitoring using LTA DataMall API.
    
    Features:
    - Find nearest bus stop from GPS coordinates
    - Query real-time bus arrivals
    - Voice-announce arrivals periodically
    - Detect "bus" class via YOLO detections
    
    Usage:
        handler = BusHandler(lta_api_key="...", tts=tts_router)
        handler.load_bus_stops()  # Load SQLite DB
        await handler.start_monitoring(lat=1.3521, lng=103.8198)
        # ... handler announces arrivals periodically
        await handler.stop_monitoring()
    """

    LTA_BUS_ARRIVAL_URL = "http://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival"
    LTA_BUS_STOPS_URL = "http://datamall2.mytransport.sg/ltaodataservice/BusStops"

    def __init__(
        self,
        lta_api_key: str = "",
        tts=None,
        db_path: str = "bus_stops.db",
        proximity_radius_m: float = 50.0,
        arrival_refresh_s: float = 30.0,
        announce_interval_s: float = 60.0,
        on_bus_detected: Optional[Callable] = None,
    ):
        """
        Args:
            lta_api_key: LTA DataMall API account key
            tts: TTSRouter instance for voice announcements
            db_path: SQLite database path for bus stop data
            proximity_radius_m: Radius to detect nearby bus stops
            arrival_refresh_s: How often to refresh arrival data
            announce_interval_s: How often to re-announce arrivals
            on_bus_detected: Callback when YOLO detects a bus
        """
        self.lta_api_key = lta_api_key
        self.tts = tts
        self.db_path = db_path
        self.proximity_radius_m = proximity_radius_m
        self.arrival_refresh_s = arrival_refresh_s
        self.announce_interval_s = announce_interval_s
        self.on_bus_detected = on_bus_detected

        # State
        self.state = BusStopMode.INACTIVE
        self.current_stop: Optional[BusStop] = None
        self.latest_arrivals: List[BusArrival] = []
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_announce_time = 0.0
        self._last_refresh_time = 0.0
        self._bus_detected_in_frame = False

        # Initialize bus stops database
        self._init_db()

        logger.info("BusHandler initialized")

    # -------------------------------------------------
    # BUS STOPS DATABASE
    # -------------------------------------------------

    def _init_db(self):
        """Create bus stops table if it doesn't exist."""
        try:
            db = sqlite3.connect(self.db_path)
            db.execute("""
                CREATE TABLE IF NOT EXISTS bus_stops (
                    code TEXT PRIMARY KEY,
                    description TEXT,
                    road_name TEXT,
                    latitude REAL,
                    longitude REAL
                )
            """)
            db.commit()
            db.close()
        except Exception as e:
            logger.warning(f"Failed to init bus stops DB: {e}")

    def get_bus_stop_count(self) -> int:
        """Get number of bus stops in the database."""
        try:
            db = sqlite3.connect(self.db_path)
            count = db.execute("SELECT COUNT(*) FROM bus_stops").fetchone()[0]
            db.close()
            return count
        except Exception:
            return 0

    def download_bus_stops(self) -> int:
        """
        Download all Singapore bus stops from LTA DataMall API.
        
        The API returns 500 records per call. We paginate through all of them.
        Call this once during setup, not during runtime.
        
        Returns:
            Number of bus stops downloaded
        """
        if not self.lta_api_key:
            logger.error("No LTA API key configured")
            return 0

        logger.info("Downloading bus stops from LTA DataMall...")
        total = 0
        skip = 0

        db = sqlite3.connect(self.db_path)

        while True:
            url = f"{self.LTA_BUS_STOPS_URL}?$skip={skip}"
            req = urllib.request.Request(url, headers={
                "AccountKey": self.lta_api_key,
                "Accept": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
            except Exception as e:
                logger.error(f"LTA BusStops API error at skip={skip}: {e}")
                break

            stops = data.get("value", [])
            if not stops:
                break

            for s in stops:
                db.execute(
                    "INSERT OR REPLACE INTO bus_stops (code, description, road_name, latitude, longitude) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        s.get("BusStopCode", ""),
                        s.get("Description", ""),
                        s.get("RoadName", ""),
                        s.get("Latitude", 0.0),
                        s.get("Longitude", 0.0),
                    ),
                )
            db.commit()
            total += len(stops)
            skip += 500

            if len(stops) < 500:
                break

        db.close()
        logger.info(f"Downloaded {total} bus stops")
        return total

    def find_nearest_stop(self, lat: float, lng: float) -> Optional[BusStop]:
        """
        Find the nearest bus stop to given coordinates.
        
        Uses a bounding box pre-filter for performance, then haversine for accuracy.
        """
        # Approximate bounding box (±0.005° ≈ ±500m)
        delta = 0.005
        try:
            db = sqlite3.connect(self.db_path)
            rows = db.execute(
                "SELECT code, description, road_name, latitude, longitude FROM bus_stops "
                "WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?",
                (lat - delta, lat + delta, lng - delta, lng + delta),
            ).fetchall()
            db.close()
        except Exception as e:
            logger.warning(f"Bus stop lookup failed: {e}")
            return None

        if not rows:
            return None

        best = None
        best_dist = float("inf")
        for code, desc, road, slat, slng in rows:
            d = _haversine(lat, lng, slat, slng)
            if d < best_dist:
                best_dist = d
                best = BusStop(code=code, description=desc, road_name=road, latitude=slat, longitude=slng)

        if best and best_dist <= self.proximity_radius_m:
            return best
        return None

    # -------------------------------------------------
    # LTA BUS ARRIVAL API
    # -------------------------------------------------

    def query_arrivals(self, stop_code: str) -> List[BusArrival]:
        """
        Query bus arrivals from LTA DataMall API.
        
        Args:
            stop_code: Bus stop code (e.g., "01012")
            
        Returns:
            List of BusArrival objects sorted by ETA
        """
        if not self.lta_api_key:
            logger.warning("No LTA API key — cannot query arrivals")
            return []

        url = f"{self.LTA_BUS_ARRIVAL_URL}?BusStopCode={urllib.parse.quote(stop_code)}"
        req = urllib.request.Request(url, headers={
            "AccountKey": self.lta_api_key,
            "Accept": "application/json",
        })

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            logger.warning(f"LTA BusArrival API error: {e}")
            return []

        arrivals = []
        for svc in data.get("Services", []):
            service_no = svc.get("ServiceNo", "?")
            operator = svc.get("Operator", "")

            # Parse next bus estimate
            next_bus = svc.get("NextBus", {})
            eta_str = next_bus.get("EstimatedArrival", "")
            eta_minutes = self._parse_eta(eta_str)
            load = next_bus.get("Load", "")
            bus_type = next_bus.get("Type", "")

            arrivals.append(BusArrival(
                service_no=service_no,
                operator=operator,
                eta_minutes=eta_minutes,
                load=load,
                bus_type=bus_type,
            ))

        # Sort by ETA (nearest first)
        arrivals.sort(key=lambda a: a.eta_minutes if a.eta_minutes >= 0 else 999)
        return arrivals

    @staticmethod
    def _parse_eta(eta_str: str) -> int:
        """Parse LTA estimated arrival time string to minutes from now."""
        if not eta_str:
            return -1
        try:
            # Format: "2026-03-11T14:30:00+08:00"
            from datetime import datetime, timezone, timedelta
            # Parse ISO format
            eta_str_clean = eta_str.replace("+08:00", "+0800").replace("+08:00", "+0800")
            # Use a simple approach: extract the datetime
            dt_part = eta_str[:19]  # "2026-03-11T14:30:00"
            eta_dt = datetime.strptime(dt_part, "%Y-%m-%dT%H:%M:%S")
            # Assume SGT (UTC+8)
            sgt = timezone(timedelta(hours=8))
            eta_dt = eta_dt.replace(tzinfo=sgt)
            now = datetime.now(sgt)
            diff = (eta_dt - now).total_seconds() / 60
            return max(0, int(diff))
        except Exception:
            return -1

    # -------------------------------------------------
    # MONITORING
    # -------------------------------------------------

    async def start_monitoring(self, lat: float, lng: float) -> bool:
        """
        Start monitoring bus arrivals at the nearest bus stop.
        
        Args:
            lat: Current latitude
            lng: Current longitude
            
        Returns:
            True if a nearby bus stop was found and monitoring started
        """
        stop = self.find_nearest_stop(lat, lng)
        if not stop:
            return False

        self.current_stop = stop
        self.state = BusStopMode.MONITORING
        self._running = True

        await self._speak(
            f"You're near bus stop {stop.description} on {stop.road_name}."
        )

        # Initial arrival query
        await self._refresh_and_announce()

        # Start monitoring loop
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Bus monitoring started at stop {stop.code} ({stop.description})")
        return True

    async def stop_monitoring(self):
        """Stop bus arrival monitoring."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        self.state = BusStopMode.INACTIVE
        self.current_stop = None
        self.latest_arrivals = []
        logger.info("Bus monitoring stopped")

    async def _monitor_loop(self):
        """Periodically refresh and announce bus arrivals."""
        while self._running:
            try:
                now = time.time()

                # Refresh arrival data
                if now - self._last_refresh_time >= self.arrival_refresh_s:
                    await self._refresh_arrivals()

                # Re-announce periodically
                if now - self._last_announce_time >= self.announce_interval_s:
                    await self._announce_arrivals()

                await asyncio.sleep(5)  # Check every 5 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bus monitor loop error: {e}")
                await asyncio.sleep(10)

    async def _refresh_arrivals(self):
        """Refresh arrival data from API."""
        if not self.current_stop:
            return
        self.latest_arrivals = await asyncio.get_event_loop().run_in_executor(
            None, self.query_arrivals, self.current_stop.code
        )
        self._last_refresh_time = time.time()

    async def _refresh_and_announce(self):
        """Refresh and immediately announce."""
        await self._refresh_arrivals()
        await self._announce_arrivals()

    async def _announce_arrivals(self):
        """Voice-announce current bus arrivals."""
        if not self.latest_arrivals:
            await self._speak("No buses approaching at the moment.")
            self._last_announce_time = time.time()
            return

        # Announce top 3 arrivals
        lines = []
        for arr in self.latest_arrivals[:3]:
            if arr.eta_minutes < 0:
                lines.append(f"Bus {arr.service_no}: no estimate")
            elif arr.eta_minutes == 0:
                lines.append(f"Bus {arr.service_no}: arriving now")
            elif arr.eta_minutes == 1:
                lines.append(f"Bus {arr.service_no}: 1 minute")
            else:
                lines.append(f"Bus {arr.service_no}: {arr.eta_minutes} minutes")

        text = ". ".join(lines) + "."
        await self._speak(text)
        self._last_announce_time = time.time()

    # -------------------------------------------------
    # YOLO BUS DETECTION
    # -------------------------------------------------

    def update_detections(self, detections: List[Dict[str, Any]]):
        """
        Process YOLO detections, looking for "bus" class.
        
        Called from the main detection loop each frame.
        """
        bus_detected = any(
            d.get("class", "").lower() == "bus" or d.get("class_name", "").lower() == "bus"
            for d in detections
        )

        if bus_detected and not self._bus_detected_in_frame:
            self._bus_detected_in_frame = True
            if self.state == BusStopMode.MONITORING:
                self.state = BusStopMode.BUS_APPROACHING
                # Trigger async announcement
                try:
                    loop = asyncio.get_running_loop()
                    asyncio.ensure_future(self._speak("A bus is approaching."), loop=loop)
                except RuntimeError:
                    logger.info("Bus approaching detected (no event loop for TTS)")

                if self.on_bus_detected:
                    self.on_bus_detected()
        elif not bus_detected:
            self._bus_detected_in_frame = False
            if self.state == BusStopMode.BUS_APPROACHING:
                self.state = BusStopMode.MONITORING

    # -------------------------------------------------
    # AUTO-DETECT (called from navigation engine)
    # -------------------------------------------------

    async def check_proximity(self, lat: float, lng: float) -> bool:
        """
        Check if user is near a bus stop and auto-start monitoring.
        
        Returns:
            True if near a bus stop (monitoring started or already active)
        """
        if self.state != BusStopMode.INACTIVE:
            # Already monitoring — check if we've moved away
            if self.current_stop:
                dist = _haversine(lat, lng, self.current_stop.latitude, self.current_stop.longitude)
                if dist > self.proximity_radius_m * 2:
                    # Moved away from bus stop
                    await self.stop_monitoring()
                    return False
            return True

        # Check for nearby bus stop
        stop = self.find_nearest_stop(lat, lng)
        if stop:
            await self.start_monitoring(lat, lng)
            return True
        return False

    # -------------------------------------------------
    # VOICE
    # -------------------------------------------------

    async def _speak(self, text: str):
        """Speak text via TTS."""
        if self.tts:
            try:
                await self.tts.speak_async(text, engine_override="kokoro")
            except Exception as e:
                logger.warning(f"TTS failed: {e}")
        else:
            logger.info(f"BUS VOICE: {text}")

    # -------------------------------------------------
    # STATUS
    # -------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Get bus handler status for dashboard/context injection."""
        result = {
            "state": self.state.value,
            "stop_code": self.current_stop.code if self.current_stop else None,
            "stop_name": self.current_stop.description if self.current_stop else None,
        }
        if self.latest_arrivals:
            result["arrivals"] = [
                {"service": a.service_no, "eta_min": a.eta_minutes, "load": a.load}
                for a in self.latest_arrivals[:5]
            ]
        return result

    def get_context_string(self) -> str:
        """Get bus context for Gemini context injection."""
        if self.state == BusStopMode.INACTIVE:
            return ""
        
        parts = [f"[BUS] At stop: {self.current_stop.description}" if self.current_stop else "[BUS] Monitoring"]
        if self.latest_arrivals:
            top = self.latest_arrivals[0]
            if top.eta_minutes >= 0:
                parts.append(f"Next: Bus {top.service_no} in {top.eta_minutes}min")
        if self.state == BusStopMode.BUS_APPROACHING:
            parts.append("Bus approaching!")
        return " | ".join(parts)

    # -------------------------------------------------
    # CLEANUP
    # -------------------------------------------------

    async def shutdown(self):
        """Clean shutdown."""
        await self.stop_monitoring()
        logger.info("BusHandler shut down")
