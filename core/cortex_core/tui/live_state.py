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
    view: dict = field(default_factory=dict)  # frame_id, refresh_ms, prep/encode/read ms
    views_skipped: int = 0
    last: dict = field(default_factory=dict)  # timings of the last answer
    log: deque = field(default_factory=lambda: deque(maxlen=200))
    mic_dbfs: Optional[float] = None
    camera_frames: int = 0

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
                                            "view_frame_id", "view_age_ms", "speech_ms", "voice") if k in ev}
        elif t == "view":
            if ev.get("skipped"):
                self.views_skipped += 1
            else:
                ms = sum(float(ev.get(k, 0) or 0) for k in ("prep_ms", "encode_ms", "read_ms"))
                self.view = {"frame_id": ev.get("frame_id"), "refresh_ms": ms,
                             **{k: ev[k] for k in ("prep_ms", "encode_ms", "read_ms") if k in ev}}
        elif t == "error":
            self.log.append(f"error: {ev.get('what', '?')}")
