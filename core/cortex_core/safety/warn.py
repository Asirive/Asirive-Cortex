"""Per-sector obstacle tracks and the warning policy (anti-spam is a requirement, core/AGENTS.md rule 8).

- An obstacle is warned at most twice: "ahead" (about ttc_warn_s before contact, or nearer than near_m) and
  "close" (about ttc_close_s, or nearer than close_m). Never repeated for the same obstacle.
- Grounded obstacles (support under them at cane height) are the cane's: never warned. Unknown = warned.
- "ahead" has a global cooldown; "close" a shorter one. A track that moves to the next sector as the head turns
  inherits the old track's state, so turning your head does not re-warn.
- No first warning while the head swings fast (a sweep is not an approach).
- A warned obstacle is remembered by direction (head yaw integrated from the gyro + where it was in view) and
  distance, so scanning your head across it while standing does not re-warn it.
- One obstacle spanning several sectors is one obstacle: a warning marks every track at about that distance.
"""
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from cortex_core.safety.perceive import SIDES, Obs

AHEAD, CLOSE = "ahead", "close"
MOTOR = {"left": "left", "right": "right", "centre": "both"}


@dataclass
class Track:
    d: float
    t: float
    born: float
    hist: deque = field(default_factory=lambda: deque(maxlen=6))
    frames: int = 1
    level: int = 0      # 0 none, 1 ahead given, 2 close given
    gscore: int = 0     # > 0 grounded evidence, < 0 seen-clear evidence
    grounded: bool = False
    open_seen: int = 0  # frames that showed open space under it

    def closing(self) -> float:
        """Closing speed (m/s, > 0 = getting nearer): least squares over the recent history."""
        h = self.hist
        if len(h) < 3 or h[-1][0] - h[0][0] < 0.12:
            return 0.0
        n = len(h)
        mt = sum(t for t, _ in h) / n
        md = sum(d for _, d in h) / n
        den = sum((t - mt) ** 2 for t, _ in h)
        return -sum((t - mt) * (d - md) for t, d in h) / den if den > 0 else 0.0


