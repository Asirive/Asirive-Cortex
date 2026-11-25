"""Cortex's modes (code owns them; the LM can only ask).

| Mode        | Entered when                                   | Vision (s) | Unprompted speech               |
| IDLE        | start, trip done, stop_navigation              | on talk    | none                            |
| OUTDOOR_NAV | start_navigation; off the bus / out of station | 2          | instructions, arrived           |
| BUS_WATCH   | at the boarding stop                           | 1          | bus coming / here               |
| TRANSIT     | on the bus / train                             | off        | next stop, get off              |
| INDOOR_NAV  | the user says they are inside                  | 1          | indoor cues                     |
| EXPLORE     | the user asks                                  | 1          | describes until told to stop    |
"""
from __future__ import annotations

from dataclasses import dataclass

MODES = ("IDLE", "OUTDOOR_NAV", "BUS_WATCH", "TRANSIT", "INDOOR_NAV", "EXPLORE")
NAV_MODES = ("OUTDOOR_NAV", "BUS_WATCH", "TRANSIT", "INDOOR_NAV")

# what code may move between (nav events, trip start / end, user requests)
LEGAL = {
    "IDLE": {"OUTDOOR_NAV", "BUS_WATCH", "INDOOR_NAV", "EXPLORE"},
    "OUTDOOR_NAV": {"IDLE", "BUS_WATCH", "TRANSIT", "INDOOR_NAV", "EXPLORE"},
    "BUS_WATCH": {"IDLE", "OUTDOOR_NAV", "TRANSIT", "INDOOR_NAV"},
    "TRANSIT": {"IDLE", "OUTDOOR_NAV", "BUS_WATCH", "INDOOR_NAV"},
    "INDOOR_NAV": {"IDLE", "OUTDOOR_NAV", "BUS_WATCH", "TRANSIT", "EXPLORE"},
    "EXPLORE": {"IDLE", "OUTDOOR_NAV", "BUS_WATCH", "TRANSIT", "INDOOR_NAV"},
}
VISION_S = {"IDLE": None, "OUTDOOR_NAV": 2.0, "BUS_WATCH": 1.0, "TRANSIT": None, "INDOOR_NAV": 1.0, "EXPLORE": 1.0}


@dataclass
class Change:
    ok: bool
    mode: str
    say: str
    reason: str = ""


class ModeMachine:
    def __init__(self, on_change=None):
        self.mode = "IDLE"
        self.before_explore: str | None = None
        self.on_change = on_change or (lambda old, new: None)

    def _set(self, new: str) -> None:
        old, self.mode = self.mode, new
        if old != new:
            self.on_change(old, new)

    def force(self, new: str) -> bool:
        """A code-driven move (nav events, trip start/end). Illegal moves are refused, never raised."""
        if new == self.mode:
            return True
        if new not in LEGAL.get(self.mode, ()):
            return False
        if self.mode == "EXPLORE" and new in NAV_MODES:
            self.before_explore = new  # the trip moved on while exploring: come back to where it is now
            return True
        self._set(new)
        return True

    def request(self, new: str, navigating: bool, nav_mode: str | None = None) -> Change:
        """The user (through the LM's set_mode) asks for a mode."""
        new = new.strip().upper()
        if new not in MODES:
            return Change(False, self.mode, f"I don't have a {new.lower()} mode.", "unknown mode")
        if new in ("BUS_WATCH", "TRANSIT"):
            return Change(False, self.mode, "That follows the trip by itself.", "set by the trip")
        if new == self.mode:
            return Change(True, self.mode, _SAY_SAME.get(new, "Already on."))
        if new == "EXPLORE":
            self.before_explore = self.mode
            self._set("EXPLORE")
            return Change(True, "EXPLORE", "Exploring. I'll describe what's around you.")
        if new == "IDLE":
            if self.mode == "EXPLORE":
                back = nav_mode if navigating and nav_mode else (self.before_explore or "IDLE")
                if navigating and back == "IDLE":
                    back = nav_mode or "OUTDOOR_NAV"
                self.before_explore = None
                self._set(back)
                return Change(True, back, "Stopped exploring." + (" Back to the trip." if navigating else ""))
            if navigating:
                return Change(False, self.mode, "We're on a trip. Say stop navigation to end it.", "navigating")
            self._set("IDLE")
            return Change(True, "IDLE", "Okay.")
        if new == "OUTDOOR_NAV":
            if not navigating:
                return Change(False, self.mode, "There's no trip yet. Where do you want to go?", "no trip")
            self._set(nav_mode or "OUTDOOR_NAV")
            return Change(True, self.mode, "Outdoor guidance on.")
        if new == "INDOOR_NAV":
            if new not in LEGAL[self.mode]:
                return Change(False, self.mode, "Not right now.", "illegal")
            self._set("INDOOR_NAV")
            return Change(True, "INDOOR_NAV", "Okay, indoor mode. I'll watch for gantries, escalators and doors.")
        return Change(False, self.mode, "Not right now.", "illegal")

    @property
    def vision_s(self) -> float | None:
        return VISION_S[self.mode]


_SAY_SAME = {"EXPLORE": "Already exploring.", "IDLE": "Okay.", "INDOOR_NAV": "Already in indoor mode.",
             "OUTDOOR_NAV": "Already guiding you."}
