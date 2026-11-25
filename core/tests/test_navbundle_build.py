"""The server-side bundle builder (infra/navbundle/build.py) on a tiny OSM file written here with pyosmium."""
import importlib.util
import json
from pathlib import Path

import pytest

osmium = pytest.importorskip("osmium")
from osmium.osm import mutable  # noqa: E402

from cortex_core.nav import bundle as B  # noqa: E402
from cortex_core.nav.places import Places  # noqa: E402
from cortex_core.nav.service import NavService  # noqa: E402
from cortex_core.nav.walk import Walker  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("navbundle_build", ROOT / "infra" / "navbundle" / "build.py")
NB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NB)

LAT0, LON0 = 1.4200, 103.8300
DLAT, DLON = 0.0009, 0.0009  # ~100 m


def at(r, c):
    return (LON0 + c * DLON, LAT0 + r * DLAT)  # osmium: (lon, lat)


def write_osm(path: Path):
    """A 3x6 footway grid (rows 0..2, cols 0..5), a road with no sidewalk, two bus stops with a bus route, two MRT
    stations on a line (one named only on its stop position), a mall whose entrance faces the north row, an HDB
    block with a postcode, a unit-number address (dropped), and a station outside Singapore (dropped)."""
    w = _Sorted(str(path))  # an OSM file is nodes, then ways, then relations
    nid = lambda r, c: 1000 + r * 10 + c  # noqa: E731
    for r in range(3):
        for c in range(6):
            tags = {"highway": "crossing", "crossing": "traffic_signals"} if (r, c) == (1, 2) else {}
            w.add_node(mutable.Node(id=nid(r, c), location=at(r, c), tags=tags))
    # mall outline between rows 1 and 2 at cols 3..4; entrance node 2010 on its north wall, facing row 2's footway
    outline = [(1.3, 3.2), (1.3, 3.8), (1.7, 3.8), (1.7, 3.2)]
    for i, (r, c) in enumerate(outline):
        w.add_node(mutable.Node(id=2000 + i, location=at(r, c), tags={}))
    w.add_node(mutable.Node(id=2010, location=at(1.7, 3.5), tags={"entrance": "main"}))  # on the north wall
    nodes = [
        mutable.Node(id=3001, location=at(0, 0.1), tags={"highway": "bus_stop", "ref": "59009", "name": "Blk 101"}),
        mutable.Node(id=3002, location=at(0, 4.9), tags={"highway": "bus_stop", "ref": "59011", "name": "Opp Blk 9"}),
        mutable.Node(id=3003, location=at(0, 3), tags={"highway": "bus_stop", "ref": "12", "name": "No code"}),
        mutable.Node(id=4001, location=at(2, 0.1), tags={"railway": "station", "station": "subway",
                                                          "name": "Khatib (NS14)"}),
        mutable.Node(id=4002, location=at(2, 4.9), tags={"public_transport": "stop_position", "subway": "yes",
                                                          "name": "Yishun MRT Station"}),
        mutable.Node(id=4003, location=(110.0, 1.5), tags={"railway": "station", "station": "subway",
                                                            "name": "Far Away"}),
        mutable.Node(id=5001, location=at(0.5, 1), tags={"addr:housenumber": "101", "addr:street": "Yishun Avenue 5",
                                                          "addr:postcode": "760101"}),
        mutable.Node(id=5002, location=at(0.5, 2), tags={"addr:housenumber": "#01-03",
                                                          "addr:street": "Yishun Avenue 5", "shop": "bakery"}),
        mutable.Node(id=5003, location=at(1.5, 0.5), tags={"amenity": "clinic", "name": "Khatib Polyclinic"}),
    ]
    for n in nodes:
        w.add_node(n)
    wid = 100
    for r in range(3):
        if r == 1:
            continue  # row 1 is a main road with no sidewalk
        w.add_way(mutable.Way(id=wid, nodes=[nid(r, c) for c in range(6)],
                              tags={"highway": "footway", "name": f"Path {r}"}))
        wid += 1
    w.add_way(mutable.Way(id=wid, nodes=[nid(1, c) for c in range(6)],
                          tags={"highway": "primary", "name": "Yishun Avenue 2"}))
    wid += 1
    for c in range(6):
        w.add_way(mutable.Way(id=wid, nodes=[nid(0, c), nid(1, c), nid(2, c)], tags={"highway": "footway"}))
        wid += 1
    # the mall outline, closed, with its entrance node on it
    w.add_way(mutable.Way(id=wid, nodes=[2000, 2001, 2002, 2010, 2003, 2000],
                          tags={"shop": "mall", "name": "Northpoint City", "building": "retail"}))
    wid += 1
    w.add_way(mutable.Way(id=wid, nodes=[2000, 2001, 2002, 2003, 2000], tags={"highway": "footway", "access": "no",
                                                                              "foot": "no"}))
    wid += 1
    # a mall mapped as a multipolygon relation (like VivoCity), outer ring an untagged closed way, rows 0..1 cols 0..1
    ring = [(0.3, 0.3), (0.3, 0.7), (0.7, 0.7), (0.7, 0.3)]
    for i, (r, c) in enumerate(ring):
        w.add_node(mutable.Node(id=6000 + i, location=at(r, c), tags={}))
    w.add_way(mutable.Way(id=wid, nodes=[6000, 6001, 6002, 6003, 6000], tags={}))
    w.add_relation(mutable.Relation(id=10, members=[("w", wid, "outer")],
                                    tags={"type": "multipolygon", "shop": "mall", "name": "Harbour Mall"}))
    wid += 1
    # a station mapped only as an area (like Sengkang / Punggol), and the line's stop position named after its
    # route ("Punggol - Loop"), 200 m away (too far for the nearest-station rule alone)
    sq = [(1.8, 5.6), (1.8, 6.2), (2.2, 6.2), (2.2, 5.6)]
    for i, (r, c) in enumerate(sq):
        w.add_node(mutable.Node(id=7000 + i, location=at(r, c), tags={}))
    w.add_way(mutable.Way(id=wid, nodes=[7000, 7001, 7002, 7003, 7000],
                          tags={"railway": "station", "public_transport": "station", "network": "Mass Rapid Transit",
                                "light_rail": "yes", "name": "Punggol", "building": "train_station"}))
    wid += 1
    w.add_node(mutable.Node(id=4004, location=at(4, 5.9), tags={"public_transport": "stop_position", "subway": "yes",
                                                               "name": "Punggol - Loop"}))
    # Punggol / Bukit Panjang LRT are route=monorail in OSM; the airport Skytrain (also monorail) is not ours
    w.add_node(mutable.Node(id=4010, location=at(0, 5.9), tags={"public_transport": "stop_position", "monorail": "yes",
                                                               "name": "Sam Kee"}))
    w.add_node(mutable.Node(id=4011, location=at(2, 6.9), tags={"public_transport": "stop_position", "monorail": "yes",
                                                               "name": "Teck Lee"}))
    w.add_relation(mutable.Relation(id=20, members=[("n", 4010, "stop"), ("n", 4011, "stop")],
                                    tags={"type": "route", "route": "monorail", "ref": "PGLRT"}))
    w.add_relation(mutable.Relation(id=21, members=[("n", 4011, "stop"), ("n", 4010, "stop")],
                                    tags={"type": "route", "route": "monorail", "ref": "Skytrain"}))
    w.add_relation(mutable.Relation(id=1, members=[("n", 3001, "stop"), ("n", 3003, "stop"), ("n", 3002, "stop")],
                                    tags={"type": "route", "route": "bus", "ref": "858"}))
    w.add_relation(mutable.Relation(id=2, members=[("n", 4001, "stop"), ("n", 4002, "stop_entry_only"),
                                                   ("n", 4004, "stop")],
                                    tags={"type": "route", "route": "subway", "ref": "NSL"}))
    w.add_relation(mutable.Relation(id=3, members=[("n", 4001, "")], tags={"type": "route", "route": "subway"}))
    w.close()


