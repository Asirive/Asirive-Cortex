"""Gemini takeover: the LM's silent second_opinion call -> the fresh frame and its question to Gemini (through the
gateway) -> Gemini's answer spoken as is. Offline or refused: "not sure". Camera off: no image is sent."""
import json
import time

import numpy as np
import pytest

from cortex_core.brain import tools as T
from cortex_core.brain.brain import Brain
from cortex_core.brain.takeover import NOT_SURE, NOT_SURE_OFFLINE, OpinionError, Takeover
from cortex_core.engine import capture

from test_brain import FakeEngine, call

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 32


class Gem:
    def __init__(self, answer="It is bus 858, right in front of you.", exc=None):
        self.answer, self.exc, self.asked = answer, exc, []

    def __call__(self, question, jpeg):
        self.asked.append((question, jpeg))
        if self.exc:
            raise self.exc
        return self.answer


def test_registry_second_opinion_is_silent_and_spoken_by_template():
    t = T.load().get("second_opinion")
    assert t.spoken_by == "template" and t.allowed_in("IDLE") and t.allowed_in("TRANSIT")
    assert "not sure" in t.description


def test_answer_with_fresh_frame():
    g = Gem()
    data, say = Takeover(g, frame=lambda: JPEG).run("which bus is this", camera_on=True)
    assert g.asked == [("which bus is this", JPEG)]
    assert say == "It is bus 858, right in front of you."
    assert data == {"answer": say, "source": "gemini", "image": True}


def test_camera_off_sends_no_image():
    g = Gem()
    data, _ = Takeover(g, frame=lambda: JPEG).run("what is this", camera_on=False)
    assert g.asked == [("what is this", None)] and data["image"] is False


def test_no_fresh_frame_still_asks_without_image():
    g = Gem()
    Takeover(g, frame=lambda: None).run("what is this", camera_on=True)
    assert g.asked == [("what is this", None)]


def test_broken_frame_source_does_not_stop_the_answer():
    def boom():
        raise RuntimeError("camera gone")
    g = Gem()
    _, say = Takeover(g, frame=boom).run("what is this", camera_on=True)
    assert say == g.answer and g.asked[0][1] is None


def test_offline_or_unconfigured_says_not_sure():
    data, say = Takeover(None).run("what is this", camera_on=True)
    assert say == NOT_SURE_OFFLINE and data["error"]
    data, say = Takeover(Gem(exc=OpinionError("offline", online=False))).run("q", True)
    assert say == NOT_SURE_OFFLINE
    data, say = Takeover(Gem(exc=OpinionError("gateway HTTP 429"))).run("q", True)
    assert say == NOT_SURE and "429" in data["error"]
    data, say = Takeover(Gem(exc=ValueError("weird"))).run("q", True)  # never raises
    assert say == NOT_SURE


def test_empty_question_is_not_sent():
    g = Gem()
    data, say = Takeover(g).run("   ", True)
    assert g.asked == [] and say == NOT_SURE


def test_brain_speaks_gemini_answer_through_the_engine():
    def script(kind, text, say):
        if kind == "ask":
            return [{"type": "tool_call", "text": call("second_opinion", question="which bus is this")},
                    {"type": "done", "tool": True}]
    eng = FakeEngine(script)
    g = Gem()
    b = Brain(eng, None, T.load(), takeover=Takeover(g, frame=lambda: JPEG))
    t = b.ask("which bus is this")
    assert eng.log[1][0] == "tool_result" and eng.log[1][2] == "It is bus 858, right in front of you."
    assert json.loads(eng.log[1][1])["source"] == "gemini"
    assert t.said == "It is bus 858, right in front of you."
    assert g.asked[0][1] == JPEG


def test_brain_camera_off_and_no_takeover():
    def script(kind, text, say):
        if kind == "ask" and text.startswith("cam"):
            return [{"type": "tool_call", "text": call("camera", on="false")}, {"type": "done", "tool": True}]
        if kind == "ask":
            return [{"type": "tool_call", "text": call("second_opinion", question="what is in front of me")},
                    {"type": "done", "tool": True}]
    g = Gem()
    eng = FakeEngine(script)
    b = Brain(eng, None, T.load(), takeover=Takeover(g, frame=lambda: JPEG))
    b.ask("camera off")
    b.ask("what is in front of me")
    assert g.asked == [("what is in front of me", None)]  # the camera is off: no frame leaves the box
    eng2 = FakeEngine(script)
    Brain(eng2, None, T.load()).ask("what is in front of me")
    assert eng2.log[1][2] == NOT_SURE_OFFLINE


def test_slow_gemini_says_checking_first():
    def slow(q, j):
        time.sleep(0.3)
        return "A door on your left."
    eng = FakeEngine(lambda k, t, s: [{"type": "tool_call", "text": call("second_opinion", question="q")},
                                      {"type": "done", "tool": True}] if k == "ask" else None)
    Brain(eng, None, T.load(), checking_s=0.05, takeover=Takeover(slow)).ask("q")
    assert ("say", "Checking.", None) in eng.log and eng.log[-1][2] == "A door on your left."


# ---------------------------------------------------------------- frames to JPEG
def test_jpeg_encodes_rgb():
    pytest.importorskip("PIL")
    rgb = np.zeros((360, 640, 3), np.uint8)
    rgb[:, :320] = 200
    j = capture.jpeg(rgb)
    assert j[:2] == b"\xff\xd8" and j[-2:] == b"\xff\xd9" and 1000 < len(j) < 200_000


def test_fresh_jpeg_only_when_recent():
    pytest.importorskip("PIL")

    class Cam:
        def __init__(self, age):
            self.age = age

        def latest(self):
            return (1, np.zeros((36, 64, 3), np.uint8))

        def latest_age(self):
            return self.age

    assert capture.fresh_jpeg(Cam(0.5), max_age_s=2.0)[:2] == b"\xff\xd8"
    assert capture.fresh_jpeg(Cam(5.0), max_age_s=2.0) is None
    assert capture.fresh_jpeg(None) is None
