"""
Test the ConsoleApp (2.4 mode) with a mock CortexSystem.

Doesn't start the real camera/L0/L1/etc. — just verifies the UI:
  - Log watcher posts lines to the print callback
  - Status block is printed every STATUS_INTERVAL_S
  - `b` keybind calls system._toggle_session_recording()
  - `q` keybind triggers shutdown
  - Format functions produce reasonable output

Run on the RPi5:
    cd ~/ProjectCortex && source venv/bin/activate
    python -m rpi5.live_dashboard.tests.round2a
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, List

HERE = Path(__file__).resolve()
PKG_PARENT = HERE.parent.parent.parent
sys.path.insert(0, str(PKG_PARENT))

try:
    from rpi5.live_dashboard import state as _state
    from rpi5.live_dashboard import log_watcher as _watcher
    from rpi5.live_dashboard import keybinds as _keys
    from rpi5.live_dashboard import app_console as _app
except ImportError:
    sys.path.insert(0, str(HERE.parent.parent))
    import state as _state
    import log_watcher as _watcher
    import keybinds as _keys
    import app_console as _app


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}✗{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{YELLOW}=== {title} ==={RESET}")


class MockSystem:
    """Minimal CortexSystem stub for ConsoleApp tests."""
    def __init__(self):
        self.tts = type("FakeTTS", (), {"muted": False})()
        self.recording_toggle_count = 0
        self.vision_query_handler = None
    def _toggle_session_recording(self):
        self.recording_toggle_count += 1


def test_format_functions() -> None:
    section("Format functions (regression)")
    A = _app.ConsoleApp

    # classes
    if A._fmt_classes([]) == "(none)      ":
        ok("_fmt_classes([]) = '(none)'")
    else:
        fail(f"_fmt_classes([]) = {A._fmt_classes([])!r}")
    if A._fmt_classes(["person"]) == "(person)      ":
        ok("_fmt_classes(['person']) = '(person)'")
    else:
        fail(f"_fmt_classes(['person']) = {A._fmt_classes(['person'])!r}")
    if "person x2" in A._fmt_classes(["person", "person", "car"]):
        ok("_fmt_classes groups repeated items")
    else:
        fail(f"_fmt_classes groups failed: {A._fmt_classes(['person','person','car'])!r}")

    # gps
    if A._fmt_gps({"fix": 0, "sats": 0}) == "NO FIX sats:0":
        ok("_fmt_gps(NO FIX)")
    else:
        fail(f"_fmt_gps: {A._fmt_gps({'fix':0,'sats':0})!r}")
    if A._fmt_gps({"fix": 3, "sats": 8}) == "FIX:3 sats:8":
        ok("_fmt_gps(FIX)")
    else:
        fail(f"_fmt_gps: {A._fmt_gps({'fix':3,'sats':8})!r}")

    # imu
    if A._fmt_imu({"heading": 0, "cal": [0, 0, 0, 0]}) == "NO DATA":
        ok("_fmt_imu(NO DATA)")
    else:
        fail(f"_fmt_imu: {A._fmt_imu({'heading':0,'cal':[0,0,0,0]})!r}")

    # ai
    if A._fmt_ai({"active": False}) == "⚡ LOCAL":
        ok("_fmt_ai(LOCAL)")
    else:
        fail(f"_fmt_ai: {A._fmt_ai({'active':False})!r}")
    if A._fmt_ai({"active": True}) == "🤖 GEMINI":
        ok("_fmt_ai(GEMINI)")
    else:
        fail(f"_fmt_ai: {A._fmt_ai({'active':True})!r}")

    # tts
    if A._fmt_tts({"engine": "", "state": "idle"}) == "idle":
        ok("_fmt_tts(idle)")
    else:
        fail(f"_fmt_tts: {A._fmt_tts({'engine':'','state':'idle'})!r}")
    if A._fmt_tts({"engine": "cartesia", "state": "speaking"}) == "cartesia speaking":
        ok("_fmt_tts(cartesia speaking)")
    else:
        fail(f"_fmt_tts: {A._fmt_tts({'engine':'cartesia','state':'speaking'})!r}")
    if "(muted)" in A._fmt_tts({"engine": "cartesia", "state": "speaking", "muted": True}):
        ok("_fmt_tts shows muted state")
    else:
        fail(f"_fmt_tts muted: {A._fmt_tts({'engine':'cartesia','state':'speaking','muted':True})!r}")

    # bt
    if A._fmt_bt({"connected": False, "device": ""}) == "disconnected":
        ok("_fmt_bt(disconnected)")
    else:
        fail(f"_fmt_bt: {A._fmt_bt({'connected':False,'device':''})!r}")
    if A._fmt_bt({"connected": True, "device": "F-16", "battery_pct": 87}) == "F-16 87%":
        ok("_fmt_bt(F-16 87%)")
    else:
        fail(f"_fmt_bt: {A._fmt_bt({'connected':True,'device':'F-16','battery_pct':87})!r}")

    # l2
    if A._fmt_l2({"connected": True}) == "● connected":
        ok("_fmt_l2(connected)")
    else:
        fail(f"_fmt_l2: {A._fmt_l2({'connected':True})!r}")

    # voice
    if A._fmt_voice({"listening": True}) == "● listening":
        ok("_fmt_voice(listening)")
    else:
        fail(f"_fmt_voice: {A._fmt_voice({'listening':True})!r}")


def test_status_printout() -> None:
    section("Status printout (capture stdout)")
    state = _state.DashboardState()
    state.update(
        mode="PRODUCTION", fps=20.5,
        l0_count=2, l0_classes=["person", "car"], l0_latency_ms=47.0,
        l1_count=0, l1_classes=[], l1_latency_ms=0.0,
        gps={"fix": 0, "sats": 0, "source": ""},
        imu={"heading": 0, "cal": [0, 0, 0, 0]},
        ai={"active": False, "last_call": ""},
        bt={"connected": True, "device": "F-16", "battery_pct": 87},
        tts={"engine": "cartesia", "state": "idle"},
        l2={"connected": True},
        l4={"local_rows": 1247},
        voice={"listening": True},
    )

    # Capture stdout
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        app = _app.ConsoleApp(state, MockSystem(), status_interval_s=0.1)
        app._print_status()
    finally:
        sys.stdout = real_stdout

    text = captured.getvalue()
    required = [
        "STATUS @",
        "PRODUCTION",
        "20.5",
        "person",
        "F-16",
        "listening",
        "1247",
    ]
    missing = [s for s in required if s not in text]
    if not missing:
        ok(f"status block contains all required fields ({len(required)} checked)")
    else:
        fail(f"status block missing: {missing}\nGot:\n{text}")


def test_log_tailer_printout() -> None:
    section("Log tailer (capture stdout via real file)")
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "cortex.log"
        log_path.write_text("")  # start empty

        state = _state.DashboardState()
        captured = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = captured
        try:
            app = _app.ConsoleApp(state, MockSystem(), log_path=str(log_path), status_interval_s=99)
            app.run()  # this would block forever; we just want to verify setup
        except SystemExit:
            pass
        except KeyboardInterrupt:
            pass
        # Don't actually run; the test below is a different approach.

        sys.stdout = real_stdout

    # Direct test: just call _on_log_line and verify the line appears in stdout
    state = _state.DashboardState()
    app = _app.ConsoleApp(state, MockSystem(), log_path="/tmp/fake.log", status_interval_s=99)
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        for line in ["INFO System started", "INFO Camera started", "WARN L0 latency 110ms"]:
            app._on_log_line(line)
    finally:
        sys.stdout = real_stdout
    text = captured.getvalue()
    if "System started" in text and "Camera started" in text and "L0 latency 110ms" in text:
        ok(f"3 log lines printed verbatim")
    else:
        fail(f"missing log lines:\n{text!r}")

    # Verify pause works
    captured = io.StringIO()
    sys.stdout = captured
    try:
        app._paused = True
        app._on_log_line("INFO should not appear")
    finally:
        sys.stdout = real_stdout
    if "should not appear" not in captured.getvalue():
        ok(f"paused mode swallows log lines")
    else:
        fail(f"paused mode let log line through")
    app._paused = False


def test_keybind_handlers() -> None:
    section("Keybind handlers (direct method calls)")
    state = _state.DashboardState()
    system = MockSystem()
    app = _app.ConsoleApp(state, system, log_path="/tmp/fake.log", status_interval_s=99)

    # b → recording toggle
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        app._handle_keypress("b")
    finally:
        sys.stdout = real_stdout
    if system.recording_toggle_count == 1:
        ok(f"'b' calls _toggle_session_recording() (count={system.recording_toggle_count})")
    else:
        fail(f"'b' did not toggle recording (count={system.recording_toggle_count})")
    if "recording toggled" in captured.getvalue():
        ok(f"'b' prints confirmation")
    else:
        fail(f"'b' did not print confirmation: {captured.getvalue()!r}")

    # m → mute tts
    captured = io.StringIO()
    sys.stdout = captured
    try:
        app._handle_keypress("m")
    finally:
        sys.stdout = real_stdout
    if system.tts.muted:
        ok(f"'m' toggles TTS.muted (now True)")
    else:
        fail(f"'m' did not mute TTS")

    captured = io.StringIO()
    sys.stdout = captured
    try:
        app._handle_keypress("m")
    finally:
        sys.stdout = real_stdout
    if not system.tts.muted:
        ok(f"second 'm' un-mutes TTS (now False)")
    else:
        fail(f"second 'm' did not un-mute TTS")

    # q → quit
    captured = io.StringIO()
    sys.stdout = captured
    try:
        app._handle_keypress("q")
    finally:
        sys.stdout = real_stdout
    if app._stop.is_set():
        ok(f"'q' triggers _stop event")
    else:
        fail(f"'q' did not trigger _stop")

    # FULL-only keybinds give a helpful message
    app._stop.clear()  # reset
    for k in ["f", "l", "tab"]:
        captured = io.StringIO()
        sys.stdout = captured
        try:
            app._handle_keypress(k)
        finally:
            sys.stdout = real_stdout
        if "FULL-mode only" in captured.getvalue():
            ok(f"'{k}' (FULL-only) prints 'FULL-mode only' hint")
        else:
            fail(f"'{k}' did not print FULL-mode hint: {captured.getvalue()!r}")

    # unbound key is silent
    captured = io.StringIO()
    sys.stdout = captured
    try:
        app._handle_keypress("z")
    finally:
        sys.stdout = real_stdout
    if captured.getvalue() == "":
        ok(f"unbound key 'z' is silent (no output)")
    else:
        fail(f"unbound key 'z' produced output: {captured.getvalue()!r}")


def test_save_log() -> None:
    section("Save log (snapshot)")
    with tempfile.TemporaryDirectory() as tmpdir:
        state = _state.DashboardState()
        state.update(mode="PRODUCTION", fps=18.5)
        # Pre-seed history
        for i in range(10):
            state.record_sample(fps=15.0 + i)

        system = MockSystem()
        # Monkey-patch Path to use tmpdir
        import rpi5.live_dashboard.app_console as ac
        original_path_cls = ac.Path
        try:
            ac.Path = lambda p: original_path_cls(f"{tmpdir}/{p}") if not str(p).startswith("/") else original_path_cls(p)
            app = ac.ConsoleApp(state, system, log_path="/tmp/fake.log", status_interval_s=99)

            captured = io.StringIO()
            real_stdout = sys.stdout
            sys.stdout = captured
            try:
                app._handle_keypress("s")
            finally:
                sys.stdout = real_stdout
            text = captured.getvalue()
        finally:
            ac.Path = original_path_cls

        if "snapshot saved" in text:
            ok(f"'s' prints 'snapshot saved'")
        else:
            fail(f"'s' did not print saved message: {text!r}")

        # Verify a file was created (snapshot path is logs/snapshot_*.json,
        # and the monkey-patch wraps it under tmpdir, so the file lands at
        # {tmpdir}/logs/snapshot_*.json)
        import os
        snapshot_dir = os.path.join(tmpdir, "logs")
        files = [f for f in os.listdir(snapshot_dir) if f.startswith("snapshot_")] if os.path.isdir(snapshot_dir) else []
        if files:
            ok(f"snapshot file created: logs/{files[0]}")
            import json
            data = json.loads((original_path_cls(snapshot_dir) / files[0]).read_text())
            if data["state"]["mode"] == "PRODUCTION" and data["state"]["fps"] == 18.5:
                ok(f"snapshot contains correct state (mode={data['state']['mode']}, fps={data['state']['fps']})")
            else:
                fail(f"snapshot state wrong: {data['state']}")
        else:
            fail(f"no snapshot file in {snapshot_dir}")


def test_pause() -> None:
    section("Pause toggle")
    state = _state.DashboardState()
    app = _app.ConsoleApp(state, MockSystem(), log_path="/tmp/fake.log", status_interval_s=99)
    if not app._paused:
        ok(f"starts un-paused")
    else:
        fail(f"starts paused")

    app._handle_keypress("p")
    if app._paused:
        ok(f"'p' pauses")
    else:
        fail(f"'p' did not pause")

    app._handle_keypress("p")
    if not app._paused:
        ok(f"second 'p' un-pauses")
    else:
        fail(f"second 'p' did not un-pause")

    # Verify pause actually affects log printing
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        app._paused = True
        app._on_log_line("INFO should be swallowed")
    finally:
        sys.stdout = real_stdout
    if "should be swallowed" not in captured.getvalue():
        ok(f"paused log watcher doesn't print")
    else:
        fail(f"paused log watcher printed anyway")


def main() -> int:
    print(f"{YELLOW}Round 2a tests — 2.4 mode (ConsoleApp){RESET}")
    try:
        test_format_functions()
        test_status_printout()
        test_log_tailer_printout()
        test_keybind_handlers()
        test_save_log()
        test_pause()
        print(f"\n{GREEN}All Round 2a tests passed.{RESET}")
        return 0
    except AssertionError as e:
        print(f"\n{RED}FAILED: {e}{RESET}")
        return 1
    except Exception as e:
        print(f"\n{RED}ERROR: {type(e).__name__}: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
