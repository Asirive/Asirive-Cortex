"""Safety service: unit behaviour. Scenario behaviour (does it warn in time, does it stay quiet) is in
test_safety_sim.py against the simulated walker."""
import ast
import math
import socket
import subprocess
import time
from pathlib import Path

import pytest

from cortex_core.safety import config as C
from cortex_core.safety.engine import Frame, SafetyService, SensorError
from cortex_core.safety.perceive import Perception, Tilt, rotate, tilt_from_accel, zone_dirs
from cortex_core.safety.perceive import Obs, Seen
from cortex_core.safety.warn import Warner

H = 1.6


def flat(eye=H, pitch_deg=-20.0, obstacle=None):
    """Synthetic 64-zone frame: the floor at eye height below, optionally a box {"y", "z0", "z1", "x0", "x1"}
    (forward distance, height range, lateral range) in front, overhanging (open under it)."""
    p = math.radians(pitch_deg)
    out = []
    for d in zone_dirs(60.0):
        x, y, z = rotate(d, p, 0.0)
        best = None
        if z < -1e-6:
            best = eye / -z
        if obstacle and y > 1e-6:
            t = obstacle["y"] / y
            px, pz = t * x, eye + t * z
            if obstacle["x0"] <= px <= obstacle["x1"] and obstacle["z0"] <= pz <= obstacle["z1"]:
                best = t if best is None else min(best, t)
        out.append(None if best is None or best > 3.5 else best * 1000.0)
    return out


def level_accel(pitch_deg=-20.0):
    p = math.radians(pitch_deg)
    return (0.0, math.sin(p), math.cos(p))


class FakeOut:
    def __init__(self):
        self.haptics, self.cues = [], []

    def haptic(self, pattern, side="both"):
        self.haptics.append((pattern, side))

    def cue(self, cue_id):
        self.cues.append(cue_id)


class Seq:
    """Plays frames (or exceptions / None) in order, then repeats the last."""

    def __init__(self, items):
        self.items = list(items)

    def read(self):
        x = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(x, Exception):
            raise x
        return x


def service(items, out=None, cfg=None, dt=1 / 15):
    out = out or FakeOut()
    t = [0.0]
    beats = []

    def clock():
        return t[0]

    s = SafetyService(Seq(items), out, lambda: beats.append(1), cfg, clock=clock)
    s.beats = beats

    def step():
        t[0] += dt
        return s.step()

    s.tick = step
    return s, out


def walk(eye=H, pitch=-20.0, v=1.2, start=4.0, obstacle=None, n=40, t0=0.0):
    """Frames of a walker approaching an overhanging box whose front starts `start` m ahead."""
    frames = []
    for k in range(n):
        o = None
        if obstacle:
            o = dict(obstacle, y=start - v * k / 15)
            if o["y"] <= 0.05:
                break
        frames.append(Frame(t0 + (k + 1) / 15, flat(eye, pitch, o), level_accel(pitch), (0.0, 0.0, 0.0)))
    return frames


BRANCH = {"z0": 1.5, "z1": 1.9, "x0": -0.4, "x1": 0.4}


# ------------------------------------------------------------------ geometry
def test_zone_rays_are_unit_and_ordered_top_left_first():
    d = zone_dirs(60.0)
    assert len(d) == 64 and all(abs(math.hypot(*v) - 1) < 1e-9 for v in d)
    assert d[0][0] < 0 and d[0][2] > 0      # row 0 col 0: up-left
    assert d[63][0] > 0 and d[63][2] < 0    # row 7 col 7: down-right


def test_tilt_from_accel_inverts_rotate():
    for p, r in ((0.0, 0.0), (-0.4, 0.1), (0.3, -0.2)):
        # gravity "up" seen in the head frame = rotate^-1 (0,0,1); check by rotating it back
        a = (-math.sin(r) * math.cos(p), math.sin(p), math.cos(r) * math.cos(p))
        pp, rr = tilt_from_accel(a)
        assert abs(pp - p) < 1e-9 and abs(rr - r) < 1e-9
        up = rotate(a, pp, rr)
        assert abs(up[2] - 1) < 1e-9


def test_tilt_filter_follows_gyro_and_ignores_hard_acceleration():
    t = Tilt()
    t.update(level_accel(0), (0, 0, 0))
    p, _ = t.update((0.0, 0.0, 3.0), (math.radians(5), 0, 0))  # 3 g: accel ignored, gyro used
    assert abs(math.degrees(p) - 5) < 1e-6


