"""One VL53L7CX frame -> what is in the walking corridor at head/body height, per sector.

Frames (sensor frame axes: x = user's right, y = forward, z = up; zone row 0 = top, column 0 = user's left):
  dist_mm[64]: distance per zone, None = no target / invalid status
  accel[3]:    mean specific force over the frame, in g (reads +1 g "up" at rest)
  dtheta[3]:   gyro rotation summed over the frame, rad, about x (pitch), y (roll), z (yaw)
The ESP32 averages and sums at its own IMU rate, so a 15 Hz frame still carries the full rotation.

Pure Python on purpose: 64 zones a frame is cheap, and safety has no heavy dependencies (measured in tests).
"""
import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

N = 8
SIDES = ("left", "centre", "right")


def zone_dirs(fov_deg: float, n: int = N) -> list[tuple[float, float, float]]:
    """Unit ray per zone centre, row-major, row 0 top, column 0 left (tangent-plane grid)."""
    t = math.tan(math.radians(fov_deg) / 2)
    out = []
    for r in range(n):
        for c in range(n):
            u = t * (2 * (c + 0.5) / n - 1)
            v = t * (1 - 2 * (r + 0.5) / n)
            k = math.sqrt(u * u + 1 + v * v)
            out.append((u / k, 1 / k, v / k))
    return out


def rotate(d: tuple[float, float, float], pitch: float, roll: float) -> tuple[float, float, float]:
    """Head frame -> level frame (heading kept): R = Rx(pitch) . Ry(roll). Pitch > 0 = looking up."""
    x, y, z = d
    cr, sr, cp, sp = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch)
    x1, z1 = cr * x + sr * z, -sr * x + cr * z
    return x1, cp * y - sp * z1, sp * y + cp * z1


def tilt_from_accel(a: Sequence[float]) -> tuple[float, float]:
    """Inverse of rotate() applied to "up": a = (-sin r cos p, sin p, cos r cos p)."""
    ax, ay, az = a
    return math.atan2(ay, math.hypot(ax, az)), math.atan2(-ax, az)


class Tilt:
    """Complementary filter: gyro for the fast part, gravity for the slow part (skipped while accelerating hard)."""

    def __init__(self, keep: float = 0.92):
        self.keep = keep
        self.pitch: Optional[float] = None
        self.roll = 0.0

    def update(self, accel: Sequence[float], dtheta: Sequence[float]) -> tuple[float, float]:
        mag = math.sqrt(sum(v * v for v in accel))
        steady = 0.8 <= mag <= 1.2
        if self.pitch is None:
            self.pitch, self.roll = tilt_from_accel(accel) if mag > 0.5 else (0.0, 0.0)
            return self.pitch, self.roll
        p, r = self.pitch + dtheta[0], self.roll + dtheta[1]
        if steady:
            ap, ar = tilt_from_accel(accel)
            p = self.keep * p + (1 - self.keep) * ap
            r = self.keep * r + (1 - self.keep) * ar
        self.pitch, self.roll = p, r
        return p, r


@dataclass
class Seen:
    d: float                # forward distance to the nearest part, m
    x0: float               # lateral extent of that nearest part, m
    x1: float
    grounded: Optional[bool]  # True: support under it at cane height; False: looked and nothing; None: can't see


@dataclass
class Obs:
    sectors: dict = field(default_factory=dict)  # side -> Seen
    blocked: bool = False
    height: float = 0.0


