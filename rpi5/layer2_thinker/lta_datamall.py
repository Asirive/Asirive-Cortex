"""
LTA DataMall Client — Real-Time Bus Arrival for Singapore

Provides real-time bus arrival information using the LTA DataMall API v3.
Used by Gemini function calling to answer "which bus is coming?" queries.

API Docs: https://datamall.lta.gov.sg/content/datamall/en/dynamic-data.html
Auth: Free AccountKey from https://datamall.lta.gov.sg/content/datamall/en/request-for-api.html

Author: Haziq (@IRSPlays)
Date: March 2026
Project: Cortex v2.0 — YIA 2026
"""

import logging
import math
import os
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# LTA DataMall v3 endpoints
BUS_ARRIVAL_URL = "http://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival"
BUS_STOPS_URL = "http://datamall2.mytransport.sg/ltaodataservice/BusStops"
BUS_SERVICES_URL = "http://datamall2.mytransport.sg/ltaodataservice/BusServices"

# In-memory cache for BusStops (~5200 records, rarely changes — 24h TTL)
_BUS_STOPS_CACHE: Optional[List[Dict[str, Any]]] = None
_BUS_STOPS_CACHE_AT: float = 0.0
_BUS_STOPS_TTL_S: float = 24 * 3600

# In-memory cache for BusServices (24h TTL)
_BUS_SERVICES_CACHE: Optional[List[Dict[str, Any]]] = None
_BUS_SERVICES_CACHE_AT: float = 0.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two GPS coordinates."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_api_key() -> Optional[str]:
    """Get LTA DataMall API key from environment or config."""
    key = os.environ.get("LTA_API_KEY")
    if key:
        return key
    # Try loading from config.yaml
    try:
        import yaml
        from pathlib import Path
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            key = cfg.get("lta", {}).get("api_key", "")
            if key and key != "YOUR_LTA_API_KEY":
                return key
    except Exception:
        pass
    return None


