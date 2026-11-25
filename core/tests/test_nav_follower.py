import numpy as np
import pytest

from cortex_core.nav import bundle as B
from cortex_core.nav.follower import Fix, Follower
from cortex_core.nav.transit import Planner

import nav_city as C


@pytest.fixture(scope="module")
def city(tmp_path_factory):
    return B.Bundle(C.make(tmp_path_factory.mktemp("nav")))


def trace(xs, ys, step=5.0):
    """Points every `step` metres along a polyline."""
    out = []
    for i in range(len(xs) - 1):
        L = float(np.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]))
        n = max(1, int(L // step))
        for k in range(n):
            t = k / n
            out.append((xs[i] + t * (xs[i + 1] - xs[i]), ys[i] + t * (ys[i + 1] - ys[i])))
    out.append((xs[-1], ys[-1]))
    return out


def run(f, pts, acc=5.0, t0=0.0, dt=4.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    evs = []
    t = t0
    for x, y in pts:
        nx, ny = rng.normal(0, noise, 2) if noise else (0.0, 0.0)
        evs += f.update(Fix(x + nx, y + ny, acc, t))
        t += dt
    return evs, t


def walk_plan(city, a, z):
    its = Planner(city).plan(a, z, hour=9)
    assert its[0].rides == 0
    return its[0]


def test_walk_to_arrival_with_turn(city):
    it = walk_plan(city, C.node(0, 0), C.node(6, 6))
    f = Follower(city, it)
    p = it.legs[0].path
    evs, _ = run(f, trace(p.xs, p.ys), noise=3.0)
    types = [e.type for e in evs]
    assert "prewarn" in types and "step" in types
    assert types[-1] == "arrived" and f.done
    assert "off_route" not in types
    # each step said once, its prewarn before it
    steps = [e.text for e in evs if e.type == "step"]
    assert len(steps) == len(set(steps))
    assert types.index("prewarn") < types.index("step")


def test_one_wild_fix_is_not_off_route(city):
    it = walk_plan(city, C.node(0, 0), C.node(0, 10))
    f = Follower(city, it)
    p = it.legs[0].path
    pts = trace(p.xs, p.ys)
    pts.insert(20, (pts[20][0], pts[20][1] + 120))  # one fix 120 m off
    evs, _ = run(f, pts)
    assert "off_route" not in [e.type for e in evs]
    assert f.done


def test_real_detour_is_off_route_then_back(city):
    it = walk_plan(city, C.node(0, 0), C.node(0, 10))
    f = Follower(city, it)
    p = it.legs[0].path
    pts = trace(p.xs, p.ys)
    x, y = pts[30]
    detour = [(x, y + d) for d in range(10, 90, 10)] + [(x, y + d) for d in range(80, -1, -10)]
    evs, _ = run(f, pts[:30] + detour + pts[30:])
    types = [e.type for e in evs]
    assert types.count("off_route") == 1 and types.count("on_route") == 1
    assert types.index("off_route") < types.index("on_route")
    assert types[-1] == "arrived"


def test_bad_accuracy_is_ignored(city):
    it = walk_plan(city, C.node(0, 0), C.node(0, 10))
    f = Follower(city, it)
    evs = f.update(Fix(0.0, 0.0, acc_m=80.0))
    assert [e.type for e in evs] == ["gps_weak"]
    assert f.update(Fix(0.0, 0.0, acc_m=90.0)) == []  # said once
    assert not f.off


def test_jitter_never_walks_you_back(city):
    it = walk_plan(city, C.node(0, 0), C.node(0, 10))
    f = Follower(city, it)
    p = it.legs[0].path
    pts = trace(p.xs, p.ys)
    run(f, pts[:40])
    a = f.along
    f.update(Fix(pts[36][0], pts[36][1]))  # a fix 20 m behind
    assert f.along == a


def test_bus_ride(city):
    # (0,1) -> (0,19): walk to Row Stop 0, bus 100 east, walk to the end
    its = Planner(city).plan(C.node(0, 1), C.node(1, 19), hour=9)
    it = next(i for i in its if any(l.mode == "bus" for l in i.legs))
    f = Follower(city, it)
    evs, t = [], 0.0
    for leg in it.legs:
        if leg.mode == "walk":
            if leg.path is not None and len(leg.path.nodes) > 1:
                e, t = run(f, trace(leg.path.xs, leg.path.ys), t0=t)
                evs += e
        else:
            sx = np.asarray(city.stop_x)[leg.stops].astype(float)
            sy = np.asarray(city.stop_y)[leg.stops].astype(float)
            e, t = run(f, [(sx[0], sy[0])] * 3, t0=t, dt=30)  # waiting at the stop
            evs += e
            e, t = run(f, trace(sx, sy, step=40), t0=t, dt=5)  # 8 m/s
            evs += e
            e, t = run(f, [(sx[-1], sy[-1])] * 3, t0=t, dt=5)  # stopped, getting off
            evs += e
    types = [e.type for e in evs]
    for need in ("at_stop", "boarded", "alight_next", "alight_now", "arrived"):
        assert need in types, (need, [(e.type, e.text) for e in evs])
    assert types.index("at_stop") < types.index("boarded") < types.index("alight_now") < types.index("arrived")
    assert types.count("at_stop") == 1
    assert "Press the bell" in next(e.text for e in evs if e.type == "alight_next")
    assert f.done


def test_state_line(city):
    it = walk_plan(city, C.node(0, 0), C.node(6, 6))
    f = Follower(city, it)
    f.update(Fix(*C.xy(0, 1)))
    s = f.state_line()
    assert s.startswith("nav: walking") and "next:" in s
    st = f.status()
    assert st["mode"] == "walk" and st["remaining_m"] == pytest.approx(550, abs=10)


def _ride_first(city):
    its = Planner(city).plan(C.node(0, 0), C.node(0, 20), hour=9)
    it = next(i for i in its if i.legs[0].mode != "walk")
    return it, np.asarray(city.stop_x)[it.legs[0].stops].astype(float), \
        np.asarray(city.stop_y)[it.legs[0].stops].astype(float)


def test_walking_away_from_the_stop_is_off_route(city):
    it, sx, sy = _ride_first(city)
    f = Follower(city, it)
    evs = []
    for k in range(1, 15):  # 1.3 m/s, south, away from the line
        evs += f.update(Fix(sx[0], sy[0] - 10 * k, 5.0, 8.0 * k, 1.3))
    types = [e.type for e in evs]
    assert types.count("off_route") == 1 and "boarded" not in types
    assert f.status()["off_route"]


def test_a_crawling_bus_is_boarding_not_off_route(city):
    it, sx, sy = _ride_first(city)
    f = Follower(city, it)
    evs = f.update(Fix(sx[0], sy[0], 5.0, 0.0, 0.0))
    evs += f.update(Fix(sx[0] + 50, sy[0], 5.0, 10.0, 5.0))  # pulled away at 5 m/s
    for k in range(1, 6):  # then a jam: 1 m/s along the line
        evs += f.update(Fix(sx[0] + 50 + 10 * k, sy[0], 5.0, 10.0 + 10 * k, 1.0))
    types = [e.type for e in evs]
    assert "boarded" in types and "off_route" not in types
