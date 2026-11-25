"""End to end: "take me to Northpoint" through the Brain (scripted LM tool calls), then a simulated walk / wait /
ride / walk of GPS fixes (tests/nav_sim.py) until "You have arrived". The synthetic city always; the real Singapore
bundle too when one is on this machine (CORTEX_NAV_BUNDLES, default ~/cortex-data/navbundle)."""
import json
import os
from pathlib import Path

import pytest

from cortex_core.brain.brain import Brain
from cortex_core.nav import bundle as B, geo
from cortex_core.nav.service import NavService

import nav_city as C
import nav_sim

RIDE_ORDER = ["at_stop", "boarded", "alight_now", "leg"]


def call(name, **args):
    body = "".join(f"<parameter={k}>\n{v}\n</parameter>\n" for k, v in args.items())
    return [{"type": "tool_call", "text": f"<tool_call>\n<function={name}>\n{body}</function>\n</tool_call>"},
            {"type": "done", "tool": True}]


class TripLM:
    """The LM side of "take me to <query>": search, plan the first match, start."""

    def __init__(self, query):
        self.query = query
        self.said = []
        self.state = []
        self.cancelled = 0

    def ask(self, text, max_tokens=0, timeout=60):
        return iter(call("search_places", query=self.query))

    def tool_result(self, result, say=None, timeout=60):
        r = json.loads(result)
        if r.get("matches"):
            return iter(call("plan_trip", place_id=r["matches"][0]["place_id"]))
        if "summary" in r:
            return iter(call("start_navigation"))
        if say:
            self.said.append(say)
        return iter([{"type": "done"}])

    def say(self, text, timeout=60):
        self.said.append(text)
        return iter([{"type": "done"}])

    def set_state(self, text):
        self.state.append(text)

    def cancel(self):
        self.cancelled += 1


def ride(bundle, start_latlon, query, **sim):
    clk = [0.0]
    nav = NavService(bundle, saved={}, clock=lambda: clk[0], hour=lambda: 9.0)
    lm = TripLM(query)
    modes = []
    br = Brain(lm, nav, on_event=lambda k, d: modes.append(d["to"]) if k == "mode" else None)
    br.on_fix(*start_latlon, 5.0, 0.0)
    turn = br.ask(f"take me to {query}")
    trip = nav.trip
    assert trip is not None, turn
    evs = []
    for lat, lon, acc, t, sp in nav_sim.trip_fixes(bundle, trip, t0=1.0, **sim):
        clk[0] = t
        evs += [e.type for e in br.on_fix(lat, lon, acc, t, sp)]
        if not nav.navigating:
            break
    return turn, trip, modes, evs, lm, nav


@pytest.fixture(scope="module")
def city(tmp_path_factory):
    return B.Bundle(C.make(tmp_path_factory.mktemp("nav")))


def test_city_home_to_northpoint_by_mrt(city):
    turn, trip, modes, evs, lm, nav = ride(city, C.latlon(0, 0), "northpoint")
    assert [c.name for c in turn.calls] == ["search_places", "plan_trip", "start_navigation"]
    assert turn.said.startswith("Starting.")
    rides = [l.mode for l in trip.legs if l.mode != "walk"]
    assert rides, trip.summary()
    # every ride is announced in order, and the trip ends with an arrival
    order = [e for e in evs if e in RIDE_ORDER + ["arrived"]]
    assert order[-1] == "arrived" and order.count("arrived") == 1
    for i in range(len(rides)):
        seq = order[i * 4:i * 4 + 4]
        assert seq == RIDE_ORDER[:len(seq)] or seq[:3] == RIDE_ORDER[:3], order
    # the modes follow the trip: walk, wait at the stop, ride, walk, done
    assert modes[0] == ("OUTDOOR_NAV" if trip.legs[0].mode == "walk" else "BUS_WATCH")
    assert modes.index("BUS_WATCH") < modes.index("TRANSIT") and modes[-1] == "IDLE"
    assert lm.said[-1] == "You have arrived." and not nav.navigating
    assert "off_route" not in evs and "rerouted" not in evs


def test_city_trip_survives_gps_jitter(city):
    _, _, _, evs, lm, nav = ride(city, C.latlon(0, 0), "northpoint", jitter_m=4.0, seed=3)
    assert evs.count("arrived") == 1 and "rerouted" not in evs and not nav.navigating


def test_city_weak_gps_is_announced_once_and_does_not_reroute(city):
    _, _, _, evs, lm, nav = ride(city, C.latlon(0, 0), "northpoint", acc_m=80.0)
    assert evs == ["gps_weak"] and lm.said.count("GPS is weak here. Go slowly.") == 1
    assert nav.navigating  # bad fixes decide nothing: still on the first leg


def test_city_detour_reroutes_and_still_arrives(city):
    clk = [0.0]
    nav = NavService(city, saved={}, clock=lambda: clk[0], hour=lambda: 9.0)
    lm = TripLM("northpoint")
    br = Brain(lm, nav)
    br.on_fix(*C.latlon(0, 0), 5.0, 0.0)
    br.ask("take me to northpoint")
    evs = []
    # wander 150 m the wrong way (south-west, off every path of the trip)
    x0, y0 = C.xy(0, 0)
    for k in range(1, 12):
        clk[0] = float(k)
        evs += [e.type for e in br.on_fix(*geo.to_latlon(x0 - 10 * k, y0 - 10 * k), 5.0, float(k), 1.3)]
    assert "off_route" in evs and "rerouted" in evs and nav.reroutes >= 1
    assert any(s.startswith("New route.") for s in lm.said)
    for lat, lon, acc, t, sp in nav_sim.trip_fixes(city, nav.trip, t0=20.0):
        clk[0] = t
        evs += [e.type for e in br.on_fix(lat, lon, acc, t, sp)]
        if not nav.navigating:
            break
    assert evs[-1] == "arrived"


REAL = Path(os.environ.get("CORTEX_NAV_BUNDLES", Path.home() / "cortex-data" / "navbundle"))


@pytest.fixture(scope="module")
def sg():
    try:
        return B.Bundle(B.latest(REAL))
    except (B.BundleError, FileNotFoundError):
        pytest.skip(f"no real nav bundle in {REAL}")


@pytest.mark.parametrize("start, dest, want", [
    ("Ang Mo Kio Hub", "northpoint", "MRT NSL"),
    ("Khoo Teck Puat Hospital", "northpoint", "Walk"),
    ("Bishan MRT Station", "causeway point", "MRT NSL"),
])
def test_singapore_trip_end_to_end(sg, start, dest, want):
    from cortex_core.nav.places import Places
    h = Places(sg).search(start)[0]
    turn, trip, modes, evs, lm, nav = ride(sg, tuple(map(float, geo.to_latlon(h.x, h.y))), dest, jitter_m=3.0)
    assert want in trip.summary()
    assert evs[-1] == "arrived" and "rerouted" not in evs and not nav.navigating
    if any(l.mode != "walk" for l in trip.legs):
        assert [m for m in modes if m != "OUTDOOR_NAV"][:2] == ["BUS_WATCH", "TRANSIT"]
    assert modes[-1] == "IDLE"