async def get_bus_arrivals(bus_stop_code: str) -> Dict[str, Any]:
    """
    Fetch real-time bus arrival data for a given bus stop.
    
    Args:
        bus_stop_code: 5-digit Singapore bus stop code (e.g. "75009")
        
    Returns:
        Dict with "services" list, each containing:
          - service_no: bus number (str)
          - next_bus_min: minutes to next bus (int or "Arr" or "N/A")
          - next_bus_2_min: minutes to 2nd bus
          - next_bus_load: "SEA" (seats), "SDA" (standing), "LSD" (limited)
          - next_bus_type: "SD" (single deck), "DD" (double deck), "BD" (bendy)
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "LTA_API_KEY not configured. Set environment variable or add to config.yaml under lta.api_key"}

    try:
        import aiohttp
    except ImportError:
        # Fallback to synchronous requests if aiohttp unavailable
        return _get_bus_arrivals_sync(bus_stop_code, api_key)

    headers = {"AccountKey": api_key, "accept": "application/json"}
    params = {"BusStopCode": bus_stop_code}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                BUS_ARRIVAL_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return {"error": f"LTA API returned HTTP {resp.status}"}
                data = await resp.json()
    except Exception as e:
        logger.error(f"LTA DataMall request failed: {e}")
        return {"error": f"Request failed: {e}"}

    return _parse_response(data, bus_stop_code)


def _get_bus_arrivals_sync(bus_stop_code: str, api_key: str) -> Dict[str, Any]:
    """Synchronous fallback using urllib (no extra dependencies)."""
    import json
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    url = f"{BUS_ARRIVAL_URL}?BusStopCode={bus_stop_code}"
    req = Request(url, headers={"AccountKey": api_key, "accept": "application/json"})

    try:
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, TimeoutError) as e:
        logger.error(f"LTA DataMall sync request failed: {e}")
        return {"error": f"Request failed: {e}"}

    return _parse_response(data, bus_stop_code)


def _parse_response(data: Dict[str, Any], bus_stop_code: str) -> Dict[str, Any]:
    """Parse LTA DataMall API response into a clean format."""
    services_raw = data.get("Services", [])
    if not services_raw:
        return {
            "bus_stop_code": bus_stop_code,
            "services": [],
            "summary": f"No bus services found for stop {bus_stop_code}",
        }

    services = []
    for svc in services_raw:
        service_no = svc.get("ServiceNo", "?")
        next1 = svc.get("NextBus", {})
        next2 = svc.get("NextBus2", {})

        services.append({
            "service_no": service_no,
            "next_bus_min": _eta_minutes(next1.get("EstimatedArrival", "")),
            "next_bus_2_min": _eta_minutes(next2.get("EstimatedArrival", "")),
            "next_bus_load": _load_label(next1.get("Load", "")),
            "next_bus_type": next1.get("Type", ""),
        })

    # Sort by ETA (arriving soonest first)
    services.sort(key=lambda s: s["next_bus_min"] if isinstance(s["next_bus_min"], int) else 999)

    # Build human-readable summary
    parts = []
    for svc in services[:5]:  # Top 5
        eta = svc["next_bus_min"]
        if isinstance(eta, int):
            if eta <= 0:
                parts.append(f"Bus {svc['service_no']} arriving now")
            else:
                parts.append(f"Bus {svc['service_no']} in {eta} min")
        else:
            parts.append(f"Bus {svc['service_no']}: {eta}")

    return {
        "bus_stop_code": bus_stop_code,
        "services": services,
        "summary": ". ".join(parts) if parts else "No upcoming buses",
    }


def _eta_minutes(estimated_arrival: str) -> Any:
    """Convert ISO timestamp to minutes from now."""
    if not estimated_arrival:
        return "N/A"
    try:
        from datetime import datetime, timezone
        # LTA returns ISO format: "2026-03-27T14:30:00+08:00"
        eta_dt = datetime.fromisoformat(estimated_arrival)
        now = datetime.now(timezone.utc)
        diff = (eta_dt - now).total_seconds() / 60
        minutes = max(0, int(diff))
        return minutes if minutes > 0 else "Arr"
    except (ValueError, TypeError):
        return "N/A"


def _load_label(load_code: str) -> str:
    """Convert load code to human-readable label."""
    return {
        "SEA": "seats available",
        "SDA": "standing only",
        "LSD": "very crowded",
    }.get(load_code, load_code)


# =====================================================
# BUS STOPS (static reference data, paginated)
# =====================================================

def _fetch_all_bus_stops_sync(api_key: str) -> List[Dict[str, Any]]:
    """
    Fetch the full BusStops list. LTA paginates 500 records at a time via $skip.
    Returns [] on failure. Results are cached by caller.
    """
    import json
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    all_stops: List[Dict[str, Any]] = []
    skip = 0
    headers = {"AccountKey": api_key, "accept": "application/json"}
    while True:
        url = f"{BUS_STOPS_URL}?$skip={skip}"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"LTA BusStops HTTP {resp.status} at skip={skip}")
                    break
                data = json.loads(resp.read().decode())
        except (URLError, TimeoutError) as e:
            logger.error(f"LTA BusStops fetch failed at skip={skip}: {e}")
            break

        values = data.get("value", [])
        if not values:
            break
        all_stops.extend(values)
        if len(values) < 500:
            break
        skip += 500
        # Hard safety cap to prevent runaway paging
        if skip > 20000:
            logger.warning("LTA BusStops pagination cap hit")
            break

    logger.info(f"LTA BusStops fetched: {len(all_stops)} records")
    return all_stops


def _fetch_all_bus_services_sync(api_key: str) -> List[Dict[str, Any]]:
    """Fetch the full BusServices list (paginated, cached)."""
    import json
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    all_svcs: List[Dict[str, Any]] = []
    skip = 0
    headers = {"AccountKey": api_key, "accept": "application/json"}
    while True:
        url = f"{BUS_SERVICES_URL}?$skip={skip}"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    break
                data = json.loads(resp.read().decode())
        except (URLError, TimeoutError) as e:
            logger.error(f"LTA BusServices fetch failed at skip={skip}: {e}")
            break

        values = data.get("value", [])
        if not values:
            break
        all_svcs.extend(values)
        if len(values) < 500:
            break
        skip += 500
        if skip > 50000:
            break

    logger.info(f"LTA BusServices fetched: {len(all_svcs)} records")
    return all_svcs


def _get_cached_bus_stops(api_key: str) -> List[Dict[str, Any]]:
    global _BUS_STOPS_CACHE, _BUS_STOPS_CACHE_AT
    now = time.time()
    if _BUS_STOPS_CACHE is not None and (now - _BUS_STOPS_CACHE_AT) < _BUS_STOPS_TTL_S:
        return _BUS_STOPS_CACHE
    stops = _fetch_all_bus_stops_sync(api_key)
    if stops:
        _BUS_STOPS_CACHE = stops
        _BUS_STOPS_CACHE_AT = now
    return stops or (_BUS_STOPS_CACHE or [])


def _get_cached_bus_services(api_key: str) -> List[Dict[str, Any]]:
    global _BUS_SERVICES_CACHE, _BUS_SERVICES_CACHE_AT
    now = time.time()
    if _BUS_SERVICES_CACHE is not None and (now - _BUS_SERVICES_CACHE_AT) < _BUS_STOPS_TTL_S:
        return _BUS_SERVICES_CACHE
    svcs = _fetch_all_bus_services_sync(api_key)
    if svcs:
        _BUS_SERVICES_CACHE = svcs
        _BUS_SERVICES_CACHE_AT = now
    return svcs or (_BUS_SERVICES_CACHE or [])


async def get_nearby_bus_stops(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Return bus stops within radius_m of (lat, lon), sorted by distance.

    Args:
        lat, lon: user position
        radius_m: search radius in meters (default 500m)
        limit: max stops to return (default 10)

    Returns:
        {"stops": [{code, description, road, lat, lon, distance_m}, ...]}
        or {"error": "..."}
    """
    import asyncio

    api_key = _get_api_key()
    if not api_key:
        return {"error": "LTA_API_KEY not configured"}

    loop = asyncio.get_running_loop()
    stops = await loop.run_in_executor(None, _get_cached_bus_stops, api_key)
    if not stops:
        return {"error": "Failed to fetch BusStops reference data"}

    nearby = []
    for s in stops:
        slat = s.get("Latitude")
        slon = s.get("Longitude")
        if slat is None or slon is None:
            continue
        d = _haversine_m(lat, lon, slat, slon)
        if d <= radius_m:
            nearby.append({
                "bus_stop_code": s.get("BusStopCode", ""),
                "description": s.get("Description", ""),
                "road": s.get("RoadName", ""),
                "lat": slat,
                "lon": slon,
                "distance_m": round(d, 1),
            })

    nearby.sort(key=lambda x: x["distance_m"])
    nearby = nearby[: max(1, int(limit))]

    return {
        "success": True,
        "count": len(nearby),
        "radius_m": radius_m,
        "stops": nearby,
    }


