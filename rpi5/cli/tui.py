"""
Cortex TUI Dashboard - Real-time terminal monitor

Watches a running Cortex system by:
  - Polling psutil for CPU/RAM/temperature/network
  - Tailing logs/cortex.log and parsing detection/STT/Gemini events
  - Detecting whether the main.py process is alive (status & uptime)

Usage:
    from rpi5.cli.tui import run_tui
    run_tui(interval=1.0, log_file="logs/cortex.log")
"""
import os
import re
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

LAYER_META = {
    0: ("Guardian", "YOLO + Depth"),
    1: ("Learner",  "YOLOE"),
    2: ("Thinker",  "Gemini Live"),
    3: ("Guide",    "GPS + Transit"),
    4: ("Memory",   "SQLite+Supa"),
}

STATE_STYLE = {
    "active":  ("●",  "bold green"),
    "ready":   ("●",  "green"),
    "idle":    ("○",  "yellow"),
    "stale":   ("◌",  "dim yellow"),
    "error":   ("✗",  "bold red"),
    "stopped": ("·",  "dim"),
    "unknown": ("?",  "dim"),
}

# Patterns for log event parsing
# L4 fix: previously required `conf=` to be followed by a decimal
# point, so logs emitting integer confidences like `conf=1` were
# silently skipped and the TUI missed the detection. Allow one OR
# more digits, optional decimal.
RE_DETECTION  = re.compile(r'\[L([0-4])\]\s+(\w+)\s+conf=(\d+(?:\.\d+)?)')
RE_SPEECH     = re.compile(r'(?:🎤\s*Speech detected|Transcribed)[^"\']*["\']([^"\']+)["\']')
RE_GEMINI     = re.compile(r'🗣️[^"\']*["\']([^"\']+)["\']')
RE_LAYER      = re.compile(r'\bLayer\s+([0-4])\s+(ready|started|active|init|error|failed)', re.IGNORECASE)
RE_FPS        = re.compile(r'FPS[:=]\s*([\d.]+)')
RE_LATENCY    = re.compile(r'(?:latency|Layer\s*0).*?([\d.]+)\s*ms', re.IGNORECASE)

# Main process signatures — match any of these substrings in cmdline
APP_SIGNATURES = ("rpi5/main.py", "rpi5.main", "cortex.py", "main.py")


