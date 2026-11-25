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


def test_nearest_many_matches_nearest(city):
    w = Walker(city)
    rng = np.random.default_rng(1)
    x0, y0 = C.xy(-3, -3)
    qx = x0 + rng.uniform(0, 1300, 400)
    qy = y0 + rng.uniform(0, 1300, 400)
    many = w.nearest_many(qx, qy, 120.0)
    one = [w.nearest(float(a), float(b), 120.0) for a, b in zip(qx, qy)]
    d_many = [np.hypot(w.x[i] - a, w.y[i] - b) if i >= 0 else -1 for i, a, b in zip(many, qx, qy)]
    d_one = [np.hypot(w.x[i] - a, w.y[i] - b) if i >= 0 else -1 for i, a, b in zip(one, qx, qy)]
    assert np.allclose(d_many, d_one)  # same distance (ties may pick another node)
    assert (many == -1).sum() > 0  # points far outside the grid


def test_area_place_uses_its_entrance(tmp_path):
    """A mall whose middle is nearest a footway across the road gets the node by its entrance instead."""
    from cortex_core.nav import build, geo
    lat, lon = [], []
    for r, c in [(0, 0), (0, 4), (6, 0), (6, 4)]:  # two separate east-west paths 300 m apart, no link between
        a, o = C.latlon(r, c)
        lat.append(a), lon.append(o)
    ways = [(0, 1, 0, "South Path"), (2, 3, 0, "North Path")]
    mid = C.latlon(2.5, 2)  # the centroid is nearer the south path...
    ent = C.latlon(5.6, 2)  # ...but the entrance opens onto the north path
    places = [{"name": "Test Mall", "kind": "mall", "lat": mid[0], "lon": mid[1], "access": [ent]},
              {"name": "Kiosk", "kind": "shop", "lat": mid[0], "lon": mid[1]}]
    arr = build.assemble(lat, lon, ways, [], [], places, log=lambda *_: None)
    b = B.Bundle(B.write(tmp_path, "v", arr, {}))
    assert set(b.place_nodes(0)) <= {2, 3}  # the ways in are on the north path, not the nearer south one
    assert b.place_nodes(1) == [int(b.place_node[1])] and int(b.place_node[1]) in (0, 1)  # a point place
    w = Walker(b)
    p = w.route(2, b.place_nodes(0))
    assert p is not None and p.nodes[-1] in (2, 3)


def test_route_to_the_quickest_of_several(city):
    w = Walker(city)
    p = w.route(C.node(0, 0), [C.node(0, 10), C.node(3, 0), C.node(20, 20)])
    assert p.nodes[-1] == C.node(3, 0) and p.length_m == pytest.approx(150, rel=0.01)
    r = w.reach([C.node(0, 0), C.node(20, 20)], 60)
    assert r[C.node(0, 1)] == pytest.approx(50, rel=0.01) and r[C.node(19, 20)] == pytest.approx(50, rel=0.01)


def test_kind_bonus_station_over_clinic(tmp_path):
    from cortex_core.nav import build
    a, o = C.latlon(0, 0)
    stops = [{"code": 0, "name": "Khatib", "lat": a, "lon": o, "kind": B.K_MRT}]
    places = [{"name": "Khatib Polyclinic", "kind": "clinic", "lat": a, "lon": o}]
    arr = build.assemble([a, a + 0.001], [o, o], [(0, 1, 0, "")], stops, [], places, log=lambda *_: None)
    b = B.Bundle(B.write(tmp_path, "v", arr, {}))
    assert Places(b).search("khatib")[0].kind == "mrt_station"
