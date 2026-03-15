"""
Unit tests for SceneChangeDetector trigger logic.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0
"""

import sys
import time
from pathlib import Path


# Add project root to import from rpi5 package
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rpi5.layer2_thinker.scene_change_detector import SceneChangeDetector  # noqa: E402


def test_nav_event_triggers_narration_immediately():
    detector = SceneChangeDetector(cooldown_seconds=0.0)
    should = detector.should_narrate([], avg_depth=None, nav_event="waypoint_reached", is_navigating=True)
    assert should is True
    assert detector.get_last_trigger().startswith("nav_event:")


def test_new_interesting_class_triggers():
    detector = SceneChangeDetector(cooldown_seconds=0.0)
    dets = [{"class": "chair"}]
    should = detector.should_narrate(dets, avg_depth=None, nav_event=None, is_navigating=False)
    assert should is True
    assert detector.get_last_trigger().startswith("new_classes:")


def test_person_only_does_not_trigger_by_default():
    detector = SceneChangeDetector(cooldown_seconds=0.0)
    dets = [{"class": "person"}]
    should = detector.should_narrate(dets, avg_depth=None, nav_event=None, is_navigating=False)
    assert should is False


def test_depth_change_triggers_after_baseline():
    detector = SceneChangeDetector(cooldown_seconds=0.0, depth_change_threshold=0.2)

    # First frame sets baseline depth
    first = detector.should_narrate([], avg_depth=5.0, nav_event=None, is_navigating=False)
    assert first is False

    # 40 percent change should trigger (threshold is 20 percent)
    second = detector.should_narrate([], avg_depth=3.0, nav_event=None, is_navigating=False)
    assert second is True
    assert detector.get_last_trigger().startswith("depth_change:")


def test_silence_timeout_triggers_and_resets():
    detector = SceneChangeDetector(
        cooldown_seconds=0.0,
        silence_timeout_navigating=0.1,
        silence_timeout_idle=0.1,
    )

    time.sleep(0.12)
    should = detector.should_narrate([], avg_depth=None, nav_event=None, is_navigating=True)
    assert should is True
    assert detector.get_last_trigger().startswith("silence:")

    # Immediately calling again should not trigger because silence timer reset
    should_again = detector.should_narrate([], avg_depth=None, nav_event=None, is_navigating=True)
    assert should_again is False


def test_record_speech_prevents_silence_trigger():
    detector = SceneChangeDetector(
        cooldown_seconds=0.0,
        silence_timeout_navigating=0.15,
        silence_timeout_idle=0.15,
    )

    detector.record_speech()
    time.sleep(0.05)
    should = detector.should_narrate([], avg_depth=None, nav_event=None, is_navigating=True)
    assert should is False
