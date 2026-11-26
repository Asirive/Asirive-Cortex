"""Safety simulator: a walker wearing the glasses (VL53L7CX on the bridge + IMU) through scenes of boxes.

Independent of cortex_core.safety's geometry on purpose (own rotations, own ray casting), so a convention
mistake in the safety code shows up as failed scenarios rather than agreeing with itself.

Sensor model (per frame, 15 Hz, 8x8 zones, square FoV):
- each zone casts K x K sub-rays; the zone reports the NEAREST surface that covers >= MIN_COVER of the zone
  (a thin pole or a pipe edge can be missed, as on the real part), else the next one, else no target
- range limit per surface = scene max range (3.5 m indoors, about 2 m in sun) x reflectance
- noise 8 mm + 1.5 % of distance, 3 % invalid zones, glass is transparent
Walker: speed, eye height, head pitch, step bob/sway/roll at cadence, slow yaw sway, look-around events.
IMU frame: mean specific force (g) + summed rotation (rad) with gyro bias and noise, as the ESP32 would send.
Timing: the frame shows the world at mid-integration (t - 33 ms); a warning reaches the skin at
t + 5 ms (USB) + 40 ms (motor spin-up).

python -m tests.safety_sim [--seeds 30] [--md PATH]  -> table of results per scenario.
"""
import argparse
import math
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from cortex_core.safety import config as SC
from cortex_core.safety.engine import Frame, SafetyService

HZ = 15.0
K = 4
MIN_COVER = 0.25
USB_S, MOTOR_S = 0.005, 0.040
FOV = SC.DEFAULTS["fov_deg"]


@dataclass
class Box:
    lo: tuple
    hi: tuple
    refl: float = 1.0
    glass: bool = False
    target: bool = False      # the thing that must be warned about
    t_on: float = 0.0         # appears at this time


@dataclass
class Walker:
    h: float = 1.6            # eye height
    v: float = 1.2
    p0: float = -8.0          # mean head pitch, degrees (negative = looking down)
    start_y: float = 0.0
    stop_y: Optional[float] = None
    f: float = 1.8            # step frequency
    yaw_sway: float = 4.0     # degrees
    looks: list = field(default_factory=list)   # (t0, dur, deg) look-around events
    scan: float = 0.0         # standing head scan amplitude, degrees (slow left-right)
    seed_phase: float = 0.0

    def y(self, t):
        y = self.start_y + self.v * t
        return min(y, self.stop_y) if self.stop_y is not None else y

    def moving(self, t):
        return self.v > 0 and (self.stop_y is None or self.start_y + self.v * t < self.stop_y)

    def pose(self, t):
        """(x, y, z, pitch, roll, yaw) at t; angles in radians, yaw > 0 = looking left."""
        a = 1.0 if self.moving(t) else 0.0
        ph = 2 * math.pi * self.f * t + self.seed_phase
        look = 0.0
        for t0, dur, deg in self.looks:
            if t0 <= t <= t0 + dur:
                r = min(1.0, (t - t0) / 0.25, (t0 + dur - t) / 0.25)
                look += deg * r
        yaw = math.radians(self.yaw_sway * math.sin(2 * math.pi * 0.25 * t + self.seed_phase) + look
                           + self.scan * math.sin(2 * math.pi * 0.2 * t))
        return (a * 0.03 * math.sin(ph / 2), self.y(t), self.h + a * 0.02 * math.sin(ph),
                math.radians(self.p0 + a * 2 * math.sin(ph + 0.5)), math.radians(a * 2 * math.sin(ph / 2)), yaw)

    def lin_acc(self, t):
        """World linear acceleration (m/s^2) of the head."""
        if not self.moving(t):
            return np.zeros(3)
        w = 2 * math.pi * self.f
        ph = w * t + self.seed_phase
        return np.array([-0.03 * (w / 2) ** 2 * math.sin(ph / 2), 0.49 * math.sin(ph), -0.02 * w * w * math.sin(ph)])


def rot(pitch, roll, yaw):
    cp, sp, cr, sr, cy, sy = map(float, (np.cos(pitch), np.sin(pitch), np.cos(roll), np.sin(roll), np.cos(yaw), np.sin(yaw)))
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    ry = np.array([[cr, 0, sr], [0, 1, 0], [-sr, 0, cr]])
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return rz @ rx @ ry