class Perception:
    def __init__(self, cfg: dict):
        self.c = cfg
        self.dirs = zone_dirs(cfg["fov_deg"])
        self.h = cfg["sensor_height_m"]
        self.h_n = 0   # ground fixes so far: until about 10, the height is a guess (the configured eye height)
        self.bottom = range(N * (N - 1), N * N)
        self.zone_rad = math.radians(cfg["fov_deg"]) / N

    def _ground(self, cands: list[float]) -> None:
        if len(cands) < 4:
            return
        top = max(cands)
        sel = sorted(g for g in cands if g >= top - 0.06)  # the ground is the lowest surface we see
        if len(sel) >= 4:
            m = sel[len(sel) // 2]
            if 1.0 <= m <= 2.1:
                self.h_n += 1
                k = max(0.1, 1.0 / (self.h_n + 2))  # learn fast at first (never all from one fix), then smooth
                self.h = (1 - k) * self.h + k * m

    def process(self, dist_mm: Sequence[Optional[float]], pitch: float, roll: float) -> Obs:
        c = self.c
        w = [rotate(d, pitch, roll) for d in self.dirs]
        grid: list[Optional[tuple[float, float, float]]] = [None] * len(w)  # level-frame point per zone (z = -drop)
        cands = []
        tiny = 0
        for i, mm in enumerate(dist_mm):
            if mm is None or mm != mm or mm <= 0:
                continue
            if mm < 40:  # something on the lens
                tiny += 1
                continue
            d = mm / 1000.0
            px, py, pz = d * w[i][0], d * w[i][1], d * w[i][2]
            # ground fixes only from rays at least 20 degrees down and well inside range: at grazing angles, or near
            # the range limit, a zone sees only the near part of its strip of floor and the floor reads high
            if w[i][2] < -0.34 and abs(px) < 1.0 and d <= 2.2:
                cands.append(-pz)
            grid[i] = (px, py, pz)
        self._ground(cands)
        h = self.h
        top = h + c["head_margin_m"]
        lifted = [None if p is None else (p[0], p[1], h + p[2]) for p in grid]
        band = [i for i, p in enumerate(lifted)
                if p is not None and c["band_low_m"] <= p[2] <= top and abs(p[0]) <= c["corridor_half_m"] and p[1] > 0.05]
        obs = Obs(blocked=tiny >= 0.8 * len(self.dirs), height=h)
        ch = c["centre_half_m"]
        for side in SIDES:
            mine = [i for i in band
                    if (lifted[i][0] < -ch if side == "left" else lifted[i][0] > ch if side == "right"
                        else -ch <= lifted[i][0] <= ch)]
            if not mine:
                continue
            dmin = min(lifted[i][1] for i in mine)
            near = [i for i in mine if lifted[i][1] <= dmin + 0.25]
            xs = [lifted[i][0] for i in near]
            first = min(near, key=lambda i: lifted[i][1])
            obs.sectors[side] = Seen(dmin, min(xs), max(xs), self._grounded(first, band, lifted))
        return obs

    def _grounded(self, seed: int, band: list[int], lifted: list) -> Optional[bool]:
        """Is the object containing band zone `seed` standing on something the cane will meet?
        Object = band zones connected in the image at about the same distance. Each of its zones on the walking line
        (|x| <= corridor - 0.1: door posts beside an opening do not vote) walks down its column; a zone at the object's
        edge only partly covers it and can see past it, so it is a vote: support must outnumber passes 2 to 1."""
        lim = self.c["corridor_half_m"] - 0.1
        inband = set(band)
        obj, todo = {seed}, [seed]
        while todo:
            i = todo.pop()
            r, col = divmod(i, N)
            for j in ((i - N) if r > 0 else -1, (i + N) if r < N - 1 else -1,
                      (i - 1) if col > 0 else -1, (i + 1) if col < N - 1 else -1):
                if j in inband and j not in obj and abs(lifted[j][1] - lifted[i][1]) < 0.3:
                    obj.add(j)
                    todo.append(j)
        voters = [i for i in obj if abs(lifted[i][0]) <= lim] or list(obj)
        dmin = min(lifted[i][1] for i in obj)
        votes = {i: self._column(i, dmin, lifted) for i in voters}
        # A column right beside one that sees support is usually the object's edge: the zone covers it only partly and,
        # lower down, sees past it (a pole on a column boundary with 2 degrees of head roll). Its "pass" is not counted.
        sup_cols = {i % N for i, v in votes.items() if v == "support"}
        sup = sum(1 for v in votes.values() if v == "support")
        pas = sum(1 for i, v in votes.items() if v == "pass" and not ({i % N - 1, i % N + 1} & sup_cols))
        if sup > 2 * pas:
            return True
        return False if pas else None

    def _column(self, i: int, dmin: float, lifted: list) -> str:
        """Walk down the image column under zone i (an obstacle zone at forward distance ~dmin):
        "support"  the obstacle continues down to cane height (wall, pole, person), or something nearer sits at
                   cane height (stairs, a bench): the cane meets it
        "pass"     a ray below reaches farther than the obstacle's depth, or the floor beyond its front: open
                   space under it (branch, door header, tailgate, sign)
        "unknown"  out of view below (the floor in front hides it, or the column ends)"""
        c = self.c
        depth = c["ground_link_depth_m"]
        # With the height a guess, the far floor can sit 0.1-0.3 m "up": demand more clearance for support.
        link_low = c["ground_link_low_m"] + (0.05 if self.h_n >= 10 else 0.15)
        empty = 0
        for j in range(i + N, N * N, N):
            q = lifted[j]
            if q is None:
                empty += 1  # no return: a dropout, or nothing in range (open space through a doorway)
                continue
            _, y, z = q
            if y > dmin + depth:
                return "pass"
            if y >= dmin - 0.15:  # the same surface, or right under its front
                if z < link_low:
                    if y > dmin + 0.1:
                        return "pass"   # the floor under it: we are looking under the obstacle
                    continue            # its foot (a wall meeting the floor): keep looking
                # A zone's point sits on its centre ray but the surface can be anywhere in the zone (7.5 degrees,
                # 0.3 m tall at 2.4 m): the lower edge of a waist-high tailgate reads at 0.7 m. Support must sit
                # below the band by half a zone at its own range; until then it may still be the obstacle itself.
                if z <= min(c["ground_link_high_m"], c["band_low_m"] - 0.5 * self.zone_rad * math.hypot(q[0], y)):
                    return "support"
                continue
            # nearer than the obstacle
            return "support" if link_low <= z < c["band_low_m"] else "unknown"
        return "pass" if empty >= 2 else "unknown"  # nothing at all below it within range: open
