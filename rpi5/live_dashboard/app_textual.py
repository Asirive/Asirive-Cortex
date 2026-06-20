"""
FULL mode dashboard for Asirive Cortex — Textual-based TUI.

The "NICE" dashboard. 6 panels + log viewer + header/footer, dark theme,
sparklines, progress bars, and animations. Built on Textual 8.x.

Why Textual:
  - Real widget system (DataTable, Sparkline, ProgressBar, RichLog)
  - CSS-like styling for consistent look across terminals
  - Asyncio render loop — only diffs changed regions, so 1Hz refresh
    is cheap even over slow SSH
  - Built-in key bindings via BINDINGS class
  - Built-in focus management (Tab/Shift+Tab)
  - save_screenshot() for headless design iteration
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, List, Optional

from rich.panel import Panel
from rich.text import Text
# rich.sparkline doesn't exist in Rich 14.3.3 (only in newer Rich);
# we render a tiny inline sparkline from block characters below.
# from rich.sparkline import Sparkline  # not in Rich 14.x
from rich.progress_bar import ProgressBar
from rich.table import Table

try:
    from textual.app import App
    from textual.widgets import Header, Footer, Static, RichLog
    from textual.containers import Container, Vertical, Horizontal
    from textual import on
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False
    App = None

from rpi5.live_dashboard.state import DashboardState
from rpi5.live_dashboard.keybinds import FOOTER_HINTS_FULL


# Pulse state for the "● connected" indicator. Toggles on every
# refresh tick (2Hz) so connected things appear to breathe. Tied to a
# counter that increments on every refresh; the render uses it to
# pick ● vs ◉.
class PulseState:
    def __init__(self):
        self._tick = 0
        self._lock = threading.Lock()
    def tick(self) -> int:
        with self._lock:
            self._tick = (self._tick + 1) % 2
            return self._tick
    def get(self) -> int:
        with self._lock:
            return self._tick


PULSE = PulseState()


# 8-level block sparkline. Lower unicode block chars give a smoother curve
# at small widths; for dashboards we only need ~30 cells of history so
# this is plenty.
_SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def render_sparkline(values, width: int = 30, color: str = "green") -> Text:
    """Render a simple sparkline using unicode block characters.

    Each value is normalized to 0..7 and mapped to a block char. NaN /
    None values render as space.

    M3 fix: a constant series (all values the same) used to render as
    a blank line because (v - lo) / (hi - lo) = 0/1 = 0, which maps
    to the first _SPARK_CHARS entry (a space). Now we render the
    midpoint char (▄) so the user can see "yes, this is data" even
    when the value is steady.
    """
    if not values:
        return Text(" " * width, style="dim")
    # Take the last `width` samples, downsampling if needed
    if len(values) > width:
        # Simple stride-based downsample: pick every Nth value
        stride = len(values) / width
        sampled = [values[int(i * stride)] for i in range(width)]
    else:
        sampled = list(values)
    lo = min((v for v in sampled if v is not None), default=0)
    hi = max((v for v in sampled if v is not None), default=1)
    constant = (hi == lo)
    if constant:
        # Render as a midpoint char so the panel still shows "live data"
        out = Text()
        for v in sampled:
            if v is None:
                out.append(" ")
            else:
                out.append(_SPARK_CHARS[4], style=color)  # ▄ — middle
        return out
    out = Text()
    for v in sampled:
        if v is None:
            out.append(" ")
            continue
        idx = int((v - lo) / (hi - lo) * 7)
        idx = max(0, min(7, idx))
        out.append(_SPARK_CHARS[idx], style=color)
    return out


if TEXTUAL_AVAILABLE:

    class CortexFullApp(App):
        """The Textual-based FULL mode dashboard.

        Usage:
            app = CortexFullApp(state, system)
            app.run()  # blocks
            app.cleanup()
        """

        CSS_PATH = "style.tcss"
        TITLE = "Asirive Cortex"
        SUB_TITLE = "FULL mode (Textual)"

        BINDINGS = [
            ("q", "quit_app", "Quit"),
            ("ctrl+c", "quit_app", "Quit"),
            ("b", "toggle_rec", "Record"),
            ("m", "mute_tts", "Mute TTS"),
            ("r", "ask_cortex", "Ask"),
            ("g", "ask_cortex", "Ask"),
            ("s", "save_log", "Save log"),
            ("k", "copy_logs", "Copy logs"),
            ("?", "show_help", "Help"),
            ("p", "toggle_pause", "Pause"),
        ]

        def __init__(self, state: DashboardState, system: Any):
            super().__init__()
            self.dashboard_state = state
            self.system = system
            self._paused = False
            self._refresh_count = 0

        def compose(self):
            yield Header(show_clock=True)
            with Container(id="outer"):
                with Container(id="body"):
                    # Top section: left column (detection, sensors) + big
                    # layer2 panel spanning the remaining width and full
                    # height. Textual's Grid can't cell-span, so we use
                    # nested Horizontal/Vertical containers instead.
                    with Horizontal(id="top-row"):
                        with Vertical(id="left-col"):
                            yield Static(id="detection")
                            yield Static(id="sensors")
                        yield Static(id="layer2")
                    # Bottom row: 3 equal-width panels
                    with Horizontal(id="bottom-row"):
                        yield Static(id="system")
                        yield Static(id="tts")
                        yield Static(id="memory")
                # Unified activity feed (full-width timeline above logs)
                yield Static(id="activity")
                # max_lines caps the buffer so the log doesn't grow
                # unbounded; wrap=True so long log lines actually wrap
                # into the panel width instead of overflowing horizontally
                # (which made them look like a single line on top). 200
                # lines x ~1s polling = ~3 minutes of scrollable history.
                yield RichLog(id="log", highlight=True, markup=True,
                              wrap=True, max_lines=200)
            yield Footer()

        def on_mount(self) -> None:
            # Textual owns the screen now (alt screen buffer). Any stderr
            # handler would leak around the TUI. The __main__.py now passes
            # file_only=True to setup_logging for FULL mode, so this is a
            # defensive cleanup in case the app is used standalone.
            self._suppress_stderr_logging()

            # Initial render
            self._refresh_all()
            # Refresh loop: 2Hz — half the latency of 1Hz for activity feed
            # events (the previous 1s lag was the "activity not reacting
            # fast enough" complaint). 2Hz is still cheap on the Pi.
            self._refresh_timer = self.set_interval(0.5, self._refresh_all)
            # Also start a log watcher that pushes to the RichLog
            self._start_log_watcher()

        def _suppress_stderr_logging(self) -> None:
            """Remove any stderr/stdout-bound handlers from the root logger
            so log records only go to the file. The file is tailed by the
            LogFileWatcher into the in-TUI log panel."""
            import logging
            import sys
            try:
                from rich.logging import RichHandler
            except ImportError:
                RichHandler = None
            root = logging.getLogger()
            for h in list(root.handlers):
                # Drop RichHandlers (they write to a console stream)
                if RichHandler is not None and isinstance(h, RichHandler):
                    root.removeHandler(h)
                    continue
                # Drop any StreamHandler pointing at stderr or stdout.
                # M30 fix: Rich wraps sys.stderr in a Console object,
                # so `stream is sys.stderr` was always False and
                # the RichHandler leaked through to the alt screen.
                # Use a name-based + class-based match to catch
                # Console-wrapped streams too.
                stream = getattr(h, "stream", None)
                if stream is None:
                    continue
                if stream is sys.stderr or stream is sys.stdout:
                    root.removeHandler(h)
                    continue
                # Console-wrapped stream — check by class name.
                cls_name = type(stream).__name__
                if cls_name in ("Console", "ConsoleFileProxy"):
                    root.removeHandler(h)
                    continue
                # Check wrapped console's file (Rich Console stores
                # the original in `.file`).
                underlying = getattr(stream, "file", None)
                if underlying is sys.stderr or underlying is sys.stdout:
                    root.removeHandler(h)

        def _start_log_watcher(self) -> None:
            from rpi5.live_dashboard.log_watcher import LogFileWatcher
            self._log_watcher = LogFileWatcher(
                log_path="logs/cortex.log",
                on_line=self._on_log_line,
                poll_interval_s=0.2,
                # Only show NEW lines from this point forward — otherwise
                # the panel dumps the entire previous session's log on
                # startup and you get an uncontrollable scroll.
                start_at_end=True,
            )
            self._log_watcher.start()

        def _on_log_line(self, line: str) -> None:
            # Called from a non-Textual thread; use call_from_thread
            self.call_from_thread(self._write_log, line)

        def _write_log(self, line: str) -> None:
            log = self.query_one("#log", RichLog)
            log.write(self._colorize_log(line))

        def _colorize_log(self, line: str) -> Text:
            # Add level icon and colorize the level
            icon = "◯"
            style = "dim white"
            if "WARNING" in line:
                icon, style = "⚠", "yellow"
            elif "ERROR" in line:
                icon, style = "✗", "bold red"
            elif "CRITICAL" in line or "FATAL" in line:
                icon, style = "⛔", "bold white on red"
            t = Text()
            t.append(f"{icon} ", style=style)
            t.append(line)
            return t

        def _refresh_all(self) -> None:
            # Always update the title bar so PAUSED / MUTED indicators
            # are visible even when panel updates are skipped.
            self._update_subtitle()

            if self._paused:
                return
            PULSE.tick()
            snap = self.dashboard_state.snapshot()
            hist = self.dashboard_state.history()
            for panel_id in ("detection", "layer2", "sensors", "system", "tts", "memory", "activity"):
                try:
                    panel = self.query_one(f"#{panel_id}", Static)
                    panel.update(self._render_panel(panel_id, snap, hist))
                except Exception as e:
                    # Log the error so the operator knows a panel is broken
                    # instead of silently going stale.
                    try:
                        self._write_log(f"[red]panel {panel_id} render error: {e}[/]")
                    except Exception:
                        pass
            self._refresh_count += 1

        def _update_subtitle(self) -> None:
            """Show PAUSED / MUTED state in the title bar so the keybinds
            feel responsive — without this, pressing `p` or `m` is silent."""
            try:
                parts = ["FULL mode (Textual)"]
                if self._paused:
                    parts.append("PAUSED — press p to resume")
                tts_snap = self.dashboard_state.snapshot().get("tts", {}) if self.dashboard_state else {}
                if tts_snap.get("muted", False):
                    parts.append("MUTED — press m to unmute")
                self.sub_title = "  ·  ".join(parts)
            except (AttributeError, TypeError):
                pass

        # --- panel renderers ---

        def _render_panel(self, panel_id: str, snap: dict, hist: dict) -> Panel:
            renderers = {
                "detection": self._render_detection,
                "layer2": self._render_layer2,
                "sensors": self._render_sensors,
                "system": self._render_system,
                "tts": self._render_tts,
                "memory": self._render_memory,
                "activity": self._render_activity,
            }
            try:
                return renderers[panel_id](snap, hist)
            except Exception as e:
                return Panel(f"[red]render error: {e}[/red]", title=panel_id)

        def _dot(self, ok: bool) -> str:
            return ("●" if ok else "○") if PULSE.get() == 0 else ("◉" if ok else "○")

        def _render_detection(self, snap: dict, hist: dict) -> Panel:
            content = Text()
            # L0
            l0 = snap["l0_count"]
            l0_lat = snap["l0_latency_ms"]
            l0_lat_color = "green" if l0_lat < 50 else "yellow" if l0_lat < 100 else "red"
            content.append(f"L0 Guardian  {self._dot(l0 >= 0)} ", style="bold")
            content.append(f"{l0:>2} obj ", style="bold")
            content.append(f"{l0_lat:.0f}ms", style=l0_lat_color)
            bar = self._latency_bar(l0_lat, 100.0)
            content.append("  ")
            content.append(bar)
            content.append("\n")
            l0_classes = ", ".join(snap["l0_classes"][:5]) or "—"
            content.append(f"  ▸ {l0_classes}\n", style="cyan")
            # L1
            l1 = snap["l1_count"]
            l1_lat = snap["l1_latency_ms"]
            l1_mode = snap.get("l1_mode", "")
            # M69 fix: L1 is laptop-only — on the Pi (standalone) the
            # YOLOE NCNN backend segfaults, so we disable L1 in config.
            # When l1_mode is empty, show a clear "laptop only" hint
            # instead of "0 obj 0ms" which made it look like the
            # detector was running but finding nothing.
            if not l1_mode:
                content.append("L1 Learner   ○ ", style="dim")
                content.append("laptop only\n", style="dim")
                content.append("  ▸ (runs on paired laptop, not on Pi)\n", style="dim")
            else:
                content.append(f"L1 Learner   {self._dot(l1 >= 0)} ")
                content.append(f"{l1:>2} obj ")
                content.append(f"{l1_lat:.0f}ms")
                bar1 = self._latency_bar(l1_lat, 100.0)
                content.append("  ")
                content.append(bar1)
                content.append("\n")
                l1_classes = ", ".join(snap["l1_classes"][:5]) or "—"
                mode_str = f" [{l1_mode}]" if l1_mode else ""
                content.append(f"  ▸ {l1_classes}{mode_str}\n", style="magenta")
            # Hailo + safety
            hailo_state = snap["hailo"].get("hailo_state", "none")
            hailo_fps = snap['hailo']['depth_fps']
            hailo_color = "green" if hailo_fps > 0.5 else ("yellow" if hailo_state == "running" else "red")
            if hailo_fps > 0.5:
                content.append(f"Hailo {hailo_fps:.0f}fps  ", style=hailo_color)
            else:
                # Show the state so the operator knows WHY it's 0
                state_label = {
                    "running": "starting…",
                    "init_failed": "init failed",
                    "no_runtime": "no runtime",
                    "not_initialized": "off",
                }.get(hailo_state, "off")
                content.append(f"Hailo {state_label}  ", style=hailo_color)
            content.append(f"OCR {snap['hailo']['ocr_state']}  ", style="dim")
            safety = snap["safety"]
            tier = safety.get("tier", 0)
            tier_color = "green" if tier == 0 else "yellow" if tier <= 2 else "bold red"
            content.append(f"T0:{safety.get('t0',0)} T1:{safety.get('t1',0)} T2:{safety.get('t2',0)}\n", style=tier_color)
            # 60s alert rate
            alert_rate = int(safety.get("alerts_last_60s", 0))
            if alert_rate > 0:
                rate_color = "green" if alert_rate < 5 else "yellow" if alert_rate < 15 else "red"
                content.append(f"alerts 60s: {alert_rate}\n", style=rate_color)

            # AI routing indicator
            ai = snap.get("ai", {})
            ai_active = bool(ai.get("active", False))
            ai_last = ai.get("last_call", "")
            ai_color = "magenta" if ai_active else "cyan"
            ai_str = "CLOUD" if ai_active else "local"
            content.append(f"AI route · {ai_str}", style=f"bold {ai_color}")
            if ai_last:
                content.append(f"  ({ai_last})", style="dim")
            content.append("\n")

            # Scene change + button (NEW: fill empty space)
            scene = snap.get("scene", {})
            scene_ts = float(scene.get("last_change_ts", 0))
            scene_type = scene.get("last_change_type", "")
            btn = snap.get("button", {})
            btn_ts = float(btn.get("last_press_ts", 0))
            btn_type = btn.get("last_press_type", "")
            now = time.time()
            content.append("─" * 22 + "\n", style="dim")
            if scene_ts > 0 and (now - scene_ts) < 300:
                age = int(now - scene_ts)
                age_str = f"{age}s" if age < 60 else f"{age // 60}m"
                content.append(f"scene · {scene_type or 'change'} ", style="cyan")
                content.append(f"{age_str} ago\n", style="dim")
            if btn_ts > 0 and (now - btn_ts) < 300:
                age = int(now - btn_ts)
                age_str = f"{age}s" if age < 60 else f"{age // 60}m"
                icon = "⏺" if btn_type == "long" else "●"
                content.append(f"button · {btn_type or 'press'} {icon} ", style="yellow")
                content.append(f"{age_str} ago\n", style="dim")

            # FPS + L0 latency sparklines (single line each)
            fps_hist = hist.get("fps", [])
            if len(fps_hist) >= 3:
                avg = sum(fps_hist) / len(fps_hist) if fps_hist else 0
                color = "green" if avg >= 15 else "yellow" if avg >= 5 else "red"
                content.append("FPS  ")
                content.append(render_sparkline(fps_hist, width=18, color=color))
                content.append(f" {avg:.0f}\n", style=color)
            l0_hist = hist.get("l0_latency_ms", [])
            if len(l0_hist) >= 3:
                content.append("L0ms ")
                content.append(render_sparkline(l0_hist, width=18, color="cyan"))
                content.append("\n")

            # Recent safety alerts (last 3 — full)
            safety_recent = snap.get("safety_recent", [])
            if safety_recent:
                content.append("─" * 22 + "\n", style="dim")
                for entry in safety_recent[-3:]:
                    age_s = now - float(entry.get("ts", 0))
                    age_str = f"{int(age_s)}s" if age_s < 60 else f"{int(age_s/60)}m"
                    t = int(entry.get("tier", 0))
                    typ = entry.get("type", "?")[:12]
                    d = float(entry.get("distance_m", 0))
                    icon = "⛔" if t == 0 else "⚠" if t <= 2 else "›"
                    style = "red" if t == 0 else "yellow" if t <= 2 else "dim"
                    content.append(f"  {icon} {typ:>12} {d:.1f}m {age_str}\n", style=style)

            return Panel(content, title="[bold cyan]DETECTION · L0/L1[/]", border_style="blue", padding=(0, 1))

        @staticmethod
        def _latency_bar(value_ms: float, target_ms: float = 100.0, width: int = 10) -> str:
            """Render a small horizontal latency bar: [████░░░░░░] 47ms."""
            ratio = min(value_ms / target_ms, 1.5)  # cap at 1.5x
            filled = int(ratio * width)
            filled = max(0, min(width, filled))
            empty = width - filled
            color = "green" if value_ms < 50 else "yellow" if value_ms < 100 else "red"
            from rich.text import Text as _T
            t = _T()
            t.append("[" )
            t.append("█" * filled, style=color)
            t.append("░" * empty, style="dim")
            t.append("]")
            return t

        def _render_layer2(self, snap: dict, hist: dict) -> Panel:
            """CLOUD AI panel — Gemini Live is the dominant feature.
            Latest response is a prominent box; full conversation flows below;
            latency, tools, mic, and audio state fill the rest."""
            l2 = snap.get("l2", {}) or {}
            # Three-state display: connected / reconnecting / disconnected.
            # The reconnecting case fires when handler.is_connected is False
            # but the manager is still trying (so the panel no longer
            # flashes red between turns).
            state = l2.get("state") or ("connected" if l2.get("connected") else "disconnected")
            if state == "connected":
                connected, state_color, state_label = True, "green", "connected"
            elif state == "reconnecting":
                connected, state_color, state_label = True, "yellow", "reconnecting"
            else:
                connected, state_color, state_label = False, "red", "disconnected"
            content = Text()

            # --- Row 1: status header (one compact line) ---
            content.append(f"Gemini Live  {self._dot(connected)} ", style="bold")
            content.append(f"{state_label}  ", style=state_color)
            if l2.get("uptime_s", 0):
                content.append(f"up {l2['uptime_s']:.0f}s  ", style="dim")
            tools = l2.get("tool_calls", 0)
            searches = l2.get("google_searches", 0)
            content.append(f"tools:{tools}  search:{searches}\n", style="dim")

            # --- Row 2: model + voice + lang + rate (one line) ---
            content.append(f"model · ", style="dim")
            content.append(f"{l2.get('model', '?')}\n", style="cyan")
            content.append(f"voice · ", style="dim")
            content.append(f"{l2.get('voice', '?')}", style="magenta")
            content.append(f"  lang · ", style="dim")
            content.append(f"{l2.get('lang', '?')}", style="cyan")
            content.append(f"  rate · 24kHz\n", style="dim")

            # --- Audio state + VU meter ---
            audio_q = l2.get("audio_queue_size", 0)
            playing = l2.get("is_playing", False)
            vad = l2.get("vad_active", False)
            speaking_icon = "🔊 SPEAKING" if playing else "○ idle"
            content.append(f"audio q · {audio_q}  ", style="dim")
            content.append(f"{speaking_icon}", style="bold green" if playing else "dim")
            content.append(f"   VAD {self._dot(vad)} ", style="dim")
            content.append("active\n" if vad else "idle\n", style="green" if vad else "dim")

            # Mic VU meter (live audio level)
            vu = l2.get("audio_input_level", 0.0)
            vu_str = self._vu_meter(vu, width=40)
            content.append("mic ")
            content.append(vu_str)
            content.append(f"  {vu*100:.0f}%\n", style="dim")

            # --- PROMINENT LATEST RESPONSE (the headline) ---
            content.append("─" * 60 + "\n", style="dim")
            content.append("  CORTEX SAID\n", style="bold magenta")
            last_said = l2.get("last_said", "").strip()
            if last_said:
                # Word-wrap to ~65 chars per line for readability
                wrapped = self._wrap_text(last_said, width=65)
                for i, line in enumerate(wrapped):
                    if i == 0:
                        content.append(f"  ┌─ ", style="dim magenta")
                    else:
                        content.append(f"  │  ", style="dim magenta")
                    content.append(f"{line}\n", style="bold white on #1a0033")
                content.append(f"  └─\n", style="dim magenta")
            else:
                content.append("  (waiting for first response...)\n", style="dim")

            # Last heard (user's last utterance)
            last_heard = l2.get("last_heard", "").strip()
            if last_heard:
                content.append(f"  YOU   →  ", style="dim")
                content.append(f"\"{self._truncate(last_heard, 60)}\"\n", style="cyan")

            # --- Conversation history (more turns now that logs are smaller) ---
            content.append("─" * 60 + "\n", style="dim")
            content.append("Conversation\n", style="bold")
            transcript = l2.get("transcript", [])
            # 4 turns keeps the panel tight while still showing context
            last_turns = transcript[-4:] if transcript else []
            for line in last_turns:
                # M32 fix: normalize shape. Producers should publish
                # strings prefixed "YOU:" or "CORTEX:"; if anything
                # else (dict, None, etc.) sneaks in, render as a
                # placeholder rather than crash on .startswith().
                if not isinstance(line, str):
                    content.append(f"  (unparsed entry: {type(line).__name__})\n", style="dim")
                    continue
                if line.startswith("YOU:"):
                    content.append("  YOU    →  ", style="bold cyan")
                    content.append(f"{self._truncate(line[4:].strip(), 58)}\n", style="white")
                elif line.startswith("CORTEX:"):
                    content.append("  CORTEX →  ", style="bold green")
                    content.append(f"{self._truncate(line[7:].strip(), 58)}\n", style="white")
                else:
                    content.append(f"  {self._truncate(line, 64)}\n", style="dim")
            if not transcript:
                content.append("  (no conversation yet)\n", style="dim")

            # --- Tool call history (last 1, super compact) ---
            tool_log = l2.get("tool_call_log", [])
            if tool_log:
                content.append("─" * 60 + "\n", style="dim")
                entry = tool_log[-1]
                name = entry.get("name", "?")
                result = entry.get("result_preview", "")
                content.append(f"  ⚙ {name}", style="bold magenta")
                content.append(f" → {self._truncate(result, 60)}\n", style="white")

            # --- L2 latency stats (one line, no sparkline — saves space) ---
            l2_lat = l2.get("latency_ms", {})
            avg = float(l2_lat.get("avg", 0))
            p95 = float(l2_lat.get("p95", 0))
            ttfb = float(l2_lat.get("ttfb", 0))
            content.append("─" * 60 + "\n", style="dim")
            content.append(f"L2 lat  ", style="dim")
            content.append(f"avg {avg:.0f}ms  ", style="green" if avg < 600 else "yellow" if avg < 1000 else "red")
            content.append(f"p95 {p95:.0f}ms  ", style="green" if p95 < 1000 else "yellow" if p95 < 1500 else "red")
            content.append(f"ttfb {ttfb:.0f}ms\n", style="green" if ttfb < 300 else "yellow" if ttfb < 600 else "red")

            return Panel(content, title="[bold magenta]CLOUD AI · Gemini Live[/]", border_style="magenta", padding=(0, 1))

        @staticmethod
        def _truncate(text: str, width: int) -> str:
            """Truncate text to `width` chars with ellipsis if needed."""
            if not text:
                return ""
            if len(text) <= width:
                return text
            return text[:width - 1] + "…"

        @staticmethod
        def _wrap_text(text: str, width: int = 65) -> list:
            """Simple word-wrap. Returns list of lines."""
            if not text:
                return [""]
            words = text.split()
            lines = []
            current = ""
            for word in words:
                if not current:
                    current = word
                elif len(current) + 1 + len(word) <= width:
                    current += " " + word
                else:
                    lines.append(current)
                    current = word
            if current:
                lines.append(current)
            return lines if lines else [""]

        @staticmethod
        def _vu_meter(level: float, width: int = 40) -> Text:
            """Render a VU meter (audio input level) using block characters.

            level: 0.0..1.0
            """
            t = Text()
            filled = int(max(0, min(1, level)) * width)
            for i in range(width):
                if i < filled:
                    # Color based on level
                    if i < width * 0.6:
                        t.append("█", style="green")
                    elif i < width * 0.85:
                        t.append("█", style="yellow")
                    else:
                        t.append("█", style="red")
                else:
                    t.append("░", style="dim")
            return t

        def _render_sensors(self, snap: dict, hist: dict) -> Panel:
            content = Text()
            gps = snap.get("gps", {}) or {}
            imu = snap.get("imu", {}) or {}
            bt = snap.get("bt", {}) or {}
            env = snap.get("environment", "unknown")
            env_color = "cyan" if env == "indoor" else "yellow" if env == "outdoor" else "dim"

            # GPS — compact, 1 line
            gps_fix = int(gps.get("fix", 0) or 0)
            gps_ok = gps_fix > 0
            content.append(f"GPS  {self._dot(gps_ok)} ", style="bold")
            if gps_ok:
                content.append(f"FIX:{gps_fix}  {int(gps.get('sats', 0) or 0)}sats", style="green")
                if gps.get("lat") and gps.get("lon"):
                    content.append(f"  {float(gps['lat']):.4f},{float(gps['lon']):.4f}", style="dim")
            else:
                content.append(f"NO FIX [{env}]", style=env_color)
            content.append("\n")
            # IMU — compact, 1 line
            imu_cal = imu.get("cal", [0, 0, 0, 0]) or [0, 0, 0, 0]
            imu_enabled = imu.get("enabled", True)
            imu_ok = any(int(c or 0) > 0 for c in imu_cal) if imu_enabled else False
            cal = imu_cal
            content.append(f"IMU  {self._dot(imu_ok)} ", style="bold")
            if not imu_enabled:
                content.append("off (disabled in config)\n", style="dim")
            else:
                content.append(f"hdg {float(imu.get('heading', 0) or 0):.0f}°  S{cal[0]}G{cal[1]}A{cal[2]}M{cal[3]}\n")
            # BT — compact, 1 line. Be forgiving: if the publisher hasn't
            # sent BT state yet (e.g. on first frame before the sensor
            # block runs), show a neutral "—" instead of "disconnected"
            # so the operator doesn't think Bluetooth is broken.
            content.append(f"BT   {self._dot(bt.get('connected', False))} ", style="bold")
            if bt.get("connected"):
                bat = f"{bt.get('battery_pct', -1)}%" if int(bt.get("battery_pct", -1) or -1) >= 0 else ""
                eb = (bt.get("earbuds", "") or bt.get("device", "")) or "—"
                content.append(f"{eb}  {bat}\n", style="green")
            elif bt.get("device") or bt.get("earbuds"):
                # Paired but not currently connected — surface the device
                # name so the operator knows what to reconnect.
                eb = (bt.get("earbuds", "") or bt.get("device", "")) or "—"
                content.append(f"{eb} (not connected)\n", style="yellow")
            else:
                content.append("not paired\n", style="dim")
            # Hailo + camera — combined on 1 line (was 2 in v6; combined to make
            # room for the new Power render in v7)
            content.append(f"Hailo ", style="bold")
            content.append(self._dot(snap['hailo']['depth_fps'] > 0))
            content.append(f" {snap['hailo']['depth_fps']:.0f}fps  ", style="dim")
            content.append(f"OCR {snap['hailo']['ocr_state']}  ", style="dim")
            cam = snap.get("camera", {})
            cam_avail = bool(cam.get("available", False))
            backend = (cam.get("backend", "") or "?")[:8]
            fps_t = float(cam.get("fps_target", 0))
            content.append(f"CAM {self._dot(cam_avail)} {backend} {fps_t:.0f}fps\n", style="dim")

            # Divider
            content.append("─" * 26 + "\n", style="dim")

            # System metrics + load (1 line, was 2 in v6)
            sys_m = snap.get("system", {})
            cpu = float(sys_m.get("cpu_percent", 0))
            ram_pct = float(sys_m.get("ram_percent", 0))
            ram_used = int(sys_m.get("ram_used_mb", 0))
            ram_total = int(sys_m.get("ram_total_mb", 0)) or 1
            temp_c = float(sys_m.get("cpu_temp_c", 0))
            load1 = float(sys_m.get("load_avg_1m", 0))
            cpu_color = "green" if cpu < 60 else "yellow" if cpu < 85 else "red"
            temp_color = "green" if temp_c < 65 else "yellow" if temp_c < 78 else "red"
            mem_color = "green" if ram_pct < 70 else "yellow" if ram_pct < 90 else "red"
            content.append("CPU ")
            content.append(f"{cpu:>3.0f}%", style=cpu_color)
            content.append(f"  T ", style="dim")
            content.append(f"{temp_c:>4.1f}°C", style=temp_color)
            content.append(f"  MEM ", style="dim")
            content.append(f"{ram_pct:>3.0f}%", style=mem_color)
            content.append(f"  L {load1:.2f}\n", style="dim")

            # Power / UPS state (NEW: "how long until this thing dies?")
            # 2 lines: bar+pct+voltage+watts, then status/runtime.
            power = snap.get("power", {})
            if power and power.get("available", False):
                pct = float(power.get("battery_pct", -1))
                voltage_v = float(power.get("voltage_v", 0.0))
                power_w = float(power.get("power_w", 0.0))
                charging = bool(power.get("charging", False))
                time_rem_s = int(power.get("time_remaining_s", -1))
                low_batt = bool(power.get("low_battery", False))
                # Color the battery pct by zone
                if pct < 0:
                    pct_color = "dim"
                elif low_batt:
                    pct_color = "bold red"
                elif pct < 30:
                    pct_color = "yellow"
                elif pct < 80:
                    pct_color = "green"
                else:
                    pct_color = "bold green"
                # Battery bar (8 cells — fits the panel width)
                bar_w = 8
                if pct >= 0:
                    filled = int((pct / 100.0) * bar_w)
                    filled = max(0, min(bar_w, filled))
                    bar = "█" * filled + "░" * (bar_w - filled)
                else:
                    bar = "?" * bar_w
                charge_icon = "⚡" if charging else "  "
                # Line 1: bar + pct + voltage + power (compact, 1 row)
                content.append(f"POW {charge_icon} {bar} ", style=pct_color)
                content.append(f"{pct:>3.0f}% ", style=pct_color)
                content.append(f"{voltage_v:.2f}V", style="dim")
                if power_w > 0:
                    content.append(f" {power_w:.1f}W", style="dim")
                content.append("\n")
                # Line 2: status + runtime (or low-battery warning)
                if low_batt:
                    content.append("     ⚠ LOW BATTERY — plug in soon\n", style="bold red")
                elif charging and time_rem_s > 0:
                    content.append(f"     charging · full in {self._fmt_duration(time_rem_s)}\n", style="cyan")
                elif time_rem_s > 0:
                    content.append(f"     discharging · {self._fmt_duration(time_rem_s)} left\n", style="dim")
                else:
                    content.append(f"     {'charging' if charging else 'discharging'}\n", style="dim")

            return Panel(content, title="[bold green]SENSORS · SYSTEM[/]", border_style="green", padding=(0, 1))

        @staticmethod
        def _fmt_duration(seconds: float) -> str:
            """Format seconds as '1h 23m', '12m 34s', or '45s'."""
            s = int(seconds)
            if s < 60:
                return f"{s}s"
            if s < 3600:
                return f"{s // 60}m {s % 60}s"
            return f"{s // 3600}h {(s % 3600) // 60}m"

        def _render_system(self, snap: dict, hist: dict) -> Panel:
            """NAV-centric panel. The NavMode is the dominant feature —
            the user said 'for navigation, it has to be the mode'."""
            content = Text()
            nav = snap["nav"]
            mode = nav.get("mode", "idle")
            state = nav.get("state", "inactive")
            destination = nav.get("destination", "")
            next_instr = nav.get("next_instruction", "")
            wp_idx = int(nav.get("waypoint_index", 0))
            wp_total = int(nav.get("total_waypoints", 0))
            d_waypoint = float(nav.get("distance_to_waypoint_m", 0))
            d_dest = float(nav.get("distance_to_destination_m", 0))
            leg_type = nav.get("current_leg_type", "")
            leg_distance = float(nav.get("current_leg_distance_m", 0))
            leg_duration = float(nav.get("current_leg_duration_s", 0))
            leg_instr = nav.get("current_leg_instruction", "")

            # 1. MODE BADGE — large, color-coded, pulsing
            mode_info = {
                "idle":     ("○", "IDLE",      "dim"),
                "outdoor":  ("◉", "OUTDOOR",   "bold green"),
                "indoor":   ("▣", "INDOOR",    "cyan"),
                "bus_stop": ("◐", "BUS STOP",  "yellow"),
                "transit":  ("⚌", "TRANSIT",   "bold magenta"),
            }
            sym, label, color = mode_info.get(mode, ("?", mode.upper(), "white"))
            content.append("  ")
            content.append(f"{sym} ", style=color)
            content.append(f"{label}", style=color)
            state_color = "green" if state == "navigating" else "yellow" if state in ("loading_route", "paused", "waiting_for_bus", "on_vehicle") else "red" if state == "error" else "dim"
            content.append(f"  · {state}\n", style=state_color)

            # 2. Destination + instruction (1 line each)
            if destination:
                content.append(f"  → {destination[:22]}\n", style="bold white")
            instr = next_instr or leg_instr
            if instr:
                content.append(f"    {instr[:42]}\n", style="white")

            # 3. Active leg + transit (compact, 1-2 lines)
            if leg_type and state == "navigating":
                leg_icon = {"walking": "→", "bus": "🚌", "mrt": "🚇"}.get(leg_type, "•")
                mins = int(leg_duration // 60)
                dist_str = self._fmt_dist(leg_distance)
                content.append(f"  {leg_icon} {leg_type:>7} ", style="cyan")
                content.append(f"{dist_str}  {mins}min\n", style="dim")
                # Transit-specific
                if leg_type in ("bus", "mrt"):
                    svc = nav.get("transit_service_no", "")
                    n_stops = int(nav.get("transit_num_stops", 0))
                    dep = nav.get("transit_departure_stop", "")
                    arr = nav.get("transit_arrival_stop", "")
                    if svc:
                        content.append(f"     svc {svc}", style="bold")
                        if n_stops:
                            content.append(f"  {n_stops} stops\n", style="dim")
                        else:
                            content.append("\n")
                    if dep and arr:
                        content.append(f"     {dep[:11]}→{arr[:11]}\n", style="dim")

            # 4. Progress bar (waypoint X/N) — 1 line
            if wp_total > 0:
                pct = (wp_idx / max(wp_total, 1)) * 100
                bar_w = 16
                filled = int(pct / 100 * bar_w)
                content.append("  ")
                content.append("█" * filled, style="green")
                content.append("░" * (bar_w - filled), style="dim")
                content.append(f" {wp_idx}/{wp_total}", style="dim")
                if d_waypoint > 0:
                    content.append(f"  wp {self._fmt_dist(d_waypoint)}", style="dim")
                content.append("\n")
            elif d_dest > 0:
                content.append(f"  {self._fmt_dist(d_dest)} remaining\n", style="dim")

            # 5. Saved locations + bus (one compact line)
            saved = nav.get("saved_locations", [])
            saved_str = ", ".join(loc.get("name", "?") for loc in saved[:2]) if saved else "—"
            bus_state = nav.get("bus_state", "idle")
            lta_ok = bool(nav.get("lta_ok", False))
            content.append("─" * 22 + "\n", style="dim")
            content.append(f"saved: {saved_str}  ", style="cyan")
            content.append(f"bus {bus_state[:5]} LTA {self._dot(lta_ok)}\n",
                          style="green" if lta_ok else "dim")

            return Panel(content, title="[bold yellow]NAVIGATION[/]", border_style="yellow", padding=(0, 1))

        @staticmethod
        def _fmt_dist(meters: float) -> str:
            """Format a distance for display: '850m', '1.2km', '—' for 0."""
            if meters <= 0:
                return "—"
            if meters < 1000:
                return f"{int(meters)}m"
            return f"{meters/1000:.1f}km"

        def _render_tts(self, snap: dict, hist: dict) -> Panel:
            content = Text()
            tts = snap["tts"]
            voice = snap["voice"]
            rec = snap["recorder"]
            muted = tts.get("muted", False)
            content.append(f"engine  · {tts.get('engine', '') or '[idle]'}\n",
                          style="cyan" if tts.get('engine') else "dim")
            content.append(f"voice   · {tts.get('voice', 'Zephyr')}  {tts.get('speed', 1.0):.1f}×\n", style="dim")
            content.append(f"state   · {tts.get('state', 'idle')}\n", style="dim")
            content.append(f"VAD     {self._dot(voice.get('listening', False))} ")
            content.append("listening\n" if voice.get("listening") else "idle\n")
            content.append(f"rec     {self._dot(rec.get('is_recording', False))} ")
            if rec.get("is_recording"):
                content.append("RECORDING\n", style="bold red")
            else:
                content.append(f"idle  [{rec.get('toggle_key', 'b')}]\n", style="dim")
            if muted:
                content.append("\n⚠ TTS MUTED\n", style="bold yellow")

            # Recent STT (last 4 with confidence bars — fills empty space)
            stt_recent = snap.get("stt_recent", [])
            if stt_recent:
                now = time.time()
                content.append("─" * 22 + "\n", style="dim")
                content.append("heard\n", style="bold")
                for entry in stt_recent[-4:]:
                    text = (entry.get("text", "") or "")
                    conf = float(entry.get("confidence", 0))
                    ts = float(entry.get("ts", 0))
                    age = int(now - ts) if ts > 0 else 0
                    age_str = f"{age}s" if age < 60 else f"{age // 60}m"
                    # Confidence mini-bar
                    bar = self._conf_bar(conf, width=8)
                    content.append(f"  {bar} ", style="dim")
                    content.append(f"{self._truncate(text, 32)}\n", style="white")
                    content.append(f"    {age_str} ago\n", style="dim")
            else:
                content.append("─" * 22 + "\n", style="dim")
                content.append("  (no STT yet)\n", style="dim")

            return Panel(content, title="[bold cyan]TTS + VOICE[/]", border_style="cyan", padding=(0, 1))

        @staticmethod
        def _conf_bar(conf: float, width: int = 8) -> str:
            """Confidence bar: [████░░] 0.5"""
            ratio = max(0.0, min(1.0, conf))
            filled = int(ratio * width)
            empty = width - filled
            return f"[{'█' * filled}{'░' * empty}]"

        def _render_memory(self, snap: dict, hist: dict) -> Panel:
            content = Text()
            m = snap.get("l4", {}) or {}
            l4_available = bool(m.get("available", False))
            # If the publisher hasn't pushed anything yet (memory_manager
            # not initialized, or startup race), show zeros honestly
            # rather than crashing. Was hard-keying m["local_rows"] before
            # which raised KeyError and silently fell back to the
            # "render error" branch.
            local_rows = int(m.get("local_rows", 0) or 0)
            detect_rows = int(m.get("detections_stored", 0) or 0)
            events_rows = int(m.get("events_stored", 0) or 0)
            queue = int(m.get("upload_queue", 0) or 0)
            failed = int(m.get("upload_failed", 0) or 0)
            content.append(f"local    · {local_rows:>5} rows\n", style="cyan")
            sync_age = m.get("last_sync_age_s", -1)
            content.append(f"sync     · ")
            if sync_age is None or sync_age < 0:
                content.append("never\n", style="dim")
            elif sync_age < 5:
                content.append(f"{sync_age:.0f}s ago ●\n", style="green")
            else:
                content.append(f"{sync_age:.0f}s ago\n", style="yellow")
            next_in = m.get("next_sync_in_s", 60)
            try:
                next_in = float(next_in)
            except Exception:
                next_in = 60.0
            if 0 < next_in < 60:
                pct = (60 - next_in) / 60 * 100
                content.append(f"next     · in {next_in:.0f}s  ")
                content.append(f"[{'█' * int(pct/10):<10}] {pct:.0f}%\n", style="cyan")
            else:
                content.append(f"next     · in {next_in:.0f}s\n", style="dim")
            content.append(f"detect   · {detect_rows:>5}\n")
            content.append(f"events   · {events_rows:>5}\n")
            # Upload queue (more detail)
            if queue or failed:
                q_color = "yellow" if failed else "dim"
                content.append(f"queue    · {queue:>3}  failed {failed}\n", style=q_color)
            # Memory manager availability — surface the truth instead of
            # staring at zeros forever when the manager didn't init.
            if not l4_available:
                content.append("memory mgr: not initialized\n", style="dim yellow")
            elif local_rows == 0 and detect_rows == 0 and events_rows == 0:
                # Manager is up but no detections yet — distinguish
                # "waiting for first frame" from "broken".
                content.append("(no data stored yet)\n", style="dim")
            # Disk usage (NEW: fill empty space).
            # Be forgiving — show whatever fields the publisher sent
            # even if some are zero. Older builds only sent l4 / power
            # and skipped disk entirely; the panel used to read
            # "(no data)" forever in that case.
            content.append("─" * 22 + "\n", style="dim")
            disk = snap.get("disk", {}) or {}
            total_gb = float(disk.get("total_gb", 0) or 0)
            used_gb = float(disk.get("used_gb", 0) or 0)
            if total_gb > 0:
                pct = float(disk.get("percent", 0) or 0)
                free_gb = total_gb - used_gb
                if free_gb < 0:
                    free_gb = 0.0
                bar_w = 14
                filled = int(pct / 100 * bar_w)
                bar = "█" * filled + "░" * (bar_w - filled)
                d_color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
                content.append("disk    · ")
                content.append(f"{bar} ", style=d_color)
                content.append(f"{pct:.0f}%\n", style=d_color)
                content.append(f"         {used_gb:.0f}G used, {free_gb:.0f}G free\n", style="dim")
            else:
                # Fall back to live psutil so the panel is never blank.
                try:
                    import psutil
                    dsk = psutil.disk_usage("/")
                    used_gb = dsk.used / (1024 ** 3)
                    total_gb = dsk.total / (1024 ** 3)
                    pct = dsk.percent
                    free_gb = (total_gb - used_gb) if total_gb > used_gb else 0.0
                    bar_w = 14
                    filled = int(pct / 100 * bar_w)
                    bar = "█" * filled + "░" * (bar_w - filled)
                    d_color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
                    content.append("disk    · ")
                    content.append(f"{bar} ", style=d_color)
                    content.append(f"{pct:.0f}%\n", style=d_color)
                    content.append(f"         {used_gb:.0f}G used, {free_gb:.0f}G free\n", style="dim")
                except Exception:
                    content.append("disk    · (no data)\n", style="dim")
            return Panel(content, title="[bold magenta]MEMORY · L4[/]", border_style="magenta", padding=(0, 1))

        # Source → (color, prefix). Compact 4-char source tag, e.g. "stt" or "l2  ".
        _EVENT_SOURCE_STYLE = {
            "stt":     ("cyan",    "stt "),
            "l2":      ("magenta", "l2  "),
            "l0":      ("blue",    "l0  "),
            "l1":      ("magenta", "l1  "),
            "nav":     ("yellow",  "nav "),
            "safety":  ("red",     "sft "),
            "ai":      ("magenta", "ai  "),
            "sys":     ("dim",     "sys "),
            "user":    ("cyan",    "user"),
            "tts":     ("green",   "tts "),
            "btn":     ("yellow",  "btn "),
            "scene":   ("cyan",    "scn "),
        }

        # Kind → icon
        _EVENT_KIND_ICON = {
            "info":     "·",
            "tool":     "⚙",
            "alert":    "⚠",
            "route":    "→",
            "heard":    "▸",
            "said":     "◂",
            "intent":   "★",
            "error":    "✗",
            "critical": "⛔",
        }

        def _render_activity(self, snap: dict, hist: dict) -> Panel:
            """Unified timeline — last 6 events from any subsystem."""
            content = Text()
            events = list(snap.get("events", []))
            if not events:
                content.append("  (no events yet — feed lights up as soon as the system produces output)\n", style="dim")
                return Panel(content, title="[bold yellow]ACTIVITY · timeline[/]", border_style="yellow", padding=(0, 1))

            # Show most recent first (newest at top) — operator scans top-down
            recent = events[-8:][::-1]
            now = time.time()
            for ev in recent:
                ts = float(ev.get("ts", 0))
                source = str(ev.get("source", "?"))
                kind = str(ev.get("kind", "info"))
                message = str(ev.get("message", ""))
                # Age
                if ts > 0:
                    age = int(now - ts)
                    if age < 60:
                        age_str = f"{age:>3}s"
                    elif age < 3600:
                        age_str = f"{age // 60:>3}m"
                    else:
                        age_str = f"{age // 3600:>3}h"
                else:
                    age_str = "  ·"
                # Source tag
                src_color, src_prefix = self._EVENT_SOURCE_STYLE.get(
                    source, ("white", source[:3].ljust(3) + " ")
                )
                icon = self._EVENT_KIND_ICON.get(kind, "·")
                # Compose line
                content.append(f"  {age_str}  ", style="dim")
                content.append(f"{src_prefix}", style=f"bold {src_color}")
                content.append(f" {icon} ", style=src_color)
                content.append(f"{self._truncate(message, 80)}\n", style="white")

            # Footer line: event count + last-update age
            count = len(events)
            latest = events[-1] if events else {}
            latest_ts = float(latest.get("ts", 0))
            latest_age = int(now - latest_ts) if latest_ts > 0 else 0
            content.append("─" * 80 + "\n", style="dim")
            content.append(f"  {count} events captured", style="dim")
            if latest_age > 0:
                content.append(f"  · latest {latest_age}s ago", style="dim")
            content.append("\n")

            return Panel(content, title="[bold yellow]ACTIVITY · timeline[/]", border_style="yellow", padding=(0, 1))

        # --- key bindings ---

        def action_quit_app(self) -> None:
            self.exit()

        def action_toggle_rec(self) -> None:
            if hasattr(self.system, "_toggle_session_recording"):
                self.system._toggle_session_recording()

        def action_mute_tts(self) -> None:
            tts = getattr(self.system, "tts", None)
            if tts is not None:
                tts.muted = not getattr(tts, "muted", False)
                # Push ONLY muted + state to DashboardState. M33 fix:
                # previously we overwrote the full tts dict including
                # engine, voice, speed, fallback_engine. If the publisher
                # (_publish_system_metrics) fires a moment later with
                # stale values, the panel flickers. Touching only what
                # we changed keeps the TUI stable.
                if self.dashboard_state is not None:
                    state = "muted" if tts.muted else (
                        "speaking" if getattr(tts, "is_playing", False) else "idle"
                    )
                    self.dashboard_state.update(tts={
                        "muted": bool(tts.muted),
                        "state": state,
                        "muted": bool(tts.muted),
                        "engine": engine,
                        "state": state,
                    })
                self._update_subtitle()

        def action_ask_cortex(self) -> None:
            """Trigger a one-shot vision query. Three paths, in order:
              1. VisionQueryHandler (if instantiated) — preferred
              2. Gemini Live (if connected) — sends "What do you see?" as text
              3. Local L0+L1 detection summary — last-resort fallback
            The r keybind will feel responsive regardless of which path
            is available, so the user can always trigger an "ask".
            """
            vqh = getattr(self.system, "vision_query_handler", None)
            if vqh is not None and hasattr(vqh, "request_query"):
                vqh.request_query("What do you see?")
                self._write_log("[bold cyan]→ Ask: routed to VisionQueryHandler[/]")
                return
            # Path 2: Gemini Live text query
            layer2 = getattr(self.system, "layer2", None)
            if layer2 is not None:
                handler = getattr(layer2, "handler", None) or layer2
                ic = getattr(handler, "is_connected", False)
                connected = bool(ic() if callable(ic) else ic)
                if connected and hasattr(handler, "send_text"):
                    try:
                        import asyncio as _asyncio
                        import inspect as _inspect
                        send_fn = handler.send_text
                        # M31 fix: send_text is async on the live
                        # handler (returns a coroutine). The Textual
                        # action_ask_cortex() runs on the main loop
                        # and cannot `await` a coroutine directly.
                        # Use run_coroutine_threadsafe if the loop is
                        # running on a worker thread, otherwise
                        # create_task on the current loop.
                        if _inspect.iscoroutinefunction(send_fn):
                            try:
                                loop = _asyncio.get_running_loop()
                            except RuntimeError:
                                loop = None
                            coro = send_fn("What do you see?")
                            if loop is not None:
                                loop.create_task(coro)
                            self._write_log("[bold cyan]→ Ask: sent to Gemini Live[/]")
                            return
                        else:
                            send_fn("What do you see?")
                            self._write_log("[bold cyan]→ Ask: sent to Gemini Live[/]")
                            return
                    except Exception as e:
                        self._write_log(f"[bold yellow]⚠ Ask → Gemini failed: {e}[/]")
            # Path 3: local summary of L0+L1
            self._write_log("[bold cyan]→ Ask: running local L0+L1 detection…[/]")
            self._run_local_ask()

        def _run_local_ask(self) -> None:
            """Last-resort fallback: pull L0+L1 classes from DashboardState
            and synthesize a short summary into the log panel."""
            if self.dashboard_state is None:
                self._write_log("[bold yellow]⚠ no dashboard state — cannot answer[/]")
                return
            snap = self.dashboard_state.snapshot()
            l0 = snap.get("l0_classes", []) or []
            l1 = snap.get("l1_classes", []) or []
            classes = list(dict.fromkeys(l0 + l1))  # dedupe, preserve order
            if classes:
                self._write_log(
                    f"[bold green]CORTEX:[/] I see: {', '.join(classes[:8])}"
                )
            else:
                self._write_log(
                    "[bold green]CORTEX:[/] I don't see anything clearly right now."
                )

        def action_save_log(self) -> None:
            import json
            from datetime import datetime
            from pathlib import Path
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = Path(f"logs/snapshot_{ts}.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(
                {"ts": ts, "state": self.dashboard_state.snapshot(),
                 "history": self.dashboard_state.history()},
                indent=2, default=str,
            ))
            self._write_log(f"[green]✓ snapshot saved to {out}[/]")

        def action_copy_logs(self) -> None:
            """Copy the FULL log file to the system clipboard so the user
            can paste it elsewhere. The previous implementation only copied
            the last 200 lines (matching the visible buffer), which truncated
            crashes and earlier session history — the operator wanted the
            WHOLE log, not just the panel tail.

            Writes a one-line status to the log panel on success/failure.
            """
            try:
                from pathlib import Path
                log_path = Path("logs/cortex.log")
                if not log_path.exists():
                    self._write_log("[bold yellow]⚠ no logs/cortex.log to copy[/]")
                    return
                # Copy the FULL file — operators paste this into bug reports
                # and need crashes from before the panel buffer started.
                # 4.4MB is fine for clipboard; tools like wl-copy handle it.
                text = log_path.read_text(encoding="utf-8", errors="replace")
                n_lines = len(text.splitlines())
                self._copy_to_clipboard(text)
                self._write_log(
                    f"[bold green]✓ copied {n_lines} lines ({len(text)} chars) — full logs/cortex.log[/]"
                )
            except Exception as e:
                self._write_log(f"[bold red]✗ copy failed: {e}[/]")

        def _copy_to_clipboard(self, text: str) -> None:
            """Cross-platform clipboard write. Tries pyperclip, then
            platform-native fallbacks (pbcopy on mac, clip on Win,
            xclip/wl-copy on Linux). On the RPi5, xclip is the recommended
            install (`sudo apt install xclip`) because it works headless
            over SSH where wl-copy/xsel need a Wayland/X session.

            The clipboard fallback chain is best-effort; each failure
            falls through to the next option before giving up."""
            # Try pyperclip first (works on all platforms)
            try:
                import pyperclip
                pyperclip.copy(text)
                return
            except ImportError:
                pass
            except Exception:
                # pyperclip installed but the underlying copy failed
                # (common on headless Pi); fall through to native tools.
                pass
            import platform
            import subprocess
            system = platform.system()
            tried = []
            try:
                if system == "Windows":
                    # Set-Clipboard doesn't read stdin; pipe via [Console]::In
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "$input = [Console]::In.ReadToEnd(); Set-Clipboard -Value $input"],
                        input=text.encode("utf-8"),
                        check=True, timeout=15,
                    )
                    return
                elif system == "Darwin":
                    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=15)
                    return
                else:
                    # Linux / RPi5 — try xclip first (headless-friendly),
                    # then xsel, then wl-copy (needs Wayland session).
                    for cmd in (["xclip", "-selection", "clipboard"],
                                ["xsel", "--input", "--clipboard"],
                                ["wl-copy"]):
                        tried.append(cmd[0])
                        try:
                            subprocess.run(cmd, input=text.encode("utf-8"),
                                           check=True, timeout=15)
                            return
                        except FileNotFoundError:
                            continue
                        except subprocess.CalledProcessError:
                            continue
                    raise RuntimeError(
                        f"no working clipboard tool on {system}. Tried: {tried}. "
                        f"On RPi5 run: sudo apt install xclip"
                    )
            except Exception:
                # Final fallback: write to a file the user can copy manually.
                # Don't raise — the file IS a successful copy, just not
                # into the system clipboard. Tell the user clearly.
                from pathlib import Path
                from datetime import datetime
                out = Path(f"logs/clipboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                out.write_text(text, encoding="utf-8")
                raise RuntimeError(
                    f"clipboard unavailable (tried {tried or [system + ' native']}); "
                    f"wrote {len(text)} chars to {out}. "
                    f"On RPi5 run: sudo apt install xclip"
                )

        def action_toggle_pause(self) -> None:
            self._paused = not self._paused
            # Immediate subtitle update so the user sees feedback instantly,
            # not after the next 1Hz refresh tick.
            self._update_subtitle()

        def action_show_help(self) -> None:
            log = self.query_one("#log", RichLog)
            log.write("[bold]Keybinds[/]")
            for key, label in FOOTER_HINTS_FULL:
                log.write(f"  [cyan]{key:>4}[/]  {label}")
            log.write("")

        def cleanup(self) -> None:
            if hasattr(self, "_refresh_timer"):
                try:
                    self._refresh_timer.stop()
                except Exception:
                    pass
            if hasattr(self, "_log_watcher") and self._log_watcher is not None:
                self._log_watcher.stop()

        # M29 fix: Textual's lifecycle calls on_unmount when the
        # app exits (q key, Ctrl+C, exit()). Previously cleanup()
        # was only called from explicit code paths, so log-watcher
        # threads and refresh timers leaked across restarts. Now
        # on_unmount invokes cleanup() so the resources are always
        # released.
        def on_unmount(self) -> None:
            try:
                self.cleanup()
            except Exception:
                pass


else:
    # Textual not installed — provide a stub so the import doesn't crash
    class CortexFullApp:
        def __init__(self, state, system):
            raise RuntimeError(
                "Textual is not installed. Run `pip install textual` to use FULL mode."
            )