def sub_rays(fov=FOV, n=8, k=K):
    """(64, k*k, 3) unit rays in the sensor frame; zone row 0 top, column 0 left."""
    t = math.tan(math.radians(fov) / 2)
    out = np.zeros((n * n, k * k, 3))
    for r in range(n):
        for c in range(n):
            j = 0
            for a in range(k):
                for b in range(k):
                    u = t * (2 * (c + (b + 0.5) / k) / n - 1)
                    v = t * (1 - 2 * (r + (a + 0.5) / k) / n)
                    out[r * n + c, j] = (u, 1, v)
                    j += 1
    return out / np.linalg.norm(out, axis=2, keepdims=True)


RAYS = sub_rays()


def cast(o, D, boxes, max_range, ground_refl=0.8):
    """Nearest hit distance per ray (inf = nothing in range)."""
    best = np.full(D.shape[0], np.inf)
    with np.errstate(divide="ignore", invalid="ignore"):
        tg = np.where(D[:, 2] < -1e-9, -o[2] / D[:, 2], np.inf)
    tg = np.where(tg <= max_range * ground_refl, tg, np.inf)
    best = np.minimum(best, tg)
    for b in boxes:
        if b.glass:
            continue
        lo, hi = np.array(b.lo), np.array(b.hi)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = 1.0 / D
            t1, t2 = (lo - o) * inv, (hi - o) * inv
        t1 = np.nan_to_num(t1, nan=-np.inf)
        t2 = np.nan_to_num(t2, nan=np.inf)
        tmin = np.max(np.minimum(t1, t2), axis=1)
        tmax = np.min(np.maximum(t1, t2), axis=1)
        hit = (tmax >= tmin) & (tmin > 0) & (tmin <= max_range * b.refl)
        best = np.where(hit & (tmin < best), tmin, best)
    return best


def zone_reading(ts, rng):
    """One zone's K*K sub-ray distances -> the sensor's reported distance in mm, or None."""
    ts = np.sort(ts[np.isfinite(ts)])
    need = MIN_COVER * K * K
    # one surface = sub-ray distances chained by gaps under 10 cm (a sloped floor is one surface: its histogram
    # peak sits near the middle of the strip it covers, not at its near end)
    i = 0
    while i < len(ts):
        j = i + 1
        while j < len(ts) and ts[j] - ts[j - 1] < 0.10:
            j += 1
        grp = ts[i:j]
        if len(grp) >= need:
            d = float(grp.mean()) + rng.normal(0, 0.008 + 0.015 * float(grp.mean()))
            return max(1.0, d * 1000.0)
        i = j
    return None


@dataclass
class Scenario:
    name: str
    kind: str                 # "warn" | "quiet" | "stand" | "appear"
    boxes: list
    walker: Walker
    dur: float
    max_range: float = 3.5
    min_lead: float = 0.7
    max_react: float = 0.4


def run(sc: Scenario, seed: int = 0, cfg: Optional[dict] = None, gyro_bias_dps: Optional[float] = None,
        fitted: bool = True) -> dict:
    """fitted: the wearer's eye height was entered at setup (to +-5 cm), as the app does; else the 1.6 m default."""
    rng = np.random.default_rng(seed)
    if cfg is None and fitted:
        cfg = {"version": SC.VERSION, "sensor_height_m": round(sc.walker.h + float(rng.uniform(-0.05, 0.05)), 2)}
    bias = np.radians(rng.uniform(-0.5, 0.5, 3) if gyro_bias_dps is None else np.full(3, gyro_bias_dps))
    w = sc.walker
    dt = 1 / HZ
    frames = []
    prev = w.pose(0.0)
    n = int(sc.dur * HZ)
    for k in range(1, n + 1):
        t = k * dt
        x, y, z, p, r, yw = w.pose(t - dt / 2)
        R = rot(p, r, yw)
        o = np.array([x, y, z])
        D = (RAYS.reshape(-1, 3) @ R.T)
        boxes = [b for b in sc.boxes if b.t_on <= t - dt / 2]
        hits = cast(o, D, boxes, sc.max_range).reshape(64, K * K)
        dist = [None if rng.random() < 0.03 else zone_reading(hits[i], rng) for i in range(64)]
        cur = w.pose(t)
        dth = np.array([cur[3] - prev[3], cur[4] - prev[4], cur[5] - prev[5]]) + bias * dt + rng.normal(0, 0.002, 3)
        prev = cur
        f_world = np.array([0.0, 0.0, 1.0]) + w.lin_acc(t - dt / 2) / 9.81
        acc = R.T @ f_world + rng.normal(0, 0.02, 3)
        frames.append(Frame(t, dist, tuple(acc), tuple(dth)))

    class Src:
        i = 0

        def read(self):
            f = frames[self.i]
            self.i += 1
            return f

    clock = [0.0]
    warns = []

    class Out:
        def haptic(self, pattern, side="both"):
            warns.append((clock[0] + USB_S + MOTOR_S, pattern, side))

        def cue(self, cue_id):
            warns.append((clock[0], "cue:" + cue_id, ""))

    svc = SafetyService(Src(), Out(), lambda: None, cfg, clock=lambda: clock[0])
    proc = []
    for f in frames:
        clock[0] = f.t
        t0 = time.perf_counter()
        svc.step()
        proc.append(time.perf_counter() - t0)
    return {"warns": warns, "contact": contact(sc), "proc_ms": [1000 * p for p in proc]}


