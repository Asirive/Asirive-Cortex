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
import os
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# LTA DataMall v3 endpoint
BUS_ARRIVAL_URL = "http://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival"


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