class _Sorted:
    def __init__(self, path):
        self.path, self.n, self.w, self.r = path, [], [], []

    def add_node(self, o):
        self.n.append(o)

    def add_way(self, o):
        self.w.append(o)

    def add_relation(self, o):
        self.r.append(o)

    def close(self):
        out = osmium.SimpleWriter(self.path)
        for objs, add in ((self.n, out.add_node), (self.w, out.add_way), (self.r, out.add_relation)):
            for o in sorted(objs, key=lambda o: o.id):
                add(o)
        out.close()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("osm")
    pbf = d / "tiny.osm.pbf"
    write_osm(pbf)
    lta = d / "lta"
    lta.mkdir()
    (lta / "BusServices.json").write_text(json.dumps({"value": [
        {"ServiceNo": "858", "AM_Peak_Freq": "08-10", "AM_Offpeak_Freq": "10-14", "PM_Peak_Freq": "09-11",
         "PM_Offpeak_Freq": "12-15"}]}))
    assert NB.main(["--pbf", str(pbf), "--out", str(d / "out"), "--lta-dir", str(lta), "--version", "t1"]) == 0
    return B.Bundle(B.latest(d / "out"), verify=True)


def test_station_naming_and_detection():
    assert NB.station_name("Bishan (NS17 / CC15)") == "Bishan"
    assert NB.station_name("NS17 Bishan") == "Bishan" and NB.station_name("Bishan MRT Station") == "Bishan"
    assert NB.station_name("Sengkang - West Loop Clockwise") == "Sengkang"
    assert NB.is_station({"railway": "station", "station": "subway"})
    assert NB.is_station({"railway": "station", "network": "Singapore MRT"})
    assert NB.is_station({"railway": "station", "station": "monorail", "name": "VivoCity"})
    assert not NB.is_station({"railway": "station"})  # a plain rail station (KTM): not ours
    assert NB.address_name({"addr:housenumber": "#01-03", "addr:street": "X"}) is None
    assert NB.address_name({"addr:housenumber": "101A", "addr:street": "Yishun Ring Road"}) == \
        "Block 101A Yishun Ring Road"


