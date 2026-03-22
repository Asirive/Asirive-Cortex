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
import threading
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
    WAITING_FOR_BUS = "waiting_for_bus"  # At bus stop, waiting for target bus
    ON_VEHICLE = "on_vehicle"   # On bus/MRT, counting stops
    ERROR = "error"


class LegType(Enum):
    """Type of a route leg."""
    WALKING = "walking"
    BUS = "bus"
    MRT = "mrt"


@dataclass
class TransitInfo:
    """Details for a transit (bus/MRT) leg."""
    service_no: str = ""        # e.g., "23", "NS Line"
    departure_stop: str = ""    # e.g., "Opp Blk 831"
    arrival_stop: str = ""      # e.g., "Tampines Int"
    departure_stop_code: str = ""  # LTA bus stop code for API queries
    arrival_stop_code: str = ""
    num_stops: int = 0
    headsign: str = ""          # direction label (e.g., "Tampines Int")
    line_name: str = ""         # e.g., "North South Line"
    line_color: str = ""        # e.g., "red"
    departure_lat: float = 0.0
    departure_lng: float = 0.0
    arrival_lat: float = 0.0
    arrival_lng: float = 0.0


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
    """A complete navigation route, possibly multi-leg (walking + transit)."""
    origin: str
    destination: str
    waypoints: List[Waypoint] = field(default_factory=list)  # flat list (walking-only fallback)
    legs: List['RouteLeg'] = field(default_factory=list)      # multi-leg route
    total_distance_m: float = 0.0
    total_duration_s: float = 0.0
    polyline: str = ""          # encoded polyline from Google
    fetched_at: float = 0.0     # timestamp
    is_transit: bool = False    # True if route uses public transport


