"""What the live TUI shows, built from engine events: the conversation, the current view and the last timings.
Pure (no engine, no Textual), so it is unit-tested; the live session calls apply() for every event."""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

# a think block, closed or still streaming (the model emits <think>, the text, </think> as separate tokens)
THINK = re.compile(r"<think>.*?(</think>|$)", re.S)


@dataclass
class Turn:
    who: str  # "you" or "cortex"
    text: str = ""
    done: bool = False
    note: str = ""
    raw: str = ""  # the answer as streamed, think tags included


@dataclass
class LiveState:
    max_turns: int = 40
    turns: deque = field(default_factory=deque)
    speaking: bool = False
    listening: bool = False
    asking: bool = False
    talking: bool = False  # Cortex's voice is coming out
    muted: bool = False    # the engine drops the mic while Cortex talks
    view: dict = field(default_factory=dict)  # frame_id, refresh_ms, prep/encode/read ms
    views_skipped: int = 0
    last: dict = field(default_factory=dict)  # timings of the last answer
    log: deque = field(default_factory=lambda: deque(maxlen=200))
    mic_dbfs: Optional[float] = None
    camera_frames: int = 0
    # the agent harness (brain), when it hosts the turns
    mode: str = ""
    nav_line: str = ""
    tools: deque = field(default_factory=lambda: deque(maxlen=6))  # "name(args) -> result  12 ms"
    cue: str = ""
    gps: dict = field(default_factory=dict)  # last fix: lat, lon, acc_m, age reference t

    def _add(self, t: Turn) -> Turn:
        self.turns.append(t)
        while len(self.turns) > self.max_turns:
            self.turns.popleft()
        return t

    def _answer(self) -> Turn:
        """The answer being streamed (a new one if the last turn is not an open answer)."""
        if self.turns and self.turns[-1].who == "cortex" and not self.turns[-1].done:
            return self.turns[-1]
        for t in reversed(self.turns):  # an answer still open behind the user's new speech (barge-in)
            if t.who == "cortex" and not t.done:
                return t
        return self._add(Turn("cortex"))

    def typed(self, question: str) -> None:
        self._add(Turn("you", question, done=True))

    def apply(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "speech_start":
            self.speaking = True
            self._add(Turn("you", "(speaking…)"))
        elif t == "speech_end":
            self.speaking = False
            for turn in reversed(self.turns):
                if turn.who == "you" and not turn.done:
                    turn.text, turn.done = f"(spoke {ev.get('speech_ms', 0) / 1000:.1f} s)", True
                    break
        elif t == "token":
            a = self._answer()
            a.raw += str(ev.get("text", ""))
            a.text = THINK.sub("", a.raw).lstrip()
        elif t == "done":
            a = self._answer()
            a.done = True
            if ev.get("cancelled"):
                a.note = "cut off"
            elif ev.get("stop") == "max":
                a.note = "max tokens"
            if not a.text and not ev.get("cancelled"):
                a.text = "(no answer)"
            self.last = {k: ev[k] for k in ("ttft_ms", "end_to_first_ms", "wait_ms", "n_out", "total_ms",
                                            "view_frame_id", "view_age_ms", "speech_ms", "voice", "frames",
                                            "frame_ms", "codec_ms", "sound_ms", "end_to_sound_ms") if k in ev}
        elif t == "sound_start":
            self.talking = self.muted = True
            if "end_to_sound_ms" in ev:
                self.last["end_to_sound_ms"] = ev["end_to_sound_ms"]
        elif t == "sound_end":
            self.talking = self.muted = False  # the engine keeps the mic off ~300 ms longer (the room's tail)
            self.last.update({"sound_ms": ev.get("sound_ms"), "gaps": ev.get("gaps"), "cut": ev.get("cut")})
        elif t == "view":
            if ev.get("skipped"):
                self.views_skipped += 1
            else:
                ms = sum(float(ev.get(k, 0) or 0) for k in ("prep_ms", "encode_ms", "read_ms"))
                self.view = {"frame_id": ev.get("frame_id"), "refresh_ms": ms,
                             **{k: ev[k] for k in ("prep_ms", "encode_ms", "read_ms") if k in ev}}
        elif t == "error":
            self.log.append(f"error: {ev.get('what', '?')}")

    def brain(self, kind: str, data: dict) -> None:
        """Events from Brain.on_event (tokens and done go through apply)."""
        if kind == "mode":
            self.mode = data.get("to", "")
            self.log.append(f"mode {data.get('from')} -> {data.get('to')}")
        elif kind == "state":
            line = data.get("line", "")
            self.nav_line = line
            m = re.search(r"mode=(\w+)", line)
            if m:
                self.mode = m.group(1)
        elif kind == "tool_run":
            args = ", ".join(f"{k}={v!r}" for k, v in (data.get("args") or {}).items())
            res = data.get("error") or data.get("say") or _short(data.get("result"))
            flag = " (checking)" if data.get("checking") else ""
            self.tools.append(f"{data.get('name')}({args}) -> {res}  {data.get('ms', 0):.0f} ms{flag}")
        elif kind == "nav":
            self.cue = data.get("text", "")
            self.log.append(f"nav {data.get('type')}: {self.cue}")
        elif kind == "said":
            self.log.append(f"said: {data.get('text')}")
        elif kind == "camera":
            self.log.append("camera " + ("on" if data.get("on") else "off"))
        elif kind == "gps":
            self.gps = dict(data)
        elif kind == "error":
            self.log.append(f"error: {data.get('what', '?')}")


def _short(v, n: int = 60) -> str:
    import json
    s = json.dumps(v, ensure_ascii=False, separators=(",", ":")) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 1] + "…"
