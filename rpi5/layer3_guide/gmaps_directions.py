"""
Google Maps Directions API wrapper.

Standalone module for fetching walking and transit routes. Extracted from
navigation_engine.py so that Gemini Live function-calling can fetch directions
directly without going through the engine's state machine.

The engine still uses this module internally via thin wrappers
(NavigationEngine.fetch_route / fetch_transit_route), so caching and state
transitions stay in one place while the raw API calls live here.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Keep in sync with NavigationEngine.MAX_WAYPOINT_SPACING
MAX_WAYPOINT_SPACING = 25.0  # meters
USER_AGENT = "ProjectCortex/2.0"
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
HTTP_TIMEOUT_S = 10


def _nav_types():
    """Deferred import to avoid circular imports with navigation_engine."""
    from rpi5.layer3_guide.navigation_engine import (
        NavRoute, Waypoint, RouteLeg, TransitInfo, LegType,
        decode_polyline, haversine_distance,
    )
    return NavRoute, Waypoint, RouteLeg, TransitInfo, LegType, decode_polyline, haversine_distance


def sanitize_location(loc: str) -> str:
    """
    Clean up a location string for Google Maps API.

    - Strips trailing punctuation from STT artifacts ("North Point." → "North Point")
    - Appends ", Singapore" to text addresses that don't already specify a region
      (prevents Google resolving "North Point" to Hong Kong instead of Northpoint City SG)
    - Leaves "lat,lng" coordinate strings untouched
    """
    loc = loc.strip()
    loc = loc.rstrip(".,;:!?")
    if "," in loc:
        parts = loc.split(",")
        try:
            float(parts[0].strip())
            float(parts[1].strip())
            return loc
        except (ValueError, IndexError):
            pass
    loc_lower = loc.lower()
    if "singapore" in loc_lower or "sg" in loc_lower:
        return loc
    return f"{loc}, Singapore"


def interpolate_waypoints(waypoints: List[Any], max_spacing_m: float = MAX_WAYPOINT_SPACING) -> List[Any]:
    """Insert extra waypoints where gaps exceed max_spacing_m."""
    _, Waypoint, _, _, _, _, haversine_distance = _nav_types()
    if len(waypoints) < 2:
        return waypoints
    result = [waypoints[0]]
    for i in range(1, len(waypoints)):
        prev = result[-1]
        curr = waypoints[i]
        dist = haversine_distance(prev.lat, prev.lng, curr.lat, curr.lng)
        if dist > max_spacing_m:
            n_segments = int(math.ceil(dist / max_spacing_m))
            for j in range(1, n_segments):
                frac = j / n_segments
                interp_lat = prev.lat + (curr.lat - prev.lat) * frac
                interp_lng = prev.lng + (curr.lng - prev.lng) * frac
                result.append(Waypoint(lat=interp_lat, lng=interp_lng))
        result.append(curr)
    return result


def _http_get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"🧭 [GMAPS] HTTP request FAILED: {e}")
        return None


def fetch_walking_route_sync(api_key: str, origin: str, destination: str):
    """
    Fetch walking directions. Returns NavRoute or None on failure.
    Blocking — wrap in executor for async callers.
    """
    NavRoute, Waypoint, _, _, _, decode_polyline, _ = _nav_types()

    if not api_key:
        logger.error("No Google Maps API key configured")
        return None

    origin = sanitize_location(origin)
    destination = sanitize_location(destination)

    params = urllib.parse.urlencode({
        "origin": origin,
        "destination": destination,
        "mode": "walking",
        "region": "sg",
        "key": api_key,
    })
    url = f"{DIRECTIONS_URL}?{params}"
    logger.info(f"🧭 [GMAPS] walking request: origin='{origin}', destination='{destination}'")

    data = _http_get_json(url)
    if data is None:
        return None

    logger.info(f"🧭 [GMAPS] walking response status: {data.get('status')}")
    if data.get("status") != "OK" or not data.get("routes"):
        logger.error(
            f"🧭 [GMAPS] walking API error: {data.get('status')}, "
            f"geocoded_waypoints={data.get('geocoded_waypoints', 'N/A')}"
        )
        return None

    route_data = data["routes"][0]
    legs = route_data.get("legs", [])
    if not legs:
        return None

    leg = legs[0]
    waypoints: List[Any] = []

    for step in leg.get("steps", []):
        start = step.get("start_location", {})
        end = step.get("end_location", {})
        instruction = re.sub(r"<[^>]+>", "", step.get("html_instructions", ""))
        maneuver = step.get("maneuver", "")
        distance_m = step.get("distance", {}).get("value", 0)

        is_turn = maneuver in (
            "turn-left", "turn-right", "turn-slight-left", "turn-slight-right",
            "turn-sharp-left", "turn-sharp-right", "uturn-left", "uturn-right",
        )

        step_polyline = step.get("polyline", {}).get("points", "")
        if step_polyline:
            points = decode_polyline(step_polyline)
            for i, (plat, plng) in enumerate(points):
                waypoints.append(Waypoint(
                    lat=plat,
                    lng=plng,
                    instruction=instruction if i == 0 else "",
                    distance_m=distance_m / max(len(points), 1) if i == 0 else 0,
                    maneuver=maneuver if i == 0 else "",
                    is_turn=is_turn if i == 0 else False,
                ))
        else:
            waypoints.append(Waypoint(
                lat=start.get("lat", 0),
                lng=start.get("lng", 0),
                instruction=instruction,
                distance_m=distance_m,
                maneuver=maneuver,
                is_turn=is_turn,
            ))

    waypoints = interpolate_waypoints(waypoints)

    import time as _time
    route = NavRoute(
        origin=origin,
        destination=destination,
        waypoints=waypoints,
        total_distance_m=leg.get("distance", {}).get("value", 0),
        total_duration_s=leg.get("duration", {}).get("value", 0),
        polyline=route_data.get("overview_polyline", {}).get("points", ""),
        fetched_at=_time.time(),
    )
    logger.info(
        f"🧭 [GMAPS] walking route: {len(waypoints)} waypoints, "
        f"{route.total_distance_m:.0f}m, ~{route.total_duration_s / 60:.0f}min"
    )
    return route


def fetch_transit_route_sync(api_key: str, origin: str, destination: str):
    """
    Fetch transit (bus/MRT + walking) directions. Returns NavRoute or None.
    Falls back to walking-only if transit returns no results.
    Blocking — wrap in executor for async callers.
    """
    NavRoute, Waypoint, RouteLeg, TransitInfo, LegType, decode_polyline, _ = _nav_types()

    if not api_key:
        logger.error("No Google Maps API key configured")
        return None

    origin = sanitize_location(origin)
    destination = sanitize_location(destination)

    params = urllib.parse.urlencode({
        "origin": origin,
        "destination": destination,
        "mode": "transit",
        "transit_mode": "bus|rail",
        "region": "sg",
        "key": api_key,
    })
    url = f"{DIRECTIONS_URL}?{params}"
    logger.info(f"🧭 [GMAPS] transit request: origin='{origin}', dest='{destination}'")

    data = _http_get_json(url)
    if data is None:
        return fetch_walking_route_sync(api_key, origin, destination)

    if data.get("status") != "OK" or not data.get("routes"):
        logger.warning(f"🧭 [GMAPS] transit API returned {data.get('status')} — falling back to walking")
        return fetch_walking_route_sync(api_key, origin, destination)

    route_data = data["routes"][0]
    api_legs = route_data.get("legs", [])
    if not api_legs:
        return fetch_walking_route_sync(api_key, origin, destination)

    api_leg = api_legs[0]
    route_legs: List[Any] = []
    all_waypoints: List[Any] = []

    has_transit = False
    for step in api_leg.get("steps", []):
        travel_mode = step.get("travel_mode", "WALKING")
        step_start = step.get("start_location", {})
        step_end = step.get("end_location", {})
        step_dist = step.get("distance", {}).get("value", 0)
        step_dur = step.get("duration", {}).get("value", 0)
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
                departure_stop_code="",
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

            all_waypoints.append(Waypoint(
                lat=transit_info.arrival_lat,
                lng=transit_info.arrival_lng,
                instruction=f"Alight at {transit_info.arrival_stop}",
            ))

        else:
            leg_waypoints: List[Any] = []
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

            leg_waypoints = interpolate_waypoints(leg_waypoints)

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
        logger.info("🧭 [GMAPS] transit route is all-walking — using walking mode")
        return fetch_walking_route_sync(api_key, origin, destination)

    import time as _time
    route = NavRoute(
        origin=origin,
        destination=destination,
        waypoints=all_waypoints,
        legs=route_legs,
        total_distance_m=api_leg.get("distance", {}).get("value", 0),
        total_duration_s=api_leg.get("duration", {}).get("value", 0),
        polyline=route_data.get("overview_polyline", {}).get("points", ""),
        fetched_at=_time.time(),
        is_transit=True,
    )

    leg_summary = []
    for lg in route_legs:
        if lg.leg_type == LegType.WALKING:
            leg_summary.append(f"Walk {lg.distance_m:.0f}m")
        elif lg.transit_info:
            leg_summary.append(f"{lg.leg_type.value.upper()} {lg.transit_info.service_no} ({lg.transit_info.num_stops} stops)")
    logger.info(
        f"🧭 [GMAPS] transit route: {' → '.join(leg_summary)}, "
        f"{route.total_distance_m:.0f}m total, ~{route.total_duration_s / 60:.0f}min"
    )
    return route


def _nav_route_to_dict(route) -> Dict[str, Any]:
    """Convert NavRoute to a JSON-serializable dict suitable for a Gemini tool response."""
    result: Dict[str, Any] = {
        "success": True,
        "origin": route.origin,
        "destination": route.destination,
        "total_distance_m": route.total_distance_m,
        "total_duration_s": route.total_duration_s,
        "is_transit": route.is_transit,
        "waypoints": [[w.lat, w.lng] for w in route.waypoints],
        "steps": [
            {
                "instruction": w.instruction,
                "distance_m": w.distance_m,
                "maneuver": w.maneuver,
                "is_turn": w.is_turn,
            }
            for w in route.waypoints if w.instruction
        ],
    }
    if route.is_transit and route.legs:
        result["legs"] = []
        for lg in route.legs:
            leg_dict: Dict[str, Any] = {
                "leg_type": lg.leg_type.value,
                "distance_m": lg.distance_m,
                "duration_s": lg.duration_s,
                "instruction": lg.instruction,
                "start_lat": lg.start_lat,
                "start_lng": lg.start_lng,
                "end_lat": lg.end_lat,
                "end_lng": lg.end_lng,
            }
            if lg.waypoints:
                leg_dict["waypoints"] = [[w.lat, w.lng] for w in lg.waypoints]
            if lg.transit_info:
                ti = lg.transit_info
                leg_dict["transit"] = {
                    "service_no": ti.service_no,
                    "line_name": ti.line_name,
                    "departure_stop": ti.departure_stop,
                    "arrival_stop": ti.arrival_stop,
                    "num_stops": ti.num_stops,
                    "headsign": ti.headsign,
                    "departure_lat": ti.departure_lat,
                    "departure_lng": ti.departure_lng,
                    "arrival_lat": ti.arrival_lat,
                    "arrival_lng": ti.arrival_lng,
                }
            result["legs"].append(leg_dict)
    return result


async def get_directions(
    api_key: str,
    origin: str,
    destination: str,
    mode: str = "walking",
) -> Dict[str, Any]:
    """
    Async Gemini-facing wrapper. Returns a dict with route data or an error.

    mode: "walking", "transit", or "driving". "driving" falls through to walking
    (not used by this project).
    """
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY not configured"}

    loop = asyncio.get_running_loop()
    if mode == "transit":
        route = await loop.run_in_executor(None, fetch_transit_route_sync, api_key, origin, destination)
    else:
        route = await loop.run_in_executor(None, fetch_walking_route_sync, api_key, origin, destination)

    if route is None or not route.waypoints:
        return {"error": "NO_ROUTE_FOUND", "origin": origin, "destination": destination}

    return _nav_route_to_dict(route)
