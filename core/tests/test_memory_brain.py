"""Memory joined to the rest: the Brain (scans while idle, cut by the user, search_memory), the engine's peek
binding, nav's where() and the phone link's memory op."""
import json
import threading
import time

import pytest

from cortex_core.brain import tools as T
from cortex_core.brain.brain import Brain
from cortex_core.engine import native
from cortex_core.link import phone_link as pl
from cortex_core.memory.memory import Memory, engine_looker
from cortex_core.memory.store import Store
from cortex_core.nav import bundle as B
from cortex_core.nav import geo
from cortex_core.nav.service import NavService

import nav_city as C
from test_brain import FakeEngine, call, toks
from test_phone_link import SECRET, mk, provision, req


class PeekEngine(FakeEngine):
    """FakeEngine with a silent look; peek_gate (if set) holds the look open until it is set or cancelled."""

    def __init__(self, script, looks=()):
        super().__init__(script)
        self.can_peek = True
        self.looks = list(looks)
        self.peeks = []
        self.peek_gate = None
        self._cut = threading.Event()

    def peek(self, text, max_tokens, timeout=60):
        self.peeks.append(text)
        self._cut.clear()
        if self.peek_gate is not None:
            while not self.peek_gate.is_set() and not self._cut.is_set():
                time.sleep(0.005)
        if self._cut.is_set():
            return iter([{"type": "done", "kind": "peek", "cancelled": True}])
        out = self.looks.pop(0) if self.looks else "none"
        return iter([{"type": "token", "text": out}, {"type": "done", "kind": "peek"}])

    def cancel(self):
        super().cancel()
        self._cut.set()


def brain_with_memory(tmp_path, looks=(), script=None, where=None):
    eng = PeekEngine(script or (lambda k, t, s: None), looks)
    events = []
    m = Memory(Store(tmp_path / "m.db"), engine_looker(eng), where=where)
    b = Brain(eng, None, T.load(), on_event=lambda k, d: events.append((k, d)), memory=m)
    return b, eng, m, events


def view(fid, skipped=False):
    return {"type": "view", "frame_id": fid, "skipped": skipped}


def test_registry_has_search_memory():
    t = T.load().get("search_memory")
    assert t.spoken_by == "lm" and t.allowed_in("IDLE") and t.allowed_in("TRANSIT")


def test_idle_view_is_scanned_and_recorded(tmp_path):
    b, eng, m, events = brain_with_memory(tmp_path, ["keys | silver | on the kitchen table"])
    th = b.on_view(view(1))
    assert th is not None
    th.join(2)
    assert m.store.sightings("keys")[0]["spot"] == "on the kitchen table"
    assert ("memory", {"seen": [{"item": "keys", "looks": "silver", "spot": "on the kitchen table"}]}) in events
    assert "keys" in eng.peeks[0]
    assert b.on_view(view(1)) is None  # the same frame again


def test_no_scan_while_talking_or_without_peek(tmp_path):
    b, eng, m, _ = brain_with_memory(tmp_path)
    b.voice_event({"type": "speech_start", "at_ms": 0})
    assert b.on_view(view(1)) is None
    b.voice_event({"type": "done", "voice": True})
    assert b.on_view(view(2)) is not None
    eng2 = FakeEngine(lambda k, t, s: None)  # an engine build without ce_peek
    m2 = Memory(Store(tmp_path / "n.db"), engine_looker(eng2))
    assert not m2.can_learn
    assert Brain(eng2, None, T.load(), memory=m2).on_view(view(1)) is None


def test_typed_question_cuts_a_running_scan(tmp_path):
    b, eng, m, _ = brain_with_memory(tmp_path, ["keys | a | b"],
                                     script=lambda k, t, s: toks("Hello.") if k == "ask" else None)
    eng.peek_gate = threading.Event()
    th = b.on_view(view(1))
    while not eng.peeks:
        time.sleep(0.005)
    t0 = time.monotonic()
    turn = b.ask("hi")
    assert time.monotonic() - t0 < 0.5 and turn.text == "Hello."
    th.join(2)
    assert eng.cancelled >= 1 and m.store.sightings("keys") == []  # a cut scan stores nothing


def test_speech_start_cuts_a_running_scan(tmp_path):
    b, eng, m, _ = brain_with_memory(tmp_path, ["keys | a | b"])
    eng.peek_gate = threading.Event()
    th = b.on_view(view(1))
    while not eng.peeks:
        time.sleep(0.005)
    b.voice_event({"type": "speech_start", "at_ms": 0})
    th.join(2)
    assert not th.is_alive() and m.store.sightings("keys") == []


def test_search_memory_tool_goes_back_to_the_lm(tmp_path):
    def script(kind, text, say):
        if kind == "ask":
            return [{"type": "tool_call", "text": call("search_memory", item="my keys")}, {"type": "done", "tool": True}]
        if kind == "tool_result":
            return toks("On the kitchen table, about 20 minutes ago.")
    b, eng, m, _ = brain_with_memory(tmp_path, script=script)
    m.store.record("keys", time.time() - 1200, "silver", "on the kitchen table", "Home", None, None, None)
    t = b.ask("where are my keys")
    res = json.loads(eng.log[1][1])
    assert eng.log[1][0] == "tool_result" and eng.log[1][2] is None  # the LM phrases it
    assert res["spot"] == "on the kitchen table" and res["place"] == "Home" and res["ago"] == "about 20 minutes ago"
    assert t.text == "On the kitchen table, about 20 minutes ago."