def contact(sc: Scenario) -> Optional[float]:
    """First time the walker's face/body reaches a target box (the walker never reacts: worst case)."""
    w = sc.walker
    for i in range(int(sc.dur * 100)):
        t = i / 100
        x, y, z, *_ = w.pose(t)
        for b in sc.boxes:
            if not b.target or b.t_on > t:
                continue
            if b.lo[1] - y <= 0.15 and b.hi[1] >= y - 0.15 and b.lo[0] <= x + 0.25 and b.hi[0] >= x - 0.25 \
                    and b.lo[2] <= w.h + 0.12 and b.hi[2] >= 0.8:
                return t
    return None


def sides_ok(sc: Scenario, side: str) -> bool:
    ch, cw = SC.DEFAULTS["centre_half_m"], SC.DEFAULTS["corridor_half_m"]
    for b in sc.boxes:
        if not b.target:
            continue
        lo, hi = max(b.lo[0], -cw), min(b.hi[0], cw)
        ok = set()
        if lo < -ch:
            ok.add("left")
        if hi > ch:
            ok.add("right")
        if hi >= -ch and lo <= ch:
            ok |= {"left", "right", "both"}
        if len(ok - {"both"}) == 2:
            ok.add("both")
        if side in ok:
            return True
    return False


def min_lead(sc: Scenario) -> float:
    """sc.min_lead, unless physics forbids it: a target is first detectable at max_range x reflectance, and three
    confirming frames (0.2 s) + mid-frame timing + USB + motor (0.08 s) + 0.07 s slack come off that."""
    refl = min(b.refl for b in sc.boxes if b.target)
    if sc.walker.v <= 0:
        return sc.min_lead
    return min(sc.min_lead, sc.max_range * refl / sc.walker.v - 0.35)


def judge(sc: Scenario, res: dict) -> dict:
    ws = [x for x in res["warns"] if not x[1].startswith("cue:") and x[1] != "degraded"]
    c = res["contact"]
    out = {"n": len(ws), "lead": None, "ok": False, "why": ""}
    if sc.kind == "quiet":
        out["ok"] = not ws
        out["why"] = "" if out["ok"] else f"false alarm at {ws[0][0]:.2f}s"
        return out
    if sc.kind == "stand":
        out["ok"] = len(ws) <= 2
        out["why"] = "" if out["ok"] else f"{len(ws)} warnings while standing"
        return out
    if c is None:
        out["why"] = "scene error: the walker never reaches the target"
        return out
    before = [x for x in ws if x[0] <= c]
    if not before:
        out["why"] = "no warning before contact"
        return out
    first = before[0]
    out["lead"] = c - first[0]
    out["n"] = len(before)
    if len(before) > 2:
        out["why"] = f"{len(before)} warnings for one obstacle"
    elif not sides_ok(sc, first[2]):
        out["why"] = f"wrong side {first[2]}"
    elif sc.kind == "appear":
        t_on = min(b.t_on for b in sc.boxes if b.target)
        out["ok"] = first[0] - t_on <= sc.max_react
        out["why"] = "" if out["ok"] else f"reacted after {first[0] - t_on:.2f}s"
    else:
        need = min_lead(sc)
        out["ok"] = out["lead"] >= need
        out["why"] = "" if out["ok"] else f"lead {out['lead']:.2f}s < {need:.2f}s"
    return out


