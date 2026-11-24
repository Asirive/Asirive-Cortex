"""Live dev TUI: talk to Cortex through the engine with the real camera and mic.

    space / l   the button: hands-free listening on / off (the VAD finds where questions start and end)
    /           type a question (enter sends, esc leaves the box)
    r           clear the conversation history        q  quit
"""
from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Grid, VerticalScroll
from textual.widgets import Footer, Input, RichLog, Static

from cortex_core.tui.app import _system
from cortex_core.tui.live import LiveSession
from cortex_core.tui.live_state import LiveState
from cortex_core.tui.state import Collector

YELLOW = "#EAFF00"
NL = "\n"


def _ms(v) -> str:
    return "—" if not isinstance(v, (int, float)) else f"{v:.0f} ms"


def conversation(s: LiveState) -> Text:
    t = Text()
    if not s.turns:
        t.append("Press space to start listening, then ask a question out loud." + NL, style="dim")
        t.append("Or press / to type one.", style="dim")
    for turn in s.turns:
        if turn.who == "you":
            t.append("You     ", style=f"bold {YELLOW}")
            t.append(turn.text + NL, style="italic" if turn.text.startswith("(") else "")
        else:
            t.append("Cortex  ", style="bold #7FD4FF")
            t.append(turn.text + ("" if turn.done else " ▌"))
            if turn.note:
                t.append(f"  [{turn.note}]", style="dim")
            t.append(NL)
    return t


def level_bar(dbfs, width: int = 20) -> str:
    if dbfs is None:
        return "no mic data"
    n = max(0, min(width, int((dbfs + 60) / 60 * width)))
    return "█" * n + "·" * (width - n) + f" {dbfs:5.0f} dBFS"


def status(s: LiveState) -> Text:
    t = Text()
    if s.listening:
        t.append(" LISTENING ", style=f"bold #0A0A08 on {YELLOW}")
    else:
        t.append(" listening off ", style="bold on #333330")
    if s.speaking:
        t.append("  ● you are speaking", style=f"bold {YELLOW}")
    elif s.asking:
        t.append("  answering…", style="#7FD4FF")
    t.append(NL + NL)
    t.append(f"Mic     {level_bar(s.mic_dbfs)}{NL}")
    t.append(f"Camera  frame {s.camera_frames}{NL}")
    v = s.view
    if v:
        t.append(f"View    frame {v.get('frame_id')}  refresh {_ms(v.get('refresh_ms'))}  "
                 f"(encode {_ms(v.get('encode_ms'))}, read {_ms(v.get('read_ms'))}){NL}")
    else:
        t.append(f"View    none yet{NL}")
    t.append(f"        still-scene skips {s.views_skipped}")
    return t


def timings(s: LiveState) -> Text:
    d = s.last
    if not d:
        return Text("no answer yet", style="dim")
    t = Text()
    if d.get("voice"):
        t.append(f"Speech end → first word  {_ms(d.get('end_to_first_ms'))}{NL}", style="bold")
        t.append(f"  waiting for last audio {_ms(d.get('wait_ms'))}{NL}")
        t.append(f"  you spoke              {_ms(d.get('speech_ms'))}{NL}")
    t.append(f"First token after start  {_ms(d.get('ttft_ms'))}{NL}")
    t.append(f"Answer total             {_ms(d.get('total_ms'))}  ({d.get('n_out', '?')} tokens){NL}")
    t.append(f"View used                frame {d.get('view_frame_id')}  age {_ms(d.get('view_age_ms'))}")
    return t


class LiveTUI(App):
    CSS_PATH = "live.tcss"
    TITLE = "ASIRIVE CORTEX · LIVE · DEV"
    BINDINGS = [("space", "listen", "listen on/off"), ("l", "listen", ""), ("slash", "type", "type"),
                ("escape", "leave_input", ""), ("r", "reset", "clear history"), ("q", "quit", "quit")]

    def __init__(self, session: LiveSession, collector: Collector):
        super().__init__()
        self.session, self.collector = session, collector

    def compose(self) -> ComposeResult:
        yield Static(self.TITLE, id="title")
        with Grid(id="panels"):
            conv = VerticalScroll(id="conv-box", classes="panel")
            conv.border_title = "CONVERSATION"
            with conv:
                yield Static(id="conv")
            for pid, title in (("status", "STATUS"), ("timings", "LAST ANSWER"), ("system", "SYSTEM")):
                box = VerticalScroll(id=pid + "-box", classes="panel")
                box.border_title = title
                with box:
                    yield Static(id=pid)
        yield Input(placeholder="press / to type a question, enter to send", id="ask")
        log = RichLog(id="log", classes="panel", markup=False)
        log.border_title = "LOG"
        yield log
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#log", RichLog).write("engine ready · space = listening button")
        self.set_interval(0.1, self.redraw)
        self.set_interval(1.0, self.redraw_system)
        self.redraw_system()
        self.screen.set_focus(None)

    def redraw(self) -> None:
        with self.session.lock:
            s = self.session.state
            conv, st, tm = conversation(s), status(s), timings(s)
            new = list(s.log)
            s.log.clear()  # the screen's log owns them now
        self.query_one("#conv", Static).update(conv)
        self.query_one("#conv-box", VerticalScroll).scroll_end(animate=False)
        self.query_one("#status", Static).update(st)
        self.query_one("#timings", Static).update(tm)
        log = self.query_one("#log", RichLog)
        for line in new:
            log.write(line)

    def redraw_system(self) -> None:
        self.query_one("#system", Static).update(_system(self.collector.snapshot()))

    def action_listen(self) -> None:
        self.session.toggle_listening()

    def action_type(self) -> None:
        self.query_one("#ask", Input).focus()

    def action_leave_input(self) -> None:
        self.screen.set_focus(None)

    def action_reset(self) -> None:
        self.session.reset_history()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.session.ask(event.value)
        event.input.value = ""
        self.screen.set_focus(None)
