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


# ---------------------------------------------------------------- the session hosting the brain (agent harness)
from cortex_core.brain.brain import Brain  # noqa: E402
from cortex_core.nav.service import Result  # noqa: E402

CALL = "<tool_call>\n<function={}>\n{}</function>\n</tool_call>"


def call(name, **a):
    return CALL.format(name, "".join(f"<parameter={k}>\n{v}\n</parameter>\n" for k, v in a.items()))


class BrainEngine(FakeEngine):
    """ask -> a tool call; tool_result -> the LM's words (or the template sentence)."""

    def __init__(self, first):
        super().__init__()
        self.first, self.results, self.said, self.states = first, [], [], []

    def ask(self, text, max_tokens=0, timeout=60):
        self.asks.append(text)
        return iter([{"type": "tool_call", "text": self.first}, {"type": "done", "tool": True}])

    def tool_result(self, result, say=None, timeout=60):
        self.results.append((result, say))
        if say:
            return iter([{"type": "done", "said": True}])
        return iter([{"type": "token", "text": "Stop 46971 is 80 metres away."}, {"type": "done", "stop": "eog"}])

    def say(self, text, timeout=60):
        self.said.append(text)
        return iter([{"type": "done"}])

    def set_state(self, text):
        self.states.append(text)


class FakeNav:
    navigating = False

    def __init__(self):
        self.fixes = []

    def mode_hint(self):
        return None

    def state_line(self):
        return ""

    def on_fix(self, lat, lon, acc_m, t=None, speed=None):
        self.fixes.append((lat, lon, acc_m))
        return []

    def call(self, name, args):
        if name == "gps_accuracy":
            return Result({"acc_m": 6}, "GPS is good, about 6 metres.")
        return Result({"stops": [{"code": "46971", "m": 80}]})


def test_brain_typed_ask_runs_the_tool_and_shows_it():
    eng = BrainEngine(call("nearby_bus_stops"))
    s = LiveSession(eng, brain=Brain(eng, FakeNav())).start()
    try:
        s.ask("which bus stop is near me")
        assert until(lambda: not s.state.asking)
        assert s.state.turns[-1].text == "Stop 46971 is 80 metres away." and s.state.turns[-1].done
        assert len(s.state.tools) == 1 and s.state.tools[0].startswith("nearby_bus_stops() -> ")
        assert eng.results[0][1] is None  # an LM tool: the model says it
        assert s.state.mode == "IDLE"
    finally:
        s.close()


def test_brain_template_tool_answer_is_the_fixed_sentence():
    eng = BrainEngine(call("gps_accuracy"))
    s = LiveSession(eng, brain=Brain(eng, FakeNav())).start()
    try:
        s.ask("is my gps ok")
        assert until(lambda: not s.state.asking)
        assert eng.results[0][1] == "GPS is good, about 6 metres."
        assert s.state.turns[-1].text == "GPS is good, about 6 metres."
    finally:
        s.close()


def test_brain_voice_tool_call_is_dispatched():
    eng = BrainEngine(call("nearby_bus_stops"))
    s = LiveSession(eng, brain=Brain(eng, FakeNav())).start()
    try:
        eng.voice.put({"type": "speech_start", "at_ms": 0.0})
        eng.voice.put({"type": "speech_end", "at_ms": 900.0, "speech_ms": 900.0})
        eng.voice.put({"type": "tool_call", "text": call("nearby_bus_stops"), "voice": True})
        eng.voice.put({"type": "done", "voice": True, "tool": True})
        assert until(lambda: any(t.text == "Stop 46971 is 80 metres away." for t in s.state.turns))
        assert len(eng.results) == 1 and len(s.state.tools) == 1
    finally:
        s.close()


def test_brain_mode_and_gps_reach_the_panel():
    eng = BrainEngine(call("set_mode", mode="EXPLORE"))
    nav = FakeNav()
    s = LiveSession(eng, brain=Brain(eng, nav)).start()
    try:
        s.ask("describe around me")
        assert until(lambda: s.state.mode == "EXPLORE" and not s.state.asking)
        assert eng.results[0][1].startswith("Exploring")
        s.on_fix({"lat": 1.43, "lon": 103.83, "acc_m": 7.0, "t": 5.0, "speed": None})
        assert nav.fixes == [(1.43, 103.83, 7.0)] and s.state.gps["acc_m"] == 7.0
    finally:
        s.close()


def test_vision_follows_the_mode_idle_looks_only_on_talk():
    eng, cam = BrainEngine(call("set_mode", mode="EXPLORE")), FakeCamera()
    brain = Brain(eng, FakeNav())
    s = LiveSession(eng, cam, brain=brain).start()
    try:
        time.sleep(0.3)
        assert eng.pushed == []  # IDLE: no views by itself
        eng.voice.put({"type": "speech_start", "at_ms": 0.0})
        assert until(lambda: eng.pushed == [1])  # the user talks: one view of the newest frame
        time.sleep(0.2)
        assert eng.pushed == [1]
        brain.camera_on = False
        brain.modes.mode = "EXPLORE"
        time.sleep(0.2)
        assert eng.pushed == [1]  # camera off: none even in a looking mode
        brain.camera_on = True
        cam.f = (2, cam.f[1])
        assert until(lambda: eng.pushed[-1] == 2)  # EXPLORE: views every second by itself
    finally:
        s.close()


def test_gateway_arrivals_only_when_claimed(tmp_path):
    from cortex_core.tui.__main__ import gateway_arrivals
    assert gateway_arrivals(None) is None and gateway_arrivals(str(tmp_path)) is None
    (tmp_path / "device.json").write_text("{half")
    assert gateway_arrivals(str(tmp_path)) is None
    (tmp_path / "device.json").write_text('{"device_id": "d", "token": "t", "gateway_ws_url": "wss://gw:8443/ws/device"}')
    assert callable(gateway_arrivals(str(tmp_path)))


def test_gateway_takeover_only_when_claimed(tmp_path):
    from cortex_core.brain.takeover import NOT_SURE_OFFLINE
    from cortex_core.tui.__main__ import gateway_takeover
    t = gateway_takeover(str(tmp_path))
    assert t.ask is None and t.run("what is this", True)[1] == NOT_SURE_OFFLINE
    assert t.clip(0.0) == []  # no camera: no frames
    (tmp_path / "device.json").write_text('{"device_id": "d", "token": "t", "gateway_ws_url": "wss://gw:8443/ws/device"}')
    assert callable(gateway_takeover(str(tmp_path)).ask)
