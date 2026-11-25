import json

import numpy as np
import pytest

from cortex_core.nav import bundle as B
from cortex_core.nav.service import NavService

import nav_city as C


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    return B.Bundle(C.make(tmp_path_factory.mktemp("nav")))


def svc(bundle, arrivals=None, saved=None):
    clk = Clock()
    lat, lon = C.latlon(20, 20)
    s = NavService(bundle, saved=saved if saved is not None else {"home": {"name": "Home", "lat": lat, "lon": lon}},
                   arrivals=arrivals, clock=clk, hour=lambda: 9.0)
    return s, clk


def at(s, r, c, acc=5.0):
    return s.on_fix(*C.latlon(r, c), acc_m=acc)


def test_search_with_and_without_position(bundle):
    s, _ = svc(bundle)
    r = s.search_places("northpoint")
    assert r.ok and r.data["matches"][0]["name"] == "Northpoint City"
    assert "distance_m" not in r.data["matches"][0]
    at(s, 0, 0)
    r = s.search_places("northpoint")
    assert r.data["matches"][0]["distance_m"] == pytest.approx(1380, abs=20)
    json.loads(r.json())


def test_search_saved_home_first(bundle):
    s, _ = svc(bundle)
    at(s, 0, 0)
    m = s.search_places("home").data["matches"]
    assert m[0] == {"place_id": "s_home", "name": "Home", "kind": "saved", "distance_m": 1410}


def test_search_nothing(bundle):
    s, _ = svc(bundle)
    r = s.search_places("qwzx")
    assert r.data["matches"] == []


def test_plan_needs_position(bundle):
    s, _ = svc(bundle)
    pid = s.search_places("northpoint").data["matches"][0]["place_id"]
    r = s.plan_trip(pid)
    assert not r.ok and "position" in r.say


def test_stale_fix_is_no_position(bundle):
    s, clk = svc(bundle)
    at(s, 0, 0)
    clk.t += 60
    assert not s.plan_trip("s_home").ok
    assert "lost GPS" in s.gps_accuracy().say


def test_plan_start_follow_arrive_home(bundle):
    s, clk = svc(bundle)
    at(s, 0, 0)
    pid = s.search_places("home").data["matches"][0]["place_id"]
    r = s.plan_trip(pid)
    assert r.ok and r.data["to"] == "Home" and r.data["best"]["rides"] == 1
    assert "MRT Test Line" in r.data["summary"] and r.data["plan_ms"] < 1000
    st = s.start_navigation()
    assert st.say.startswith("Starting.")
    assert s.navigating and s.mode_hint() == "BUS_WATCH"  # the MRT is at the start: wait at the platform
    assert "Test Line" in s.state_line()
    # ride the diagonal
    evs = []
    for k in range(0, 21):
        clk.t += 20
        evs += at(s, k, k)
    for _ in range(3):
        clk.t += 5
        evs += at(s, 20, 20)
    types = [e.type for e in evs]
    assert "boarded" in types and "alight_now" in types and types[-1] == "arrived", [(e.type, e.text) for e in evs]
    assert not s.navigating and s.state_line() == ""


def test_plan_by_name_instead_of_id(bundle):
    s, _ = svc(bundle)
    at(s, 0, 0)
    r = s.plan_trip("Yishun Polyclinic")  # the LM skipped search_places
    assert r.ok and r.data["to"] == "Yishun Polyclinic"


def test_plan_unknown_place(bundle):
    s, _ = svc(bundle)
    at(s, 0, 0)
    assert not s.plan_trip("p_99999").ok


