import json
import time

import numpy as np
import pytest

from cortex_core.nav import bundle as B
from cortex_core.nav.places import Places, normalize
from cortex_core.nav.transit import Planner
from cortex_core.nav.walk import Walker, describe_distance

import nav_city as C


@pytest.fixture(scope="module")
def city(tmp_path_factory):
    return B.Bundle(C.make(tmp_path_factory.mktemp("nav")), verify=True)


def test_bundle_roundtrip_and_manifest(city, tmp_path):
    assert city.n_nodes == C.N * C.N + 1
    assert city.n_patterns == 6
    assert city.s(int(city.pat_service[0])) == "100"
    assert city.stop_label(0) == "Row Stop 0 (59000)"
    m = json.loads((city.path / "manifest.json").read_text())
    assert m["format"] == 1 and "node_x" in m["files"]
    assert not city.node_x.flags.writeable  # memory-mapped read-only


def test_bundle_tamper_detected(tmp_path):
    p = C.make(tmp_path)
    f = p / "edge_len.npy"
    data = bytearray(f.read_bytes())
    data[-1] ^= 0xFF
    f.write_bytes(bytes(data))
    with pytest.raises(B.BundleError, match="edge_len"):
        B.Bundle(p, verify=True)


def test_bundle_versions_never_overwritten(tmp_path):
    C.make(tmp_path, "v1")
    with pytest.raises(B.BundleError):
        C.make(tmp_path, "v1")
    C.make(tmp_path, "v2")
    assert B.latest(tmp_path).name == "v2"


def test_band_of():
    assert [B.band_of(h) for h in (7, 9, 17.5, 22, 3)] == [0, 1, 2, 3, 3]


def test_walk_straight_and_steps(city):
    w = Walker(city)
    p = w.route(C.node(0, 0), C.node(0, 10))
    assert p.length_m == pytest.approx(500, rel=0.01)
    assert p.steps[0].text.startswith("Head east along Row Street 0")
    assert p.steps[-1].kind == "arrive"


def test_walk_turn_instruction(city):
    w = Walker(city)
    p = w.route(C.node(0, 0), C.node(6, 6))
    assert p.length_m == pytest.approx(600, rel=0.01)
    turns = [s for s in p.steps if s.kind == "turn"]
    assert turns, p.steps
    assert any("turn" in s.text.lower() for s in turns)


def test_walk_prefers_ramp_over_steps(city):
    w = Walker(city)
    p = w.route(C.node(10, 4), C.node(10, 5))
    assert len(p.nodes) == 3  # via the ramp node, not the 50 m of steps
    assert p.length_m > 50


def test_walk_crossing_announced(city):
    w = Walker(city)
    p = w.route(C.node(4, 10), C.node(7, 10))
    assert any(s.kind == "cross" and "traffic light" in s.text for s in p.steps)


def test_nearest(city):
    w = Walker(city)
    x, y = C.xy(3.2, 7.9)
    assert w.nearest(x, y) == C.node(3, 8)
    assert w.nearest(x + 5000, y) == -1


def test_places_search(city):
    pl = Places(city)
    x, y = C.xy(0, 0)
    hits = pl.search("northpoint", x, y)
    assert hits[0].name == "Northpoint City"
    assert hits[0].dist_m == pytest.approx(np.hypot(19 * 50, 20 * 50), rel=0.01)
    assert pl.search("KTPH")[0].name == "Khoo Teck Puat Hospital"
    assert pl.search("769098")[0].name == "Northpoint City"
    assert pl.search("amk hub")[0].name == "Ang Mo Kio Hub"
    assert pl.search("hawker")[0].kind == "hawker_centre"
    assert pl.search("blk 101 yishun ave 5")[0].name.startswith("Block 101")
    assert pl.search("beta mrt")[0].kind == "mrt_station"
    assert pl.search("59008")  # bus stop codes are searchable
    assert pl.search("zzqx") == []
    assert normalize("Blk 101, Yishun Ave 5") == "block 101 yishun avenue 5"


def test_place_id_roundtrip(city):
    h = Places(city).search("northpoint")[0]
    assert Places.parse_id(h.brief()["place_id"]) == h.id
    with pytest.raises(ValueError):
        Places.parse_id("northpoint")


def test_transfers_exist(city):
    # Row Stop 20 (0,20) and Col Stop 0 (0,20) are the same corner
    s_row = 5  # row0 stops: c = 0,4,8,12,16,20 -> index 5
    tos = city.tr_to[city.tr_off[s_row]:city.tr_off[s_row + 1]]
    assert len(tos) > 0


def test_plan_bus_trip(city):
    pl = Planner(city)
    its = pl.plan(C.node(0, 0), C.node(0, 20), hour=9)
    assert its
    best = its[0]
    assert best.rides >= 1
    modes = [l.mode for l in best.legs]
    assert "bus" in modes or "MRT" in modes
    assert best.minutes < 1000 / 1.1 / 60  # quicker than walking the kilometre


def test_plan_two_rides(city):
    pl = Planner(city)
    its = pl.plan(C.node(0, 0), C.node(20, 20), hour=9)
    # the MRT goes straight there (1 ride): fewer rides within 5 min wins
    assert its[0].rides == 1 and [l.mode for l in its[0].legs if l.mode != "walk"] == ["MRT"]
    # no plan rides away from the destination and walks back (a second ride must be strictly quicker)
    assert all(i.rides <= 1 for i in its)
    s = its[0].summary()
    assert "MRT Test Line" in s and "minutes" in s


def test_plan_short_trip_walks(city):
    its = Planner(city).plan(C.node(0, 0), C.node(2, 2), hour=9)
    assert its[0].rides == 0 and its[0].legs[0].mode == "walk"


def test_plan_brief_is_json(city):
    its = Planner(city).plan(C.node(0, 0), C.node(20, 20), hour=18)
    json.dumps([i.brief() for i in its])


def test_plan_speed(city):
    pl = Planner(city)
    t = time.perf_counter()
    pl.plan(C.node(0, 0), C.node(20, 20))
    assert time.perf_counter() - t < 1.0


def test_describe_distance():
    assert describe_distance(8) == "now"
    assert describe_distance(42) == "in 40 metres"
    assert describe_distance(240) == "in 240 metres"
    assert describe_distance(1500) == "in 1.5 kilometres"