# ------------------------------------------------------------------ scenes
def _walker(rng, **kw):
    w = Walker(h=float(rng.uniform(1.45, 1.75)), v=float(rng.uniform(0.8, 1.5)), p0=float(rng.uniform(-15, 0)),
               seed_phase=float(rng.uniform(0, 6.28)))
    for k, v in kw.items():
        setattr(w, k, v)
    return w


def _walk_dur(w, y_front):
    return (y_front + 0.3 - w.start_y) / w.v


def scenarios(seed: int) -> list[Scenario]:
    rng = np.random.default_rng(10_000 + seed)
    S = []

    def warn(name, boxes_fn, y=5.0, max_range=3.5, min_lead=0.7, **kw):
        w = _walker(rng, **kw)
        S.append(Scenario(name, "warn", boxes_fn(w), w, _walk_dur(w, y), max_range, min_lead))

    # ---- must warn: head-level / overhanging, nothing under them for the cane
    warn("branch ahead", lambda w: [Box((-0.5, 5.0, 1.45), (0.5, 5.3, 2.0), refl=0.6, target=True)])
    warn("signboard right", lambda w: [Box((0.05, 5.0, w.h - 0.1), (0.9, 5.05, 2.3), target=True)])
    warn("tailgate at waist", lambda w: [Box((-0.7, 5.0, 0.95), (0.7, 5.9, 1.05), target=True),
                                         Box((-0.8, 5.9, 0.35), (0.8, 6.2, 0.95)),
                                         Box((-1.0, 6.2, 0.9), (1.0, 9.0, 2.8))])
    warn("shelf on the left", lambda w: [Box((-0.7, 5.0, 1.25), (-0.1, 5.35, 1.6), target=True),
                                         Box((-0.85, 0.0, 0.0), (-0.75, 10.0, 2.5))])
    warn("low door header", lambda w: [Box((-0.45, 5.0, w.h + 0.08), (0.45, 5.15, w.h + 0.6), target=True),
                                       Box((-0.6, 5.0, 0.0), (-0.45, 5.15, w.h + 0.6)),
                                       Box((0.45, 5.0, 0.0), (0.6, 5.15, w.h + 0.6))])
    warn("pipe at head height", lambda w: [Box((-1.5, 5.0, w.h - 0.05), (1.5, 5.12, w.h + 0.07), target=True)])
    warn("truck mirror", lambda w: [Box((0.15, 5.0, 1.35), (0.4, 5.15, 1.55), target=True)])
    warn("branch, looking down", lambda w: [Box((-0.5, 5.0, 1.45), (0.5, 5.3, 2.0), refl=0.6, target=True)],
         p0=-25.0)
    warn("branch, fast walker", lambda w: [Box((-0.5, 5.0, 1.45), (0.5, 5.3, 2.0), refl=0.6, target=True)],
         v=1.7)
    warn("branch, slow walker", lambda w: [Box((-0.5, 5.0, 1.45), (0.5, 5.3, 2.0), refl=0.6, target=True)],
         v=0.5)
    warn("branch in sunlight", lambda w: [Box((-0.5, 5.0, 1.45), (0.5, 5.3, 2.0), refl=0.6, target=True)],
         max_range=2.0)
    warn("dark sign", lambda w: [Box((-0.3, 5.0, 1.5), (0.6, 5.05, 2.2), refl=0.4, target=True)])
    warn("branch over a trunk 1 m behind", lambda w: [Box((-0.5, 5.0, 1.45), (0.5, 6.3, 2.0), refl=0.6, target=True),
                                                     Box((-0.15, 6.0, 0.0), (0.15, 6.3, 1.45))])
    # appears close: a cabinet door swung open 0.5-0.7 m ahead
    w = _walker(rng, v=0.8)
    S.append(Scenario("door swings open", "appear",
                      [Box((-0.3, 1.5, 1.3), (0.4, 1.53, 1.8), target=True, t_on=1.0)], w, 2.0, max_react=0.4))

    # ---- must stay quiet
    def quiet(name, boxes, dur=None, **kw):
        w = _walker(rng, **kw)
        S.append(Scenario(name, "quiet", boxes, w, dur or 8.0))

    quiet("open path, looking around", [], dur=15.0,
          looks=[(3.0, 1.0, 35.0), (8.0, 1.2, -40.0), (11.0, 0.8, 30.0)])
    quiet("wall ahead, stop 0.8 m", [Box((-3, 6.0, 0), (3, 6.2, 3))], stop_y=5.2, scan=0.0)
    quiet("pole ahead", [Box((-0.05, 5.0, 0), (0.05, 5.1, 2.5))], dur=4.4)
    quiet("person standing ahead", [Box((-0.25, 5.0, 0), (0.25, 5.3, 1.7))], dur=4.4)
    quiet("ceiling 2.3 m", [Box((-3, 0, 2.3), (3, 20, 2.5))], h=1.6)
    quiet("stairs up", [Box((-1, 5.0 + 0.28 * i, 0), (1, 12, 0.16 * (i + 1))) for i in range(12)], stop_y=4.7)
    quiet("looking at the phone", [], p0=-45.0)
    quiet("branch beside the path", [Box((0.7, 5.0, 1.4), (1.6, 5.3, 2.0))], yaw_sway=2.0)
    quiet("parked car beside", [Box((0.6, 3.0, 0.3), (2.4, 8.0, 1.5))], yaw_sway=2.0)
    quiet("canopy 2.4 m", [Box((-2, 3.0, 2.4), (2, 9.0, 2.6))])
    quiet("glass wall (sensor can't see glass)", [Box((-3, 6.0, 0), (3, 6.05, 3), glass=True)], stop_y=5.5)

    # ---- standing next to an overhang, scanning the head: at most two warnings
    w = _walker(rng, v=0.0, start_y=4.4, scan=30.0)
    S.append(Scenario("standing 0.6 m from a branch, scanning", "stand",
                      [Box((-0.5, 5.0, 1.45), (0.5, 5.3, 2.0), refl=0.6, target=True)], w, 20.0))
    return S


