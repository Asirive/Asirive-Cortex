"""Small-area geometry for Singapore: metres on a local equirectangular plane (error < 0.1 % across the island)."""
from __future__ import annotations

import math

import numpy as np

R = 6371008.8
LAT0 = 1.35  # Singapore's middle: x/y metres are taken around it
KX = math.radians(1) * R * math.cos(math.radians(LAT0))
KY = math.radians(1) * R


def haversine(lat1, lon1, lat2, lon2):
    """Metres; works on scalars and NumPy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def to_xy(lat, lon):
    return (np.asarray(lon) - 103.8) * KX, (np.asarray(lat) - LAT0) * KY


def to_latlon(x, y):
    return np.asarray(y) / KY + LAT0, np.asarray(x) / KX + 103.8


def bearing(lat1, lon1, lat2, lon2) -> float:
    """Degrees clockwise from north, 0..360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def turn_angle(b_in: float, b_out: float) -> float:
    """Signed change of heading, -180..180 (positive = right)."""
    return (b_out - b_in + 540) % 360 - 180


def project_on_polyline(px: float, py: float, xs: np.ndarray, ys: np.ndarray) -> tuple[float, float, int]:
    """(distance from the line, distance along it to the closest point, segment index)."""
    ax, ay, bx, by = xs[:-1], ys[:-1], xs[1:], ys[1:]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = np.where(L2 > 0, ((px - ax) * dx + (py - ay) * dy) / np.where(L2 > 0, L2, 1), 0.0)
    t = np.clip(t, 0, 1)
    cx, cy = ax + t * dx, ay + t * dy
    d = np.hypot(px - cx, py - cy)
    i = int(np.argmin(d))
    seg = np.hypot(dx, dy)
    along = float(seg[:i].sum() + t[i] * seg[i])
    return float(d[i]), along, i


def clock_side(angle: float) -> str:
    """A turn for speech: 'turn left', 'bear right', 'continue straight'..."""
    a = abs(angle)
    side = "right" if angle > 0 else "left"
    if a < 25:
        return "continue straight"
    if a < 60:
        return f"bear {side}"
    if a < 150:
        return f"turn {side}"
    return "make a U-turn"
