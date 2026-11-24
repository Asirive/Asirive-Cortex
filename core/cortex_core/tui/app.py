"""Asirive Cortex dev terminal UI: system, engine baseline, NPU and log panels."""
from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.widgets import Footer, RichLog, Static

from cortex_core.tui.state import Collector, Snapshot, fmt

HELP = "q quit · ? help"


def _system(s: Snapshot) -> Text:
    hot = max(s.temps_c.items(), key=lambda kv: kv[1]) if s.temps_c else None
    t = Text()
    t.append(f"CPU load   {fmt(None if s.cpu_load is None else s.cpu_load * 100, '%', 0)}\n")
    t.append(f"RAM used   {fmt(s.mem_used_mb, 'MB', 0)}\n")
    t.append(f"Hottest    {fmt(hot[1] if hot else None, '°C')}" + (f"  ({hot[0]})" if hot else "") + "\n")
    t.append(f"Power      {fmt(s.power_w, 'W', 2)}")
    return t


def _ms(m: dict) -> str:
    return "n/a" if not m or m.get("median") is None else f"{m['median']:.2f} s"


def _engine(s: Snapshot) -> Text:
    b = s.baseline
    if not b:
        return Text("no baseline yet\nrun: python -m cortex_core.engine.bench …")
    meta = b.get("meta", {})
    t = Text(f"{meta.get('backend', '?')} · {meta.get('model', '?')}\n\n", style="bold")
    for cid, c in (b.get("cases") or {}).items():
        if c.get("unsupported"):
            t.append(f"{cid}: unsupported ({c['unsupported'][:60]})\n")
            continue
        decode = (c.get("decode_tps") or {}).get("median")
        ok = {True: "over 1 s", False: "< 1 s", None: "n/a"}[c.get("over_target")]
        t.append(f"{cid}: first token {_ms(c.get('ttft_s'))} · first audio {_ms(c.get('ttfa_s'))} · "
                 f"decode {fmt(decode, 'tok/s')} · {ok}\n")
    return t


def _npu(s: Snapshot) -> Text:
    n = s.npu
    if not n:
        return Text("not probed yet\nrun: python -m cortex_core.engine.npu_probe --out …")
    t = Text("Reachable: " + ("YES" if n.get("reachable") else "no") + "\n", style="bold")
    for note in n.get("notes") or []:
        t.append(f"· {note}\n")
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
            for pid, title in (("system", "SYSTEM"), ("engine", "ENGINE · LFM3-OMNI"), ("npu", "NPU")):
                p = Static(id=pid, classes="panel")
                p.border_title = title
                yield p
            log = RichLog(id="log", classes="panel", markup=False)
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
