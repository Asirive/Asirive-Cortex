"""Asirive Cortex dev terminal UI: system, engine baseline, NPU and log panels."""
from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Grid, VerticalScroll
from textual.widgets import Footer, RichLog, Static

from cortex_core.tui.state import Collector, Snapshot, fmt

HELP = "q quit · ? help"
NL = "\n"


def _system(s: Snapshot) -> Text:
    hot = max(s.temps_c.items(), key=lambda kv: kv[1]) if s.temps_c else None
    t = Text()
    t.append(f"CPU load   {fmt(None if s.cpu_load is None else s.cpu_load * 100, '%', 0)}{NL}")
    t.append(f"RAM used   {fmt(s.mem_used_mb, 'MB', 0)}{NL}")
    t.append(f"Hottest    {fmt(hot[1] if hot else None, '°C')}" + (f"  ({hot[0]})" if hot else "") + NL)
    t.append(f"Power      {fmt(s.power_w, 'W', 2)}")
    return t


def _num(v: object) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _med(c: dict, key: str) -> Optional[float]:
    m = c.get(key)
    return _num(m.get("median")) if isinstance(m, dict) else None


def _s(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.2f}s"


def _engine(s: Snapshot) -> Text:
    """Baseline table, at most 74 columns per line; any odd JSON shape degrades, never crashes."""
    b = s.baseline
    if not b:
        return Text("no baseline yet" + NL + "run: python -m cortex_core.engine.bench ...")
    try:
        meta = b.get("meta") if isinstance(b.get("meta"), dict) else {}
        cases = b.get("cases") if isinstance(b.get("cases"), dict) else {}
        t = Text(f"{meta.get('backend', '?')} · {meta.get('model', '?')}"[:72] + NL, style="bold")
        t.append(f"{'case':<20} {'1st tok':>8} {'1st aud':>8} {'decode':>10}  < 1 s{NL}", style="#EAFF00")
        for cid, c in cases.items():
            name = str(cid)[:20]
            if not isinstance(c, dict):
                t.append(f"{name:<20} unreadable{NL}")
                continue
            if isinstance(c.get("unsupported"), str):
                t.append(f"{name:<20} unsupported: {c['unsupported'][:38]}{NL}")
                continue
            dec = _med(c, "decode_tps")
            dec_s = "n/a" if dec is None else f"{dec:.1f} t/s"
            if c.get("no_audio") is True:
                verdict = "no audio"
            else:
                verdict = {True: "over", False: "yes"}.get(c.get("over_target"), "n/a")
            t.append(f"{name:<20} {_s(_med(c, 'ttft_s')):>8} {_s(_med(c, 'ttfa_s')):>8} {dec_s:>10}  {verdict}{NL}")
        return t
    except Exception:
        return Text("baseline file unreadable")


def _npu(s: Snapshot) -> Text:
    n = s.npu
    if not n:
        return Text("not probed yet" + NL + "run: python -m cortex_core.engine.npu_probe --out ...")
    t = Text("Reachable: " + ("YES" if n.get("reachable") is True else "no") + NL, style="bold")
    notes = n.get("notes")
    for note in notes if isinstance(notes, list) else []:
        if isinstance(note, str):
            t.append(f"· {note}{NL}")
    return t


class CortexTUI(App):
    CSS_PATH = "app.tcss"
    TITLE = "ASIRIVE CORTEX · DEV"
    BINDINGS = [("q", "quit", "quit"), ("question_mark", "help", "help")]

    def __init__(self, collector: Collector, refresh_s: float = 1.0):
        super().__init__()
        self.collector, self.refresh_s = collector, refresh_s

    def compose(self) -> ComposeResult:
        yield Static(self.TITLE, id="title")
        with Grid(id="panels"):
            for pid, title, extra in (("system", "SYSTEM", ""), ("npu", "NPU", ""),
                                      ("engine", "ENGINE · LFM3-OMNI", " wide")):
                box = VerticalScroll(classes="panel" + extra, id=pid + "-box")
                box.border_title = title
                with box:
                    yield Static(id=pid)
            log = RichLog(id="log", classes="panel wide", markup=False)
            log.border_title = "LOG"
            yield log
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#log", RichLog).write("Cortex dev UI started")
        self.refresh_panels()
        self.set_interval(self.refresh_s, self.refresh_panels)

    def refresh_panels(self) -> None:
        s = self.collector.snapshot()
        self.query_one("#system", Static).update(_system(s))
        self.query_one("#engine", Static).update(_engine(s))
        self.query_one("#npu", Static).update(_npu(s))

    def action_help(self) -> None:
        self.query_one("#log", RichLog).write("Keys: " + HELP)