def test_off_route_reroutes(bundle):
    s, clk = svc(bundle)
    at(s, 0, 0)
    pid = s.search_places("polyclinic").data["matches"][0]["place_id"]
    assert s.plan_trip(pid).ok and s.trip.rides == 0
    s.start_navigation()
    evs = []
    # walk north up column 0 instead (the route goes east first or north: go west off the map grid side)
    x0, y0 = C.xy(0, 0)
    from cortex_core.nav import geo
    for d in range(0, 200, 10):
        clk.t += 5
        lat, lon = geo.to_latlon(x0 - 40 - d, y0)
        evs += s.on_fix(float(lat), float(lon), 5.0)
    types = [e.type for e in evs]
    assert "off_route" in types and "rerouted" in types
    assert s.reroutes >= 1


def test_stop_navigation(bundle):
    s, _ = svc(bundle)
    at(s, 0, 0)
    s.plan_trip("s_home")
    s.start_navigation()
    assert s.stop_navigation().say == "Navigation stopped."
    assert s.stop_navigation().say == "I wasn't navigating."
    assert s.nav_status().data == {"navigating": False}
    assert not s.start_navigation().ok


def test_nav_status_walking(bundle):
    s, _ = svc(bundle)
    at(s, 0, 0)
    s.plan_trip(s.search_places("polyclinic").data["matches"][0]["place_id"])
    s.start_navigation()
    at(s, 0, 1)
    r = s.nav_status()
    assert r.data["mode"] == "walk" and "metres to" in r.say


def test_nearby_and_services(bundle):
    s, _ = svc(bundle)
    at(s, 0, 1)
    r = s.nearby_bus_stops()
    assert r.data["stops"][0]["code"] == "59000" and r.data["stops"][0]["services"] == ["100"]
    assert s.services_at_stop("").data["services"] == ["100"]
    assert s.services_at_stop("59120").data["services"] == ["200"]
    assert s.services_at_stop("Col Stop 8").data["stop"] == "Col Stop 8 (59108)"
    assert not s.services_at_stop("99999").ok


def test_arrivals_live(bundle):
    seen = []

    def live(code, service):
        seen.append((code, service))
        return [{"service": "100", "minutes": [0, 7]}]
    s, _ = svc(bundle, arrivals=live)
    at(s, 0, 1)
    r = s.bus_arrivals("100", "")
    assert seen == [(59000, "100")]
    assert r.data["live"] and r.say == "At Row Stop 0: 100 arriving now, then 7."


def test_arrivals_offline_fallback(bundle):
    def broken(code, service):
        raise TimeoutError("gateway")
    s, _ = svc(bundle, arrivals=broken)
    at(s, 0, 1)
    r = s.bus_arrivals("", "")
    assert not r.data["live"] and r.data["headway_min"] == {"100": 8}
    assert r.say.startswith("I can't get live times.") and "every 8 minutes" in r.say


def test_arrivals_wrong_service(bundle):
    s, _ = svc(bundle)
    at(s, 0, 1)
    r = s.bus_arrivals("858", "")
    assert not r.ok and r.say == "Bus 858 doesn't stop at Row Stop 0."


def test_gps_accuracy(bundle):
    s, _ = svc(bundle)
    assert s.gps_accuracy().say == "I don't have a GPS position yet."
    at(s, 0, 0, acc=18)
    r = s.gps_accuracy()
    assert r.data["quality"] == "fair" and r.say == "GPS is fair, about 18 metres."


def test_call_dispatch(bundle):
    s, _ = svc(bundle)
    assert s.call("search_places", {"query": "ktph"}).data["matches"][0]["name"] == "Khoo Teck Puat Hospital"
    assert not s.call("search_places", {}).ok
    assert not s.call("launch_rockets", {}).ok


def test_saved_file(bundle, tmp_path):
    p = tmp_path / "saved_places.json"
    lat, lon = C.latlon(5, 5)
    p.write_text(json.dumps({"work": {"lat": lat, "lon": lon}}))
    s, _ = svc(bundle, saved=str(p))
    assert s.search_places("work").data["matches"][0]["name"] == "Work"
    s2, _ = svc(bundle, saved=str(tmp_path / "missing.json"))
    assert s2.saved == {}
