"""Automatic object memory: when to scan the current view, what a scan stores, and recall (search_memory).

    m = Memory(Store(), looker=engine_looker(engine), where=nav.where)
    if m.wants_scan(view_event, idle=brain_is_idle):   # the brain calls this for every view event
        m.scan(view_event)                             # runs the LM's silent look; [] if cut short
    m.search("my keys") -> (data, None)                # the search_memory tool (the LM phrases the answer)

looker(prompt, max_tokens) -> text, or None when the look was cut short or failed (nothing is stored then).
where() -> {"name", "lat", "lon", "acc_m"} or None (the newest fresh GPS fix and its named place).
Scans never start the camera: they read only views the engine already has. See
docs/superpowers/specs/2026-11-26-memory-design.md for the rules and the load budget.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

from cortex_core.memory import items as I
from cortex_core.memory import look as L
from cortex_core.memory.store import Store

log = logging.getLogger(__name__)


def ago(dt: float) -> str:
    dt = max(0.0, dt)
    if dt < 60:
        return "just now"
    if dt < 3600:
        m = max(1, round(dt / 60))
        return f"about {m} minute{'s' * (m != 1)} ago"
    if dt < 86400:
        h = max(1, round(dt / 3600))
        return f"about {h} hour{'s' * (h != 1)} ago"
    if dt < 2 * 86400:
        return "about a day ago"
    return f"{int(dt // 86400)} days ago"


def engine_looker(engine) -> Callable[[str, int], str | None] | None:
    """The engine's silent look (ce_peek), or None when this engine build cannot peek."""
    if not getattr(engine, "can_peek", False):
        return None

    def look(prompt: str, max_tokens: int) -> str | None:
        text = ""
        for ev in engine.peek(prompt, max_tokens):
            typ = ev.get("type")
            if typ == "token":
                text += ev.get("text", "")
            elif typ == "error":
                return None
            elif typ == "done" and ev.get("cancelled"):
                return None
        return text

    return look


class Memory:
    MIN_GAP_S = 30.0
    BUDGET_N = 10
    BUDGET_S = 600.0
    MAX_TOKENS = 60

    def __init__(self, store: Store, looker: Callable[[str, int], str | None] | None = None,
                 where: Callable[[], dict | None] | None = None, clock: Callable[[], float] = time.time):
        self.store = store
        self.looker = looker
        self.where = where
        self.clock = clock
        self._lock = threading.Lock()
        self._starts: deque[float] = deque()
        self._last_frame = None
        self._last_t = float("-inf")

    @property
    def can_learn(self) -> bool:
        return self.looker is not None

    def wants_scan(self, ev: dict, idle: bool) -> bool:
        if self.looker is None or not idle or ev.get("type") != "view" or ev.get("skipped"):
            return False
        now = self.clock()
        with self._lock:
            while self._starts and now - self._starts[0] >= self.BUDGET_S:
                self._starts.popleft()
            return (ev.get("frame_id") != self._last_frame and now - self._last_t >= self.MIN_GAP_S
                    and len(self._starts) < self.BUDGET_N)

    def scan(self, ev: dict) -> list[L.Seen]:
        if self.looker is None:
            return []
        now = self.clock()
        with self._lock:
            self._starts.append(now)
            self._last_frame = ev.get("frame_id")
            self._last_t = now
        cat = I.catalogue(self.store)
        text = self.looker(L.prompt(cat), self.MAX_TOKENS)
        if text is None:
            return []
        seen = L.parse(cat, text)
        if not seen:
            return []
        place = self._where()
        t = self.clock()
        for s in seen:
            self.store.record(s.item, t, s.looks, s.spot, place.get("name"), place.get("lat"), place.get("lon"),
                              place.get("acc_m"))
        return seen

    def _where(self) -> dict:
        if self.where is None:
            return {}
        try:
            return self.where() or {}
        except Exception:  # noqa: BLE001 - a nav fault must not lose the sighting
            log.exception("memory: where() failed")
            return {}

    def search(self, item: str) -> tuple[dict, str | None]:
        cat = I.catalogue(self.store)
        it = I.match(cat, item)
        if it is None:
            names = ", ".join(i.name for i in cat)
            return {"error": f"'{item}' is not an item I remember. I remember: {names}. "
                             "Other items can be added in the app."}, None
        rows = self.store.sightings(it.name)
        if not rows:
            return {"item": it.name, "seen": False}, None
        now = self.clock()
        last = rows[0]
        data = {"item": it.name, "seen": True}
        for k in ("spot", "place"):
            if last[k]:
                data[k] = last[k]
        data["ago"] = ago(now - last["t"])
        if last["looks"]:
            data["looks"] = last["looks"]
        for r in rows[1:]:
            if (r["place"], r["spot"]) != (last["place"], last["spot"]):
                b = {k: r[k] for k in ("spot", "place") if r[k]}
                b["ago"] = ago(now - r["t"])
                data["before"] = b
                break
        return data, None