def test_search_memory_without_memory(tmp_path):
    eng = FakeEngine(lambda k, t, s: [{"type": "tool_call", "text": call("search_memory", item="keys")},
                                      {"type": "done", "tool": True}] if k == "ask" else None)
    Brain(eng, None, T.load()).ask("where are my keys")
    assert "error" in json.loads(eng.log[1][1])


def test_cue_waits_for_scan_then_is_spoken(tmp_path):
    b, eng, m, events = brain_with_memory(tmp_path, ["keys | a | b"])
    eng.peek_gate = threading.Event()
    th = b.on_view(view(1))
    while not eng.peeks:
        time.sleep(0.005)
    b.cue("Turn left in 40 metres.")
    assert ("said", {"text": "Turn left in 40 metres."}) not in events
    eng.peek_gate.set()
    th.join(2)
    assert ("said", {"text": "Turn left in 40 metres."}) in events


# ---------------------------------------------------------------- engine binding
def test_peek_events_route_to_the_answer_queue():
    assert native.route_event({"type": "token", "text": "x"}, True) == "answer"
    assert native.route_event({"type": "done", "kind": "peek"}, True) == "answer"


def test_engine_looker_reads_tokens_and_drops_cut_looks():
    class E:
        can_peek = True

        def __init__(self, evs):
            self.evs = evs

        def peek(self, text, n):
            return iter(self.evs)
    assert engine_looker(E([{"type": "token", "text": "keys | a"}, {"type": "token", "text": " | b"},
                            {"type": "done", "kind": "peek"}]))("p", 9) == "keys | a | b"
    assert engine_looker(E([{"type": "done", "kind": "peek", "cancelled": True}]))("p", 9) is None
    assert engine_looker(E([{"type": "error", "what": "busy"}, {"type": "done"}]))("p", 9) is None


# ---------------------------------------------------------------- nav where()
@pytest.fixture(scope="module")
def city(tmp_path_factory):
    d = tmp_path_factory.mktemp("city")
    return B.Bundle(C.make(d))


def test_where_names_a_saved_place_or_a_nearby_place(city):
    i = next(i for i in range(city.n_places) if city.s(int(city.place_kind[i])) not in ("bus_stop", "postcode",
                                                                                          "address"))
    px, py = float(city.place_x[i]), float(city.place_y[i])
    lat, lon = geo.to_latlon(px + 20, py)
    clock = lambda: 1000.0
    nav = NavService(city, saved={}, clock=clock)
    assert nav.where() is None  # no fix yet
    nav.on_fix(lat, lon, 6.0, 1000.0)
    w = nav.where()
    assert w["name"] == city.s(int(city.place_name[i])) and w["acc_m"] == 6.0 and abs(w["lat"] - lat) < 1e-9
    nav2 = NavService(city, saved={"home": {"name": "Home", "lat": lat, "lon": lon}}, clock=clock)
    nav2.on_fix(*geo.to_latlon(px + 50, py), 6.0, 1000.0)  # 30 m from home
    assert nav2.where()["name"] == "Home"
    far = NavService(city, saved={}, clock=clock)
    far.on_fix(*geo.to_latlon(px + 1e6, py + 1e6), 6.0, 1000.0)
    w = far.where()
    assert w["name"] is None and w["lat"] is not None


# ---------------------------------------------------------------- phone link op
def test_phone_link_memory_op(tmp_path):
    link, _ = mk(tmp_path)
    assert provision(link)["ok"]
    store = Store(tmp_path / "m.db")
    link.memory = store
    st = {}

    def op(rid, args):
        return link.handle(req(rid, "memory", args, SECRET), "n", st)

    r = op(10, {"action": "list"})
    assert r["ok"] and [i["name"] for i in r["items"]][:6] == ["keys", "wallet", "phone", "glasses", "bag", "cane"]
    assert r["items"][0]["builtin"] is True
    assert op(11, {"action": "add", "name": "Water bottle", "details": "blue", "aliases": ["flask"]})["ok"]
    items = op(12, {"action": "list"})["items"]
    assert {"name": "water bottle", "details": "blue", "aliases": ["flask"], "builtin": False} in items
    bad = op(13, {"action": "add", "name": "keys"})
    assert not bad["ok"] and "already" in bad["error"]
    store.record("water bottle", 1.0, "", "on the desk", None, None, None, None)
    store.record("keys", 1.0, "", "on the desk", None, None, None, None)
    assert op(14, {"action": "forget", "item": "keys"})["ok"] and store.sightings("keys") == []
    assert op(15, {"action": "remove", "name": "flask"})["ok"] and store.sightings("water bottle") == []
    assert not op(16, {"action": "remove", "name": "cane"})["ok"]
    assert op(17, {"action": "forget"})["ok"]
    assert not op(18, {"action": "explode"})["ok"]
    assert not op(19, {"action": "add", "name": ["not", "a", "string"]})["ok"]
    link.memory = None
    assert op(20, {"action": "list"}) == {"id": 20, "ok": False, "error": "memory not running"}
