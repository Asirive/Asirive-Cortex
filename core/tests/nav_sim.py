"""A synthetic trip along an itinerary: GPS fixes as a person would make them (walk 1.3 m/s, wait at the stop,
ride between stops, get off), for end-to-end tests of the follower, the nav service and the brain."""
from __future__ import annotations

import math
from typing import Iterator

import numpy as np

from cortex_core.nav import geo

WALK_MPS = 1.3
RIDE_MPS = 9.0
EVERY_S = 1.0


def _line(pts: list[tuple[float, float]], mps: float, t: float, every_s: float = EVERY_S):
    """(x, y, t, speed) every every_s seconds along a polyline at mps."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(d / (mps * every_s)))
        for k in range(1, n + 1):
            out.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, t, mps))
            t += d / n / mps
    return out, t


def trip_fixes(b, it, acc_m: float = 5.0, wait_s: float = 120.0, t0: float = 0.0,
               jitter_m: float = 0.0, seed: int = 0) -> Iterator[tuple[float, float, float, float, float]]:
    """(lat, lon, acc_m, t, speed) along every leg of the itinerary, in order."""
    rng = np.random.default_rng(seed)
    t = t0
    walker_x, walker_y = b.node_x, b.node_y
    for leg in it.legs:
        if leg.mode == "walk":
            if leg.path is None or len(leg.path.nodes) < 1:
                continue
            pts = [(float(walker_x[n]), float(walker_y[n])) for n in leg.path.nodes]
            if len(pts) == 1:
                pts = pts * 2
            seg, t = _line(pts, WALK_MPS, t)
        else:
            sx = [float(b.stop_x[s]) for s in leg.stops]
            sy = [float(b.stop_y[s]) for s in leg.stops]
            seg = [(sx[0], sy[0], t + k, 0.0) for k in range(int(wait_s))]  # waiting at the stop
            t += wait_s
            ride, t = _line(list(zip(sx, sy)), RIDE_MPS, t, every_s=3.0)
            seg += ride
        for x, y, tt, sp in seg:
            if jitter_m:
                x += float(rng.normal(0, jitter_m))
                y += float(rng.normal(0, jitter_m))
            lat, lon = geo.to_latlon(x, y)
            yield float(lat), float(lon), acc_m, tt, sp
