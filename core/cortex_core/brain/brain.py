"""The Brain: the engine (LFM3-Omni), the nav service and the modes, joined by the tool dispatcher.

    brain = Brain(engine, nav)          # engine: cortex_core.engine.native.Engine (or a fake with the same methods)
    brain.ask("when is bus 858 coming") # typed question: drives the answer through any tool calls; returns a Turn
    brain.voice_event(ev)               # every event from engine.next_voice(): spoken questions are driven the same way
    brain.on_fix(lat, lon, acc_m, t)    # GPS: follower cues are spoken, modes follow the trip, the state line updates
    brain.vision_s                      # camera cadence for the current mode (None: only when the user talks)

on_event(kind, data): "token"/"done" (the LM's text after a tool result, and typed answers), "tool_call", "tool_run",
"mode", "state", "nav", "said", "camera", "error". Voice events the host fed in through voice_event are not echoed.

Dispatch (spec 6.2): parse -> validate -> mode check -> run. Tools taking longer than CHECKING_S get "Checking."
spoken first. spoken_by "template" results are spoken as a fixed sentence (ce_tool_result with say); "lm" results go
back to the LM, which answers or calls again (chains up to MAX_CHAIN calls). A malformed call gets one error result
so the LM can try again; a second one ends the turn with "Sorry, I couldn't do that."
Cues (nav events) wait for the running turn to end, except urgent ones (get off now, off route), which cut it.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable

from cortex_core.brain import prompt
from cortex_core.brain import tools as T
from cortex_core.brain.modes import ModeMachine

CHECKING_S = 0.7
MAX_CHAIN = 4
SORRY = "Sorry, I couldn't do that."
URGENT = {"alight_now", "off_route"}
BRAIN_TOOLS = {"set_mode", "camera"}


@dataclass
class ToolRun:
    name: str
    args: dict
    result: dict
    say: str | None
    ms: float
    checking: bool = False
    error: str | None = None


@dataclass
class Turn:
    text: str = ""
    calls: list[ToolRun] = field(default_factory=list)
    done: dict = field(default_factory=dict)
    voice: bool = False
    said: str | None = None  # a template sentence that ended the turn


class Brain:
    def __init__(self, engine, nav=None, registry: T.Registry | None = None,
                 on_event: Callable[[str, dict], None] | None = None, checking_s: float = CHECKING_S):
        self.eng = engine
        self.nav = nav
        self.reg = registry or T.load()
        self.on_event = on_event or (lambda kind, data: None)
        self.checking_s = checking_s
        self.modes = ModeMachine(self._mode_changed)
        self.camera_on = True
        self.turn_lock = threading.RLock()
        self.cues: deque[str] = deque()
        self._state = None
        self._voice_call: str | None = None
        self._voice_turn: Turn | None = None
        self.last_turn: Turn | None = None
        self._update_state()

    # ------------------------------------------------------------------ modes and state
    @property
    def mode(self) -> str:
        return self.modes.mode

    def _mode_changed(self, old: str, new: str) -> None:
        self.on_event("mode", {"from": old, "to": new})
        self._update_state()

    def _update_state(self) -> None:
        line = prompt.state_line(self.mode, self.nav.state_line() if self.nav is not None else "")
        if line != self._state:
            self._state = line
            self.eng.set_state(line)
            self.on_event("state", {"line": line})

    def _follow_trip(self) -> None:
        """The mode the trip says (walking, at the stop, on board), or IDLE when it ended."""
        if self.nav is None:
            return
        hint = self.nav.mode_hint()
        if hint is None:
            if self.mode in ("OUTDOOR_NAV", "BUS_WATCH", "TRANSIT"):
                self.modes.force("IDLE")
        elif not (self.mode == "INDOOR_NAV" and hint == "OUTDOOR_NAV"):  # inside a station: the user said so
            self.modes.force(hint)

    # ------------------------------------------------------------------ asking
    def ask(self, text: str, max_tokens: int = 0) -> Turn:
        with self.turn_lock:
            t = Turn()
            self._drive(self.eng.ask(text, max_tokens), t)
            self.last_turn = t
        self._flush_cues()
        return t

    def voice_event(self, ev: dict) -> Turn | None:
        """Feed every event from engine.next_voice(). Returns the Turn when a spoken question has been answered."""
        typ = ev.get("type")
        if typ == "tool_call" and ev.get("voice"):
            self._voice_call = ev["text"]
            self.on_event("tool_call", {"text": ev["text"], "voice": True})
            return None
        if typ == "token" and ev.get("voice"):
            if self._voice_turn is None:
                self._voice_turn = Turn(voice=True)
            self._voice_turn.text += ev["text"]  # the host already has this event (it fed it in): no on_event
            return None
        if typ == "done" and ev.get("voice"):
            t = self._voice_turn or Turn(voice=True)
            self._voice_turn = None
            t.done = ev
            call, self._voice_call = self._voice_call, None
            if call is not None:
                with self.turn_lock:
                    malformed = [0]
                    nxt = self._handle_call(call, t, malformed)
                    self._drive(nxt, t, depth=1, malformed=malformed)
            self.last_turn = t
            self._flush_cues()
            return t
        return None

    def _drive(self, it: Iterable[dict], t: Turn, depth: int = 0, malformed: list[int] | None = None) -> None:
        malformed = malformed if malformed is not None else [0]
        while True:
            call = None
            for ev in it:
                typ = ev.get("type")
                if typ == "token":
                    t.text += ev["text"]
                    self.on_event("token", ev)
                elif typ == "tool_call":
                    call = ev["text"]
                    self.on_event("tool_call", {"text": call})
                elif typ == "done":
                    t.done = ev
                    if not ev.get("tool"):
                        self.on_event("done", ev)
                elif typ == "error":
                    t.done = {"error": ev.get("what")}
                    self.on_event("error", ev)
            if call is None:
                return
            depth += 1
            if depth > MAX_CHAIN:
                t.said = SORRY
                it = self.eng.tool_result(json.dumps({"error": "too many tool calls"}), SORRY)
                continue
            it = self._handle_call(call, t, malformed)

    # ------------------------------------------------------------------ dispatch
    def _handle_call(self, text: str, t: Turn, malformed: list[int]) -> Iterable[dict]:
        """Runs one call; returns the engine's tool_result iterator (the LM's next step)."""
        calls = T.parse_calls(text)
        err = None
        call = None
        if not calls:
            err = "could not read the tool call"
        else:
            try:
                call = self.reg.validate(calls[0])
            except T.ToolError as e:
                err = str(e)
        if err is not None:
            malformed[0] += 1
            run = ToolRun(calls[0].name if calls else "?", calls[0].args if calls else {}, {"error": err}, None, 0.0,
                          error=err)
            t.calls.append(run)
            self.on_event("tool_run", run.__dict__)
            if malformed[0] >= 2:
                t.said = SORRY
                return self.eng.tool_result(json.dumps({"error": err}), SORRY)
            return self.eng.tool_result(json.dumps({"error": err + "; call the tool again correctly"}), None)
        tool = self.reg.get(call.name)
        if not tool.allowed_in(self.mode):
            res, say = {"error": f"{call.name} is not available in {self.mode} mode"}, None
            run = ToolRun(call.name, call.args, res, None, 0.0, error=res["error"])
            t.calls.append(run)
            self.on_event("tool_run", run.__dict__)
            return self.eng.tool_result(json.dumps(res), None)
        run = self._run_tool(call)
        t.calls.append(run)
        self.on_event("tool_run", run.__dict__)
        self._follow_trip()
        self._update_state()
        say = run.say if tool.spoken_by == "template" and run.say else None
        if say is not None:
            t.said = say
        return self.eng.tool_result(json.dumps(run.result, ensure_ascii=False, separators=(",", ":")), say)

    def _run_tool(self, call: T.Call) -> ToolRun:
        box: dict = {}

        def work():
            try:
                box["r"] = self._exec(call)
            except Exception as e:  # noqa: BLE001 - a broken tool must not kill the turn
                box["r"] = ({"error": f"{call.name} failed: {e}"}, None)

        t0 = time.monotonic()
        th = threading.Thread(target=work, name=f"tool-{call.name}", daemon=True)
        th.start()
        th.join(self.checking_s)
        checking = th.is_alive()
        if checking:
            for _ in self.eng.say("Checking."):
                pass
            th.join()
        res, say = box["r"]
        return ToolRun(call.name, call.args, res, say, (time.monotonic() - t0) * 1000, checking,
                       res.get("error") if isinstance(res, dict) else None)

    def _exec(self, call: T.Call) -> tuple[dict, str | None]:
        if call.name == "set_mode":
            nav_on = self.nav is not None and self.nav.navigating
            ch = self.modes.request(call.args["mode"], nav_on, self.nav.mode_hint() if nav_on else None)
            r = {"mode": ch.mode, "changed": ch.ok}
            if not ch.ok:
                r["error"] = ch.reason
            return r, ch.say
        if call.name == "camera":
            self.camera_on = bool(call.args["on"])
            self.on_event("camera", {"on": self.camera_on})
            return {"camera": self.camera_on}, "Camera on." if self.camera_on else "Camera off."
        if self.nav is None:
            return {"error": "navigation is not running"}, "Navigation isn't available right now."
        r = self.nav.call(call.name, call.args)
        return r.data, r.say

    # ------------------------------------------------------------------ GPS and cues
    def on_fix(self, lat: float, lon: float, acc_m: float = 5.0, t: float | None = None,
               speed: float | None = None) -> list:
        if self.nav is None:
            return []
        evs = self.nav.on_fix(lat, lon, acc_m, t, speed)
        self._follow_trip()
        self._update_state()
        for e in evs:
            self.on_event("nav", {"type": e.type, "text": e.text})
            self.cue(e.text, urgent=e.type in URGENT)
        return evs

    def cue(self, text: str, urgent: bool = False) -> None:
        """Speak a nav cue now if nothing is being said, else after the running turn (urgent: cut it)."""
        if urgent and not self.turn_lock.acquire(blocking=False):
            self.eng.cancel()
            self.cues.appendleft(text)
            return
        if not urgent and not self.turn_lock.acquire(blocking=False):
            self.cues.append(text)
            return
        try:
            self._say(text)
        finally:
            self.turn_lock.release()
        self._flush_cues()

    def _flush_cues(self) -> None:
        while self.cues and self.turn_lock.acquire(blocking=False):
            try:
                text = self.cues.popleft()
                self._say(text)
            finally:
                self.turn_lock.release()

    def _say(self, text: str) -> None:
        for ev in self.eng.say(text):
            if ev.get("type") == "error":
                self.on_event("error", ev)
        self.on_event("said", {"text": text})

    # ------------------------------------------------------------------ vision
    @property
    def vision_s(self) -> float | None:
        """Seconds between camera views in this mode; None: only when the user talks (or the camera is off: never)."""
        return self.modes.vision_s if self.camera_on else None