def test_ground_height_is_learned_when_looking_down():
    per = Perception(C.load({"version": 1, "sensor_height_m": 1.6}))
    for _ in range(40):
        per.process(flat(eye=1.45, pitch_deg=-35), math.radians(-35), 0.0)
    assert abs(per.h - 1.45) < 0.03 and per.h_n >= 10


def test_open_floor_is_empty_and_ceiling_is_ignored():
    per = Perception(C.load(None))
    obs = per.process(flat(), math.radians(-20), 0.0)
    assert obs.sectors == {} and not obs.blocked
    # ceiling at 2.3 m (eye 1.6 + band margin 0.25 = 1.85): not in the band
    obs = per.process(flat(pitch_deg=10, obstacle={"y": 1.5, "z0": 2.3, "z1": 2.6, "x0": -2, "x1": 2}),
                      math.radians(10), 0.0)
    assert obs.sectors == {}


def test_overhang_is_seen_open_underneath_and_sides_are_right():
    per = Perception(C.load(None))
    obs = per.process(flat(obstacle=dict(BRANCH, y=1.5)), math.radians(-20), 0.0)
    assert set(obs.sectors) == {"left", "centre", "right"}
    assert all(s.grounded is False for s in obs.sectors.values())
    obs = per.process(flat(obstacle={"y": 1.5, "z0": 1.5, "z1": 1.9, "x0": 0.2, "x1": 0.6}), math.radians(-20), 0.0)
    assert set(obs.sectors) == {"right"}


def test_wall_is_grounded():
    per = Perception(C.load(None))
    obs = per.process(flat(obstacle={"y": 1.5, "z0": 0.0, "z1": 3.0, "x0": -3, "x1": 3}), math.radians(-20), 0.0)
    assert obs.sectors and all(s.grounded is True for s in obs.sectors.values())


def test_covered_lens_is_blocked():
    per = Perception(C.load(None))
    assert per.process([20.0] * 64, 0.0, 0.0).blocked


# ------------------------------------------------------------------ warning policy
def seen(d, g=False):
    return Obs(sectors={"centre": Seen(d, -0.1, 0.1, g)})


def test_approach_warns_ahead_then_close_and_nothing_more():
    w = Warner(C.load(None))
    fired = []
    for k in range(60):
        t, d = k / 15, 3.5 - 1.2 * k / 15
        if d <= 0.05:
            break
        for f in w.update(t, seen(d)):
            fired.append((round(t, 2), round(d, 2)) + f)
    assert [f[2] for f in fired] == ["ahead", "close"]
    assert fired[0][3] == "both"
    ttc = fired[0][1] / 1.2
    assert 1.0 <= ttc <= 1.65  # about ttc_warn_s before contact


def test_grounded_obstacle_is_never_warned():
    w = Warner(C.load(None))
    assert not any(w.update(k / 15, seen(3.0 - 1.2 * k / 15, True)) for k in range(30))


def test_standing_still_near_something_warns_once():
    w = Warner(C.load(None))
    n = sum(len(w.update(k / 15, seen(0.7))) for k in range(15 * 20))
    assert n == 1  # "ahead" (nearer than near_m), never repeated


def test_fast_head_swing_does_not_start_a_warning():
    w = Warner(C.load(None))
    assert not any(w.update(k / 15, seen(1.2 - 0.1 * k / 15), yaw_dps=250) for k in range(10))


def test_hand_over_between_sectors_does_not_rewarn():
    w = Warner(C.load(None))
    out = []
    for k in range(20):
        side = "left" if k < 10 else "centre"
        out += w.update(k / 15, Obs(sectors={side: Seen(2.0 - 1.2 * k / 15, -0.2, -0.2, False)}))
    assert [p for p, _ in out].count("ahead") == 1


# ------------------------------------------------------------------ service
def test_overhang_approach_vibrates_with_heartbeat():
    s, out = service(walk(obstacle=BRANCH))
    fired = [f for _ in range(40) for f in s.tick()]
    assert ("ahead", "both") in fired and out.haptics[0] == ("ahead", "both")
    assert len(s.beats) == 40 and not out.cues


def test_open_path_is_quiet():
    s, out = service(walk())
    for _ in range(40):
        s.tick()
    assert out.haptics == [] and out.cues == []


def test_nan_negative_and_short_frames_do_not_crash():
    bad = [float("nan"), -5.0] + [None] * 62
    s, out = service([Frame(0.1, bad), Frame(0.2, [None] * 10)])
    s.tick()
    s.tick()
    assert out.haptics == []


