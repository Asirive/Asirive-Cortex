"""Gemini takeover: the LM's silent second_opinion call -> a short clip of recent frames (1 a second, oldest first)
and its question to Gemini Live (through the gateway) -> Gemini's answer spoken as is. Offline or refused: "not
sure". Camera off: no frame is sent."""
import json
import time

import numpy as np
import pytest

from cortex_core.brain import tools as T
from cortex_core.brain.brain import Brain
from cortex_core.brain.takeover import LOST, MAX_FRAMES, NOT_SURE, NOT_SURE_OFFLINE, OpinionError, Takeover
from cortex_core.engine import capture

from test_brain import FakeEngine, call

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 32
CLIP = [JPEG, JPEG, JPEG]


class Gem:
    def __init__(self, answer="It is bus 858, right in front of you.", exc=None):
        self.answer, self.exc, self.asked = answer, exc, []

    def __call__(self, question, frames, say=None):
        self.asked.append((question, frames))
        if self.exc:
            raise self.exc
        return self.answer


def test_registry_second_opinion_is_silent_and_spoken_by_template():
    t = T.load().get("second_opinion")
    assert t.spoken_by == "template" and t.allowed_in("IDLE") and t.allowed_in("TRANSIT")
    assert "not sure" in t.description


def test_answer_with_recent_clip():
    g = Gem()
    data, say = Takeover(g, clip=lambda since: CLIP).run("which bus is this", camera_on=True)
    assert g.asked == [("which bus is this", CLIP)]
    assert say == "It is bus 858, right in front of you."
    assert data == {"answer": say, "source": "gemini", "frames": 3}


def test_camera_off_sends_no_frames():
    g = Gem()
    data, _ = Takeover(g, clip=lambda since: CLIP).run("what is this", camera_on=False)
    assert g.asked == [("what is this", [])] and data["frames"] == 0


def test_no_recent_frames_still_asks_without():
    g = Gem()
    Takeover(g, clip=lambda since: []).run("what is this", camera_on=True)
    Takeover(g, clip=lambda since: None).run("what is this", camera_on=True)
    assert g.asked == [("what is this", []), ("what is this", [])]


def test_clip_is_capped():
    g = Gem()
    Takeover(g, clip=lambda since: [JPEG] * 9).run("q", camera_on=True)
    assert len(g.asked[0][1]) == MAX_FRAMES


def test_broken_frame_source_does_not_stop_the_answer():
    def boom():
        raise RuntimeError("camera gone")
    g = Gem()
    _, say = Takeover(g, clip=lambda since: boom()).run("what is this", camera_on=True)
    assert say == g.answer and g.asked[0][1] == []


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
    b = Brain(eng, None, T.load(), takeover=Takeover(g, clip=lambda since: CLIP))
    t = b.ask("which bus is this")
    assert eng.log[1][0] == "tool_result" and eng.log[1][2] == "It is bus 858, right in front of you."
    assert json.loads(eng.log[1][1])["source"] == "gemini"
    assert t.said == "It is bus 858, right in front of you."
    assert g.asked[0][1] == CLIP


def test_brain_camera_off_and_no_takeover():
    def script(kind, text, say):
        if kind == "ask" and text.startswith("cam"):
            return [{"type": "tool_call", "text": call("camera", on="false")}, {"type": "done", "tool": True}]
        if kind == "ask":
            return [{"type": "tool_call", "text": call("second_opinion", question="what is in front of me")},
                    {"type": "done", "tool": True}]
    g = Gem()
    eng = FakeEngine(script)
    b = Brain(eng, None, T.load(), takeover=Takeover(g, clip=lambda since: CLIP))
    b.ask("camera off")
    b.ask("what is in front of me")
    assert g.asked == [("what is in front of me", [])]  # the camera is off: no frame leaves the box
    eng2 = FakeEngine(script)
    Brain(eng2, None, T.load()).ask("what is in front of me")
    assert eng2.log[1][2] == NOT_SURE_OFFLINE


def test_clip_only_has_frames_from_after_the_camera_came_back_on():
    seen = []
    g = Gem()

    def clip(since):
        seen.append(since)
        return CLIP

    def script(kind, text, say):
        if kind == "ask" and text.startswith("cam"):
            return [{"type": "tool_call", "text": call("camera", on=text.endswith("on"))}, {"type": "done", "tool": True}]
        if kind == "ask":
            return [{"type": "tool_call", "text": call("second_opinion", question="q")}, {"type": "done", "tool": True}]
    b = Brain(FakeEngine(script), None, T.load(), takeover=Takeover(g, clip=clip))
    b.ask("q")
    assert seen == [0.0]  # on since start: any recent frame
    b.ask("camera off")
    t_on = time.monotonic()
    b.ask("camera on")
    b.ask("q")
    assert seen[1] >= t_on  # frames taken while it was off are never part of the clip


