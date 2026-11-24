import queue
import threading
import time

import pytest

np = pytest.importorskip("numpy")

from cortex_core.tui.live import LiveSession  # noqa: E402


class FakeEngine:
    def __init__(self):
        self.voice = queue.Queue()
        self.views = queue.Queue()
        self.pushed, self.audio, self.listening = [], 0, []
        self.asks = []
        self.cancelled = 0

    def cancel(self):  # like the engine: the sound is cut at once
        self.cancelled += 1
        self.voice.put({"type": "sound_end", "at_ms": 2.0, "sound_ms": 400.0, "gaps": 0, "cut": True})

    def set_listening(self, on):
        self.listening.append(on)

    def push_audio(self, pcm):
        self.audio += len(pcm)

    def push_frame(self, rgb, frame_id):
        self.pushed.append(frame_id)

    def refresh(self):
        self.views.put({"type": "view", "frame_id": self.pushed[-1], "prep_ms": 2.0, "encode_ms": 280.0,
                        "read_ms": 1100.0, "skipped": False})

    def wait_view(self, timeout=30.0):
        return self.views.get(timeout=timeout)

    def next_voice(self, timeout=None):
        return self.voice.get(timeout=timeout)

    def ask(self, text, max_tokens=60):
        self.asks.append(text)
        yield {"type": "token", "text": "A cup."}
        yield {"type": "done", "ttft_ms": 100.0, "n_out": 3, "cancelled": False, "stop": "eog"}

    def reset_history(self):
        pass


class FakeCamera:
    def __init__(self):
        self.f = (1, np.zeros((360, 640, 3), dtype=np.uint8))

    def latest(self):
        return self.f


def until(cond, s=3.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_toggle_mic_and_voice_events():
    eng = FakeEngine()
    s = LiveSession(eng).start()
    try:
        assert s.toggle_listening() is True and eng.listening == [True]
        s.on_mic(np.full(320, 1000, dtype=np.int16))
        assert eng.audio == 320 and -31 < s.state.mic_dbfs < -29
        eng.voice.put({"type": "speech_start", "at_ms": 0.0})
        eng.voice.put({"type": "speech_end", "at_ms": 2000.0, "speech_ms": 2000.0})
        eng.voice.put({"type": "token", "text": "Hello", "voice": True})
        eng.voice.put({"type": "done", "voice": True, "end_to_first_ms": 140.0, "cancelled": False, "stop": "eog"})
        assert until(lambda: s.state.last.get("end_to_first_ms") == 140.0)
        assert [t.text for t in s.state.turns] == ["(spoke 2.0 s)", "Hello"]
        assert s.toggle_listening() is False and eng.listening == [True, False]
    finally:
        s.close()


def test_vision_pushes_each_new_frame_once():
    eng, cam = FakeEngine(), FakeCamera()
    s = LiveSession(eng, cam, refresh_s=0.05).start()
    try:
        assert until(lambda: s.state.view.get("frame_id") == 1)
        time.sleep(0.2)
        assert eng.pushed == [1]  # same frame: not pushed again
        cam.f = (2, cam.f[1])
        assert until(lambda: s.state.view.get("frame_id") == 2)
    finally:
        s.close()


def test_typed_ask_runs_off_thread_and_refuses_overlap():
    eng = FakeEngine()
    gate = threading.Event()
    real = eng.ask

    def slow(text, max_tokens=60):
        gate.wait(2)
        yield from real(text, max_tokens)

    eng.ask = slow
    s = LiveSession(eng).start()
    try:
        s.ask("What is this?")
        s.ask("And this?")  # refused while the first runs
        gate.set()
        assert until(lambda: not s.state.asking and any(t.text == "A cup." for t in s.state.turns))
        assert eng.asks == ["What is this?"]
        assert "busy" in s.state.log[-1]
    finally:
        s.close()
