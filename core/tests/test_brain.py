"""The Brain against a scripted engine (same methods as engine.native.Engine) and the synthetic nav city."""
import json
import threading
import time

import pytest

from cortex_core.brain import tools as T
from cortex_core.brain.brain import SORRY, Brain
from cortex_core.brain.modes import ModeMachine
from cortex_core.nav import bundle as B
from cortex_core.nav.service import NavService

import nav_city as C


def call(name, **args):
    body = "".join(f"<parameter={k}>\n{v}\n</parameter>\n" for k, v in args.items())
    return f"<tool_call>\n<function={name}>\n{body}</function>\n</tool_call>"


class FakeEngine:
    """script(kind, text, say) -> list of events for that step. Records every call."""

    def __init__(self, script):
        self.script = script
        self.log = []
        self.state = []
        self.cancelled = 0

    def _events(self, kind, text, say=None):
        self.log.append((kind, text, say))
        return iter(self.script(kind, text, say) or [{"type": "done", "kind": kind}])

    def ask(self, text, max_tokens=0, timeout=60):
        return self._events("ask", text)

    def tool_result(self, result, say=None, timeout=60):
        return self._events("tool_result", result, say)

    def say(self, text, timeout=60):
        return self._events("say", text)

    def set_state(self, text):
        self.state.append(text)

    def cancel(self):
        self.cancelled += 1


def toks(text):
    return [{"type": "token", "text": text}, {"type": "done", "kind": "ask"}]


def calls(text):
    return [{"type": "tool_call", "text": text}, {"type": "done", "tool": True}]


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    return B.Bundle(C.make(tmp_path_factory.mktemp("nav")))


def nav(bundle):
    lat, lon = C.latlon(20, 20)
    clk = [1000.0]
    s = NavService(bundle, saved={"home": {"lat": lat, "lon": lon}}, clock=lambda: clk[0], hour=lambda: 9.0)
    return s, clk


def results(eng):
    return [(json.loads(t), s) for k, t, s in eng.log if k == "tool_result"]


def test_chitchat_no_tools(bundle):
    eng = FakeEngine(lambda k, t, s: toks("Hello!") if k == "ask" else None)
    b = Brain(eng, nav(bundle)[0])
    turn = b.ask("hi")
    assert turn.text == "Hello!" and turn.calls == []
    assert eng.state[0] == "mode=IDLE"


def test_search_then_plan_chain_lm_spoken(bundle):
    s, _ = nav(bundle)
    s.on_fix(*C.latlon(0, 0))

    def script(kind, text, say):
        if kind == "ask":
            return calls(call("search_places", query="northpoint"))
        if kind == "tool_result" and "matches" in text:
            pid = json.loads(text)["matches"][0]["place_id"]
            return calls(call("plan_trip", place_id=pid))
        if kind == "tool_result" and "summary" in text:
            return toks("Take the MRT, about 9 minutes.")
    eng = FakeEngine(script)
    b = Brain(eng, s)
    turn = b.ask("how to get to northpoint")
    assert [c.name for c in turn.calls] == ["search_places", "plan_trip"]
    assert turn.text == "Take the MRT, about 9 minutes."
    assert all(say is None for _, say in results(eng))  # both are spoken by the LM
    assert s.trip is not None


def test_template_tool_spoken_fixed(bundle):
    s, _ = nav(bundle)
    s.on_fix(*C.latlon(0, 1))
    eng = FakeEngine(lambda k, t, sy: calls(call("bus_arrivals", service="100")) if k == "ask" else None)
    b = Brain(eng, s)
    turn = b.ask("when is the 100 coming")
    (res, say), = results(eng)
    assert say.startswith("I can't get live times.") and turn.said == say
    assert res["live"] is False