async def get_all_services_at_stop(bus_stop_code: str) -> Dict[str, Any]:
    """
    Return all bus services at a given stop, combined with next-arrival data.

    Pulls live arrivals (same source as get_bus_arrivals) and enriches each
    service with its route description from BusServices if available.
    """
    import asyncio

    arrivals = await get_bus_arrivals(bus_stop_code)
    if "error" in arrivals:
        return arrivals

    api_key = _get_api_key()
    services_ref: List[Dict[str, Any]] = []
    if api_key:
        loop = asyncio.get_running_loop()
        services_ref = await loop.run_in_executor(None, _get_cached_bus_services, api_key)

    # Build service_no → reference map for this stop (origin/destination labels)
    ref_by_svc: Dict[str, Dict[str, Any]] = {}
    for s in services_ref:
        svc_no = s.get("ServiceNo", "")
        if not svc_no:
            continue
        # Keep the first occurrence (direction 1) as the default
        ref_by_svc.setdefault(svc_no, {
            "operator": s.get("Operator", ""),
            "origin_code": s.get("OriginCode", ""),
            "destination_code": s.get("DestinationCode", ""),
            "category": s.get("Category", ""),
        })

    enriched = []
    for svc in arrivals.get("services", []):
        svc_copy = dict(svc)
        ref = ref_by_svc.get(svc_copy.get("service_no", ""))
        if ref:
            svc_copy["route"] = ref
        enriched.append(svc_copy)

    return {
        "success": True,
        "bus_stop_code": bus_stop_code,
        "count": len(enriched),
        "services": enriched,
        "summary": arrivals.get("summary", ""),
    }
