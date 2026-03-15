"""
Phase 1 tests: wall hum parameter mapping and restart behavior.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0
"""

import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rpi5.layer3_guide.spatial_audio.manager import SpatialAudioManager  # noqa: E402


def test_update_from_depth_generates_left_hum_params_for_near_wall():
    m = SpatialAudioManager()

    calls = {"count": 0}

    def _fake_restart():
        calls["count"] += 1

    m._restart_hum_thread = _fake_restart

    # All regions far by default (3m), then make left region near (0.5m)
    depth = np.full((30, 30), 3.0, dtype=np.float32)
    depth[:, :10] = 0.5

    m.update_from_depth(depth)

    assert calls["count"] == 1
    assert "left" in m._hum_params
    freq, left_gain, right_gain = m._hum_params["left"]

    # Near obstacle should produce stronger left channel than right
    assert left_gain > right_gain
    assert 80.0 <= freq <= 200.0


def test_update_from_depth_clears_params_when_far():
    m = SpatialAudioManager()

    calls = {"count": 0}

    def _fake_restart():
        calls["count"] += 1

    m._restart_hum_thread = _fake_restart

    # First call creates params
    near = np.full((30, 30), 1.0, dtype=np.float32)
    m.update_from_depth(near)
    assert calls["count"] == 1

    # Second call removes params (all far)
    far = np.full((30, 30), 3.0, dtype=np.float32)
    m.update_from_depth(far)

    assert calls["count"] == 2
    assert m._hum_params == {}