def test_start_navigation_moves_mode_and_state(bundle):
    s, clk = nav(bundle)
    s.on_fix(*C.latlon(0, 0))
    s.plan_trip(s.search_places("polyclinic").data["matches"][0]["place_id"])
    eng = FakeEngine(lambda k, t, sy: calls(call("start_navigation")) if k == "ask" else None)
    b = Brain(eng, s)
    b.ask("let's go")
    assert b.mode == "OUTDOOR_NAV"
    assert eng.state[-1].startswith("mode=OUTDOOR_NAV; nav: walking")
    # walk the route: cues are spoken with say, the trip ends in IDLE
    p = s.trip.legs[0].path
    for x, y in zip(p.xs, p.ys):
        clk[0] += 5
        from cortex_core.nav import geo
        lat, lon = geo.to_latlon(x, y)
        b.on_fix(float(lat), float(lon), 5.0)
    spoken = [t for k, t, _ in eng.log if k == "say"]
    assert spoken[-1] == "You have arrived."
    assert b.mode == "IDLE" and eng.state[-1] == "mode=IDLE"


def test_mode_gating(bundle):
    s, _ = nav(bundle)
    eng = FakeEngine(lambda k, t, sy: calls(call("nav_status")) if k == "ask" else toks("We're not on a trip."))
    b = Brain(eng, s)
    turn = b.ask("how far still")
    (res, say), = results(eng)
    assert "not available in IDLE" in res["error"] and say is None
    assert turn.text == "We're not on a trip."


def test_malformed_once_retries_then_sorry(bundle):
    s, _ = nav(bundle)
    seen = []

    def script(kind, text, say):
        seen.append(kind)
        if kind in ("ask", "tool_result") and say is None:
            return calls(call("search_places"))  # missing query, every time
    eng = FakeEngine(script)
    b = Brain(eng, s)
    turn = b.ask("find")
    rs = results(eng)
    assert len(rs) == 2
    assert "needs query" in rs[0][0]["error"] and rs[0][1] is None  # the LM gets to try again
    assert rs[1][1] == SORRY and turn.said == SORRY


def test_malformed_then_good(bundle):
    s, _ = nav(bundle)
    step = [0]

    def script(kind, text, say):
        step[0] += 1
        if step[0] == 1:
            return calls("<tool_call>\n<function=search_places>\n<parameter=qery>\nktph")
        if step[0] == 2:
            return calls(call("search_places", query="ktph"))
        return toks("Khoo Teck Puat Hospital is 1 km away.")
    eng = FakeEngine(script)
    turn = Brain(eng, s).ask("where is ktph")
    assert [c.error is None for c in turn.calls] == [False, True]
    assert turn.text.startswith("Khoo Teck Puat")


def test_chain_limit(bundle):
    s, _ = nav(bundle)
    eng = FakeEngine(lambda k, t, sy: calls(call("nearby_bus_stops")) if sy is None else None)  # LM-spoken, loops
    turn = Brain(eng, s).ask("loop")
    assert len(turn.calls) == 4 and turn.said == SORRY


def test_unknown_tool_is_malformed(bundle):
    eng = FakeEngine(lambda k, t, sy: calls(call("launch", x=1)) if sy is None else None)
    turn = Brain(eng, nav(bundle)[0]).ask("x")
    assert "unknown tool" in turn.calls[0].error and turn.said == SORRY


def test_slow_tool_says_checking(bundle):
    s, _ = nav(bundle)
    real = s.call

    def slow(name, args):
        time.sleep(0.3)
        return real(name, args)
    s.call = slow
    eng = FakeEngine(lambda k, t, sy: calls(call("gps_accuracy")) if k == "ask" else None)
    turn = Brain(eng, s, checking_s=0.1).ask("gps?")
    kinds = [(k, t) for k, t, _ in eng.log]
    assert ("say", "Checking.") in kinds
    assert kinds.index(("say", "Checking.")) < [k for k, _ in kinds].index("tool_result")
    assert turn.calls[0].checking


