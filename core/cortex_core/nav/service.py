"""The nav tools (contracts/tools/tools.json) over a bundle, the latest GPS fix and the live trip.

    nav = NavService(Bundle(latest(root)), saved="/var/lib/cortex/nav/saved_places.json", arrivals=gateway_fn)
    nav.on_fix(lat, lon, acc_m, t, speed)  -> [Event]   (follower events; reroutes itself when off route)
    nav.call("search_places", {"query": "northpoint"}) -> Result(data, say)

Every tool returns a Result: `data` (a small JSON-able dict for the LM's tool turn) and, for tools the registry marks
spoken_by "template", `say` (a fixed sentence spoken straight away). Errors are results too (data {"error": ...}):
the LM explains them better than an exception would.

Saved places (home, work...) live only on the box, never in git: {"home": {"name": "Home", "lat": .., "lon": ..}}.
Live bus arrivals come from `arrivals(stop_code, service|None) -> [{"service", "minutes": [..]}]` (the gateway's
LTA proxy); without it, or when it fails, the answer is the published headway, and says so.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from cortex_core.nav import bundle as B
from cortex_core.nav import geo
from cortex_core.nav.follower import Event, Fix, Follower
from cortex_core.nav.places import Places, normalize
from cortex_core.nav.transit import Itinerary, Planner
from cortex_core.nav.walk import Walker

NEAR_STOPS_M = 400.0
FIX_STALE_S = 30.0


@dataclass
class Result:
    data: dict
    say: str | None = None
    events: list[Event] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return "error" not in self.data

    def json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))


def _err(msg: str, say: str | None = None) -> Result:
    return Result({"error": msg}, say)


class NavService:
    def __init__(self, b, saved: str | Path | dict | None = None,
                 arrivals: Callable[[int, str | None], list[dict]] | None = None,
                 clock: Callable[[], float] = time.time, hour: Callable[[], float] | None = None):
        self.b = b
        self.walker = Walker(b)
        self.planner = Planner(b, self.walker)
        self.places = Places(b)
        self.arrivals = arrivals
        self.clock = clock
        self.hour = hour or (lambda: (lambda t: t.tm_hour + t.tm_min / 60)(time.localtime(self.clock())))
        self.saved = self._load_saved(saved)
        self.fix: Fix | None = None
        self.fix_wall = 0.0
        self.matches: dict[str, dict] = {}  # place_id -> {name, x, y}
        self.dest: dict | None = None
        self.trip: Itinerary | None = None
        self.follower: Follower | None = None
        self.reroutes = 0
        self.tools = {
            "search_places": self.search_places, "plan_trip": self.plan_trip,
            "start_navigation": self.start_navigation, "stop_navigation": self.stop_navigation,
            "nav_status": self.nav_status, "nearby_bus_stops": self.nearby_bus_stops,
            "services_at_stop": self.services_at_stop, "bus_arrivals": self.bus_arrivals,
            "gps_accuracy": self.gps_accuracy,
        }

    @staticmethod
    def _load_saved(saved) -> dict:
        if saved is None:
            return {}
        if isinstance(saved, dict):
            raw = saved
        else:
            p = Path(saved)
            raw = json.loads(p.read_text()) if p.is_file() else {}
        out = {}
        for k, v in raw.items():
            x, y = geo.to_xy(float(v["lat"]), float(v["lon"]))
            out[normalize(k)] = {"name": v.get("name") or k.title(), "x": float(x), "y": float(y)}
        return out

    # ---- position
    def on_fix(self, lat: float, lon: float, acc_m: float = 5.0, t: float | None = None,
               speed: float | None = None) -> list[Event]:
        t = self.clock() if t is None else t
        self.fix = Fix.from_latlon(lat, lon, acc_m, t, speed)
        self.fix_wall = self.clock()
        if self.follower is None:
            return []
        ev = self.follower.update(self.fix)
        if any(e.type == "off_route" for e in ev) and self.dest is not None:
            r = self._plan_to(self.dest)
            if r is not None:
                self.reroutes += 1
                self.trip = r
                self.follower = Follower(self.b, r)
                ev.append(Event("rerouted", "New route. " + self._first_step(r), {"summary": r.summary()}))
        if self.follower is not None and self.follower.done:
            self.follower = None
            self.trip = None
            self.dest = None
        return ev

    def _here(self) -> tuple[float, float] | None:
        if self.fix is None or self.clock() - self.fix_wall > FIX_STALE_S:
            return None
        return self.fix.x, self.fix.y

    @property
    def navigating(self) -> bool:
        return self.follower is not None

    def mode_hint(self) -> str | None:
        """What the trip says the mode should be: OUTDOOR_NAV walking, BUS_WATCH at a stop, TRANSIT on board."""
        f = self.follower
        if f is None:
            return None
        l = f.it.legs[f.leg]
        if l.mode == "walk":
            return "OUTDOOR_NAV"
        return "TRANSIT" if ("boarded", f.leg) in f._said else "BUS_WATCH"

    def state_line(self) -> str:
        if self.follower is not None:
            return self.follower.state_line()
        if self.trip is not None:
            return f"nav: trip planned to {self.dest['name']}, not started"
        return ""

    # ---- dispatch
    def call(self, name: str, args: dict) -> Result:
        fn = self.tools.get(name)
        if fn is None:
            return _err(f"no nav tool {name}")
        try:
            return fn(**args)
        except TypeError as e:
            return _err(f"bad arguments for {name}: {e}")

    # ---- tools
    def search_places(self, query: str) -> Result:
        q = normalize(query)
        here = self._here()
        out = []
        for k, v in self.saved.items():
            if q == k or q == normalize(v["name"]):
                pid = f"s_{k.replace(' ', '_')}"
                self.matches[pid] = v
                d = {"place_id": pid, "name": v["name"], "kind": "saved"}
                if here:
                    d["distance_m"] = int(round(float(np.hypot(v["x"] - here[0], v["y"] - here[1])), -1))
                out.append(d)
        x, y = here if here else (None, None)
        for h in self.places.search(query, x, y, limit=3 - len(out) if out else 3):
            d = h.brief()
            self.matches[d["place_id"]] = {"name": h.name, "x": h.x, "y": h.y}
            out.append(d)
        if not out:
            return Result({"matches": [], "note": f"nothing called {query!r} in the map"})
        return Result({"matches": out})

    def _resolve_place(self, place_id: str) -> dict | None:
        pid = str(place_id).strip()
        if pid in self.matches:
            return self.matches[pid]
        if pid.startswith("s_"):
            return self.saved.get(pid[2:].replace("_", " "))
        try:
            i = Places.parse_id(pid)
        except ValueError:
            # the LM passed a name instead of an id: take the best match
            hits = self.places.search(pid, *(self._here() or (None, None)), limit=1)
            return {"name": hits[0].name, "x": hits[0].x, "y": hits[0].y} if hits else None
        if 0 <= i < self.b.n_places:
            return {"name": self.places.name(i), "x": float(self.b.place_x[i]), "y": float(self.b.place_y[i])}
        return None

    def _plan_to(self, dest: dict) -> Itinerary | None:
        here = self._here()
        if here is None:
            return None
        a = self.walker.nearest(*here, max_m=300.0)
        z = self.walker.nearest(dest["x"], dest["y"], max_m=500.0)
        if a < 0 or z < 0:
            return None
        its = self.planner.plan(a, z, hour=self.hour())
        return its[0] if its else None

    def plan_trip(self, place_id: str) -> Result:
        dest = self._resolve_place(place_id)
        if dest is None:
            return _err(f"unknown place {place_id}; search_places first")
        if self._here() is None:
            return _err("no GPS position yet", "I don't have your position yet. Is the phone's location on?")
        here = self._here()
        if self.walker.nearest(*here, max_m=300.0) < 0:
            return _err("you are off the walking map here")
        t = time.perf_counter()
        a = self.walker.nearest(*here, max_m=300.0)
        z = self.walker.nearest(dest["x"], dest["y"], max_m=500.0)
        if z < 0:
            return _err(f"{dest['name']} is off the walking map")
        its = self.planner.plan(a, z, hour=self.hour())
        ms = (time.perf_counter() - t) * 1000
        if not its:
            return _err(f"no route to {dest['name']}")
        self.dest = dest
        self.trip = its[0]
        d = {"to": dest["name"], "summary": its[0].summary(), "best": its[0].brief(), "plan_ms": int(ms)}
        if len(its) > 1:
            d["other"] = [i.summary() for i in its[1:]]
        return Result(d)

    @staticmethod
    def _first_step(it: Itinerary) -> str:
        l = it.legs[0]
        if l.mode == "walk" and l.path is not None and l.path.steps:
            return l.path.steps[0].text
        if l.mode != "walk":
            return f"Wait here for {l.mode} {l.service}."
        return ""

    def start_navigation(self) -> Result:
        if self.trip is None:
            return _err("no trip planned", "There's no trip planned yet. Where do you want to go?")
        self.follower = Follower(self.b, self.trip)
        self.reroutes = 0
        say = f"Starting. {self.trip.summary()} {self._first_step(self.trip)}"
        return Result({"started": True, "to": self.dest["name"] if self.dest else ""}, say.strip())

    def stop_navigation(self) -> Result:
        was = self.follower is not None
        self.follower = None
        self.trip = None
        self.dest = None
        return Result({"stopped": was}, "Navigation stopped." if was else "I wasn't navigating.")

    def nav_status(self) -> Result:
        if self.follower is None:
            return Result({"navigating": False}, "We're not navigating right now.")
        st = self.follower.status()
        st["to"] = self.dest["name"] if self.dest else ""
        if st["mode"] == "walk":
            say = f"{st.get('remaining_m', 0)} metres to {self.follower.it.legs[self.follower.leg].to_name}."
            if "next" in st:
                say += f" Next, {st['next'][0].lower()}{st['next'][1:]} in {st['next_in_m']} metres."
        else:
            say = f"On {st['mode']} {st['service']}: {st['stops_left']} stops to {st['alight']}." if st.get("on_board") \
                else f"Waiting for {st['mode']} {st['service']}."
        if st.get("off_route"):
            say = "You're off the route. " + say
        return Result(st, say)

    def _bus_stops_near(self, x: float, y: float, r: float = NEAR_STOPS_M) -> list[tuple[int, float]]:
        sx, sy = np.asarray(self.b.stop_x), np.asarray(self.b.stop_y)
        d = np.hypot(sx - x, sy - y)
        ids = np.nonzero((d <= r) & (np.asarray(self.b.stop_kind) == B.K_BUS))[0]
        return sorted(((int(i), float(d[i])) for i in ids), key=lambda t: t[1])

    def _services(self, s: int) -> list[str]:
        pats = self.b.sp_pat[self.b.sp_off[s]:self.b.sp_off[s + 1]]
        return sorted({self.b.s(int(self.b.pat_service[p])) for p in pats}, key=lambda v: (len(v), v))

    def nearby_bus_stops(self) -> Result:
        here = self._here()
        if here is None:
            return _err("no GPS position yet")
        near = self._bus_stops_near(*here)[:3]
        return Result({"stops": [{"code": f"{int(self.b.stop_code[s]):05d}", "name": self.b.s(int(self.b.stop_name[s])),
                                  "distance_m": int(round(d, -1)), "services": self._services(s)} for s, d in near]})

    def _resolve_stop(self, stop: str | None) -> int | None:
        stop = (stop or "").strip()
        if not stop:
            here = self._here()
            if here is None:
                return None
            near = self._bus_stops_near(*here)
            return near[0][0] if near else None
        if re.fullmatch(r"\d{4,5}", stop):
            ids = np.nonzero(np.asarray(self.b.stop_code) == int(stop))[0]
            return int(ids[0]) if len(ids) else None
        q = normalize(stop)
        names = [normalize(self.b.s(int(n))) for n in self.b.stop_name]
        cands = [i for i, n in enumerate(names) if q and (n == q or q in n)]
        if not cands:
            return None
        here = self._here()
        if here is not None and len(cands) > 1:
            cands.sort(key=lambda i: np.hypot(self.b.stop_x[i] - here[0], self.b.stop_y[i] - here[1]))
        return cands[0]

    def services_at_stop(self, stop: str = "") -> Result:
        s = self._resolve_stop(stop)
        if s is None:
            return _err(f"no bus stop {stop!r}" if stop else "no bus stop near you")
        return Result({"stop": self.b.stop_label(s), "services": self._services(s)})

    def bus_arrivals(self, service: str = "", stop: str = "") -> Result:
        s = self._resolve_stop(stop)
        if s is None and not stop and self.follower is not None:
            l = self.follower.it.legs[self.follower.leg]
            if l.mode == "bus":
                s, service = l.board_stop, service or l.service
        if s is None:
            return _err("no bus stop near you" if not stop else f"no bus stop {stop!r}",
                        "I can't find a bus stop near you." if not stop else f"I can't find bus stop {stop}.")
        code = int(self.b.stop_code[s])
        svc = service.strip().upper() or None
        label = self.b.s(int(self.b.stop_name[s]))
        if svc and svc not in {v.upper() for v in self._services(s)}:
            return _err(f"bus {svc} does not stop at {label}", f"Bus {svc} doesn't stop at {label}.")
        live = None
        if self.arrivals is not None:
            try:
                live = self.arrivals(code, svc)
            except Exception as e:  # noqa: BLE001 - offline, timeout, bad key: fall back to headways
                live = None
                err = str(e)
        if live:
            parts, data = [], []
            for a in live:
                mins = [max(0, int(m)) for m in a.get("minutes", [])][:2]
                if not mins:
                    continue
                data.append({"service": a["service"], "minutes": mins})
                when = "arriving now" if mins[0] == 0 else f"in {mins[0]} minute{'s' if mins[0] != 1 else ''}"
                nxt = f", then {mins[1]}" if len(mins) > 1 else ""
                parts.append(f"{a['service']} {when}{nxt}")
            if parts:
                return Result({"stop": self.b.stop_label(s), "live": True, "arrivals": data},
                              f"At {label}: " + "; ".join(parts[:3]) + ".")
        # offline: published headways
        band = B.band_of(self.hour())
        pats = self.b.sp_pat[self.b.sp_off[s]:self.b.sp_off[s + 1]]
        hw: dict[str, float] = {}
        for p in pats:
            name = self.b.s(int(self.b.pat_service[p]))
            if svc and name.upper() != svc:
                continue
            h = float(self.b.pat_headway[p, band])
            if h > 0:
                hw[name] = min(hw.get(name, h), h)
        if not hw:
            return _err("no service now", f"No {svc + ' ' if svc else ''}buses at {label} now.")
        items = sorted(hw.items(), key=lambda kv: (len(kv[0]), kv[0]))
        parts = [f"{k} about every {round(v)} minutes" for k, v in items[:3]]
        return Result({"stop": self.b.stop_label(s), "live": False, "headway_min": {k: round(v) for k, v in items}},
                      f"I can't get live times. At {label}, " + "; ".join(parts) + ".")

    def gps_accuracy(self) -> Result:
        if self.fix is None:
            return Result({"fix": False}, "I don't have a GPS position yet.")
        age = self.clock() - self.fix_wall
        acc = int(round(self.fix.acc_m))
        if age > FIX_STALE_S:
            return Result({"fix": False, "age_s": int(age)}, f"I lost GPS {int(age)} seconds ago.")
        q = "good" if acc <= 10 else "fair" if acc <= 25 else "poor"
        return Result({"fix": True, "acc_m": acc, "quality": q}, f"GPS is {q}, about {acc} metres.")
