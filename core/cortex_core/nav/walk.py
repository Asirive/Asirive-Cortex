"""Walking: A* over the bundle's footpath graph, bounded Dijkstra for reaching stops, and spoken steps.

Cost = metres x a factor by edge flags: stairs cost 3x (a ramp or lift beside them wins), unsignalled crossings
add 25 m, signalled crossings 10 m, walking on a road without a footway 1.3x, covered links 0.95x.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np

from cortex_core.nav import bundle as B
from cortex_core.nav import geo

WALK_MPS = 1.1  # a careful pace with a cane


def edge_cost(length: np.ndarray, flags: np.ndarray) -> np.ndarray:
    f = np.asarray(flags)
    c = np.asarray(length, np.float64).copy()
    c = np.where(f & B.F_STEPS, c * 3.0, c)
    c = np.where(f & B.F_ROAD, c * 1.3, c)
    c = np.where(f & B.F_COVERED, c * 0.95, c)
    cross = (f & B.F_CROSSING) != 0
    sig = (f & B.F_SIGNALS) != 0
    c = c + np.where(cross & sig, 10.0, np.where(cross, 25.0, 0.0))
    return c


@dataclass
class Step:
    """One spoken instruction: at `at_m` along the path, `text`."""
    at_m: float
    text: str
    node: int
    kind: str = "turn"  # turn | cross | steps | arrive | start


@dataclass
class WalkPath:
    nodes: list[int]
    length_m: float
    cost: float
    xs: np.ndarray = field(repr=False)
    ys: np.ndarray = field(repr=False)
    steps: list[Step] = field(default_factory=list)

    @property
    def minutes(self) -> float:
        return self.length_m / WALK_MPS / 60


class Walker:
    def __init__(self, b):
        self.b = b
        self.x = np.asarray(b.node_x, np.float64)
        self.y = np.asarray(b.node_y, np.float64)
        self.off = np.asarray(b.edge_off)
        self.to = np.asarray(b.edge_to)
        self.len = np.asarray(b.edge_len, np.float64)
        self.flags = np.asarray(b.edge_flags)
        self.cost = edge_cost(self.len, self.flags)
        self._grid = None

    # ---- nearest node
    def _build_grid(self, cell: float = 100.0):
        gx = np.floor(self.x / cell).astype(np.int64)
        gy = np.floor(self.y / cell).astype(np.int64)
        key = gx * 1_000_003 + gy
        order = np.argsort(key, kind="stable")
        self._grid = (cell, key[order], order)

    def nearest(self, x: float, y: float, max_m: float = 300.0) -> int:
        """The walking node nearest to (x, y) with at least one edge; -1 if none within max_m."""
        if self._grid is None:
            self._build_grid()
        cell, keys, order = self._grid
        r = int(np.ceil(max_m / cell))
        cx, cy = int(np.floor(x / cell)), int(np.floor(y / cell))
        best, bd = -1, max_m
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                k = (cx + dx) * 1_000_003 + (cy + dy)
                lo, hi = np.searchsorted(keys, k), np.searchsorted(keys, k, side="right")
                if lo == hi:
                    continue
                ids = order[lo:hi]
                ids = ids[self.off[ids + 1] > self.off[ids]]
                if len(ids) == 0:
                    continue
                d = np.hypot(self.x[ids] - x, self.y[ids] - y)
                j = int(np.argmin(d))
                if d[j] < bd:
                    best, bd = int(ids[j]), float(d[j])
        return best

    def nearest_many(self, qx, qy, max_m: float = 300.0, cell: float = 50.0) -> np.ndarray:
        """nearest() for many points at once (vectorised; the bundle builder places 100k+ addresses with it)."""
        qx = np.asarray(qx, np.float64)
        qy = np.asarray(qy, np.float64)
        ok = self.off[1:] > self.off[:-1]
        ids = np.nonzero(ok)[0]
        gx = np.floor(self.x[ids] / cell).astype(np.int64)
        gy = np.floor(self.y[ids] / cell).astype(np.int64)
        key = gx * 4_000_037 + gy
        order = np.argsort(key, kind="stable")
        keys, ids = key[order], ids[order]
        cx = np.floor(qx / cell).astype(np.int64)
        cy = np.floor(qy / cell).astype(np.int64)
        best = np.full(len(qx), -1, np.int64)
        bd = np.full(len(qx), np.inf)
        stop_after = np.full(len(qx), 1 << 30)  # ring index after which a query is settled
        R = int(np.ceil(max_m / cell)) + 1
        for r in range(R + 1):
            live = np.nonzero(stop_after >= r)[0]
            if len(live) == 0:
                break
            ring = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if max(abs(dx), abs(dy)) == r]
            for dx, dy in ring:
                k = (cx[live] + dx) * 4_000_037 + (cy[live] + dy)
                lo = np.searchsorted(keys, k)
                hi = np.searchsorted(keys, k, side="right")
                n = hi - lo
                j = 0
                while True:
                    sel = np.nonzero(n > j)[0]
                    if len(sel) == 0:
                        break
                    q = live[sel]
                    c = ids[lo[sel] + j]
                    d = np.hypot(self.x[c] - qx[q], self.y[c] - qy[q])
                    better = d < bd[q]
                    bd[q[better]] = d[better]
                    best[q[better]] = c[better]
                    j += 1
            found = live[np.isfinite(bd[live]) & (stop_after[live] == 1 << 30)]
            stop_after[found] = r + 1  # a point in the next ring can still be nearer (cell corners)
        best[bd > max_m] = -1
        return best

    # ---- routing
    def route(self, src: int, dst, max_cost: float = 30000.0) -> WalkPath | None:
        """A* by cost to dst (a node, or several: the path ends at the cheapest). Heuristic: straight-line metres to
        the nearest target x 0.95, admissible since every cost factor is >= 0.95."""
        targets = {int(dst)} if np.isscalar(dst) else {int(d) for d in dst}
        if not targets:
            return None
        if src in targets:
            return self._path([src], 0.0)
        x, y, off, to, cost = self.x, self.y, self.off, self.to, self.cost
        tl = sorted(targets)
        tx, ty = x[tl], y[tl]
        one = len(tl) == 1
        t0x, t0y = float(tx[0]), float(ty[0])

        def h(v):
            if one:
                return 0.95 * math.hypot(x[v] - t0x, y[v] - t0y)
            return 0.95 * float(np.min(np.hypot(tx - x[v], ty - y[v])))
        g = {src: 0.0}
        prev = {src: -1}
        pq = [(h(src), 0.0, src)]
        done = set()
        end = -1
        while pq:
            f, gc, u = heapq.heappop(pq)
            if u in done:
                continue
            if u in targets:
                end = u
                break
            done.add(u)
            if gc > max_cost:
                return None
            for e in range(off[u], off[u + 1]):
                v = int(to[e])
                ng = gc + cost[e]
                if ng < g.get(v, np.inf):
                    g[v] = ng
                    prev[v] = u
                    heapq.heappush(pq, (ng + h(v), ng, v))
        if end < 0:
            return None
        dst = end
        nodes = [dst]
        while prev[nodes[-1]] != -1:
            nodes.append(prev[nodes[-1]])
        nodes.reverse()
        return self._path(nodes, g[dst])

    def reach(self, src, max_m: float) -> dict[int, float]:
        """Walking cost-metres from src (a node, or several) to every node within max_m."""
        srcs = [int(src)] if np.isscalar(src) else [int(v) for v in src]
        dist = {v: 0.0 for v in srcs}
        pq = [(0.0, v) for v in srcs]
        off, to, cost = self.off, self.to, self.cost
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, np.inf):
                continue
            for e in range(off[u], off[u + 1]):
                nd = d + cost[e]
                v = int(to[e])
                if nd <= max_m and nd < dist.get(v, np.inf):
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        return dist

    def _edge(self, u: int, v: int) -> int:
        for e in range(self.off[u], self.off[u + 1]):
            if int(self.to[e]) == v:
                return e
        raise KeyError((u, v))

    def _path(self, nodes: list[int], cost: float) -> WalkPath:
        xs, ys = self.x[nodes], self.y[nodes]
        length = float(np.hypot(np.diff(xs), np.diff(ys)).sum()) if len(nodes) > 1 else 0.0
        p = WalkPath(nodes, length, cost, xs, ys)
        p.steps = self.steps(nodes)
        return p

    def steps(self, nodes: list[int]) -> list[Step]:
        """Instructions where the way changes: turns over 25 degrees, crossings, steps, street name changes."""
        b = self.b
        if len(nodes) < 2:
            return [Step(0.0, "You have arrived.", nodes[0] if nodes else -1, "arrive")]
        edges = [self._edge(u, v) for u, v in zip(nodes[:-1], nodes[1:])]
        seg = np.hypot(np.diff(self.x[nodes]), np.diff(self.y[nodes]))
        cum = np.concatenate([[0.0], np.cumsum(seg)])

        def head(i):  # heading of segment i (x east, y north)
            return (np.degrees(np.arctan2(self.x[nodes[i + 1]] - self.x[nodes[i]],
                                          self.y[nodes[i + 1]] - self.y[nodes[i]])) + 360) % 360

        def name(i):
            return b.s(int(b.edge_name[edges[i]]))

        first = name(0)
        out = [Step(0.0, f"Head {_compass(head(0))}" + (f" along {first}" if first else "") + ".", nodes[0], "start")]
        i = 0
        while i < len(edges) - 1:
            j = i + 1
            fl = int(self.flags[edges[j]])
            ang = geo.turn_angle(head(i), head(j))
            nm, prev_nm = name(j), name(i)
            if fl & B.F_CROSSING and not int(self.flags[edges[i]]) & B.F_CROSSING:
                sig = " at the traffic light" if fl & B.F_SIGNALS else ""
                out.append(Step(float(cum[j]), f"Cross the road{sig}.", nodes[j], "cross"))
            elif fl & B.F_STEPS and not int(self.flags[edges[i]]) & B.F_STEPS:
                out.append(Step(float(cum[j]), "Steps ahead.", nodes[j], "steps"))
            elif abs(ang) >= 25 or (nm and nm != prev_nm and abs(ang) >= 10):
                t = geo.clock_side(ang)
                if t == "continue straight":
                    t = "continue"
                out.append(Step(float(cum[j]), t[0].upper() + t[1:] + (f" onto {nm}" if nm and nm != prev_nm else "") + ".",
                                nodes[j], "turn"))
            i = j
        out.append(Step(float(cum[-1]), "You have arrived.", nodes[-1], "arrive"))
        return _merge_close(out)


def _compass(h: float) -> str:
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][int((h + 22.5) // 45) % 8]


def _merge_close(steps: list[Step], gap: float = 8.0) -> list[Step]:
    """Two instructions within a few metres become one (a kink in the mapped line is not a turn of its own)."""
    out: list[Step] = []
    for s in steps:
        if out and s.kind == "turn" and out[-1].kind == "turn" and s.at_m - out[-1].at_m < gap:
            out[-1] = s
            continue
        out.append(s)
    return out


def describe_distance(m: float) -> str:
    if m < 15:
        return "now"
    if m < 100:
        return f"in {int(round(m / 5) * 5)} metres"
    if m < 1000:
        return f"in {int(round(m, -1))} metres"
    return f"in {m / 1000:.1f} kilometres"
