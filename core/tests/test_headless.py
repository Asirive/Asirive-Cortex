"""Headless Cortex (the user build, no screen, no SSH): the glasses button or the app's talk button through
/run/cortex/button.fifo, the app's pause / mic mute flags, spoken start-up and spoken problems (the user cannot see a
screen), and the systemd watchdog only while the session is alive."""
import os
import threading
import time

import pytest

np = pytest.importorskip("numpy")

from cortex_core.brain import headless as H  # noqa: E402
from cortex_core.safety.glasses import BUTTON_LONG, BUTTON_TAP, ButtonFifo  # noqa: E402
from cortex_core.tui.live import LiveSession  # noqa: E402

from test_live_session import FakeEngine, until  # noqa: E402


class SayEngine(FakeEngine):
    def __init__(self):
        super().__init__()
        self.said = []

    def say(self, text, timeout=60.0):
        self.said.append(text)
        return iter([{"type": "done", "kind": "say"}])


class Dog:
    def __init__(self):
        self.ready_n = self.pets = 0

    def ready(self):
        self.ready_n += 1

    def pet(self):
        self.pets += 1


@pytest.fixture
def rig(tmp_path):
    eng = SayEngine()
    s = LiveSession(eng).start()
    dog = Dog()
    h = H.Headless(s, eng, run_dir=str(tmp_path), watchdog=dog)
    yield h, eng, s, dog, tmp_path
    h.close()
    s.close()


def test_start_says_ready_and_tells_systemd(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[])
    assert eng.said == [H.READY] and dog.ready_n == 1
    assert os.path.exists(d / "button.fifo")


def test_problems_are_spoken_not_printed(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[H.NO_MIC, H.NO_CAMERA])
    assert eng.said == [H.READY, H.NO_MIC, H.NO_CAMERA]


def test_tap_from_the_glasses_fifo_toggles_listening(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[])
    ButtonFifo(str(d / "button.fifo"))(BUTTON_TAP, 1.0)
    assert until(lambda: eng.listening == [True])
    ButtonFifo(str(d / "button.fifo"))(BUTTON_TAP, 2.0)
    assert until(lambda: eng.listening == [True, False])


def test_tap_while_talking_cuts(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[])
    eng.voice.put({"type": "sound_start", "at_ms": 0.0})
    assert until(lambda: s.state.talking)
    h.on_button("tap")
    assert eng.cancelled == 1


def test_long_press_is_ignored_for_now(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[])
    ButtonFifo(str(d / "button.fifo"))(BUTTON_LONG, 1.0)
    time.sleep(0.2)
    assert eng.listening == [] and eng.cancelled == 0


def test_fifo_survives_writers_coming_and_going(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[])
    for k in range(4):  # the safety service writes one press per open
        ButtonFifo(str(d / "button.fifo"))(BUTTON_TAP, float(k))
        assert until(lambda: len(eng.listening) == k + 1)
    with open(d / "button.fifo", "w") as f:  # junk is skipped
        f.write("garbage\n\ntap 9.0\n")
    assert until(lambda: len(eng.listening) == 5)


def test_pause_from_the_app_stops_listening_and_ignores_the_button(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[])
    h.on_button("tap")
    assert eng.listening == [True]
    (d / "assistant.paused").touch()
    h.tick()
    assert eng.listening == [True, False] and eng.said[-1] == H.PAUSED
    h.on_button("tap")
    assert eng.listening == [True, False]  # paused: the button does nothing
    os.remove(d / "assistant.paused")
    h.tick()
    assert eng.said[-1] == H.RESUMED
    h.on_button("tap")
    assert eng.listening == [True, False, True]


def test_mic_mute_from_the_app_drops_audio(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[])
    pcm = np.zeros(320, np.int16)
    h.on_mic(pcm)
    assert eng.audio == 320
    (d / "mic.muted").touch()
    h.tick()
    h.on_mic(pcm)
    assert eng.audio == 320
    os.remove(d / "mic.muted")
    h.tick()
    h.on_mic(pcm)
    assert eng.audio == 640


def test_watchdog_only_while_the_session_lives(rig):
    h, eng, s, dog, d = rig
    h.start(problems=[])
    h.tick()
    assert dog.pets == 1
    s.stop.set()
    for t in s._threads:
        t.join(2)
    h.tick()
    assert dog.pets == 1  # the voice thread died: systemd restarts the service


def test_run_loop_stops(tmp_path):
    eng = SayEngine()
    s = LiveSession(eng).start()
    h = H.Headless(s, eng, run_dir=str(tmp_path), watchdog=Dog())
    stop = threading.Event()
    th = threading.Thread(target=h.run, args=([], stop, 0.05))
    th.start()
    assert until(lambda: eng.said == [H.READY])
    stop.set()
    th.join(2)
    assert not th.is_alive()
    s.close()


def test_problems_list():
    assert H.problems(None, None, None) == [H.NO_MIC, H.NO_CAMERA, H.NO_NAV]
    assert H.problems("/dev/video0", "mic", "bundle") == []


def test_main_refuses_without_engine_library(tmp_path, capsys):
    assert H.main(["--lib", str(tmp_path / "missing.so")], env={}) == 2