def test_slow_gemini_says_checking_first():
    def slow(q, j, say=None):
        time.sleep(0.3)
        return "A door on your left."
    eng = FakeEngine(lambda k, t, s: [{"type": "tool_call", "text": call("second_opinion", question="q")},
                                      {"type": "done", "tool": True}] if k == "ask" else None)
    Brain(eng, None, T.load(), checking_s=0.05, takeover=Takeover(slow)).ask("q")
    assert ("say", "Checking.", None) in eng.log and eng.log[-1][2] == "A door on your left."


class Streaming:
    """A gateway that streams: early sentences through say (with a pause between, like Gemini speaking), then the
    whole answer; or a drop after the early sentences."""

    def __init__(self, early, answer, drop=False, gap=0.15):
        self.early, self.answer, self.drop, self.gap = early, answer, drop, gap
        self.said_at = []

    def __call__(self, question, frames, say=None):
        for s in self.early:
            time.sleep(self.gap)
            self.said_at.append(time.monotonic())
            say(s)
        time.sleep(self.gap)
        if self.drop:
            raise OpinionError("gateway failed: stream cut")
        return self.answer


def test_run_returns_only_the_unsaid_rest_to_speak():
    heard = []
    g = Streaming(["It is bus 858."], "It is bus 858. It is stopping now.", gap=0)
    data, say = Takeover(g).run("which bus", True, say=heard.append)
    assert heard == ["It is bus 858."] and say == "It is stopping now."
    assert data["answer"] == "It is bus 858. It is stopping now."  # the whole answer is recorded for follow-ups


def test_run_without_a_say_hook_speaks_everything_at_the_end():
    g = Streaming(["It is bus 858."], "It is bus 858. It is stopping now.", gap=0)
    _, say = Takeover(g).run("which bus", True)
    assert say == "It is bus 858. It is stopping now."


def test_a_drop_after_some_sentences_says_the_rest_was_lost():
    heard = []
    g = Streaming(["Cross now."], None, drop=True, gap=0)
    data, say = Takeover(g).run("can I cross", True, say=heard.append)
    assert heard == ["Cross now."] and say == LOST and "error" in data


def test_brain_speaks_early_sentences_before_gemini_finishes_and_nothing_twice():
    spoken = []

    def script(kind, text, say):
        if kind == "say":
            spoken.append((time.monotonic(), text))
        if kind == "ask":
            return [{"type": "tool_call", "text": call("second_opinion", question="which bus")},
                    {"type": "done", "tool": True}]
    eng = FakeEngine(script)
    g = Streaming(["It is bus 858.", "It is at the stop."], "It is bus 858. It is at the stop. Step forward.")
    t = Brain(eng, None, T.load(), checking_s=0.05, takeover=Takeover(g)).ask("which bus")
    said = [x for _, x in spoken]
    assert said == ["Checking.", "It is bus 858.", "It is at the stop."]
    assert spoken[1][0] < g.said_at[1] + 0.1  # sentence 1 spoken before Gemini had finished sentence 2
    assert eng.log[-1][0] == "tool_result" and eng.log[-1][2] == "Step forward." and t.said == "Step forward."
    assert json.loads(eng.log[-1][1])["answer"] == "It is bus 858. It is at the stop. Step forward."


# ---------------------------------------------------------------- frames to JPEG
def test_jpeg_encodes_rgb():
    pytest.importorskip("PIL")
    rgb = np.zeros((360, 640, 3), np.uint8)
    rgb[:, :320] = 200
    j = capture.jpeg(rgb)
    assert j[:2] == b"\xff\xd8" and j[-2:] == b"\xff\xd9" and 1000 < len(j) < 200_000


def test_ring_keeps_one_frame_a_second_oldest_first():
    r = capture.FrameRing(every_s=1.0, n=4)
    for k in range(25):  # 5 fps for 5 s
        r.push(np.full((2, 2, 3), k, np.uint8), t=100 + k * 0.2)
    clip = r.clip(now=104.9, max_age_s=2.0)
    assert [int(f[0, 0, 0]) for f in clip] == [5, 10, 15, 20]  # 1 s apart, the newest 4, oldest first


def test_ring_gives_nothing_stale():
    r = capture.FrameRing(every_s=1.0, n=4)
    for k in range(5):
        r.push(np.zeros((2, 2, 3), np.uint8), t=100 + k)
    assert r.clip(now=110, max_age_s=2.0) == []  # the camera stopped: nothing old is sent
    r.push(np.ones((2, 2, 3), np.uint8), t=200)  # back on after a gap: the old frames are not part of the clip
    assert len(r.clip(now=200.5, max_age_s=2.0)) == 1
    r.push(np.ones((2, 2, 3), np.uint8), t=201)
    assert len(r.clip(now=201.5, since=200.5)) == 1  # nothing from before the camera came back on
    r.clear()
    assert r.clip(now=200.5) == []


def test_fresh_clip_encodes_jpegs():
    pytest.importorskip("PIL")

    class Cam:
        def __init__(self):
            self.ring = capture.FrameRing()
            for k in range(3):
                self.ring.push(np.zeros((36, 64, 3), np.uint8), t=time.monotonic() - 2 + k)

    clip = capture.fresh_clip(Cam())
    assert len(clip) == 3 and all(j[:2] == b"\xff\xd8" for j in clip)
    assert capture.fresh_clip(None) == []
