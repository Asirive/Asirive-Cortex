"""Trips by walking, bus and MRT: frequency-based RAPTOR over the bundle's patterns.

Singapore publishes headways (LTA frequency bands), not timetables, so a ride is: wait half the headway for the time
of day, then ride (metres along the pattern / its mean speed). Round k allows k rides. Transfers between stops are
the bundle's walking links. The planner returns up to 3 itineraries: the fastest per number of rides, and picks the
one with the fewest rides within +5 min of the fastest (a blind traveller pays more for each change than a minute).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from cortex_core.nav import bundle as B
from cortex_core.nav.walk import WALK_MPS, Walker, WalkPath

ACCESS_M = 900.0     # walking to the first stop / from the last stop
BOARD_S = 45.0       # getting on (finding the door, the card)
MAX_RIDES = 4
SLACK_S = 300.0      # fewer rides wins within this of the fastest
MODE_WORD = {B.K_BUS: "bus", B.K_MRT: "MRT", B.K_LRT: "LRT"}


@dataclass
class Leg:
    mode: str  # walk | bus | MRT | LRT
    minutes: float
    from_name: str = ""
    to_name: str = ""
    meters: float = 0.0
    service: str = ""
    board_stop: int = -1
    alight_stop: int = -1
    stops: list[int] = field(default_factory=list)  # bus/MRT: the stops passed, boarding to alighting
    wait_min: float = 0.0
    path: WalkPath | None = field(default=None, repr=False)

    def brief(self) -> dict:
        d = {"mode": self.mode, "minutes": round(self.minutes)}
        if self.mode == "walk":
            d.update(meters=int(round(self.meters, -1)), to=self.to_name)
        else:
            d.update(service=self.service, board=self.from_name, alight=self.to_name, stops=len(self.stops) - 1,
                     wait_minutes=round(self.wait_min))
        return d


@dataclass
class Itinerary:
    legs: list[Leg]
    minutes: float
    rides: int

    def brief(self) -> dict:
        return {"minutes": round(self.minutes), "rides": self.rides, "legs": [l.brief() for l in self.legs]}

    def summary(self) -> str:
        parts = []
        for l in self.legs:
            if l.mode == "walk":
                if l.minutes >= 0.5:
                    parts.append(f"walk {max(1, round(l.minutes))} min")
            elif l.mode == "bus":
                parts.append(f"bus {l.service} for {_n(len(l.stops) - 1, 'stop')}")
            else:
                parts.append(f"{l.mode} {l.service} for {_n(len(l.stops) - 1, 'stop')}")
        s = ", then ".join(parts) if parts else "you are there"
        return f"{s[0].upper()}{s[1:]}. About {_n(max(1, round(self.minutes)), 'minute')}."


class Planner:
    def __init__(self, b, walker: Walker | None = None):
        self.b = b
        self.w = walker or Walker(b)
        self.stop_node = np.asarray(b.stop_node)
        self.node_stops: dict[int, list[int]] = {}
        for s, nd in enumerate(self.stop_node):
            if nd >= 0:
                self.node_stops.setdefault(int(nd), []).append(s)
        self.pat_off = np.asarray(b.pat_off)
        self.pat_stop = np.asarray(b.pat_stop)
        self.pat_dist = np.asarray(b.pat_dist, np.float64)
        self.pat_speed = np.asarray(b.pat_speed, np.float64)
        self.pat_hw = np.asarray(b.pat_headway, np.float64)
        self.sp_off, self.sp_pat, self.sp_idx = np.asarray(b.sp_off), np.asarray(b.sp_pat), np.asarray(b.sp_idx)
        self.tr_off, self.tr_to, self.tr_len = np.asarray(b.tr_off), np.asarray(b.tr_to), np.asarray(b.tr_len, np.float64)

    def _stops_near(self, node: int) -> dict[int, float]:
        """stop -> walking metres from node (within ACCESS_M)."""
        out: dict[int, float] = {}
        for v, d in self.w.reach(node, ACCESS_M).items():
            for s in self.node_stops.get(v, ()):
                if d < out.get(s, np.inf):
                    out[s] = d
        return out

    def plan(self, src_node: int, dst_node, hour: float = 9.0, n: int = 3) -> list[Itinerary]:
        """Best itineraries, the chosen one first. dst_node: a node or several (a place's ways in)."""
        b = self.b
        band = B.band_of(hour)
        walk_only = self.w.route(src_node, dst_node, max_cost=4000.0)
        access = self._stops_near(src_node)
        egress = self._stops_near(dst_node)
        S = b.n_stops
        INF = np.inf
        tau = np.full((MAX_RIDES + 1, S), INF)
        best = np.full(S, INF)
        # label[k][s]: how s was reached in round k: ("ride", pattern, board_idx, alight_idx) | ("walk", from_stop, m)
        label: list[dict[int, tuple]] = [dict() for _ in range(MAX_RIDES + 1)]
        for s, d in access.items():
            tau[0, s] = d / WALK_MPS
            label[0][s] = ("access", d)
        best[:] = tau[0]
        marked = set(access)
        for k in range(1, MAX_RIDES + 1):
            # patterns to scan, from their earliest marked stop
            q: dict[int, int] = {}
            for s in marked:
                for j in range(self.sp_off[s], self.sp_off[s + 1]):
                    p, i = int(self.sp_pat[j]), int(self.sp_idx[j])
                    if i < q.get(p, 1 << 30):
                        q[p] = i
            new = set()
            for p, i0 in q.items():
                hw = self.pat_hw[p, band]
                if hw <= 0:
                    continue
                wait = hw * 60 / 2 + BOARD_S
                lo, hi = int(self.pat_off[p]), int(self.pat_off[p + 1])
                v = self.pat_speed[p]
                cur, cur_i = INF, -1  # best (boarding time - dist/v) so far along the pattern
                for i in range(i0, hi - lo):
                    s = int(self.pat_stop[lo + i])
                    d = self.pat_dist[lo + i]
                    if cur_i >= 0:
                        arr = cur + d / v
                        if arr < best[s] and arr < tau[k, s]:
                            tau[k, s] = arr
                            best[s] = arr
                            label[k][s] = ("ride", p, cur_i, i)
                            new.add(s)
                    prev = tau[k - 1, s]
                    if prev < INF:
                        c = prev + wait - d / v
                        if c < cur:
                            cur, cur_i = c, i
            # walking transfers
            for s in list(new):
                for j in range(self.tr_off[s], self.tr_off[s + 1]):
                    t = int(self.tr_to[j])
                    arr = tau[k, s] + self.tr_len[j] / WALK_MPS
                    if arr < best[t] and arr < tau[k, t]:
                        tau[k, t] = arr
                        best[t] = arr
                        label[k][t] = ("walk", s, float(self.tr_len[j]))
                        new.add(t)
            marked = new
            if not marked:
                break
        cands: list[Itinerary] = []
        bound = walk_only.length_m / WALK_MPS if walk_only is not None else INF
        for k in range(1, MAX_RIDES + 1):
            tot = [(tau[k, s] + d / WALK_MPS, s) for s, d in egress.items() if tau[k, s] < INF]
            if not tot:
                continue
            t, s = min(tot)
            if t >= bound:  # Pareto: another ride must arrive strictly earlier than every plan with fewer rides
                continue
            bound = t
            it = self._build(k, s, label, tau, access, egress, src_node, dst_node, band)
            if it is not None:
                cands.append(it)
        if walk_only is not None:
            cands.append(Itinerary([Leg("walk", walk_only.minutes, meters=walk_only.length_m, path=walk_only,
                                        to_name="your destination")], walk_only.minutes, 0))
        if not cands:
            return []
        fastest = min(c.minutes for c in cands)
        cands.sort(key=lambda c: (c.minutes > fastest + SLACK_S / 60, c.rides, c.minutes))
        # walking that is within 5 min of the best ride and under 1.2 km is simply better for a blind traveller
        if walk_only is not None and walk_only.length_m <= 1200 and walk_only.minutes <= cands[0].minutes + 5:
            cands.sort(key=lambda c: c.rides != 0)
        return cands[:n]

    def _build(self, k, s, label, tau, access, egress, src_node, dst_node, band) -> Itinerary | None:
        b = self.b
        legs: list[Leg] = []
        rides = 0
        tail = self._walk_leg(int(self.stop_node[s]), dst_node, egress[s], "your destination")
        cur, kk = s, k
        while True:
            lab = label[kk].get(cur)
            if lab is None:
                return None
            if lab[0] == "access":
                legs.append(self._walk_leg(src_node, int(self.stop_node[cur]), lab[1], b.stop_label(cur)))
                break
            if lab[0] == "walk":
                frm = lab[1]
                legs.append(self._walk_leg(int(self.stop_node[frm]), int(self.stop_node[cur]), lab[2], b.stop_label(cur)))
                cur = frm
                continue
            _, p, bi, ai = lab
            lo = int(self.pat_off[p])
            st = [int(x) for x in self.pat_stop[lo + bi:lo + ai + 1]]
            ride_s = (self.pat_dist[lo + ai] - self.pat_dist[lo + bi]) / self.pat_speed[p]
            wait = self.pat_hw[p, band] / 2
            mode = MODE_WORD[int(b.pat_mode[p])]
            legs.append(Leg(mode, ride_s / 60 + wait + BOARD_S / 60, b.stop_label(st[0]), b.stop_label(st[-1]),
                            service=b.s(int(b.pat_service[p])), board_stop=st[0], alight_stop=st[-1], stops=st,
                            wait_min=wait))
            rides += 1
            cur = st[0]
            kk -= 1
        legs.reverse()
        legs.append(tail)
        legs = [l for l in legs if not (l.mode == "walk" and l.meters < 1 and l.path is not None and len(l.path.nodes) <= 1)] or legs
        return Itinerary(legs, sum(l.minutes for l in legs), rides)

    def _walk_leg(self, a: int, z, metres: float, to_name: str) -> Leg:
        ok = a >= 0 and (z >= 0 if np.isscalar(z) else len(z) > 0)
        p = self.w.route(a, z, max_cost=3000.0) if ok else None
        m = p.length_m if p is not None else metres
        return Leg("walk", m / WALK_MPS / 60, meters=m, to_name=to_name, path=p)


def _n(k: int, word: str) -> str:
    return f"{k} {word}" if k == 1 else f"{k} {word}s"