def test_fast_tool_no_checking(bundle):
    eng = FakeEngine(lambda k, t, sy: calls(call("gps_accuracy")) if k == "ask" else None)
    Brain(eng, nav(bundle)[0]).ask("gps?")
    assert ("say", "Checking.", None) not in eng.log


def test_tool_exception_is_a_result(bundle):
    s, _ = nav(bundle)
    s.call = lambda n, a: 1 / 0
    eng = FakeEngine(lambda k, t, sy: calls(call("gps_accuracy")) if k == "ask" else toks("Something broke."))
    turn = Brain(eng, s).ask("gps?")
    assert "failed" in turn.calls[0].result["error"]


def test_set_mode_and_camera(bundle):
    s, _ = nav(bundle)
    seq = iter([call("set_mode", mode="EXPLORE"), call("camera", on="false"), call("set_mode", mode="IDLE"),
                call("set_mode", mode="TRANSIT")])
    eng = FakeEngine(lambda k, t, sy: calls(next(seq)) if k == "ask" else None)
    b = Brain(eng, s)
    b.ask("explore"); assert b.mode == "EXPLORE"
    b.ask("camera off"); assert b.camera_on is False
    b.ask("stop"); assert b.mode == "IDLE"
    b.ask("bus mode"); assert b.mode == "IDLE"
    says = [sy for _, sy in results(eng)]
    assert says == ["Exploring. I'll describe what's around you.", "Camera off.", "Stopped exploring.", None]
    # TRANSIT is outside set_mode's enum: a malformed call the LM may retry, not a mode change
    assert "one of" in results(eng)[3][0]["error"]


def test_voice_call_path(bundle):
    s, _ = nav(bundle)
    s.on_fix(*C.latlon(0, 1))
    eng = FakeEngine(lambda k, t, sy: toks("Bus stop Row Stop 0 is 50 metres away.") if k == "tool_result" else None)
    b = Brain(eng, s)
    assert b.voice_event({"type": "speech_start"}) is None
    assert b.voice_event({"type": "tool_call", "text": call("nearby_bus_stops"), "voice": True}) is None
    turn = b.voice_event({"type": "done", "voice": True, "tool": True})
    assert turn.voice and turn.calls[0].name == "nearby_bus_stops"
    assert turn.text.endswith("50 metres away.")


def test_voice_plain_answer(bundle):
    b = Brain(FakeEngine(lambda *a: None), nav(bundle)[0])
    b.voice_event({"type": "token", "text": "Hi ", "voice": True})
    b.voice_event({"type": "token", "text": "there", "voice": True})
    t = b.voice_event({"type": "done", "voice": True})
    assert t.text == "Hi there" and t.calls == []


def test_cue_waits_for_turn_urgent_cuts(bundle):
    eng = FakeEngine(lambda *a: None)
    b = Brain(eng, nav(bundle)[0])
    started, release = threading.Event(), threading.Event()

    def hold():
        with b.turn_lock:
            started.set()
            release.wait(2)
    th = threading.Thread(target=hold)
    th.start()
    started.wait(1)
    b.cue("Turn left.")
    b.cue("Get off now.", urgent=True)
    assert eng.cancelled == 1 and list(b.cues) == ["Get off now.", "Turn left."]
    release.set()
    th.join()
    b._flush_cues()
    assert [t for k, t, _ in eng.log if k == "say"] == ["Get off now.", "Turn left."]


def test_no_nav_service(bundle):
    eng = FakeEngine(lambda k, t, sy: calls(call("gps_accuracy")) if k == "ask" else None)
    b = Brain(eng, None)
    b.ask("gps")
    (res, say), = results(eng)
    assert res == {"error": "navigation is not running"} and say == "Navigation isn't available right now."