@dataclass
class RouteLeg:
    """A single leg of a multi-leg route."""
    leg_type: LegType
    waypoints: List[Waypoint] = field(default_factory=list)  # walking waypoints for this leg
    transit_info: Optional[TransitInfo] = None                # bus/MRT details
    distance_m: float = 0.0
    duration_s: float = 0.0
    start_lat: float = 0.0
    start_lng: float = 0.0
    end_lat: float = 0.0
    end_lng: float = 0.0
    instruction: str = ""       # human-readable (e.g., "Walk to bus stop Opp Blk 831")


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
    ARRIVAL_THRESHOLD = 10.0
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
        self._road_crossing_pos = None  # GPS pos when crossing detected

        # Multi-leg transit tracking
        self.current_leg_idx = 0
        self._current_leg: Optional[RouteLeg] = None
        self._transit_stops_remaining = 0
        self._transit_departure_pos = None  # (lat, lng) of transit departure stop
        self._transit_arrival_pos = None    # (lat, lng) of transit arrival stop
        self._on_vehicle_announced = False
        self._alight_announced = False
        self._leg_waypoints = None  # Current leg's waypoints (for transit walking legs)
        self.bus_handler = None  # Set externally when bus_handler is available

        # Breadcrumb trail — GPS position log for "retrace steps" / "I'm lost"
        self._breadcrumbs: List[Tuple[float, float, float]] = []  # (lat, lng, timestamp)
        self._breadcrumb_interval = 5.0  # Record every 5 seconds
        self._last_breadcrumb_time = 0.0
        self._approaching_dest_announced = False  # Track "approaching destination" event
        self._nav_start_time = 0.0  # When navigation started (for GPS grace period)
        self._gps_grace_seconds = 30.0  # Don't switch to indoor mode for this long after start
        self._started_without_gps = False  # True if nav started with saved location (no GPS)

        # GPS accuracy tracking (set by _get_current_position)
        self._gps_accuracy: float = 999.0
        self._last_known_heading: float = 0.0
        self._last_waypoint_advance_time: float = 0.0  # Rate-limit waypoint advancement

        # Vision context from YOLO + depth (updated each frame by main loop)
        self._latest_detections: List[Dict[str, Any]] = []
        self._latest_depth_map: Optional[Any] = None  # numpy array

        # Route cache database
        self._cache_db_path = cache_db_path
        self._init_cache_db()

        # Persistent event loop for the navigation loop task
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._ensure_event_loop()

    def _ensure_event_loop(self):
        """Create a persistent background event loop for nav tasks."""
        if self._event_loop and self._event_loop.is_running():
            return
        self._event_loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_event_loop,
            name="nav-engine-loop",
            daemon=True,
        )
        self._loop_thread.start()

    def _run_event_loop(self):
        """Run the persistent event loop (blocking, on background thread)."""
        asyncio.set_event_loop(self._event_loop)
        self._event_loop.run_forever()

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

    def fetch_transit_route(self, origin: str, destination: str) -> Optional[NavRoute]:
        """
        Fetch transit directions from Google Maps Directions API.
        Returns a multi-leg route (WALKING + BUS/MRT legs).
        
        Falls back to walking-only if transit mode returns no results.
        """
        if not self.api_key:
            logger.error("No Google Maps API key configured")
            return None

        self.state = NavState.LOADING_ROUTE
        destination = self._sanitize_location(destination)
        origin = self._sanitize_location(origin)

        params = urllib.parse.urlencode({
            "origin": origin,
            "destination": destination,
            "mode": "transit",
            "transit_mode": "bus|rail",
            "region": "sg",
            "key": self.api_key,
        })
        url = f"https://maps.googleapis.com/maps/api/directions/json?{params}"
        logger.info(f"🧭 [NAV] Google Maps transit request: origin='{origin}', dest='{destination}'")

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ProjectCortex/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            logger.error(f"🧭 [NAV] Google Maps transit request FAILED: {e}")
            return self.fetch_route(origin, destination)  # Fall back to walking

        if data.get("status") != "OK" or not data.get("routes"):
            logger.warning(f"🧭 [NAV] Transit API returned {data.get('status')} — falling back to walking")
            return self.fetch_route(origin, destination)

        route_data = data["routes"][0]
        api_legs = route_data.get("legs", [])
        if not api_legs:
            return self.fetch_route(origin, destination)

        # Google returns one "leg" for origin→destination, with "steps" that
        # have travel_mode = WALKING or TRANSIT
        api_leg = api_legs[0]
        route_legs: List[RouteLeg] = []
        all_waypoints: List[Waypoint] = []  # flat list for backward compat

        has_transit = False
        for step in api_leg.get("steps", []):
            travel_mode = step.get("travel_mode", "WALKING")
            step_start = step.get("start_location", {})
            step_end = step.get("end_location", {})
            step_dist = step.get("distance", {}).get("value", 0)
            step_dur = step.get("duration", {}).get("value", 0)
            import re
            instruction = re.sub(r"<[^>]+>", "", step.get("html_instructions", ""))

            if travel_mode == "TRANSIT":
                has_transit = True
                td = step.get("transit_details", {})
                line = td.get("line", {})
                dep_stop = td.get("departure_stop", {})
                arr_stop = td.get("arrival_stop", {})
                vehicle = line.get("vehicle", {})
                vehicle_type = vehicle.get("type", "BUS")

                leg_type = LegType.MRT if vehicle_type in ("SUBWAY", "HEAVY_RAIL", "METRO_RAIL", "RAIL") else LegType.BUS

                transit_info = TransitInfo(
                    service_no=line.get("short_name", line.get("name", "")),
                    departure_stop=dep_stop.get("name", ""),
                    arrival_stop=arr_stop.get("name", ""),
                    departure_stop_code="",  # LTA code set later via bus_handler lookup
                    arrival_stop_code="",
                    num_stops=td.get("num_stops", 0),
                    headsign=td.get("headsign", ""),
                    line_name=line.get("name", ""),
                    line_color=line.get("color", ""),
                    departure_lat=dep_stop.get("location", {}).get("lat", 0),
                    departure_lng=dep_stop.get("location", {}).get("lng", 0),
                    arrival_lat=arr_stop.get("location", {}).get("lat", 0),
                    arrival_lng=arr_stop.get("location", {}).get("lng", 0),
                )

                leg = RouteLeg(
                    leg_type=leg_type,
                    transit_info=transit_info,
                    distance_m=step_dist,
                    duration_s=step_dur,
                    start_lat=step_start.get("lat", 0),
                    start_lng=step_start.get("lng", 0),
                    end_lat=step_end.get("lat", 0),
                    end_lng=step_end.get("lng", 0),
                    instruction=instruction,
                )
                route_legs.append(leg)

                # Add transit endpoint as a waypoint for flat list
                all_waypoints.append(Waypoint(
                    lat=transit_info.arrival_lat,
                    lng=transit_info.arrival_lng,
                    instruction=f"Alight at {transit_info.arrival_stop}",
                ))

            else:
                # WALKING step — may contain sub-steps
                leg_waypoints: List[Waypoint] = []
                sub_steps = step.get("steps", [])
                if sub_steps:
                    for sub in sub_steps:
                        sub_instr = re.sub(r"<[^>]+>", "", sub.get("html_instructions", ""))
                        sub_maneuver = sub.get("maneuver", "")
                        sub_dist = sub.get("distance", {}).get("value", 0)
                        is_turn = sub_maneuver in (
                            "turn-left", "turn-right", "turn-slight-left", "turn-slight-right",
                            "turn-sharp-left", "turn-sharp-right",
                        )
                        poly = sub.get("polyline", {}).get("points", "")
                        if poly:
                            points = decode_polyline(poly)
                            for i, (plat, plng) in enumerate(points):
                                leg_waypoints.append(Waypoint(
                                    lat=plat, lng=plng,
                                    instruction=sub_instr if i == 0 else "",
                                    distance_m=sub_dist / max(len(points), 1) if i == 0 else 0,
                                    maneuver=sub_maneuver if i == 0 else "",
                                    is_turn=is_turn if i == 0 else False,
                                ))
                        else:
                            s_start = sub.get("start_location", {})
                            leg_waypoints.append(Waypoint(
                                lat=s_start.get("lat", 0), lng=s_start.get("lng", 0),
                                instruction=sub_instr, distance_m=sub_dist,
                                maneuver=sub_maneuver, is_turn=is_turn,
                            ))
                else:
                    # No sub-steps — decode the step polyline
                    poly = step.get("polyline", {}).get("points", "")
                    if poly:
                        points = decode_polyline(poly)
                        for i, (plat, plng) in enumerate(points):
                            leg_waypoints.append(Waypoint(
                                lat=plat, lng=plng,
                                instruction=instruction if i == 0 else "",
                                distance_m=step_dist / max(len(points), 1) if i == 0 else 0,
                            ))
                    else:
                        leg_waypoints.append(Waypoint(
                            lat=step_start.get("lat", 0), lng=step_start.get("lng", 0),
                            instruction=instruction, distance_m=step_dist,
                        ))

                leg_waypoints = self._interpolate_waypoints(leg_waypoints)

                leg = RouteLeg(
                    leg_type=LegType.WALKING,
                    waypoints=leg_waypoints,
                    distance_m=step_dist,
                    duration_s=step_dur,
                    start_lat=step_start.get("lat", 0),
                    start_lng=step_start.get("lng", 0),
                    end_lat=step_end.get("lat", 0),
                    end_lng=step_end.get("lng", 0),
                    instruction=instruction,
                )
                route_legs.append(leg)
                all_waypoints.extend(leg_waypoints)

        if not has_transit:
            # Google returned an all-walking transit route — use walking fetch instead
            logger.info("🧭 [NAV] Transit route is all-walking — using walking mode")
            return self.fetch_route(origin, destination)

        route = NavRoute(
            origin=origin,
            destination=destination,
            waypoints=all_waypoints,
            legs=route_legs,
            total_distance_m=api_leg.get("distance", {}).get("value", 0),
            total_duration_s=api_leg.get("duration", {}).get("value", 0),
            polyline=route_data.get("overview_polyline", {}).get("points", ""),
            fetched_at=time.time(),
            is_transit=True,
        )

        leg_summary = []
        for lg in route_legs:
            if lg.leg_type == LegType.WALKING:
                leg_summary.append(f"Walk {lg.distance_m:.0f}m")
            elif lg.transit_info:
                leg_summary.append(f"{lg.leg_type.value.upper()} {lg.transit_info.service_no} ({lg.transit_info.num_stops} stops)")
        logger.info(
            f"🧭 [NAV] Transit route: {' → '.join(leg_summary)}, "
            f"{route.total_distance_m:.0f}m total, ~{route.total_duration_s / 60:.0f}min"
        )
        return route

    # -------------------------------------------------
    # NAVIGATION CONTROL
    # -------------------------------------------------

    async def start_navigation(self, origin: str, destination: str, prefer_transit: bool = True) -> bool:
        """
        Start navigating from origin to destination.
        
        Tries transit routing first (bus/MRT + walking). Falls back to
        walking-only if transit is unavailable or returns a walking route.
        
        Args:
            origin: "lat,lng" or address (use "current" for GPS position)
            destination: "lat,lng" or address
            prefer_transit: If True, try transit routing first
            
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

        logger.info(f"🧭 [NAV] start_navigation: origin='{origin}', destination='{destination}', transit={prefer_transit}")

        # Fetch route (try transit first, then walking)
        route = None
        if prefer_transit:
            route = await asyncio.get_running_loop().run_in_executor(
                None, self.fetch_transit_route, origin, destination
            )
        if not route or not route.waypoints:
            route = await asyncio.get_running_loop().run_in_executor(
                None, self.fetch_route, origin, destination
            )

        if not route or not route.waypoints:
            logger.warning(f"🧭 [NAV] Route fetch FAILED: origin='{origin}', destination='{destination}'")
            return False

        self.route = route
        self.current_waypoint_idx = 0
        self._turn_announced.clear()
        self._road_crossing_active = False
        self._road_crossing_pos = None
        self._approaching_dest_announced = False
        self._nav_start_time = time.time()
        self._started_without_gps = (self.gps is None or self.gps.get_fix() is None)
        self._running = True

        # Multi-leg setup
        if route.is_transit and route.legs:
            self.current_leg_idx = 0
            self._current_leg = route.legs[0]
            self._on_vehicle_announced = False
            self._alight_announced = False
            # Set walking waypoints to first walking leg's waypoints
            if self._current_leg.leg_type == LegType.WALKING and self._current_leg.waypoints:
                self.current_waypoint_idx = 0
                # Replace flat waypoints with first leg's waypoints for the nav loop
                self._leg_waypoints = self._current_leg.waypoints
            else:
                self._leg_waypoints = None
        else:
            self.current_leg_idx = 0
            self._current_leg = None
            self._leg_waypoints = None

        self.state = NavState.NAVIGATING

        total_min = route.total_duration_s / 60
        total_m = route.total_distance_m

        if route.is_transit and route.legs:
            leg_summary = []
            for i, leg in enumerate(route.legs):
                if leg.leg_type == LegType.WALKING:
                    leg_summary.append(f"Walk {leg.distance_m:.0f}m")
                elif leg.leg_type == LegType.BUS:
                    svc = leg.transit_info.service_no if leg.transit_info else "?"
                    stops = leg.transit_info.num_stops if leg.transit_info else "?"
                    leg_summary.append(f"Bus {svc} ({stops} stops)")
                elif leg.leg_type == LegType.MRT:
                    line = leg.transit_info.line_name if leg.transit_info else "?"
                    stops = leg.transit_info.num_stops if leg.transit_info else "?"
                    leg_summary.append(f"MRT {line} ({stops} stops)")
            logger.info(
                f"🧭 [NAV] Transit route OK: {total_m:.0f}m, ~{total_min:.0f}min, "
                f"{len(route.legs)} legs: {' → '.join(leg_summary)}"
            )
        else:
            logger.info(
                f"🧭 [NAV] Route OK: {total_m:.0f}m, ~{total_min:.0f}min, "
                f"{len(route.waypoints)} waypoints"
            )

        # Start beacon for first walking leg (or whole walking route)
        first_leg = self._current_leg
        if not first_leg or first_leg.leg_type == LegType.WALKING:
            if self.spatial_audio:
                self.spatial_audio.start_beacon("navigation_target")

        # Build nav event payload
        nav_event_data = {
            "destination": destination,
            "distance_m": route.total_distance_m,
            "duration_min": round(route.total_duration_s / 60, 1),
            "waypoints": len(route.waypoints),
            "is_transit": route.is_transit,
        }
        if route.is_transit and route.legs:
            nav_event_data["legs"] = len(route.legs)
            nav_event_data["leg_types"] = [l.leg_type.value for l in route.legs]

        # Notify Gemini: navigation starting
        self._fire_nav_event("navigating_to", nav_event_data)

        # Start the navigation loop on the persistent event loop
        self._ensure_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._navigation_loop(), self._event_loop
        )
        self._nav_future = future
        logger.info(f"Navigation started: {origin} → {destination}")
        return True

    async def stop_navigation(self):
        """Stop the current navigation session."""
        self._running = False
        if hasattr(self, '_nav_future') and self._nav_future:
            self._nav_future.cancel()
            self._nav_future = None
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
        """Pause navigation (e.g., for road crossing). Beacon stops, loop keeps running to detect crossing."""
        self.state = NavState.PAUSED
        self._road_crossing_active = True
        # Record position at crossing for movement detection
        self._road_crossing_pos = self._get_current_position()
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

    async def _advance_to_next_leg(self) -> bool:
        """Advance to the next leg on a multi-leg transit route.
        
        Returns True if advanced, False if no more legs.
        """
        if not self.route or not self.route.legs:
            return False

        next_idx = self.current_leg_idx + 1
        if next_idx >= len(self.route.legs):
            return False

        self.current_leg_idx = next_idx
        self._current_leg = self.route.legs[next_idx]
        self._on_vehicle_announced = False
        self._alight_announced = False
        self._transit_arrival_pos = None
        self._transit_stops_remaining = 0

        leg = self._current_leg
        logger.info(f"🧭 [NAV] Advancing to leg {next_idx}: {leg.leg_type.value}")

        if leg.leg_type == LegType.WALKING:
            # Walking leg: set up waypoints and resume beacon
            self.state = NavState.NAVIGATING
            self._set_mode(NavMode.OUTDOOR)
            self.current_waypoint_idx = 0
            self._leg_waypoints = leg.waypoints if leg.waypoints else None
            if self.spatial_audio:
                self.spatial_audio.start_beacon("navigation_target")
            walk_min = leg.duration_s / 60 if leg.duration_s else 0
            await self._speak(
                f"Walk {leg.distance_m:.0f} meters, about {walk_min:.0f} minutes. "
                f"{leg.instruction or ''}"
            )
            self._fire_nav_event("leg_started", {
                "leg_idx": next_idx,
                "type": "walking",
                "distance_m": leg.distance_m,
                "instruction": leg.instruction,
            })

        elif leg.leg_type in (LegType.BUS, LegType.MRT):
            # Transit leg: stop beacon, wait for vehicle
            self.state = NavState.WAITING_FOR_BUS
            if self.spatial_audio:
                self.spatial_audio.stop_beacon()

            ti = leg.transit_info
            if ti:
                if leg.leg_type == LegType.BUS:
                    await self._speak(
                        f"Wait for bus {ti.service_no} at {ti.departure_stop}. "
                        f"It will take you {ti.num_stops} stops to {ti.arrival_stop}."
                    )
                    # Start bus monitoring if bus_handler is available
                    if self.bus_handler and hasattr(self.bus_handler, 'start_monitoring'):
                        try:
                            await self.bus_handler.start_monitoring(
                                ti.departure_lat, ti.departure_lng,
                                target_service=ti.service_no
                            )
                        except Exception as e:
                            logger.warning(f"Failed to start bus monitoring: {e}")
                else:
                    await self._speak(
                        f"Take the {ti.line_name} line from {ti.departure_stop}. "
                        f"{ti.num_stops} stops to {ti.arrival_stop}."
                    )
                self._transit_arrival_pos = (ti.arrival_lat, ti.arrival_lng)
                self._transit_stops_remaining = ti.num_stops
            else:
                await self._speak("Wait for your transport.")

            self._fire_nav_event("leg_started", {
                "leg_idx": next_idx,
                "type": leg.leg_type.value,
                "service": ti.service_no if ti else None,
                "departure_stop": ti.departure_stop if ti else None,
                "arrival_stop": ti.arrival_stop if ti else None,
            })

        return True

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

        while self._running and self.state in (
            NavState.NAVIGATING, NavState.PAUSED,
            NavState.WAITING_FOR_BUS, NavState.ON_VEHICLE,
        ):
            try:
                loop_start = time.monotonic()

                if not self.route or not self.route.waypoints:
                    break

                # 1. Get current position
                current_pos = self._get_current_position()
                if current_pos is None:
                    # No GPS — check grace period (skip if started without GPS)
                    if not self._started_without_gps:
                        elapsed_since_start = time.time() - self._nav_start_time
                        if elapsed_since_start < self._gps_grace_seconds:
                            logger.debug(
                                f"No GPS fix yet ({elapsed_since_start:.0f}s / "
                                f"{self._gps_grace_seconds:.0f}s grace period)"
                            )
                            await asyncio.sleep(interval)
                            continue
                    if self.mode != NavMode.INDOOR:
                        self._set_mode(NavMode.INDOOR)
                    # Indoor: keep beacon alive by ticking
                    if self.spatial_audio and hasattr(self.spatial_audio, 'tick_beacon'):
                        self.spatial_audio.tick_beacon()
                    await asyncio.sleep(interval)
                    continue

                # --- Road crossing auto-resume ---
                # If paused at a crossing, check if user has moved >8m (crossed the road)
                if self.state == NavState.PAUSED and self._road_crossing_active:
                    if self._road_crossing_pos:
                        cross_dist = haversine_distance(
                            self._road_crossing_pos[0], self._road_crossing_pos[1],
                            current_pos[0], current_pos[1]
                        )
                        if cross_dist > 8.0:
                            logger.info(f"Road crossing complete (moved {cross_dist:.1f}m). Resuming navigation.")
                            await self.resume_navigation()
                    await asyncio.sleep(interval)
                    continue

                # --- WAITING_FOR_BUS state ---
                if self.state == NavState.WAITING_FOR_BUS:
                    # Monitor GPS speed — boarding detected as >15km/h
                    gps_fix = self.gps.get_fix() if self.gps else None
                    gps_speed = gps_fix.speed_kmh if gps_fix and hasattr(gps_fix, 'speed_kmh') else 0.0
                    if gps_speed > 15.0:
                        self.state = NavState.ON_VEHICLE
                        self._on_vehicle_announced = True
                        self._set_mode(NavMode.TRANSIT)
                        leg = self._current_leg
                        if leg and leg.transit_info:
                            ti = leg.transit_info
                            await self._speak(
                                f"You've boarded bus {ti.service_no}. "
                                f"{ti.num_stops} stops to {ti.arrival_stop}."
                            )
                            self._transit_arrival_pos = (ti.arrival_lat, ti.arrival_lng)
                            self._transit_stops_remaining = ti.num_stops
                        else:
                            await self._speak("You're on a vehicle. I'll track your progress.")
                        self._fire_nav_event("boarded_vehicle", {
                            "leg_idx": self.current_leg_idx,
                            "service": leg.transit_info.service_no if leg and leg.transit_info else None,
                        })
                    await asyncio.sleep(interval)
                    continue

                # --- ON_VEHICLE state ---
                if self.state == NavState.ON_VEHICLE:
                    gps_fix = self.gps.get_fix() if self.gps else None
                    gps_speed = gps_fix.speed_kmh if gps_fix and hasattr(gps_fix, 'speed_kmh') else 0.0

                    # Check proximity to alighting stop
                    if self._transit_arrival_pos:
                        dist_to_alight = haversine_distance(
                            current_pos[0], current_pos[1],
                            self._transit_arrival_pos[0], self._transit_arrival_pos[1]
                        )
                        # Pre-announce when within 300m
                        if dist_to_alight < 300.0 and not self._alight_announced:
                            self._alight_announced = True
                            leg = self._current_leg
                            stop_name = leg.transit_info.arrival_stop if leg and leg.transit_info else "your stop"
                            await self._speak(f"Approaching {stop_name}. Prepare to alight.")
                            self._fire_nav_event("approaching_alight", {
                                "stop": stop_name,
                                "distance_m": round(dist_to_alight, 0),
                            })

                        # Alighted: speed dropped AND near the stop
                        if gps_speed < 5.0 and dist_to_alight < 150.0 and self._alight_announced:
                            logger.info(f"Alighted at transit stop (speed={gps_speed:.1f}, dist={dist_to_alight:.0f}m)")
                            advanced = await self._advance_to_next_leg()
                            if not advanced:
                                # Last leg — arrived at destination
                                self.state = NavState.ARRIVED
                                self._running = False
                                await self._speak("You've arrived at your destination.")
                                self._fire_nav_event("arrived", {"destination": self.route.destination})
                                break
                            await asyncio.sleep(interval)
                            continue

                    # Fallback: if speed drops to walking and we don't have arrival pos
                    elif gps_speed < 5.0 and self._on_vehicle_announced:
                        # Check if we've been at walking speed for a while (avoid false triggers from traffic stops)
                        if not hasattr(self, '_vehicle_slow_start') or self._vehicle_slow_start is None:
                            self._vehicle_slow_start = time.monotonic()
                        elif time.monotonic() - self._vehicle_slow_start > 30.0:
                            logger.info("Vehicle speed dropped for 30s, likely alighted")
                            self._vehicle_slow_start = None
                            advanced = await self._advance_to_next_leg()
                            if not advanced:
                                self.state = NavState.ARRIVED
                                self._running = False
                                await self._speak("You've arrived at your destination.")
                                self._fire_nav_event("arrived", {"destination": self.route.destination})
                                break
                    else:
                        # Reset slow timer if speed picks back up
                        self._vehicle_slow_start = None

                    await asyncio.sleep(interval)
                    continue

                # Record breadcrumb
                now = time.monotonic()
                if now - self._last_breadcrumb_time >= self._breadcrumb_interval:
                    self._breadcrumbs.append((current_pos[0], current_pos[1], time.time()))
                    self._last_breadcrumb_time = now

                # Ensure outdoor mode when GPS is available
                # For transit routes, the leg state machine handles vehicle detection
                # Only use the simple speed-based transit detection on non-transit routes
                gps_fix = self.gps.get_fix() if self.gps else None
                gps_speed = gps_fix.speed_kmh if gps_fix and hasattr(gps_fix, 'speed_kmh') else 0.0
                if not (self.route and self.route.is_transit):
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
                else:
                    # Transit route: ensure outdoor mode for walking legs
                    if self.state == NavState.NAVIGATING and self.mode != NavMode.OUTDOOR:
                        self._set_mode(NavMode.OUTDOOR)

                # 2. Get current heading from IMU
                user_heading = self._get_user_heading()

                # 3. Current waypoint (use leg-specific waypoints for transit routes)
                active_wps = self._leg_waypoints if self._leg_waypoints else self.route.waypoints
                wp = active_wps[self.current_waypoint_idx]

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
                    if self.mode == NavMode.INDOOR:
                        # Indoor: keep beacon pinging at last Gemini-set direction
                        if hasattr(self.spatial_audio, 'tick_beacon'):
                            self.spatial_audio.tick_beacon()
                    else:
                        hrtf_pos = angle_to_hrtf_position(rel_angle, dist_to_wp)
                        # Update beacon via SpatialAudioManager's API
                        if Position3D and hasattr(self.spatial_audio, '_update_beacon_position'):
                            pos3d = Position3D(
                                x=hrtf_pos[0], y=hrtf_pos[1], z=hrtf_pos[2],
                                distance_meters=dist_to_wp
                            )
                            self.spatial_audio._update_beacon_position(pos3d)
                        # Degraded beacon: reduce volume when GPS is stale/inaccurate
                        beacon_src = getattr(self.spatial_audio, '_beacon_source', None)
                        if beacon_src and hasattr(self.spatial_audio, 'comfort'):
                            if self._gps_accuracy > 500:
                                # Stale/last-known GPS — quiet beacon signals uncertainty
                                beacon_src.set_gain(
                                    self.spatial_audio.comfort.master_volume * 0.2
                                )
                            else:
                                # Normal GPS — full beacon volume
                                beacon_src.set_gain(
                                    self.spatial_audio.comfort.master_volume *
                                    self.spatial_audio.comfort.beacon_volume
                                )

                # 7. Check for upcoming turn announcement
                await self._check_turn_announcement(current_pos, dist_to_wp)

                # 8. Check road crossing
                await self._check_road_crossing(wp)

                # 9. Determine if current waypoint is the final one
                # For transit routes with leg waypoints, check against the leg's waypoints
                active_waypoints = self._leg_waypoints if self._leg_waypoints else self.route.waypoints
                is_leg_final = self.current_waypoint_idx >= len(active_waypoints) - 1
                is_route_final = (
                    is_leg_final
                    and (not self.route.is_transit or not self.route.legs
                         or self.current_leg_idx >= len(self.route.legs) - 1)
                )

                # 10. Check approaching destination (within 50m) — only for truly final destination
                if is_route_final and not self._approaching_dest_announced:
                    final_wp = active_waypoints[-1]
                    dist_to_dest = haversine_distance(
                        current_pos[0], current_pos[1], final_wp.lat, final_wp.lng
                    )
                    if dist_to_dest < 50.0:
                        self._approaching_dest_announced = True
                        self._fire_nav_event("approaching_destination", {
                            "destination": self.route.destination,
                            "distance_m": round(dist_to_dest, 0),
                        })

                # 11. Check waypoint arrival (scale threshold with GPS accuracy)
                base_threshold = self.DESTINATION_THRESHOLD if is_route_final else self.ARRIVAL_THRESHOLD
                # With poor GPS (e.g. phone GPS ±100m), widen the arrival zone
                accuracy_boost = max(0.0, self._gps_accuracy * 0.3) if self._gps_accuracy > 30 else 0.0
                threshold = base_threshold + accuracy_boost

                # Gate waypoint advancement on GPS quality: if accuracy is worse
                # than the distance to the waypoint, GPS jitter is likely faking movement.
                # Still allow final-destination arrival (user might genuinely be there).
                if (dist_to_wp < threshold
                        and (is_route_final or self._gps_accuracy < dist_to_wp * 1.5)):
                    if is_leg_final:
                        if is_route_final:
                            # Arrived at final destination
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
                            # End of current leg on a multi-leg transit route — advance
                            logger.info(f"Walking leg {self.current_leg_idx} complete, advancing to next leg")
                            advanced = await self._advance_to_next_leg()
                            if not advanced:
                                # Shouldn't happen (is_route_final would be True), but safety net
                                self.state = NavState.ARRIVED
                                self._running = False
                                await self._speak("You've arrived at your destination.")
                                self._fire_nav_event("arrived", {"destination": self.route.destination})
                                break
                    else:
                        # Rate-limit waypoint advancement: max 1 per second to
                        # prevent GPS jitter (±5-15m) from cascading through
                        # closely-spaced polyline waypoints.
                        now_mono = time.monotonic()
                        if now_mono - self._last_waypoint_advance_time < 1.0:
                            # Skip advancement this cycle — we just advanced
                            pass
                        else:
                            # Advance to next waypoint
                            self.current_waypoint_idx += 1
                            self._last_waypoint_advance_time = now_mono
                            next_wp = active_waypoints[self.current_waypoint_idx]
                            if next_wp.instruction and next_wp.is_turn:
                                await self._speak_turn(next_wp)  # Silent — fires event only
                            self._fire_nav_event("waypoint_reached", {
                                "index": self.current_waypoint_idx,
                                "total": len(active_waypoints),
                                "next_instruction": next_wp.instruction,
                            })
                            logger.debug(
                                f"Waypoint {self.current_waypoint_idx}/{len(active_waypoints)} reached"
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
        """Get current GPS position (lat, lng) or None.
        
        Accepts all quality levels including q=0 (phone GPS ±100m).
        Consumers should check self._gps_accuracy for precision-sensitive logic.
        """
        if not self.gps:
            return None
        fix = self.gps.get_fix()
        if fix is None:
            # Try last-known position (indoor/stale fallback)
            if hasattr(self.gps, 'get_last_known_fix'):
                lk = self.gps.get_last_known_fix()
                if lk:
                    self._gps_accuracy = 9999  # Mark as very rough
                    return (lk.latitude, lk.longitude)
            return None
        # Store accuracy for threshold scaling
        self._gps_accuracy = getattr(fix, 'accuracy', 999)
        return (fix.latitude, fix.longitude)

    def _get_user_heading(self) -> float:
        """
        Get user's facing direction in degrees (0-360).
        Priority: IMU (calibrated) > GPS course > breadcrumb heading > last known.
        """
        # Primary: BNO055 IMU heading (only if magnetometer calibrated)
        if self.imu:
            heading = self.imu.get_heading()
            if heading is not None:
                # Check magnetometer calibration if available
                cal = getattr(self.imu, 'get_calibration', lambda: None)()
                mag_cal = cal.get('mag', 0) if isinstance(cal, dict) else -1
                if mag_cal >= 1:  # At least partially calibrated
                    self._last_known_heading = heading
                    return heading
                elif mag_cal == 0:
                    logger.debug("IMU magnetometer uncalibrated (M0), using fallback")

        # Fallback 1: GPS course-over-ground (only reliable when moving)
        if self.gps:
            fix = self.gps.get_fix()
            if fix and fix.speed_kmh > 1.0:
                self._last_known_heading = fix.heading
                return fix.heading

        # Fallback 2: Breadcrumb-based heading (direction of recent travel)
        if len(self._breadcrumbs) >= 2:
            p1 = self._breadcrumbs[-2]
            p2 = self._breadcrumbs[-1]
            dist = haversine_distance(p1[0], p1[1], p2[0], p2[1])
            if dist > 2.0:  # Only if moved > 2m
                bc_heading = bearing_between(p1[0], p1[1], p2[0], p2[1])
                self._last_known_heading = bc_heading
                return bc_heading

        # Fallback 3: Last known heading (better than snapping to north)
        return getattr(self, '_last_known_heading', 0.0)

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
                await self.tts.speak_async(text)
            except Exception as e:
                logger.warning(f"TTS failed: {e}")
        else:
            logger.info(f"NAV VOICE: {text}")

    async def _speak_turn(self, wp: Waypoint):
        """Handle a turn waypoint.
        
        Voice is intentionally silent — the 3D audio beam direction
        change IS the guidance. Gemini receives the turn event via
        context injection and can provide voice context if needed.
        """
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
            # Beam direction change IS the guidance — no voice needed
            self._fire_nav_event("turn_executed", {
                "direction": direction,
                "instruction": wp.instruction,
            })
            logger.debug(f"Turn {direction} — beam redirected (silent)")

    async def _check_turn_announcement(
        self, current_pos: Tuple[float, float], dist_to_current: float
    ):
        """Announce upcoming turns before reaching the waypoint."""
        if not self.route:
            return

        # Look ahead for turns (use leg waypoints for transit routes)
        active_wps = self._leg_waypoints if self._leg_waypoints else self.route.waypoints
        for i in range(self.current_waypoint_idx, min(
            self.current_waypoint_idx + 3, len(active_wps)
        )):
            wp = active_wps[i]
            if not wp.is_turn or i in self._turn_announced:
                continue

            dist = haversine_distance(current_pos[0], current_pos[1], wp.lat, wp.lng)
            if dist < self.TURN_ANNOUNCE_DISTANCE:
                self._turn_announced.add(i)
                maneuver = wp.maneuver
                direction = "left" if "left" in maneuver else "right" if "right" in maneuver else maneuver
                # No voice — beam direction change IS the guidance.
                # Fire event so Gemini receives context and can speak if needed.
                self._fire_nav_event("approaching_turn", {
                    "direction": direction,
                    "distance_m": round(dist, 0),
                    "instruction": wp.instruction,
                })
                logger.debug(f"Approaching turn: {direction} in {dist:.0f}m (beam guides)")
                break  # One announcement at a time

    async def _check_road_crossing(self, wp: Waypoint):
        """Check if current waypoint indicates a road crossing.
        
        Enhanced with YOLO: detects vehicles/traffic lights near crossing.
        """
        if self._road_crossing_active:
            return

        instruction_lower = wp.instruction.lower()
        if any(kw in instruction_lower for kw in self.ROAD_CROSSING_KEYWORDS):
            # Enrich with YOLO vehicle/traffic light detections
            road_objects = []
            vehicle_classes = {"car", "truck", "bus", "motorcycle", "bicycle", "traffic light"}
            for det in self._latest_detections:
                cls = det.get('class', '')
                if cls in vehicle_classes:
                    dist = det.get('distance_m', 999)
                    road_objects.append(f"{cls}({dist:.0f}m)")
            
            if road_objects:
                warning = f"Road crossing detected. I see: {', '.join(road_objects[:5])}. Check it's safe."
            else:
                warning = "Road crossing detected. Check it's safe before crossing."
            await self._speak(warning)
            # Pause beacon during road crossing (NAVIGATION_MASTER_PLAN §10)
            await self.pause_navigation()
            self._fire_nav_event("road_crossing", {
                "instruction": wp.instruction,
                "vehicles_detected": road_objects[:5],
            })

    # -------------------------------------------------
    # VISION CONTEXT
    # -------------------------------------------------

    def update_vision_context(self, detections: List[Dict[str, Any]], depth_map=None):
        """Update latest YOLO detections and depth map for nav-aware reasoning.
        
        Called each frame from the main loop. Data is consumed by
        get_context_string() and future road-crossing / obstacle logic.
        """
        self._latest_detections = detections or []
        self._latest_depth_map = depth_map

    def get_vision_summary(self) -> str:
        """Return a compact text summary of current detections + depth for Gemini context."""
        parts = []
        
        # Object detections (closest per class, max 8)
        if self._latest_detections:
            by_class: Dict[str, float] = {}
            for det in self._latest_detections:
                cls = det.get('class', 'unknown')
                dist = det.get('distance_m', 999)
                if cls not in by_class or dist < by_class[cls]:
                    by_class[cls] = dist
            obj_parts = [f"{cls}({d:.1f}m)" for cls, d in sorted(by_class.items(), key=lambda x: x[1])[:8]]
            parts.append("Nearby: " + ", ".join(obj_parts))
        
        # Depth directional cues (left/center/right clearance)
        if self._latest_depth_map is not None:
            try:
                dm = self._latest_depth_map
                h, w = dm.shape[:2]
                third = w // 3
                # Inverse depth: higher = closer, so lower mean = more clearance
                left_mean = float(dm[:, :third].mean())
                center_mean = float(dm[:, third:2*third].mean())
                right_mean = float(dm[:, 2*third:].mean())
                # Report which direction has more clearance (lower depth value)
                min_val = min(left_mean, center_mean, right_mean)
                if min_val == center_mean:
                    parts.append("Path clear ahead")
                elif min_val == left_mean:
                    parts.append("More space to left")
                else:
                    parts.append("More space to right")
            except Exception:
                pass
        
        return " | ".join(parts) if parts else ""

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
        """Fire a navigation event to Gemini via callback, enriched with vision context."""
        if self.on_nav_event:
            try:
                enriched = dict(details or {})
                # Attach vision summary for Gemini awareness
                vision = self.get_vision_summary()
                if vision:
                    enriched["vision"] = vision
                self.on_nav_event(event, enriched)
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
        # Append vision summary if available
        vision = self.get_vision_summary()
        if vision:
            parts.append(vision)
        return " | ".join(parts)

    # -------------------------------------------------
    # CLEANUP
    # -------------------------------------------------

    async def shutdown(self):
        """Clean shutdown."""
        await self.stop_navigation()
        logger.info("NavigationEngine shut down")
