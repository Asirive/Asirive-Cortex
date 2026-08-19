"""
2.4 mode dashboard for Asirive Cortex — plain-print UI for slow SSH.

No Rich Live, no Layout, no cursor control. Just print() to stdout.
Designed to be readable and lag-free even on 2.4 GHz WiFi or flaky
SSH connections.

Output format (mixed log stream + periodic status snapshots):

    [22:31:04] INFO     System started
    [22:31:05] INFO     Camera started 1920x1080
    [22:31:05] INFO     TTS engines loaded
    ─── STATUS @ 22:31:06 ───
    Mode    : PRODUCTION     FPS    : 20.5
    L0      : 0 (none) 47ms  L1     : 0 (none) 0ms
    GPS     : NO FIX sats:0  IMU    : NO DATA
    AI      : LOCAL          TTS    : idle
    BT      : F-16 + CMF     L2 Live: connected
    L4 Mem  : 1247 rows      Voice  : listening
    ──────────────────────
    [22:31:07] INFO     TTS routing ...

Keybinds (POSIX TTY only — silent no-op otherwise):
    q / Ctrl+C : quit
    b          : toggle session recording
    m          : mute TTS
    r          : ask cortex
    s          : save log snapshot
    p          : pause status updates
    ?          : help
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rpi5.live_dashboard.state import DashboardState
from rpi5.live_dashboard.log_watcher import LogFileWatcher
from rpi5.live_dashboard.keybinds import KeyAction, resolve_key, is_full_only, FOOTER_HINTS

logger = logging.getLogger(__name__)


# Width of the status block separator. Tuned to look good in 100-120 col
# terminals; truncates gracefully if the terminal is narrower.
SEP_WIDTH = 60


class ConsoleApp:
    """2.4 mode: plain-print UI.

    Lifecycle:
        app = ConsoleApp(state, system)
        app.run()            # blocks until quit
        app.cleanup()        # called automatically on exit
    """

    DEFAULT_STATUS_INTERVAL_S = 2.0
    DEFAULT_LOG_PATH = "logs/cortex.log"

    def __init__(
        self,
        state: DashboardState,
        system: Any,                            # CortexSystem (typed Any to avoid circular import)
        log_path: str = DEFAULT_LOG_PATH,
        status_interval_s: float = DEFAULT_STATUS_INTERVAL_S,
    ) -> None:
        self.state = state
        self.system = system
        self.log_path = log_path
        self.status_interval_s = status_interval_s

        self._stop = threading.Event()
        self._log_watcher: Optional[LogFileWatcher] = None
        self._status_thread: Optional[threading.Thread] = None
        self._keybind_thread: Optional[threading.Thread] = None

        self._paused = False
        self._last_status_ts = 0.0

        # Original signal handlers — restored on cleanup
        self._old_sigint: Optional[Any] = None
        self._old_sigterm: Optional[Any] = None

        # M37 fix: store terminal attrs so cleanup() can restore them
        # even if the keybind thread's own join times out.
        self._saved_termios_attrs: Optional[Any] = None
        self._termios_fd: Optional[int] = None

    # --- public ---

    def run(self) -> int:
        """Run the dashboard. Blocks until quit. Returns exit code."""
        # Install signal handlers
        self._old_sigint = signal.signal(signal.SIGINT, self._on_signal)
        self._old_sigterm = signal.signal(signal.SIGTERM, self._on_signal)

        self._print_banner()
        self._log_watcher = LogFileWatcher(
            log_path=self.log_path,
            on_line=self._on_log_line,
            poll_interval_s=0.1,
            start_at_end=False,   # 2.4 mode: show all recent logs since process start
        )
        self._log_watcher.start()

        self._status_thread = threading.Thread(
            target=self._status_loop, name="console-status", daemon=True
        )
        self._status_thread.start()

        self._keybind_thread = threading.Thread(
            target=self._keybind_loop, name="console-keybind", daemon=True
        )
        self._keybind_thread.start()

        try:
            while not self._stop.is_set():
                self._stop.wait(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

        return 0

    def cleanup(self) -> None:
        self._stop.set()
        if self._log_watcher:
            self._log_watcher.stop()
            self._log_watcher = None
        for t in (self._status_thread, self._keybind_thread):
            if t and t.is_alive():
                t.join(timeout=1.0)
        # M37 fix: explicitly restore terminal attrs even if the
        # keybind thread's own finally-block didn't run (join timed out
        # because the thread was stuck in sys.stdin.read). Without this
        # the user's terminal is left in cbreak mode and echo is off.
        if self._saved_termios_attrs is not None and self._termios_fd is not None:
            try:
                import termios
                termios.tcsetattr(self._termios_fd, termios.TCSADRAIN, self._saved_termios_attrs)
            except Exception:
                pass
        # Restore signal handlers
        if self._old_sigint is not None:
            try:
                signal.signal(signal.SIGINT, self._old_sigint)
            except Exception:
                pass
        if self._old_sigterm is not None:
            try:
                signal.signal(signal.SIGTERM, self._old_sigterm)
            except Exception:
                pass
        sys.stdout.write("\n[2.4 mode: dashboard stopped]\n")
        sys.stdout.flush()

    # --- internals ---

    def _on_signal(self, signum: int, frame: Any) -> None:
        # M36 fix: signal handlers must be async-signal-safe. Only touch
        # the Event (thread-safe) here. All other cleanup runs from
        # the main thread when it sees the Event set.
        self._stop.set()

    def _print_banner(self) -> None:
        sep = "═" * SEP_WIDTH
        sys.stdout.write(f"\n{sep}\n")
        sys.stdout.write(f"  Asirive Cortex v2.1 — 2.4 mode (plain-print)\n")
        sys.stdout.write(f"  Status block every {self.status_interval_s:.1f}s · logs tailed live\n")
        keys = " · ".join(f"[{k}] {v}" for k, v in FOOTER_HINTS)
        sys.stdout.write(f"  {keys}\n")
        sys.stdout.write(f"{sep}\n\n")
        sys.stdout.flush()

    # --- log tailer callback ---

    def _on_log_line(self, line: str) -> None:
        if self._paused:
            return
        # Write directly to stdout. Plain text, one line per record.
        # (We bypass logging to avoid recursion through RichHandler.)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    # --- status printer ---

    def _status_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(0.5)
            if self._stop.is_set():
                break
            now = time.time()
            if now - self._last_status_ts < self.status_interval_s:
                continue
            self._print_status()
            self._last_status_ts = now

    def _print_status(self) -> None:
        snap = self.state.snapshot()
        ts = datetime.now().strftime("%H:%M:%S")
        lines = [
            "",
            f"─── STATUS @ {ts} ───".center(SEP_WIDTH, " "),
            f"Mode    : {snap['mode']:11}  FPS      : {snap['fps']:.1f}",
            f"L0      : {snap['l0_count']:>2} {self._fmt_classes(snap['l0_classes'])} {snap['l0_latency_ms']:.0f}ms",
            f"L1      : {'laptop only' if not snap.get('l1_mode') else f'{snap['l1_count']:>2} {self._fmt_classes(snap['l1_classes'])} {snap['l1_latency_ms']:.0f}ms'}",
            f"GPS     : {self._fmt_gps(snap['gps']):17}  IMU      : {self._fmt_imu(snap['imu'])}",
            f"AI      : {self._fmt_ai(snap['ai']):17}  TTS      : {self._fmt_tts(snap['tts'])}",
            f"BT      : {self._fmt_bt(snap['bt']):17}  L2 Live  : {self._fmt_l2(snap['l2'])}",
            f"L4 Mem  : {snap['l4'].get('local_rows', 0):>5} rows      Voice    : {self._fmt_voice(snap['voice'])}",
            "─────────────────────"[:SEP_WIDTH],
        ]
        for line in lines:
            sys.stdout.write(line + "\n")
        sys.stdout.flush()

    # --- formatters (kept tiny — these are the "Easy to understand" part) ---

    @staticmethod
    def _fmt_classes(classes: list) -> str:
        if not classes:
            return "(none)      "
        c = Counter(classes)
        items = []
        for cls, count in c.most_common(3):
            if count > 1:
                items.append(f"{cls} x{count}")
            else:
                items.append(cls)
        if len(c) > 3:
            items.append(f"+{len(c) - 3} more")
        s = "(" + ", ".join(items) + ")"
        return s.ljust(14)

    @staticmethod
    def _fmt_gps(gps: dict) -> str:
        # L5 fix: guard against None / missing keys. A producer
        # pushing gps={} (no fix yet) would raise KeyError here
        # and crash the status print loop.
        fix = gps.get("fix", 0) or 0
        sats = gps.get("sats", 0)
        sats = sats if sats is not None else 0
        if fix == 0:
            return f"NO FIX sats:{sats}"
        return f"FIX:{fix} sats:{sats}"

    @staticmethod
    def _fmt_imu(imu: dict) -> str:
        if all(c == 0 for c in imu["cal"]):
            return "NO DATA"
        cal = imu["cal"]
        return f"hdg:{imu['heading']:.0f}° S{cal[0]}G{cal[1]}A{cal[2]}M{cal[3]}"

    @staticmethod
    def _fmt_ai(ai: dict) -> str:
        return "🤖 GEMINI" if ai["active"] else "⚡ LOCAL"

    @staticmethod
    def _fmt_tts(tts: dict) -> str:
        if not tts.get("engine"):
            return "idle"
        muted = " (muted)" if tts.get("muted") else ""
        return f"{tts['engine']} {tts['state']}{muted}"

    @staticmethod
    def _fmt_bt(bt: dict) -> str:
        if not bt["connected"]:
            return "disconnected"
        bat = f" {bt['battery_pct']}%" if bt.get("battery_pct", -1) >= 0 else ""
        return f"{bt['device']}{bat}"

    @staticmethod
    def _fmt_l2(l2: dict) -> str:
        return "● connected" if l2["connected"] else "○ disconnected"

    @staticmethod
    def _fmt_voice(voice: dict) -> str:
        if voice.get("listening"):
            return "● listening"
        return "○ idle"

    # --- keybind reader (POSIX TTY only) ---

    def _keybind_loop(self) -> None:
        """Single-keypress reader using POSIX tty mode.

        Silent no-op on Windows or when stdin is not a TTY (e.g. running
        under `nohup`, `&`, or piped). The user can still quit via
        Ctrl+C (signal handler handles it).
        """
        if os.name != "posix" or not sys.stdin or not sys.stdin.isatty():
            return

        try:
            import select
            import termios
            import tty
        except ImportError:
            return

        fd = sys.stdin.fileno()
        try:
            old_attrs = termios.tcgetattr(fd)
        except Exception:
            return
        # M37 fix: also store on the app so cleanup() can restore if
        # this thread's own finally-block is skipped (e.g. on hang).
        self._saved_termios_attrs = old_attrs
        self._termios_fd = fd

        try:
            tty.setcbreak(fd)
            while not self._stop.is_set():
                r, _, _ = select.select([sys.stdin], [], [], 0.2)
                if not r:
                    continue
                ch = sys.stdin.read(1)
                if not ch:
                    continue
                self._handle_keypress(ch)
        except Exception as e:
            logger.debug(f"Keybind loop error: {e}")
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
            except Exception:
                pass

    def _handle_keypress(self, ch: str) -> None:
        action = resolve_key(ch)
        if action is None:
            return
        if action == KeyAction.QUIT:
            sys.stdout.write("\n[2.4: quit]\n")
            sys.stdout.flush()
            self._stop.set()
        elif action == KeyAction.TOGGLE_RECORDING:
            self._action_toggle_recording()
        elif action == KeyAction.MUTE_TTS:
            self._action_mute_tts()
        elif action == KeyAction.ASK_CORTEX:
            self._action_ask_cortex()
        elif action == KeyAction.SAVE_LOG:
            self._action_save_log()
        elif action == KeyAction.PAUSE:
            self._action_toggle_pause()
        elif action == KeyAction.TOGGLE_OVERHEAD_FORCE:
            self._action_toggle_overhead_force()
        elif action == KeyAction.HELP:
            self._action_help()
        elif is_full_only(action):
            sys.stdout.write(f"\n[2.4: '{ch}' is FULL-mode only — ignored]\n")
            sys.stdout.flush()
        else:
            sys.stdout.write(f"\n[2.4: '{ch}' bound to {action.value} but no handler wired yet]\n")
            sys.stdout.flush()

    def _action_toggle_recording(self) -> None:
        if hasattr(self.system, "_toggle_session_recording"):
            self.system._toggle_session_recording()
            sys.stdout.write("\n[2.4: recording toggled]\n")
        else:
            sys.stdout.write("\n[2.4: recording handler not found on system]\n")
        sys.stdout.flush()

    def _action_mute_tts(self) -> None:
        tts = getattr(self.system, "tts", None)
        if tts is None:
            sys.stdout.write("\n[2.4: no TTS engine on system]\n")
        else:
            tts.muted = not getattr(tts, "muted", False)
            sys.stdout.write(f"\n[2.4: TTS muted={tts.muted}]\n")
        sys.stdout.flush()

    def _action_ask_cortex(self) -> None:
        vqh = getattr(self.system, "vision_query_handler", None)
        if vqh is None:
            sys.stdout.write("\n[2.4: vision_query_handler not available]\n")
        else:
            vqh.request_query("What do you see?")
            sys.stdout.write("\n[2.4: asked cortex 'What do you see?']\n")
        sys.stdout.flush()

    def _action_save_log(self) -> None:
        import json
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(f"logs/snapshot_{ts}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {
                "ts": ts,
                "state": self.state.snapshot(),
                "history": self.state.history(),
            },
            indent=2,
            default=str,
        ))
        sys.stdout.write(f"\n[2.4: snapshot saved to {out}]\n")
        sys.stdout.flush()

    def _action_toggle_pause(self) -> None:
        self._paused = not self._paused
        sys.stdout.write(f"\n[2.4: status updates {'PAUSED' if self._paused else 'RESUMED'}]\n")
        sys.stdout.flush()

    def _action_toggle_overhead_force(self) -> None:
        if hasattr(self.system, "_toggle_overhead_force"):
            self.system._toggle_overhead_force()


    def _action_help(self) -> None:
        keys = "\n".join(f"  [{k:^4}] {v}" for k, v in FOOTER_HINTS)
        sys.stdout.write(f"\n2.4 mode keybinds:\n{keys}\n")
        sys.stdout.flush()