# ---- modes
def test_modes_requests():
    m = ModeMachine()
    assert not m.request("OUTDOOR_NAV", navigating=False).ok
    assert m.request("indoor_nav", False).ok and m.mode == "INDOOR_NAV"
    assert m.request("EXPLORE", False).ok
    assert m.request("IDLE", False).mode == "INDOOR_NAV"  # back to where exploring began
    assert not m.request("DANCE", False).ok


def test_modes_explore_during_trip():
    m = ModeMachine()
    m.force("OUTDOOR_NAV")
    m.request("EXPLORE", True, "OUTDOOR_NAV")
    m.force("BUS_WATCH")  # the trip moved on while exploring: mode stays EXPLORE
    assert m.mode == "EXPLORE"
    ch = m.request("IDLE", True, "BUS_WATCH")
    assert ch.mode == "BUS_WATCH" and "Back to the trip" in ch.say
    assert not m.request("IDLE", True, "BUS_WATCH").ok  # stop_navigation ends a trip, not set_mode


def test_modes_force_illegal():
    m = ModeMachine()
    seen = []
    m.on_change = lambda a, b: seen.append((a, b))
    assert not m.force("TRANSIT") or m.mode == "TRANSIT"
    m2 = ModeMachine()
    m2.force("EXPLORE")
    assert m2.force("BUS_WATCH")
    assert m2.mode == "EXPLORE" and m2.before_explore == "BUS_WATCH"


def test_registry_covers_every_service_tool(bundle):
    reg = T.load()
    s, _ = nav(bundle)
    names = {t.name for t in reg.tools}
    assert names == set(s.tools) | {"set_mode", "camera"}


def test_chitchat_set_mode_to_the_same_mode_lets_the_model_answer():
    """Small LMs call set_mode IDLE on "hi". Cortex is already IDLE: the user must hear the answer, not "Okay."."""
    eng = FakeEngine(lambda k, t, sy: calls(call("set_mode", mode="IDLE")) if k == "ask" else toks("Hi! I'm here."))
    b = Brain(eng, None)
    turn = b.ask("hi there")
    kind, result, say = [x for x in eng.log if x[0] == "tool_result"][0]
    assert say is None  # no template: the LM answers
    assert json.loads(result)["changed"] is False
    assert turn.text.endswith("Hi! I'm here.") and turn.said is None
    assert b.mode == "IDLE"


def test_leaving_explore_still_speaks_the_template():
    eng = FakeEngine(lambda k, t, sy: calls(call("set_mode", mode="EXPLORE")) if k == "ask" else toks("x"))
    b = Brain(eng, None)
    b.ask("what's around me")
    assert eng.log[-1][2] == "Exploring. I'll describe what's around you."
    eng.script = lambda k, t, sy: calls(call("set_mode", mode="IDLE")) if k == "ask" else toks("x")
    b.ask("stop exploring")
    assert eng.log[-1][2] == "Okay." or eng.log[-1][2].startswith("Stopped exploring")
    assert b.mode == "IDLE"


def test_repeated_same_mode_call_ends_with_the_template_not_a_loop():
    # the LM keeps calling; once a template is spoken the engine ends the turn (say != None)
    eng = FakeEngine(lambda k, t, sy: None if sy else calls(call("set_mode", mode="IDLE")))
    b = Brain(eng, None)
    turn = b.ask("hello")
    results = [x for x in eng.log if x[0] == "tool_result"]
    assert [x[2] for x in results] == [None, "Okay."]
    assert turn.said == "Okay."


def test_answered_then_same_mode_call_does_not_answer_twice():
    """Seen on the stand-in: the LM answers in words, then also calls set_mode IDLE."""
    def script(k, t, sy):
        if k == "ask":
            return [{"type": "token", "text": "Four."}, *calls(call("set_mode", mode="IDLE"))]
        return None
    eng = FakeEngine(script)
    b = Brain(eng, None)
    turn = b.ask("what is two plus two")
    assert [x[2] for x in eng.log if x[0] == "tool_result"] == ["Okay."]
    assert turn.text == "Four."
