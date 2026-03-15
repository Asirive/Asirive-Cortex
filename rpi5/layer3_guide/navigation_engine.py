"""
Navigation Engine — GPS Waypoint Following with 3D Audio Beam

Integrates Google Maps Directions API, GPS waypoint tracking,
IMU heading, and the existing spatial audio system to provide
turn-by-turn 3D audio navigation for visually impaired users.

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
import urllib.error
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from rpi5.layer3_guide.spatial_audio.position_calculator import Position3D
except ImportError:
    Position3D = None

logger = logging.getLogger(__name__)


# =====================================================
# DATA TYPES
# =====================================================

class NavMode(Enum):
    """Navigation mode — auto-detected from GPS quality."""
    IDLE = "idle"
    OUTDOOR = "outdoor"         # GPS fix available — beam active
    INDOOR = "indoor"           # No GPS fix — Gemini Guide Mode
    BUS_STOP = "bus_stop"       # Near a bus stop — LTA mode
    TRANSIT = "transit"         # On bus/MRT — stop counting mode


class NavState(Enum):
    """Current state of the navigation session."""
    INACTIVE = "inactive"
    LOADING_ROUTE = "loading_route"
    NAVIGATING = "navigating"
    ARRIVED = "arrived"
    PAUSED = "paused"           # e.g., road crossing
    ERROR = "error"


@dataclass
class Waypoint:
    """A single waypoint along a navigation route."""
    lat: float
    lng: float
    instruction: str = ""       # e.g., "Turn right onto Orchard Road"
    distance_m: float = 0.0     # distance from previous waypoint
    maneuver: str = ""          # e.g., "turn-right", "turn-left", "straight"
    is_turn: bool = False       # True if this waypoint has a direction change


@dataclass
class NavRoute:
    """A complete navigation route."""
    origin: str
    destination: str
    waypoints: List[Waypoint] = field(default_factory=list)
    total_distance_m: float = 0.0
    total_duration_s: float = 0.0
    polyline: str = ""          # encoded polyline from Google
    fetched_at: float = 0.0     # timestamp


# =====================================================
# POLYLINE DECODER
# =====================================================

def decode_polyline(encoded: str) -> List[Tuple[float, float]]:
    """
    Decode a Google Maps encoded polyline into (lat, lng) pairs.
    
    Reference: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
    """
    points = []
    index = 0
    lat = 0
    lng = 0
    while index < len(encoded):
        # Decode latitude
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lat += (~(result >> 1) if (result & 1) else (result >> 1))

        # Decode longitude
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lng += (~(result >> 1) if (result & 1) else (result >> 1))

        points.append((lat / 1e5, lng / 1e5))
    return points


# =====================================================
# GEO MATH
# =====================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two GPS coordinates."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Bearing in degrees (0-360) from point 1 to point 2.
    0 = North, 90 = East, 180 = South, 270 = West.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    bearing = math.degrees(math.atan2(x, y))
    return bearing % 360


def relative_angle(target_bearing: float, user_heading: float) -> float:
    """
    Relative angle from user's heading to target bearing.
    Returns -180 to +180. Negative = target is to the LEFT, positive = RIGHT.
    """
    diff = (target_bearing - user_heading + 180) % 360 - 180
    return diff


def angle_to_hrtf_position(angle_deg: float, distance_m: float) -> Tuple[float, float, float]:
    """
    Convert relative angle + distance to OpenAL 3D position.
    
    OpenAL coordinate system:
    - X: right (+) / left (-)
    - Y: up (+) / down (-)
    - Z: behind (+) / front (-)
    User faces -Z direction.
    
    We place the beacon on a unit sphere scaled to ~2m for consistent HRTF,
    then encode distance via pitch/ping rate (not position).
    """
    rad = math.radians(angle_deg)
    hrtf_radius = 2.0  # Fixed radius for consistent HRTF perception
    x = math.sin(rad) * hrtf_radius    # Left(-)/Right(+)
    z = -math.cos(rad) * hrtf_radius   # Front(-)/Behind(+)
    y = 0.0                             # Keep on ear plane
    return (x, y, z)


# =====================================================
# NAVIGATION ENGINE
# =====================================================

class NavigationEngine:
    """
    GPS waypoint navigation with 3D audio beam guidance.
    
    Integrates:
    - Google Maps Directions API for route fetching
    - GPSHandler for position
    - IMUHandler for heading
    - SpatialAudioManager for 3D audio beam
    - TTSRouter for voice announcements
    
    Usage:
        engine = NavigationEngine(api_key="...", gps=gps_handler, imu=imu_handler)
        await engine.start_navigation("1.3521,103.8198", "Orchard Road, Singapore")
        # Engine runs its own async loop, updating beam position
        await engine.stop_navigation()
    """

    # Waypoint arrival threshold (meters)
    ARRIVAL_THRESHOLD = 15.0
    # Final destination arrival threshold
    DESTINATION_THRESHOLD = 20.0
    # Distance to announce upcoming turn
    TURN_ANNOUNCE_DISTANCE = 25.0
    # Minimum interval between voice announcements (seconds)
    VOICE_COOLDOWN = 5.0
    # Navigation loop frequency (Hz)
    NAV_LOOP_HZ = 10
    # Maximum waypoint spacing (meters) — interpolate if larger
    MAX_WAYPOINT_SPACING = 25.0
    # Road crossing detection: depth + curb keywords
    ROAD_CROSSING_KEYWORDS = {"crossing", "crosswalk", "cross", "road"}
    # GPS quality threshold for outdoor mode (satellites)
    GPS_MIN_SATELLITES = 4

    def __init__(
        self,
        api_key: str = "",
        gps=None,
        imu=None,
        spatial_audio=None,
        tts=None,
        on_mode_change: Optional[Callable] = None,
        on_arrival: Optional[Callable] = None,
        on_nav_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        cache_db_path: str = "nav_cache.db",
    ):
        """
        Args:
            api_key: Google Maps Directions API key
            gps: GPSHandler instance
            imu: IMUHandler instance
            spatial_audio: SpatialAudioManager instance
            tts: TTSRouter instance
            on_mode_change: Callback(NavMode) when mode changes
            on_arrival: Callback() when destination reached
            on_nav_event: Callback(event_name, details_dict) for Gemini context injection
            cache_db_path: SQLite path for route caching
        """
        self.api_key = api_key
        self.gps = gps
        self.imu = imu
        self.spatial_audio = spatial_audio
        self.tts = tts
        self.on_mode_change = on_mode_change
        self.on_arrival = on_arrival
        self.on_nav_event = on_nav_event

        # State
        self.state = NavState.INACTIVE
        self.mode = NavMode.IDLE
        self.route: Optional[NavRoute] = None
        self.current_waypoint_idx = 0
        self._nav_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_voice_time = 0.0
        self._turn_announced = set()  # waypoint indices where turn was announced
        self._road_crossing_active = False

        # Breadcrumb trail — GPS position log for "retrace steps" / "I'm lost"
        self._breadcrumbs: List[Tuple[float, float, float]] = []  # (lat, lng, timestamp)
        self._breadcrumb_interval = 5.0  # Record every 5 seconds
        self._last_breadcrumb_time = 0.0
        self._approaching_dest_announced = False  # Track "approaching destination" event
        self._nav_start_time = 0.0  # When navigation started (for GPS grace period)
        self._gps_grace_seconds = 30.0  # Don't switch to indoor mode for this long after start

        # Route cache database
        self._cache_db_path = cache_db_path
        self._init_cache_db()

        logger.info("NavigationEngine initialized")

    # -------------------------------------------------
    # ROUTE CACHE (SQLite)
    # -------------------------------------------------

    def _init_cache_db(self):
        """Create route cache table if it doesn't exist."""
        try:
            db = sqlite3.connect(self._cache_db_path)
            db.execute("""
                CREATE TABLE IF NOT EXISTS route_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    route_json TEXT NOT NULL,
                    fetched_at REAL NOT NULL
                )
            """)
            db.commit()
            db.close()
        except Exception as e:
            logger.warning(f"Failed to init route cache DB: {e}")

    def _cache_route(self, route: NavRoute):
        """Save route to SQLite cache."""
        try:
            db = sqlite3.connect(self._cache_db_path)
            waypoints_json = json.dumps([
                {
                    "lat": w.lat, "lng": w.lng, "instruction": w.instruction,
                    "distance_m": w.distance_m, "maneuver": w.maneuver, "is_turn": w.is_turn,
                }
                for w in route.waypoints
            ])
            route_data = json.dumps({
                "origin": route.origin,
                "destination": route.destination,
                "waypoints": waypoints_json,
                "total_distance_m": route.total_distance_m,
                "total_duration_s": route.total_duration_s,
                "polyline": route.polyline,
            })
            db.execute(
                "INSERT INTO route_cache (origin, destination, route_json, fetched_at) VALUES (?, ?, ?, ?)",
                (route.origin, route.destination, route_data, time.time()),
            )
            db.commit()
            db.close()
            logger.info(f"Route cached: {route.origin} → {route.destination}")
        except Exception as e:
            logger.warning(f"Failed to cache route: {e}")

    def _load_cached_route(self, origin: str, destination: str) -> Optional[NavRoute]:
        """Load most recent cached route matching origin/destination."""
        try:
            db = sqlite3.connect(self._cache_db_path)
            row = db.execute(
                "SELECT route_json, fetched_at FROM route_cache "
                "WHERE origin = ? AND destination = ? ORDER BY fetched_at DESC LIMIT 1",
                (origin, destination),
            ).fetchone()
            db.close()
            if row:
                data = json.loads(row[0])
                waypoints_raw = json.loads(data["waypoints"])
                waypoints = [Waypoint(**w) for w in waypoints_raw]
                return NavRoute(
                    origin=data["origin"],
                    destination=data["destination"],
                    waypoints=waypoints,
                    total_distance_m=data.get("total_distance_m", 0),
                    total_duration_s=data.get("total_duration_s", 0),
                    polyline=data.get("polyline", ""),
                    fetched_at=row[1],
                )
        except Exception as e:
            logger.warning(f"Failed to load cached route: {e}")
        return None

    # -------------------------------------------------
    # GOOGLE MAPS API
    # -------------------------------------------------

    @staticmethod
    def _sanitize_location(loc: str) -> str:
        """
        Clean up a location string for Google Maps API.
        
        - Strips trailing punctuation from STT artifacts ("North Point." → "North Point")
        - Appends ", Singapore" to text addresses that don't already specify a region
          (prevents Google resolving "North Point" to Hong Kong instead of Northpoint City SG)
        - Leaves "lat,lng" coordinate strings untouched
        """
        loc = loc.strip()
        # Strip trailing punctuation (periods, commas, question marks from STT)
        loc = loc.rstrip(".,;:!?")
        # If it looks like coordinates (e.g. "1.3521,103.8198"), leave it alone
        if "," in loc:
            parts = loc.split(",")
            try:
                float(parts[0].strip())
                float(parts[1].strip())
                return loc  # It's coordinates
            except (ValueError, IndexError):
                pass
        # If it already mentions Singapore or a country, leave it
        loc_lower = loc.lower()
        if "singapore" in loc_lower or "sg" in loc_lower:
            return loc
        # Append ", Singapore" to bias Google Maps correctly
        return f"{loc}, Singapore"

    def fetch_route(self, origin: str, destination: str) -> Optional[NavRoute]:
        """
        Fetch walking directions from Google Maps Directions API.
        
        Args:
            origin: "lat,lng" or address string
            destination: "lat,lng" or address string
            
        Returns:
            NavRoute with interpolated waypoints, or None on failure
        """
        if not self.api_key:
            logger.error("No Google Maps API key configured")
            return None

        self.state = NavState.LOADING_ROUTE

        # Sanitize destination: strip trailing punctuation from STT,
        # and append ", Singapore" if no country/region is specified
        # (prevents Google Maps from resolving to wrong country, e.g. HK)
        destination = self._sanitize_location(destination)
        origin = self._sanitize_location(origin)

        params = urllib.parse.urlencode({
            "origin": origin,
            "destination": destination,
            "mode": "walking",
            "region": "sg",  # Bias results toward Singapore
            "key": self.api_key,
        })
        url = f"https://maps.googleapis.com/maps/api/directions/json?{params}"
        logger.info(f"🧭 [NAV] Google Maps API request: origin='{origin}', destination='{destination}', mode=walking, region=sg")

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ProjectCortex/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            logger.error(f"🧭 [NAV] Google Maps API request FAILED: {e}")
            # Try cached route
            cached = self._load_cached_route(origin, destination)
            if cached:
                logger.info("🧭 [NAV] Using cached route as fallback")
                return cached
            self.state = NavState.ERROR
            return None

        logger.info(f"🧭 [NAV] Google Maps API response status: {data.get('status')}")
        if data.get("status") != "OK" or not data.get("routes"):
            logger.error(f"🧭 [NAV] Google Maps API error: {data.get('status')}, geocoded_waypoints={data.get('geocoded_waypoints', 'N/A')}")
            cached = self._load_cached_route(origin, destination)
            if cached:
                logger.info("Using cached route as fallback")
                return cached
            self.state = NavState.ERROR
            return None

        route_data = data["routes"][0]
        legs = route_data.get("legs", [])
        if not legs:
            self.state = NavState.ERROR
            return None

        leg = legs[0]
        waypoints: List[Waypoint] = []

        # Extract waypoints from steps
        for step in leg.get("steps", []):
            start = step.get("start_location", {})
            end = step.get("end_location", {})
            instruction = step.get("html_instructions", "")
            # Strip HTML tags from instruction
            import re
            instruction = re.sub(r"<[^>]+>", "", instruction)
            maneuver = step.get("maneuver", "")
            distance_m = step.get("distance", {}).get("value", 0)

            is_turn = maneuver in (
                "turn-left", "turn-right", "turn-slight-left", "turn-slight-right",
                "turn-sharp-left", "turn-sharp-right", "uturn-left", "uturn-right",
            )

            # Decode step polyline for dense waypoints
            step_polyline = step.get("polyline", {}).get("points", "")
            if step_polyline:
                points = decode_polyline(step_polyline)
                for i, (plat, plng) in enumerate(points):
                    wp = Waypoint(
                        lat=plat,
                        lng=plng,
                        instruction=instruction if i == 0 else "",
                        distance_m=distance_m / max(len(points), 1) if i == 0 else 0,
                        maneuver=maneuver if i == 0 else "",
                        is_turn=is_turn if i == 0 else False,
                    )
                    waypoints.append(wp)
            else:
                # Fallback: use start/end locations
                waypoints.append(Waypoint(
                    lat=start.get("lat", 0),
                    lng=start.get("lng", 0),
                    instruction=instruction,
                    distance_m=distance_m,
                    maneuver=maneuver,
                    is_turn=is_turn,
                ))

        # Interpolate waypoints that are too far apart
        waypoints = self._interpolate_waypoints(waypoints)

        route = NavRoute(
            origin=origin,
            destination=destination,
            waypoints=waypoints,
            total_distance_m=leg.get("distance", {}).get("value", 0),
            total_duration_s=leg.get("duration", {}).get("value", 0),
            polyline=route_data.get("overview_polyline", {}).get("points", ""),
            fetched_at=time.time(),
        )

        # Cache for offline use
        self._cache_route(route)
        logger.info(
            f"Route fetched: {len(waypoints)} waypoints, "
            f"{route.total_distance_m:.0f}m, ~{route.total_duration_s / 60:.0f}min"
        )
        return route

    def _interpolate_waypoints(self, waypoints: List[Waypoint]) -> List[Waypoint]:
        """Insert extra waypoints where gaps exceed MAX_WAYPOINT_SPACING."""
        if len(waypoints) < 2:
            return waypoints
        result = [waypoints[0]]
        for i in range(1, len(waypoints)):
            prev = result[-1]
            curr = waypoints[i]
            dist = haversine_distance(prev.lat, prev.lng, curr.lat, curr.lng)
            if dist > self.MAX_WAYPOINT_SPACING:
                # Interpolate intermediate points
                n_segments = int(math.ceil(dist / self.MAX_WAYPOINT_SPACING))
                for j in range(1, n_segments):
                    frac = j / n_segments
                    interp_lat = prev.lat + (curr.lat - prev.lat) * frac
                    interp_lng = prev.lng + (curr.lng - prev.lng) * frac
                    result.append(Waypoint(lat=interp_lat, lng=interp_lng))
            result.append(curr)
        return result

    # -------------------------------------------------
    # NAVIGATION CONTROL
    # -------------------------------------------------

    async def start_navigation(self, origin: str, destination: str) -> bool:
        """
        Start navigating from origin to destination.
        
        Args:
            origin: "lat,lng" or address (use "current" for GPS position)
            destination: "lat,lng" or address
            
        Returns:
            True if navigation started successfully
        """
        # Resolve "current" to GPS position
        if origin.lower() == "current":
            if self.gps:
                loc = self.gps.get_location()
                if loc:
                    origin = f"{loc[0]},{loc[1]}"
                else:
                    logger.warning("🧭 [NAV] Cannot resolve 'current' — no GPS position")
                    return False
            else:
                logger.warning("🧭 [NAV] Cannot resolve 'current' — GPS not available")
                return False

        logger.info(f"🧭 [NAV] start_navigation: origin='{origin}', destination='{destination}'")

        # Fetch route (blocking I/O, but fast enough for a single HTTP call)
        route = await asyncio.get_event_loop().run_in_executor(
            None, self.fetch_route, origin, destination
        )

        if not route or not route.waypoints:
            logger.warning(f"🧭 [NAV] Route fetch FAILED: origin='{origin}', destination='{destination}'")
            return False

        self.route = route
        self.current_waypoint_idx = 0
        self._turn_announced.clear()
        self._road_crossing_active = False
        self._approaching_dest_announced = False
        self._nav_start_time = time.time()
        self.state = NavState.NAVIGATING
        self._running = True

        total_min = route.total_duration_s / 60
        total_m = route.total_distance_m
        logger.info(
            f"🧭 [NAV] Route OK: {total_m:.0f}m, ~{total_min:.0f}min, "
            f"{len(route.waypoints)} waypoints"
        )

        # Start beacon sound on spatial audio
        if self.spatial_audio:
            self.spatial_audio.start_beacon("navigation_target")

        # Notify Gemini: navigation starting
        self._fire_nav_event("navigating_to", {
            "destination": destination,
            "distance_m": route.total_distance_m,
            "duration_min": round(route.total_duration_s / 60, 1),
            "waypoints": len(route.waypoints),
        })

        # Start the navigation loop
        self._nav_task = asyncio.create_task(self._navigation_loop())
        logger.info(f"Navigation started: {origin} → {destination}")
        return True

    async def stop_navigation(self):
        """Stop the current navigation session."""
        self._running = False
        if self._nav_task:
            self._nav_task.cancel()
            try:
                await self._nav_task
            except asyncio.CancelledError:
                pass
            self._nav_task = None

        if self.spatial_audio:
            self.spatial_audio.stop_beacon()

        self.state = NavState.INACTIVE
        self.route = None
        self.current_waypoint_idx = 0
        await self._speak("Navigation stopped.")
        self._fire_nav_event("navigation_stopped", {})
        logger.info("Navigation stopped")

    async def pause_navigation(self):
        """Pause navigation (e.g., for road crossing)."""
        self.state = NavState.PAUSED
        self._road_crossing_active = True
        if self.spatial_audio:
            self.spatial_audio.stop_beacon()
        logger.info("Navigation paused (road crossing)")

    async def resume_navigation(self):
        """Resume navigation after pause."""
        self.state = NavState.NAVIGATING
        self._road_crossing_active = False
        if self.spatial_audio:
            self.spatial_audio.start_beacon("navigation_target")
        await self._speak("Continuing navigation.")
        logger.info("Navigation resumed")

    # -------------------------------------------------
    # CORE NAVIGATION LOOP
    # -------------------------------------------------

    async def _navigation_loop(self):
        """
        Main navigation loop. Runs at NAV_LOOP_HZ.
        
        Each iteration:
        1. Get GPS position
        2. Get IMU heading
        3. Calculate bearing to next waypoint
        4. Calculate relative angle
        5. Update audio beam position
        6. Check waypoint arrival
        7. Announce upcoming turns
        """
        interval = 1.0 / self.NAV_LOOP_HZ
        logger.info(f"Navigation loop started at {self.NAV_LOOP_HZ}Hz")

        while self._running and self.state == NavState.NAVIGATING:
            try:
                loop_start = time.monotonic()

                if not self.route or not self.route.waypoints:
                    break

                # 1. Get current position
                current_pos = self._get_current_position()
                if current_pos is None:
                    # No GPS — check if we're still in the grace period
                    elapsed_since_start = time.time() - self._nav_start_time
                    if elapsed_since_start < self._gps_grace_seconds:
                        # Grace period: user may still be walking to get GPS fix
                        logger.debug(
                            f"No GPS fix yet ({elapsed_since_start:.0f}s / "
                            f"{self._gps_grace_seconds:.0f}s grace period)"
                        )
                    elif self.mode != NavMode.INDOOR:
                        # Grace period expired — genuinely indoors
                        self._set_mode(NavMode.INDOOR)
                        await self._speak(
                            "I've lost GPS signal. Switching to voice guidance. "
                            "I'll describe what I see to help you navigate."
                        )
                    await asyncio.sleep(interval)
                    continue

                # Record breadcrumb
                now = time.monotonic()
                if now - self._last_breadcrumb_time >= self._breadcrumb_interval:
                    self._breadcrumbs.append((current_pos[0], current_pos[1], time.time()))
                    self._last_breadcrumb_time = now

                # Ensure outdoor mode when GPS is available
                # Check for transit: speed > 15 km/h means vehicle, not walking
                gps_fix = self.gps.get_fix() if self.gps else None
                gps_speed = gps_fix.speed_kmh if gps_fix and hasattr(gps_fix, 'speed_kmh') else 0.0
                if gps_speed > 15.0:
                    if self.mode != NavMode.TRANSIT:
                        self._set_mode(NavMode.TRANSIT)
                        if self.spatial_audio:
                            self.spatial_audio.stop_beacon()
                        await self._speak("You're on a vehicle. I'll track your progress.")
                elif self.mode == NavMode.TRANSIT:
                    # Speed dropped — exited vehicle
                    self._set_mode(NavMode.OUTDOOR)
                    await self._speak("You've stopped. Resuming navigation.")
                elif self.mode != NavMode.OUTDOOR:
                    self._set_mode(NavMode.OUTDOOR)

                # 2. Get current heading from IMU
                user_heading = self._get_user_heading()

                # 3. Current waypoint
                wp = self.route.waypoints[self.current_waypoint_idx]

                # 4. Distance and bearing to waypoint
                dist_to_wp = haversine_distance(
                    current_pos[0], current_pos[1], wp.lat, wp.lng
                )
                target_bearing = bearing_between(
                    current_pos[0], current_pos[1], wp.lat, wp.lng
                )

                # 5. Relative angle from user heading
                rel_angle = relative_angle(target_bearing, user_heading)

                # 6. Update audio beam position
                if self.spatial_audio and not self._road_crossing_active:
                    hrtf_pos = angle_to_hrtf_position(rel_angle, dist_to_wp)
                    # Update beacon via SpatialAudioManager's API
                    if Position3D and hasattr(self.spatial_audio, '_update_beacon_position'):
                        pos3d = Position3D(
                            x=hrtf_pos[0], y=hrtf_pos[1], z=hrtf_pos[2],
                            distance_meters=dist_to_wp
                        )
                        self.spatial_audio._update_beacon_position(pos3d)

                # 7. Check for upcoming turn announcement
                await self._check_turn_announcement(current_pos, dist_to_wp)

                # 8. Check road crossing
                await self._check_road_crossing(wp)

                # 9. Determine if current waypoint is the final one
                is_final = self.current_waypoint_idx >= len(self.route.waypoints) - 1

                # 10. Check approaching destination (within 50m)
                if is_final and not self._approaching_dest_announced:
                    final_wp = self.route.waypoints[-1]
                    dist_to_dest = haversine_distance(
                        current_pos[0], current_pos[1], final_wp.lat, final_wp.lng
                    )
                    if dist_to_dest < 50.0:
                        self._approaching_dest_announced = True
                        self._fire_nav_event("approaching_destination", {
                            "destination": self.route.destination,
                            "distance_m": round(dist_to_dest, 0),
                        })

                # 11. Check waypoint arrival
                threshold = self.DESTINATION_THRESHOLD if is_final else self.ARRIVAL_THRESHOLD

                if dist_to_wp < threshold:
                    if is_final:
                        # Arrived at destination
                        self.state = NavState.ARRIVED
                        self._running = False
                        if self.spatial_audio:
                            self.spatial_audio.stop_beacon()
                        await self._speak("You've arrived at your destination.")
                        self._fire_nav_event("arrived", {
                            "destination": self.route.destination,
                        })
                        if self.on_arrival:
                            self.on_arrival()
                        logger.info("Destination reached!")
                        break
                    else:
                        # Advance to next waypoint
                        self.current_waypoint_idx += 1
                        next_wp = self.route.waypoints[self.current_waypoint_idx]
                        if next_wp.instruction and next_wp.is_turn:
                            await self._speak_turn(next_wp)
                        self._fire_nav_event("waypoint_reached", {
                            "index": self.current_waypoint_idx,
                            "total": len(self.route.waypoints),
                            "next_instruction": next_wp.instruction,
                        })
                        logger.debug(
                            f"Waypoint {self.current_waypoint_idx}/{len(self.route.waypoints)} reached"
                        )

                # Sleep for remainder of interval
                elapsed = time.monotonic() - loop_start
                sleep_time = max(0, interval - elapsed)
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Navigation loop error: {e}", exc_info=True)
                await asyncio.sleep(interval)

        logger.info("Navigation loop ended")

    # -------------------------------------------------
    # POSITION & HEADING
    # -------------------------------------------------

    def _get_current_position(self) -> Optional[Tuple[float, float]]:
        """Get current GPS position (lat, lng) or None."""
        if not self.gps:
            return None
        fix = self.gps.get_fix()
        if fix is None:
            return None
        # Check fix quality
        if fix.fix_quality < 1:
            return None
        return (fix.latitude, fix.longitude)

    def _get_user_heading(self) -> float:
        """
        Get user's facing direction in degrees (0-360).
        Falls back to GPS heading if IMU unavailable.
        """
        # Primary: BNO055 IMU heading
        if self.imu:
            heading = self.imu.get_heading()
            if heading is not None:
                return heading

        # Fallback: GPS heading (only reliable when moving)
        if self.gps:
            fix = self.gps.get_fix()
            if fix and fix.speed_kmh > 1.0:
                return fix.heading

        return 0.0  # Default north if nothing available

    # -------------------------------------------------
    # VOICE ANNOUNCEMENTS
    # -------------------------------------------------

    async def _speak(self, text: str):
        """Speak text via TTS with cooldown."""
        now = time.time()
        if now - self._last_voice_time < self.VOICE_COOLDOWN:
            # Queue instead of dropping — but respect cooldown
            await asyncio.sleep(self.VOICE_COOLDOWN - (now - self._last_voice_time))

        self._last_voice_time = time.time()
        if self.tts:
            try:
                await self.tts.speak_async(text, engine_override="kokoro")
            except Exception as e:
                logger.warning(f"TTS failed: {e}")
        else:
            logger.info(f"NAV VOICE: {text}")

    async def _speak_turn(self, wp: Waypoint):
        """Announce a turn direction."""
        maneuver = wp.maneuver
        if "left" in maneuver:
            direction = "left"
        elif "right" in maneuver:
            direction = "right"
        elif "uturn" in maneuver:
            direction = "around"
        else:
            direction = ""

        if direction:
            text = f"Turn {direction}."
            if wp.instruction:
                text = f"Turn {direction}. {wp.instruction}"
            await self._speak(text)

    async def _check_turn_announcement(
        self, current_pos: Tuple[float, float], dist_to_current: float
    ):
        """Announce upcoming turns before reaching the waypoint."""
        if not self.route:
            return

        # Look ahead for turns
        for i in range(self.current_waypoint_idx, min(
            self.current_waypoint_idx + 3, len(self.route.waypoints)
        )):
            wp = self.route.waypoints[i]
            if not wp.is_turn or i in self._turn_announced:
                continue

            dist = haversine_distance(current_pos[0], current_pos[1], wp.lat, wp.lng)
            if dist < self.TURN_ANNOUNCE_DISTANCE:
                self._turn_announced.add(i)
                maneuver = wp.maneuver
                if "left" in maneuver:
                    await self._speak(f"Turn left in {dist:.0f} meters.")
                elif "right" in maneuver:
                    await self._speak(f"Turn right in {dist:.0f} meters.")
                self._fire_nav_event("approaching_turn", {
                    "direction": "left" if "left" in maneuver else "right" if "right" in maneuver else maneuver,
                    "distance_m": round(dist, 0),
                    "instruction": wp.instruction,
                })
                break  # One announcement at a time

    async def _check_road_crossing(self, wp: Waypoint):
        """Check if current waypoint indicates a road crossing."""
        if self._road_crossing_active:
            return

        instruction_lower = wp.instruction.lower()
        if any(kw in instruction_lower for kw in self.ROAD_CROSSING_KEYWORDS):
            await self._speak("Road crossing detected. Check it's safe before crossing.")
            self._fire_nav_event("road_crossing", {
                "instruction": wp.instruction,
            })
            # Don't auto-pause — just warn. User keeps walking at their own discretion.

    # -------------------------------------------------
    # MODE MANAGEMENT
    # -------------------------------------------------

    def _set_mode(self, new_mode: NavMode):
        """Change navigation mode and notify callback."""
        if new_mode == self.mode:
            return
        old_mode = self.mode
        self.mode = new_mode
        logger.info(f"Nav mode: {old_mode.value} → {new_mode.value}")
        if self.on_mode_change:
            try:
                self.on_mode_change(new_mode)
            except Exception as e:
                logger.warning(f"Mode change callback error: {e}")
        # Fire nav event for Gemini
        if new_mode == NavMode.INDOOR:
            self._fire_nav_event("indoor_mode_activated", {"from": old_mode.value})
        elif new_mode == NavMode.OUTDOOR:
            self._fire_nav_event("outdoor_mode_activated", {"from": old_mode.value})
        elif new_mode == NavMode.TRANSIT:
            self._fire_nav_event("transit_mode", {"from": old_mode.value})

    def _fire_nav_event(self, event: str, details: Optional[Dict[str, Any]] = None):
        """Fire a navigation event to Gemini via callback."""
        if self.on_nav_event:
            try:
                self.on_nav_event(event, details or {})
            except Exception as e:
                logger.debug(f"Nav event callback error: {e}")

    # -------------------------------------------------
    # STATUS / INFO
    # -------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Get current navigation status for dashboard/context injection."""
        if not self.route or self.state == NavState.INACTIVE:
            return {"state": self.state.value, "mode": self.mode.value}

        current_pos = self._get_current_position()
        wp = self.route.waypoints[self.current_waypoint_idx] if self.route.waypoints else None

        dist_to_wp = 0.0
        bearing = 0.0
        if current_pos and wp:
            dist_to_wp = haversine_distance(current_pos[0], current_pos[1], wp.lat, wp.lng)
            bearing = bearing_between(current_pos[0], current_pos[1], wp.lat, wp.lng)

        # Distance to final destination
        dist_to_dest = 0.0
        if current_pos and self.route.waypoints:
            final = self.route.waypoints[-1]
            dist_to_dest = haversine_distance(
                current_pos[0], current_pos[1], final.lat, final.lng
            )

        return {
            "state": self.state.value,
            "mode": self.mode.value,
            "waypoint_index": self.current_waypoint_idx,
            "total_waypoints": len(self.route.waypoints),
            "distance_to_waypoint_m": round(dist_to_wp, 1),
            "bearing_to_waypoint": round(bearing, 1),
            "distance_to_destination_m": round(dist_to_dest, 1),
            "destination": self.route.destination,
            "next_instruction": wp.instruction if wp else "",
        }

    def get_breadcrumbs(self) -> List[Tuple[float, float, float]]:
        """Return recorded breadcrumb trail [(lat, lng, timestamp), ...]."""
        return list(self._breadcrumbs)

    async def retrace_steps(self) -> bool:
        """
        Start navigating back along the breadcrumb trail (reverse order).
        
        Used by "I'm lost" protocol to guide user back to start.
        Returns True if retrace started successfully.
        """
        if len(self._breadcrumbs) < 2:
            await self._speak("I don't have enough location history to retrace your steps.")
            return False

        # Stop any current navigation
        await self.stop_navigation()

        # Build waypoints from reversed breadcrumbs (skip duplicates within 10m)
        reversed_crumbs = list(reversed(self._breadcrumbs))
        waypoints = []
        for i, (lat, lng, _ts) in enumerate(reversed_crumbs):
            if i == 0:
                continue  # Skip current position
            # Skip if too close to previous waypoint
            if waypoints:
                prev = waypoints[-1]
                if haversine_distance(prev.lat, prev.lng, lat, lng) < 10.0:
                    continue
            is_final = (i == len(reversed_crumbs) - 1)
            waypoints.append(Waypoint(
                lat=lat, lng=lng,
                instruction="Retrace" if not is_final else "Starting point",
                distance_m=0.0, maneuver="",
                is_turn=False,
            ))

        if not waypoints:
            await self._speak("Your trail is too short to retrace.")
            return False

        # Create a synthetic route from breadcrumbs
        self.route = NavRoute(
            origin="current",
            destination="starting point",
            waypoints=waypoints,
            total_distance_m=0.0,
            total_duration_s=0.0,
            polyline="",
        )
        self.current_waypoint_idx = 0
        self.state = NavState.NAVIGATING
        self._running = True
        self._turn_announced.clear()

        await self._speak(
            f"Retracing your steps. {len(waypoints)} waypoints back to where you started."
        )

        # Start the nav loop
        self._nav_task = asyncio.create_task(self._navigation_loop())
        return True

    def get_context_string(self) -> str:
        """
        Get navigation context for Gemini context injection.
        
        Returns a single-line string like:
        "[NAV] Outdoor | 45m to waypoint, bearing 035° | Next: turn right in 20m | Dest: 230m"
        """
        status = self.get_status()
        if status["state"] == "inactive":
            return "[NAV] Inactive"
        
        parts = [f"[NAV] {status['mode'].capitalize()}"]
        if status.get("distance_to_waypoint_m"):
            parts.append(
                f"{status['distance_to_waypoint_m']:.0f}m to waypoint, "
                f"bearing {status['bearing_to_waypoint']:.0f}°"
            )
        if status.get("next_instruction"):
            parts.append(f"Next: {status['next_instruction']}")
        if status.get("distance_to_destination_m"):
            parts.append(f"Dest: {status['distance_to_destination_m']:.0f}m")
        return " | ".join(parts)

    # -------------------------------------------------
    # CLEANUP
    # -------------------------------------------------

    async def shutdown(self):
        """Clean shutdown."""
        await self.stop_navigation()
        logger.info("NavigationEngine shut down")