class Warner:
    def __init__(self, cfg: dict):
        self.c = cfg
        self.tracks: dict[str, Track] = {}
        self.gone: list[tuple[float, Track]] = []  # recently lost, for hand-over between sectors
        self.last_ahead = -1e9
        self.last_close = -1e9
        self.yaw = 0.0                                       # integrated head yaw, rad (drifts slowly; fine for 30 s)
        self.memory: list[list[float]] = []                  # [bearing, distance, time, level]

    def _bearing(self, seen) -> float:
        return self.yaw - math.atan2((seen.x0 + seen.x1) / 2, max(seen.d, 0.05))

    def _remembered(self, seen, t: float) -> int:
        b, lvl = self._bearing(seen), 0
        lim = math.radians(self.c["memory_deg"])
        for m in self.memory:
            if t - m[2] < self.c["memory_s"] and abs(m[0] - b) < lim and abs(m[1] - seen.d) < 0.4:
                lvl = max(lvl, int(m[3]))
                m[1], m[2] = seen.d, t   # still there: keep remembering it
        return lvl

    def _remember(self, seen, t: float, level: int) -> None:
        self.memory = [m for m in self.memory if t - m[2] < self.c["memory_s"]][-32:]
        self.memory.append([self._bearing(seen), seen.d, t, level])

    def _inherit(self, side: str, d: float, t: float) -> Optional[Track]:
        best = None
        for s, tr in self.tracks.items():
            if s != side and abs(tr.d - d) < 0.3 and (best is None or tr.level > best.level):
                best = tr
        for lost_t, tr in self.gone:
            if t - lost_t < 1.0 and abs(tr.d - d) < 0.3 and (best is None or tr.level > best.level):
                best = tr
        return best

    def update(self, t: float, obs: Obs, yaw_dps: float = 0.0, dyaw: float = 0.0) -> list[tuple[str, str]]:
        c = self.c
        self.yaw += dyaw
        self.gone = [(lt, tr) for lt, tr in self.gone if t - lt < 1.0]
        fired: list[tuple[str, str]] = []
        for side in SIDES:
            seen = obs.sectors.get(side)
            tr = self.tracks.get(side)
            if seen is None:
                if tr is not None and t - tr.t > c["lose_s"]:
                    self.gone.append((t, tr))
                    del self.tracks[side]
                continue
            d = seen.d
            if tr is None or abs(d - tr.d) > 0.6 or t - tr.t > c["lose_s"]:  # a jump is a different surface
                if tr is not None:
                    self.gone.append((t, tr))
                src = self._inherit(side, d, t)
                tr = Track(d, t, t)
                if src is not None:
                    tr.level, tr.gscore, tr.grounded, tr.frames = src.level, src.gscore, src.grounded, max(src.frames, 1)
                    tr.open_seen = src.open_seen
                    tr.hist.extend(src.hist)
                tr.level = max(tr.level, self._remembered(seen, t))
                self.tracks[side] = tr
            else:
                tr.frames += 1
            tr.d, tr.t = d, t
            tr.hist.append((t, d))
            # Support under it is strong evidence; "open under it" is weaker (a thin pole's foot covers part of a
            # zone and flickers). Hysteresis: grounded at +2, cleared at -2; capped at +6 / -3 so a run of support
            # outlasts a flicker of "open", and a little support turns "open" round. (Weighting far support lower
            # was tried: it fixed one door case and cost more false alarms on walls and people; see the sim doc.)
            if seen.grounded is True:
                tr.gscore = min(tr.gscore + 3, 6)
            elif seen.grounded is False:
                tr.gscore = max(tr.gscore - 1, -3)
                tr.open_seen += 1
            if tr.gscore >= 2:
                tr.grounded = True
            elif tr.gscore <= -2:
                tr.grounded = False
            if tr.frames < 3 or tr.grounded:
                continue
            if tr.level == 0 and abs(yaw_dps) > c["swing_dps"]:
                continue
            v = tr.closing()
            ttc = d / v if v > c["min_closing_mps"] else float("inf")
            close = d <= c["close_m"] or ttc <= c["ttc_close_s"]
            # Never yet seen open underneath: its foot is usually just out of view and comes in as we approach, so
            # give it 0.3 s more before calling it overhanging. Seen open: the full lead.
            ttc_warn = c["ttc_warn_s"] if tr.open_seen else c["ttc_warn_s"] - 0.3
            ahead = d <= c["near_m"] or (ttc <= ttc_warn and d <= c["max_warn_m"])
            if close and tr.level < 2 and t - self.last_close >= c["close_cooldown_s"]:
                self.last_close = self.last_ahead = t
                self._mark(tr, seen, t, 2)
                fired.append((CLOSE, side))
            elif ahead and tr.level < 1 and t - self.last_ahead >= c["cooldown_s"]:
                self.last_ahead = t
                self._mark(tr, seen, t, 1)
                fired.append((AHEAD, side))
        return _merge(fired)

    def _mark(self, tr: Track, seen, t: float, level: int) -> None:
        """This obstacle has been warned at `level`: so has anything else at about its distance (same object
        across sectors), and it is remembered."""
        for other in self.tracks.values():
            if abs(other.d - tr.d) < 0.3:
                other.level = max(other.level, level)
        tr.level = level
        self._remember(seen, t, level)


def _merge(fired: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """One pattern per frame: the most urgent; several sides at once = both motors."""
    if not fired:
        return []
    lvl = CLOSE if any(p == CLOSE for p, _ in fired) else AHEAD
    sides = {s for p, s in fired if p == lvl}
    motor = MOTOR[sides.pop()] if len(sides) == 1 else "both"
    return [(lvl, motor)]
