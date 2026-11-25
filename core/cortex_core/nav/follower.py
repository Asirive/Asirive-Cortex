"""Following an itinerary: GPS fixes in, spoken events out.

    f = Follower(bundle, itinerary)
    for ev in f.update(Fix(x, y, acc_m, t, speed)):   # ev: Event(type, text, data)
        say(ev.text)

Walking legs: the position is projected onto the leg's path; each step is announced once ahead (PREWARN_M) and once
when reached. Off route: farther than max(OFF_MIN_M, 1.5 x accuracy) for OFF_FIXES fixes in a row (one wild fix
is not a detour); back on route after ON_FIXES good fixes. Fixes worse than BAD_ACC_M are ignored for decisions.
Bus/MRT legs: BUS_WATCH once within BOARD_M of the boarding stop; on board once moving faster than a walk away
from it; then the next stop, "alight at the next stop", and "get off now". Arrived within ARRIVE_M of the end.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from cortex_core.nav import geo
from cortex_core.nav.transit import Itinerary
from cortex_core.nav.walk import describe_distance

PREWARN_M = 40.0
STEP_NOW_M = 12.0
OFF_MIN_M = 25.0
OFF_FIXES = 3
ON_FIXES = 2
BAD_ACC_M = 50.0
BOARD_M = 40.0
ALIGHT_NOW_M = 120.0  # a bus covers this in ~15 s: time to stand and press the bell
ARRIVE_M = 15.0
RIDING_MPS = 3.0


@dataclass
class Fix:
    x: float
    y: float
    acc_m: float = 5.0
    t: float = 0.0
    speed: float | None = None

    @staticmethod
    def from_latlon(lat: float, lon: float, acc_m: float = 5.0, t: float = 0.0, speed: float | None = None) -> "Fix":
        x, y = geo.to_xy(lat, lon)
        return Fix(float(x), float(y), acc_m, t, speed)


@dataclass
class Event:
    type: str  # step | prewarn | off_route | on_route | at_stop | boarded | next_stop | alight_next | alight_now | leg | arrived | gps_weak
    text: str
    data: dict = field(default_factory=dict)


class Follower:
    def __init__(self, b, it: Itinerary):
        self.b = b
        self.it = it
        self.leg = 0
        self.off = False
        self._bad = 0
        self._good = 0
        self._said: set = set()
        self.along = 0.0
        self.dist_to_route = 0.0
        self.done = False
        self._ride_idx = 0
        self._weak = False
        self._last: Fix | None = None
        self._enter_leg()

    # ---- state for the LM's [state] line and nav_status
    def status(self) -> dict:
        if self.done:
            return {"leg": self.leg, "arrived": True}
        l = self.it.legs[self.leg]
        d = {"leg": self.leg, "legs": len(self.it.legs), "mode": l.mode, "off_route": self.off}
        if l.mode == "walk" and l.path is not None:
            d["remaining_m"] = int(max(0.0, l.path.length_m - self.along))
            nxt = self._next_step()
            if nxt is not None:
                d["next"] = nxt.text
                d["next_in_m"] = int(max(0.0, nxt.at_m - self.along))
        elif l.mode != "walk":
            d.update(service=l.service, alight=l.to_name, stops_left=max(0, len(l.stops) - 1 - self._ride_idx),
                     on_board=self._ride_idx > 0 or ("boarded", self.leg) in self._said)
        return d

    def state_line(self) -> str:
        s = self.status()
        if s.get("arrived"):
            return "nav: arrived"
        if s["mode"] == "walk":
            t = f"nav: walking, {s.get('remaining_m', '?')} m left in this leg"
            if "next" in s:
                t += f"; next: {s['next']} in {s['next_in_m']} m"
            return t + ("; OFF ROUTE" if s["off_route"] else "")
        return f"nav: {s['mode']} {s['service']}, {s['stops_left']} stops to {s['alight']}"

    # ----
    def _enter_leg(self):
        self.along = 0.0
        self._ride_idx = 0
        self.off = False
        self._bad = self._good = 0

    def _next_step(self):
        l = self.it.legs[self.leg]
        for i, st in enumerate(l.path.steps if l.path else []):
            if st.kind != "start" and ("step", self.leg, i) not in self._said and st.at_m > self.along - STEP_NOW_M:
                return st
        return None

    def update(self, f: Fix) -> list[Event]:
        if self.done:
            return []
        ev: list[Event] = []
        if f.acc_m > BAD_ACC_M:
            if not self._weak:
                self._weak = True
                ev.append(Event("gps_weak", "GPS is weak here. Go slowly.", {"acc_m": f.acc_m}))
            return ev
        if self._weak:
            self._weak = False
        speed = f.speed
        if speed is None and self._last is not None and f.t > self._last.t:
            speed = float(np.hypot(f.x - self._last.x, f.y - self._last.y) / (f.t - self._last.t))
        self._last = f
        l = self.it.legs[self.leg]
        if l.mode == "walk":
            ev += self._walk(l, f)
        else:
            ev += self._ride(l, f, speed or 0.0)
        return ev

    def _advance(self) -> list[Event]:
        self.leg += 1
        if self.leg >= len(self.it.legs):
            self.done = True
            return [Event("arrived", "You have arrived.", {})]
        self._enter_leg()
        l = self.it.legs[self.leg]
        if l.mode == "walk":
            first = l.path.steps[0].text if l.path and l.path.steps else ""
            return [Event("leg", f"Now walk {round(l.meters, -1):.0f} metres to {l.to_name}. {first}".strip(),
                          {"leg": self.leg})]
        return [Event("leg", f"Wait here for {l.mode} {l.service}.", {"leg": self.leg})]

    def _walk(self, l, f: Fix) -> list[Event]:
        ev: list[Event] = []
        if l.path is None or len(l.path.nodes) < 2:
            return self._advance()
        d, along, _ = geo.project_on_polyline(f.x, f.y, l.path.xs, l.path.ys)
        lim = max(OFF_MIN_M, 1.5 * f.acc_m)
        if d > lim:
            self._bad += 1
            self._good = 0
            if not self.off and self._bad >= OFF_FIXES:
                self.off = True
                ev.append(Event("off_route", "You are off the route. Finding the way again.", {"dist_m": d}))
            return ev
        self._good += 1
        self._bad = 0
        if self.off and self._good >= ON_FIXES:
            self.off = False
            ev.append(Event("on_route", "Back on the route.", {}))
        if self.off:
            return ev
        self.along = max(self.along, along) if along >= self.along - 30 else along  # GPS jitter never walks you back
        nxt_leg = self.it.legs[self.leg + 1] if self.leg + 1 < len(self.it.legs) else None
        for i, st in enumerate(l.path.steps):
            if st.kind == "start":
                continue
            ahead = st.at_m - self.along
            if st.kind == "arrive":
                if ahead <= ARRIVE_M:
                    if nxt_leg is not None and nxt_leg.mode != "walk":
                        if ("at_stop", self.leg) not in self._said:
                            self._said.add(("at_stop", self.leg))
                            ev.append(Event("at_stop", f"You are at {nxt_leg.from_name}. Wait here for "
                                                       f"{nxt_leg.mode} {nxt_leg.service}.",
                                            {"stop": nxt_leg.board_stop, "service": nxt_leg.service}))
                        ev += self._advance_quiet()
                    else:
                        ev += self._advance()
                    return ev
                continue
            if ahead <= STEP_NOW_M and ("step", self.leg, i) not in self._said:
                self._said.add(("step", self.leg, i))
                self._said.add(("pre", self.leg, i))
                ev.append(Event("step", st.text, {"at_m": st.at_m}))
            elif STEP_NOW_M < ahead <= PREWARN_M and ("pre", self.leg, i) not in self._said:
                self._said.add(("pre", self.leg, i))
                ev.append(Event("prewarn", f"{describe_distance(ahead)[0].upper()}{describe_distance(ahead)[1:]}, "
                                           f"{st.text[0].lower()}{st.text[1:]}", {"at_m": st.at_m}))
        return ev

    def _advance_quiet(self) -> list[Event]:
        """Into a ride leg after at_stop was said (no second 'wait here')."""
        self.leg += 1
        self._enter_leg()
        return []

    def _ride(self, l, f: Fix, speed: float) -> list[Event]:
        ev: list[Event] = []
        b = self.b
        sx = np.asarray(b.stop_x)[l.stops].astype(np.float64)
        sy = np.asarray(b.stop_y)[l.stops].astype(np.float64)
        d0 = float(np.hypot(f.x - sx[0], f.y - sy[0]))
        boarded = ("boarded", self.leg) in self._said
        if not boarded:
            if d0 <= BOARD_M and ("at_stop", self.leg - 1) not in self._said and ("watch", self.leg) not in self._said:
                self._said.add(("watch", self.leg))
                ev.append(Event("at_stop", f"You are at {l.from_name}. Wait here for {l.mode} {l.service}.",
                                {"stop": l.board_stop, "service": l.service}))
            if speed >= RIDING_MPS and d0 > BOARD_M:
                self._said.add(("boarded", self.leg))
                ev.append(Event("boarded", f"On {l.mode} {l.service}. {len(l.stops) - 1} stops to {l.to_name}.",
                                {"stops": len(l.stops) - 1}))
            else:
                return ev
        # which stop have we passed: the last stop whose position along the line is behind us
        d, along, seg = geo.project_on_polyline(f.x, f.y, sx, sy)
        idx = int(seg)
        if idx > self._ride_idx:
            self._ride_idx = idx
            nxt = idx + 1
            if nxt < len(l.stops) - 1 and ("next", self.leg, nxt) not in self._said:
                self._said.add(("next", self.leg, nxt))
                ev.append(Event("next_stop", f"Next stop {b.stop_label(l.stops[nxt])}.", {"index": nxt}))
            if nxt == len(l.stops) - 1 and ("alight_next", self.leg) not in self._said:
                self._said.add(("alight_next", self.leg))
                ev.append(Event("alight_next", f"Get off at the next stop, {l.to_name}. Press the bell."
                                if l.mode == "bus" else f"Get off at the next station, {l.to_name}.", {}))
        dz = float(np.hypot(f.x - sx[-1], f.y - sy[-1]))
        if dz <= ALIGHT_NOW_M and ("alight_now", self.leg) not in self._said:
            self._said.add(("alight_now", self.leg))
            self._said.add(("alight_next", self.leg))
            ev.append(Event("alight_now", f"Get off now at {l.to_name}.", {}))
        if ("alight_now", self.leg) in self._said and dz <= BOARD_M and speed < RIDING_MPS:
            ev += self._advance()
        return ev
