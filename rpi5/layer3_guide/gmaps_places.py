"""
Google Maps Places API wrapper.

Used by Gemini Live function-calling to disambiguate destinations before
calling get_directions. Example: user says "navigate to the library" —
Gemini calls search_places("library", near_lat=<gps>, near_lon=<gps>) and
picks the best match before calling get_directions with a concrete place.

Uses the legacy Places Text Search + Details endpoints (same API key as
Directions). No additional billing changes required.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 — YIA 2026
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

USER_AGENT = "ProjectCortex/2.0"
TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
HTTP_TIMEOUT_S = 8
DEFAULT_RADIUS_M = 1000
MAX_CANDIDATES = 5


def _http_get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"📍 [PLACES] HTTP request FAILED: {e}")
        return None


def _search_places_sync(
    api_key: str,
    query: str,
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    radius_m: int = DEFAULT_RADIUS_M,
) -> Dict[str, Any]:
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY not configured"}

    params: Dict[str, Any] = {
        "query": query,
        "region": "sg",
        "key": api_key,
    }
    if near_lat is not None and near_lon is not None:
        params["location"] = f"{near_lat},{near_lon}"
        # radius must be <= 50000 per Google docs
        params["radius"] = min(int(radius_m), 50000)

    url = f"{TEXT_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    logger.info(f"📍 [PLACES] search: query='{query}' near=({near_lat}, {near_lon})")

    data = _http_get_json(url)
    if data is None:
        return {"error": "HTTP_FAILURE"}

    status = data.get("status")
    if status != "OK" and status != "ZERO_RESULTS":
        return {"error": f"API_STATUS:{status}", "message": data.get("error_message", "")}

    candidates: List[Dict[str, Any]] = []
    for r in data.get("results", [])[:MAX_CANDIDATES]:
        loc = r.get("geometry", {}).get("location", {})
        candidates.append({
            "name": r.get("name", ""),
            "place_id": r.get("place_id", ""),
            "address": r.get("formatted_address", ""),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "types": r.get("types", []),
            "rating": r.get("rating"),
            "user_ratings_total": r.get("user_ratings_total"),
        })

    return {
        "success": True,
        "query": query,
        "count": len(candidates),
        "candidates": candidates,
    }


def _get_place_details_sync(api_key: str, place_id: str) -> Dict[str, Any]:
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY not configured"}

    fields = ",".join([
        "place_id", "name", "formatted_address",
        "geometry/location", "types", "rating",
        "opening_hours", "website", "international_phone_number",
    ])
    params = {
        "place_id": place_id,
        "fields": fields,
        "key": api_key,
    }
    url = f"{PLACE_DETAILS_URL}?{urllib.parse.urlencode(params)}"
    logger.info(f"📍 [PLACES] details: place_id='{place_id}'")

    data = _http_get_json(url)
    if data is None:
        return {"error": "HTTP_FAILURE"}

    status = data.get("status")
    if status != "OK":
        return {"error": f"API_STATUS:{status}", "message": data.get("error_message", "")}

    r = data.get("result", {})
    loc = r.get("geometry", {}).get("location", {})
    opening = r.get("opening_hours", {}) or {}

    return {
        "success": True,
        "place_id": r.get("place_id", place_id),
        "name": r.get("name", ""),
        "address": r.get("formatted_address", ""),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "types": r.get("types", []),
        "rating": r.get("rating"),
        "open_now": opening.get("open_now"),
        "weekday_hours": opening.get("weekday_text", []),
        "website": r.get("website", ""),
        "phone": r.get("international_phone_number", ""),
    }


async def search_places(
    api_key: str,
    query: str,
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    radius_m: int = DEFAULT_RADIUS_M,
) -> Dict[str, Any]:
    """Async wrapper around Google Places Text Search."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _search_places_sync, api_key, query, near_lat, near_lon, radius_m
    )


async def get_place_details(api_key: str, place_id: str) -> Dict[str, Any]:
    """Async wrapper around Google Places Details."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_place_details_sync, api_key, place_id)
