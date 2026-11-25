"""A small synthetic city for nav tests: a 21 x 21 grid of footpaths 50 m apart (1 km square) around Yishun.

Streets: rows are "Row Street <r>", columns "Col Avenue <c>". Node (r, c) is at x = X0 + 50c, y = Y0 + 50r.
Bus 100 runs along row 0 west -> east (stops every 4 nodes), bus 200 up column 20 (south -> north), and the
"Test Line" MRT from (0, 0) to (20, 20) diagonally with 3 stations. Steps beside a ramp between (10, 4) and
(10, 5); a signalled crossing between (5, 10) and (6, 10).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from cortex_core.nav import bundle as B
from cortex_core.nav import build, geo

N = 21
X0, Y0 = geo.to_xy(1.42, 103.83)
X0, Y0 = float(X0), float(Y0)


def node(r: int, c: int) -> int:
    return r * N + c


def xy(r: float, c: float) -> tuple[float, float]:
    return X0 + 50 * c, Y0 + 50 * r


def latlon(r: float, c: float) -> tuple[float, float]:
    x, y = xy(r, c)
    lat, lon = geo.to_latlon(x, y)
    return float(lat), float(lon)


def make(root: Path, version: str = "20261126-0000") -> Path:
    lat, lon = [], []
    for r in range(N):
        for c in range(N):
            a, o = latlon(r, c)
            lat.append(a), lon.append(o)
    ways = []
    for r in range(N):
        for c in range(N - 1):
            f = 0
            if (r, c) == (10, 4):
                f = B.F_STEPS
            ways.append((node(r, c), node(r, c + 1), f, f"Row Street {r}"))
    for c in range(N):
        for r in range(N - 1):
            f = B.F_CROSSING | B.F_SIGNALS if (r, c) == (5, 10) else 0
            ways.append((node(r, c), node(r + 1, c), f, f"Col Avenue {c}"))
    # the ramp beside the steps: a detour (10,4) -> (10.4,4.5) -> (10,5) via an extra node
    a, o = latlon(10.4, 4.5)
    lat.append(a), lon.append(o)
    ramp = len(lat) - 1
    ways += [(node(10, 4), ramp, B.F_RAMP, "Ramp"), (ramp, node(10, 5), B.F_RAMP, "Ramp")]

    stops = []
    def add_stop(code, name, r, c, kind=B.K_BUS, ref=""):
        a, o = latlon(r, c)
        stops.append({"code": code, "ref": ref, "name": name, "lat": a, "lon": o, "kind": kind})
        return len(stops) - 1
    row0 = [add_stop(59000 + c, f"Row Stop {c}", 0, c) for c in range(0, N, 4)]
    col20 = [add_stop(59100 + r, f"Col Stop {r}", r, 20) for r in range(0, N, 4)]
    stations = [add_stop(0, n, rc, rc, B.K_MRT, ref) for n, rc, ref in
                (("Alpha", 0, "TL1"), ("Beta", 10, "TL2"), ("Gamma", 20, "TL3"))]
    patterns = [
        {"service": "100", "mode": B.K_BUS, "stops": row0, "headway": [6, 8, 6, 10]},
        {"service": "100", "mode": B.K_BUS, "stops": row0[::-1], "headway": [6, 8, 6, 10]},
        {"service": "200", "mode": B.K_BUS, "stops": col20, "headway": [8, 10, 8, 12]},
        {"service": "200", "mode": B.K_BUS, "stops": col20[::-1], "headway": [8, 10, 8, 12]},
        {"service": "Test Line", "mode": B.K_MRT, "stops": stations, "headway": [3, 5, 3, 6]},
        {"service": "Test Line", "mode": B.K_MRT, "stops": stations[::-1], "headway": [3, 5, 3, 6]},
    ]
    places = []
    def add_place(name, kind, r, c, postal=0):
        a, o = latlon(r, c)
        places.append({"name": name, "kind": kind, "lat": a, "lon": o, "postal": postal})
    add_place("Northpoint City", "mall", 20, 19, 769098)
    add_place("Northpoint City South Wing", "mall", 19, 18)
    add_place("Block 101 Yishun Avenue 5", "address", 1, 1, 760101)
    add_place("Yishun Polyclinic", "clinic", 2, 6)
    add_place("Khoo Teck Puat Hospital", "hospital", 15, 2, 768828)
    add_place("Chong Pang Hawker Centre", "hawker_centre", 8, 12)
    add_place("Ang Mo Kio Hub", "mall", 12, 16)
    arrays = build.assemble(lat, lon, ways, stops, patterns, places, log=lambda *_: None)
    return B.write(root, version, arrays, {"test": "nav_city"})