def test_bus_stops_routes_and_lta_headways(built):
    b = built
    codes = sorted(int(b.stop_code[i]) for i in range(b.n_stops) if b.stop_kind[i] == B.K_BUS)
    assert codes == [59009, 59011]  # "12" is no LTA code
    pats = [(b.s(int(b.pat_service[p])), int(b.pat_mode[p])) for p in range(len(b.pat_service))]
    assert ("858", B.K_BUS) in pats and ("NSL", B.K_MRT) in pats and ("PGLRT", B.K_LRT) in pats
    assert not any(svc == "Skytrain" for svc, _ in pats)
    sources = json.loads((b.path / "manifest.json").read_text())["sources"]
    assert sources["headways"].startswith("LTA BusServices (1")


def test_stations_from_nodes_and_named_stop_positions(built):
    b = built
    names = sorted(b.s(int(b.stop_name[i])) for i in range(b.n_stops) if b.stop_kind[i] == B.K_MRT)
    assert names == ["Khatib", "Punggol", "Yishun"]  # MRT only; Sam Kee / Teck Lee are LRT  # 'Far Away' is outside Singapore; Punggol from its area
    pung = [i for i in range(b.n_stops) if b.s(int(b.stop_name[i])) == "Punggol"]
    assert len(pung) == 1  # the route-named stop position joined the station, not a stop of its own
    assert b.stop_kind[pung[0]] == B.K_MRT  # tagged light_rail too, but an MRT line calls there
    assert Places(b).search("punggol mrt")[0].name == "Punggol MRT Station"
    hits = Places(b).search("yishun mrt")
    assert hits[0].kind == "mrt_station" and hits[0].name == "Yishun MRT Station"


def test_places_addresses_and_entrances(built):
    b = built
    pl = Places(b)
    assert pl.search("khatib")[0].kind == "mrt_station"  # the station over the polyclinic of the same name
    blk = pl.search("760101")[0]
    assert blk.name == "Block 101 Yishun Avenue 5"
    assert not any("#01" in pl.name(i) for i in range(b.n_places))
    mall = pl.search("northpoint")[0]
    assert mall.kind == "mall"
    w = Walker(b)
    ways_in = b.place_nodes(mall.id)
    assert ways_in, "the mall has walking nodes to reach it by"
    # the mapped entrance faces row 2: its way in is on the row 2 footway, not the road on row 1
    _, y2 = _xy(at(2, 0))
    assert any(abs(float(b.node_y[n]) - y2) < 5 for n in ways_in)  # the entrance side
    assert len(ways_in) >= 2  # the outline too: one mapped entrance must not send people round the building
    p = w.route(w.nearest(*_xy(at(2, 0))), ways_in)
    assert p is not None and p.nodes[-1] in ways_in and abs(float(b.node_y[p.nodes[-1]]) - y2) < 5


def test_multipolygon_mall_is_a_place(built):
    hits = Places(built).search("harbour mall")
    assert hits and hits[0].name == "Harbour Mall" and hits[0].kind == "mall"
    assert len(built.place_nodes(hits[0].id)) >= 1


def test_reader_sees_entrance_nodes(tmp_path):
    pbf = tmp_path / "t.osm.pbf"
    write_osm(pbf)
    assert 2010 in NB.read_osm(pbf).entrances  # entrance=* passes the reader's tag filter


def _xy(lonlat):
    from cortex_core.nav import geo
    return geo.to_xy(lonlat[1], lonlat[0])


def test_road_without_sidewalk_is_flagged_and_signals_kept(built):
    import numpy as np
    flags = np.asarray(built.edge_flags)
    assert np.any(flags & B.F_ROAD)  # Yishun Avenue 2 (primary, no sidewalk)
    assert np.any(flags & B.F_SIGNALS) and np.any(flags & B.F_CROSSING)


def test_service_plans_on_the_built_bundle(built):
    nav = NavService(built, saved={})
    la, lo = at(2, 0)[1], at(2, 0)[0]
    nav.on_fix(la, lo, 5.0, t=0.0)
    r = nav.call("search_places", {"query": "northpoint"})
    assert r.ok and r.data["matches"][0]["name"] == "Northpoint City"
    r = nav.call("plan_trip", {"place_id": r.data["matches"][0]["place_id"]})
    assert r.ok and r.data["to"] == "Northpoint City" and r.data["best"]["minutes"] >= 1
    assert r.data["summary"].startswith("Walk")
