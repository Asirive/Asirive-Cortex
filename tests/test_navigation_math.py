"""
Unit tests for navigation math helpers.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0
"""

import math
import sys
from pathlib import Path


# Add project root to import from rpi5 package
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rpi5.layer3_guide.navigation_engine import (  # noqa: E402
    angle_to_hrtf_position,
    bearing_between,
    haversine_distance,
    relative_angle,
)


def test_haversine_distance_zero():
    """Distance between identical points should be ~0."""
    dist = haversine_distance(1.3000, 103.8000, 1.3000, 103.8000)
    assert dist == 0.0


def test_haversine_distance_reasonable_range():
    """One small SG coordinate delta should be in a sane meter range."""
    dist = haversine_distance(1.3000, 103.8000, 1.3010, 103.8010)
    assert 100.0 < dist < 200.0


def test_bearing_cardinal_north():
    """Bearing should be near 0 deg when moving north."""
    bearing = bearing_between(1.3000, 103.8000, 1.3100, 103.8000)
    assert bearing < 5.0 or bearing > 355.0


def test_bearing_cardinal_east():
    """Bearing should be near 90 deg when moving east."""
    bearing = bearing_between(1.3000, 103.8000, 1.3000, 103.8100)
    assert 85.0 < bearing < 95.0


def test_relative_angle_wraparound_right_side():
    """Wraparound should keep result in [-180, 180]."""
    # 350 -> 10 means +20 degrees (right)
    rel = relative_angle(10.0, 350.0)
    assert math.isclose(rel, 20.0, abs_tol=1e-6)


def test_relative_angle_wraparound_left_side():
    """Wraparound should keep result in [-180, 180]."""
    # 10 -> 350 means -20 degrees (left)
    rel = relative_angle(350.0, 10.0)
    assert math.isclose(rel, -20.0, abs_tol=1e-6)


def test_angle_to_hrtf_front():
    """Front should map to negative Z in OpenAL coordinates."""
    x, y, z = angle_to_hrtf_position(0.0, 5.0)
    assert math.isclose(x, 0.0, abs_tol=1e-6)
    assert math.isclose(y, 0.0, abs_tol=1e-6)
    assert z < 0.0


def test_angle_to_hrtf_right_and_left():
    """+90 should be right (x>0), -90 should be left (x<0)."""
    x_right, _, z_right = angle_to_hrtf_position(90.0, 5.0)
    x_left, _, z_left = angle_to_hrtf_position(-90.0, 5.0)

    assert x_right > 0.0
    assert x_left < 0.0
    assert abs(z_right) < 1e-6
    assert abs(z_left) < 1e-6