def _read_thermal() -> Optional[float]:
    """Read RPi5 CPU temp from /sys/class/thermal/thermal_zone0/temp (°C)."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def _find_cortex_process() -> Optional[psutil.Process]:
    """Return the Cortex main process if running, else None."""
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            joined = " ".join(cmdline)
            if any(sig in joined for sig in APP_SIGNATURES):
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def _bar(pct: float, width: int = 12) -> Text:
    """Render a horizontal bar [████░░░░] 45%"""
    pct = max(0.0, min(100.0, pct))
    fill = int(round(pct / 100 * width))
    bar = "█" * fill + "░" * (width - fill)
    color = "green"
    if pct > 70:
        color = "yellow"
    if pct > 90:
        color = "red"
    return Text.assemble((bar, color), f" {pct:5.1f}%")


class CortexTUI:
    """Live dashboard for a running Cortex system."""

    def __init__(self, log_file: str = "logs/cortex.log", interval: float = 1.0):
        self.log_file = Path(log_file)
        self.interval = interval
        self.console = Console()
        self.events: deque = deque(maxlen=50)
        self.fps_value: Optional[float] = None
        self.yolo_latency_ms: Optional[float] = None
        self.layer_state = {i: "unknown" for i in range(5)}
        self.layer_last_seen: dict[int, float] = {}
        self._stop_event = threading.Event()
        self._log_thread: Optional[threading.Thread] = None
        self._last_log_pos = 0
        self._net_prev: Optional[psutil._common.snetio] = None
        self._net_prev_t: Optional[float] = None
        self._net_rate_up = 0.0
        self._net_rate_down = 0.0
        self._proc: Optional[psutil.Process] = None
        self._start_time = time.time()

    # ---------- main entry ----------
    def run(self) -> int:
        signal.signal(signal.SIGINT, lambda *_: self._stop_event.set())
        self._log_thread = threading.Thread(target=self._tail_log_loop, daemon=True)
        self._log_thread.start()

        layout = self._make_layout()
        try:
            with Live(layout, console=self.console, refresh_per_second=4, screen=True) as live:
                while not self._stop_event.is_set():
                    self._refresh_layout()
                    live.update(layout)
                    self._stop_event.wait(self.interval)
        except Exception:
            # If alt-screen fails (e.g. tiny terminal) fall back to inline
            self.console.print("[yellow]⚠️  Alt-screen unavailable, falling back to inline mode[/]")
            while not self._stop_event.is_set():
                self.console.clear()
                self.console.print(self._render_group())
                self._stop_event.wait(self.interval)
        self.console.print("[dim]Cortex TUI stopped.[/]")
        return 0

    # ---------- background: log tail ----------
    def _tail_log_loop(self):
        while not self._stop_event.is_set():
            try:
                if not self.log_file.exists():
                    self._stop_event.wait(0.5)
                    continue
                size = self.log_file.stat().st_size
                if size < self._last_log_pos:
                    # File was truncated/rotated
                    self._last_log_pos = 0
                if size > self._last_log_pos:
                    with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(self._last_log_pos)
                        chunk = f.read()
                    self._last_log_pos = size
                    for line in chunk.splitlines():
                        self._parse_line(line)
            except Exception:
                pass
            self._stop_event.wait(0.5)

    def _parse_line(self, line: str):
        # Strip Rich/ANSI for matching
        clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
        ts = datetime.now().strftime("%H:%M:%S")

        m = RE_DETECTION.search(clean)
        if m:
            layer, cls, conf = int(m.group(1)), m.group(2), float(m.group(3))
            self.events.appendleft((ts, "detection", f"[L{layer}] {cls} conf={conf:.2f}"))
            return

        m = RE_SPEECH.search(clean)
        if m:
            text = m.group(1)[:60]
            self.events.appendleft((ts, "stt", f"🎤 \"{text}\""))
            return

        m = RE_GEMINI.search(clean)
        if m:
            text = m.group(1)[:80]
            self.events.appendleft((ts, "gemini", f"🗣️ \"{text}\""))
            return

        m = RE_LAYER.search(clean)
        if m:
            layer = int(m.group(1))
            action = m.group(2).lower()
            if action in ("ready", "started", "active"):
                self.layer_state[layer] = "active"
            elif action in ("init",):
                self.layer_state[layer] = "idle"
            elif action in ("error", "failed"):
                self.layer_state[layer] = "error"
            self.layer_last_seen[layer] = time.time()
            return

        m = RE_FPS.search(clean)
        if m:
            self.fps_value = float(m.group(1))
            return

        m = RE_LATENCY.search(clean)
        if m and "ms" in clean.lower():
            try:
                val = float(m.group(1))
                if 1 < val < 1000:
                    self.yolo_latency_ms = val
            except ValueError:
                pass

    # ---------- rendering ----------
    def _make_layout(self) -> Layout:
        root = Layout(name="root")
        root.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=3),
        )
        root["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )
        root["left"].split_column(
            Layout(name="layers", size=11),
            Layout(name="activity", ratio=1),
        )
        root["right"].split_column(
            Layout(name="metrics", size=14),
            Layout(name="network", size=8),
        )
        return root

    def _refresh_layout(self):
        layout = getattr(self, "_active_layout", None)
        if layout is None:
            layout = self._make_layout()
            self._active_layout = layout

        # header
        layout["header"].update(self._render_header())
        # left
        layout["layers"].update(self._render_layers())
        layout["activity"].update(self._render_activity())
        # right
        layout["metrics"].update(self._render_metrics())
        layout["network"].update(self._render_network())
        # footer
        layout["footer"].update(self._render_footer())

    def _render_group(self) -> Group:
        return Group(
            self._render_header(),
            self._render_layers(),
            self._render_metrics(),
            self._render_network(),
            self._render_activity(),
            self._render_footer(),
        )

    def _render_header(self) -> Panel:
        proc = _find_cortex_process()
        status = "[bold green]RUNNING[/]" if proc else "[bold red]STOPPED[/]"
        mode = "[yellow]standalone[/]" if (proc and "standalone" in " ".join(proc.info.get("cmdline") or [])) else "[cyan]connected[/]"
        uptime = "—"
        if proc:
            try:
                uptime = _fmt_uptime(time.time() - proc.info["create_time"])
            except (psutil.NoSuchProcess, KeyError):
                pass

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = Text()
        text.append("⚡ ", style="bold yellow")
        text.append("Asirive Cortex v2.5  ", style="bold white")
        text.append(f"  {status}  ", style="")
        text.append(f"  {mode}  ", style="")
        text.append(f"  ⏱ {uptime}  ", style="dim")
        text.append(f"  🕒 {now}", style="dim")
        return Panel(Align.center(text), box=box.HEAVY, style="white", height=3)

    def _render_layers(self) -> Panel:
        table = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
        table.add_column("L",  width=3,  style="bold")
        table.add_column("State", width=10)
        table.add_column("Name", style="bold")
        table.add_column("Role", style="dim")

        now = time.time()
        for i in range(5):
            name, role = LAYER_META[i]
            state = self.layer_state[i]
            # Demote to "stale" if last seen > 30s
            last = self.layer_last_seen.get(i)
            if last and state == "active" and (now - last) > 30:
                state = "stale"
            sym, style = STATE_STYLE.get(state, STATE_STYLE["unknown"])
            table.add_row(
                f"[{i}]",
                Text.assemble((sym, style), f" {state}"),
                name,
                role,
            )
        return Panel(table, title="[bold]Layers[/]", box=box.ROUNDED, border_style="blue")

    def _render_metrics(self) -> Panel:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        temp = _read_thermal()
        fps = f"{self.fps_value:.1f}" if self.fps_value is not None else "—"
        yolo = f"{self.yolo_latency_ms:.0f}ms" if self.yolo_latency_ms is not None else "—"

        body = Text()
        body.append("FPS    "); body.append_text(_bar(self.fps_value or 0, 16))
        body.append("\n")
        body.append("YOLO   "); body.append(yolo); body.append("\n")
        body.append("CPU    "); body.append_text(_bar(cpu, 16))
        body.append("\n")
        body.append("RAM    "); body.append_text(_bar(mem.percent, 16))
        body.append(f"  {_fmt_bytes(mem.used)}/{_fmt_bytes(mem.total)}")
        body.append("\n")
        body.append("Temp   ")
        if temp is not None:
            tcolor = "green" if temp < 65 else ("yellow" if temp < 75 else "red")
            body.append(f"{temp:.1f}°C", style=tcolor)
        else:
            body.append("n/a", style="dim")
        body.append("\n")
        body.append("Cores  "); body.append(str(psutil.cpu_count(logical=True)))
        body.append("  Load "); body.append(f"{psutil.getloadavg()[0]:.2f}" if hasattr(psutil, "getloadavg") else "n/a")
        return Panel(body, title="[bold]System[/]", box=box.ROUNDED, border_style="green")

    def _render_network(self) -> Panel:
        now = time.time()
        net = psutil.net_io_counters()
        if self._net_prev and self._net_prev_t:
            dt = max(0.001, now - self._net_prev_t)
            self._net_rate_up = (net.bytes_sent - self._net_prev.bytes_sent) / dt
            self._net_rate_down = (net.bytes_recv - self._net_prev.bytes_recv) / dt
        self._net_prev = net
        self._net_prev_t = now

        body = Text()
        body.append("▲ "); body.append(f"{_fmt_bytes(self._net_rate_up)}/s\n", style="cyan")
        body.append("▼ "); body.append(f"{_fmt_bytes(self._net_rate_down)}/s\n", style="magenta")
        body.append("Total sent: "); body.append(f"{_fmt_bytes(net.bytes_sent)}\n", style="dim")
        body.append("Total recv: "); body.append(f"{_fmt_bytes(net.bytes_recv)}", style="dim")
        return Panel(body, title="[bold]Network[/]", box=box.ROUNDED, border_style="magenta")

    def _render_activity(self) -> Panel:
        if not self.events:
            body = Text("Waiting for log events...", style="dim italic")
        else:
            lines = []
            for ts, kind, msg in list(self.events)[:15]:
                color = {"detection": "green", "stt": "cyan", "gemini": "magenta"}.get(kind, "white")
                lines.append(Text.assemble(
                    (f"{ts} ", "dim"),
                    (msg, color),
                ))
            body = Group(*lines)
        return Panel(body, title="[bold]Recent Activity[/]", box=box.ROUNDED, border_style="yellow")

    def _render_footer(self) -> Panel:
        text = Text()
        text.append(" q ", style="bold reverse"); text.append(" quit  ")
        text.append(" r ", style="bold reverse"); text.append(" refresh  ")
        text.append(" c ", style="bold reverse"); text.append(" clear events  ")
        text.append(" s ", style="bold reverse"); text.append(" status  ")
        text.append(" t ", style="bold reverse"); text.append(" test  ")
        text.append(" h ", style="bold reverse"); text.append(" help")
        return Panel(Align.center(text), box=box.HEAVY, style="white", height=3)


def run_tui(interval: float = 1.0, log_file: str = "logs/cortex.log") -> int:
    """Entry point: launch the dashboard."""
    return CortexTUI(log_file=log_file, interval=interval).run()