def test_sensor_failure_is_never_silent_and_repeats():
    s, out = service([SensorError("usb")])
    for _ in range(3):
        s.tick()
    assert s.degraded and s.reason == "sensor error"
    assert out.haptics == [("degraded", "both")] and out.cues == ["safety_degraded"]
    for _ in range(5):
        s.tick()
    assert len(out.cues) == 1  # rate limited...
    for _ in range(75):
        s.tick()
    assert len(out.cues) == 2  # ...but repeats every 5 s until the sensor is back


def test_no_frames_is_degraded():
    s, out = service([None])
    for _ in range(6):
        s.tick()
    assert s.degraded and s.reason == "no frames" and out.cues == ["safety_degraded"]


def test_covered_lens_is_degraded_after_blocked_s():
    s, out = service([Frame(k / 15, [10.0] * 64) for k in range(1, 60)])
    for _ in range(20):
        s.tick()
    assert not s.degraded  # a hand brushing past is not a fault
    for _ in range(20):
        s.tick()
    assert s.degraded and s.reason == "sensor covered" and out.cues == ["safety_degraded"]


def test_recovery_clears_degraded():
    s, out = service([SensorError("x")] * 3 + walk())
    for _ in range(6):
        s.tick()
    assert not s.degraded


@pytest.mark.parametrize("bad", [
    None, {}, "junk", [], {"version": 2}, {"version": 1, "nope": 1}, {"version": 1, "ttc_warn_s": True},
    {"version": 1, "ttc_warn_s": "2"}, {"version": 1, "ttc_warn_s": 99}, {"version": 1, "ttc_warn_s": float("nan")},
    {"version": 1, "close_m": 0.9, "near_m": 0.8},           # inconsistent: close beyond near
    {"version": 1, "ttc_close_s": 1.5, "ttc_warn_s": 1.0},
])
def test_bad_config_is_the_safe_defaults_never_off(bad):
    assert C.load(bad) == C.DEFAULTS


def test_good_config_overrides():
    c = C.load({"version": 1, "ttc_warn_s": 2.0, "sensor_height_m": 1.5})
    assert c["ttc_warn_s"] == 2.0 and c["sensor_height_m"] == 1.5 and c["close_m"] == C.DEFAULTS["close_m"]


def test_warns_with_network_model_and_phone_dead(monkeypatch):
    """Poison every way out of the process; safety must neither touch them nor care."""
    def boom(*a, **k):
        raise ConnectionError("network/phone/model unavailable")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    s, out = service(walk(obstacle=BRANCH))
    for _ in range(40):
        s.tick()
    assert ("ahead", "both") in out.haptics


def test_output_fault_does_not_kill_the_loop():
    class Flaky(FakeOut):
        n = 0

        def haptic(self, pattern, side="both"):
            Flaky.n += 1
            if Flaky.n == 1:
                raise OSError("motor driver busy")
            super().haptic(pattern, side)

    out = Flaky()
    t = [0.0]
    s = SafetyService(Seq([SensorError("x")]), out, lambda: None, clock=lambda: t.__setitem__(0, t[0] + 6) or t[0])
    stops = iter([False] * 6 + [True])
    s.run(lambda: next(stops), sleep=lambda _: None)
    assert out.haptics  # a later step got through


def test_processing_fits_the_frame_budget():
    """64 zones in pure Python: must be far under the 66 ms frame period (measured here; the box is slower, about
    5x, still far under). The sim reports the distribution."""
    per = Perception(C.load(None))
    w = Warner(C.load(None))
    frames = [flat(obstacle=dict(BRANCH, y=y)) for y in (3.0, 2.0, 1.5, 1.0)]
    n = 400
    t0 = time.perf_counter()
    for k in range(n):
        obs = per.process(frames[k % 4], math.radians(-20), 0.0)
        w.update(k / 15, obs)
    per_frame_ms = 1000 * (time.perf_counter() - t0) / n
    assert per_frame_ms < 5.0, per_frame_ms


def test_safety_package_imports_nothing_but_stdlib_and_itself():
    """Static guard for AGENTS.md rule 1: no agent/voice/perception/link/ota/network/phone imports."""
    forbidden = {"socket", "ssl", "http", "urllib", "requests", "asyncio", "subprocess", "multiprocessing",
                 "cortex_core.link", "cortex_core.ota", "cortex_core.supervisor", "cortex_core.contracts",
                 "agent", "voice", "perception", "grpc", "google", "numpy"}
    for f in (Path(__file__).resolve().parents[1] / "cortex_core" / "safety").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for m in mods:
                assert not any(m == x or m.startswith(x + ".") for x in forbidden), f"{f.name} imports {m}"
