import math

import numpy as np
import pytest

from cortex_core.nav import geo


def test_haversine_known_distance():
    # Yishun MRT -> Khatib MRT, ~1.9 km apart
    d = geo.haversine(1.4295, 103.8350, 1.4174, 103.8329)
    assert 1300 < d < 1400


def test_xy_matches_haversine():
    x1, y1 = geo.to_xy(1.4295, 103.8350)
    x2, y2 = geo.to_xy(1.4174, 103.8329)
    assert math.hypot(x2 - x1, y2 - y1) == pytest.approx(geo.haversine(1.4295, 103.8350, 1.4174, 103.8329), rel=2e-3)
    lat, lon = geo.to_latlon(x1, y1)
    assert lat == pytest.approx(1.4295) and lon == pytest.approx(103.8350)


def test_bearing_and_turns():
    assert geo.bearing(1.35, 103.8, 1.36, 103.8) == pytest.approx(0, abs=0.1)
    assert geo.bearing(1.35, 103.8, 1.35, 103.81) == pytest.approx(90, abs=0.1)
    assert geo.turn_angle(0, 90) == 90 and geo.turn_angle(350, 10) == 20 and geo.turn_angle(10, 350) == -20
    assert geo.clock_side(90) == "turn right" and geo.clock_side(-40) == "bear left"
    assert geo.clock_side(5) == "continue straight" and geo.clock_side(175) == "make a U-turn"


def test_project_on_polyline():
    xs, ys = np.array([0.0, 100.0, 100.0]), np.array([0.0, 0.0, 100.0])
    d, along, i = geo.project_on_polyline(50, 10, xs, ys)
    assert (d, along, i) == (pytest.approx(10), pytest.approx(50), 0)
    d, along, i = geo.project_on_polyline(110, 50, xs, ys)
    assert (d, along, i) == (pytest.approx(10), pytest.approx(150), 1)