def sweep(seeds: int, cfg: Optional[dict] = None, fitted: bool = True) -> dict:
    rows: dict[str, dict] = {}
    proc: list[float] = []
    for s in range(seeds):
        for sc in scenarios(s):
            res = run(sc, s, cfg, fitted=fitted)
            j = judge(sc, res)
            r = rows.setdefault(sc.name, {"kind": sc.kind, "ok": 0, "n": 0, "leads": [], "fails": []})
            r["n"] += 1
            r["ok"] += j["ok"]
            if j["lead"] is not None:
                r["leads"].append(j["lead"])
            if not j["ok"]:
                r["fails"].append((s, j["why"]))
            proc += res["proc_ms"]
    return {"rows": rows, "proc_ms": proc}


def table(out: dict) -> str:
    lines = ["| Scenario | Must | Pass | Lead p10 / median (s) | Failures (seed: why) |", "|:--|:--|--:|:--|:--|"]
    for name, r in out["rows"].items():
        leads = sorted(r["leads"])
        lead = f"{leads[len(leads) // 10]:.2f} / {leads[len(leads) // 2]:.2f}" if leads else ""
        fails = "; ".join(f"{s}: {w}" for s, w in r["fails"][:3]) + (" ..." if len(r["fails"]) > 3 else "")
        must = {"warn": "warn", "appear": "warn fast", "quiet": "stay quiet", "stand": "<= 2 warnings"}[r["kind"]]
        lines.append(f"| {name} | {must} | {r['ok']}/{r['n']} | {lead} | {fails} |")
    p = sorted(out["proc_ms"])
    lines.append("")
    lines.append(f"Processing per frame (this machine, pure Python): median {p[len(p) // 2]:.3f} ms, "
                 f"p99 {p[int(len(p) * 0.99)]:.3f} ms, max {p[-1]:.3f} ms over {len(p)} frames.")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--unfitted", action="store_true", help="no eye height from setup: the 1.6 m default")
    a = ap.parse_args()
    print(table(sweep(a.seeds, fitted=not a.unfitted)))
