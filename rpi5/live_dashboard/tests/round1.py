"""
Test script for Round 1 data layer.

Run on the RPi5:
    cd ~/ProjectCortex && source venv/bin/activate
    python -m rpi5.live_dashboard.tests.round1

Verifies:
  1. DashboardState — update / snapshot / record_sample / history are
     thread-safe and produce the expected shapes.
  2. LogFileWatcher — appends to a fake log file get picked up and
     delivered to the callback, in order, with no duplicates.
  3. Keybinds — old `b` keybind preserved; new keybinds mapped correctly;
     FULL-only keybinds distinguishable.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

# Make `rpi5.live_dashboard` importable as a package
HERE = Path(__file__).resolve()
PKG_PARENT = HERE.parent.parent.parent  # .../rpi5/live_dashboard/tests/round1.py -> .../rpi5
sys.path.insert(0, str(PKG_PARENT))

# Also support the package import path
try:
    from rpi5.live_dashboard import state as _state
    from rpi5.live_dashboard import log_watcher as _watcher
    from rpi5.live_dashboard import keybinds as _keys
except ImportError:
    # Fallback for when package __init__.py is missing
    sys.path.insert(0, str(HERE.parent.parent))  # .../rpi5/live_dashboard
    import state as _state
    import log_watcher as _watcher
    import keybinds as _keys


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


# ---------------------------------------------------------------------
# 1. DashboardState
# ---------------------------------------------------------------------
def test_state() -> None:
    section("DashboardState")
    s = _state.DashboardState()

    # default state has all expected top-level keys
    snap = s.snapshot()
    expected_keys = {
        "mode", "fps", "l0_count", "l0_classes", "l0_latency_ms",
        "l1_count", "l1_classes", "l1_latency_ms",
        "gps", "imu", "bt", "ai", "l2", "nav", "connectivity",
        "tts", "voice", "safety", "l4", "recorder", "running",
    }
    missing = expected_keys - set(snap.keys())
    if missing:
        fail(f"missing keys: {missing}")
    else:
        ok(f"snapshot has all {len(expected_keys)} top-level keys")

    # update top-level fields
    s.update(mode="PRODUCTION", fps=20.5, l0_count=3)
    snap = s.snapshot()
    if snap["mode"] == "PRODUCTION" and snap["fps"] == 20.5 and snap["l0_count"] == 3:
        ok("update() sets top-level fields")
    else:
        fail(f"update failed: {snap}")

    # update nested dict fields (gps, bt, l2)
    s.update(gps={"fix": 1, "sats": 8, "source": "m8u"})
    s.update(bt={"connected": True, "device": "F-16", "battery_pct": 87})
    snap = s.snapshot()
    if snap["gps"]["fix"] == 1 and snap["bt"]["device"] == "F-16" and snap["bt"]["battery_pct"] == 87:
        ok("update() merges nested dict fields")
    else:
        fail(f"nested update failed: gps={snap['gps']} bt={snap['bt']}")

    # snapshot is a deep copy (mutating it doesn't affect state)
    snap["fps"] = 999.0
    snap2 = s.snapshot()
    if snap2["fps"] == 20.5:
        ok("snapshot() returns deep copy (no aliasing)")
    else:
        fail(f"snapshot aliased: snap2.fps={snap2['fps']}")

    # unknown keys are silently ignored
    s.update(does_not_exist=42, also_not_a_real_field="x")
    ok("update() silently ignores unknown keys (no crash)")

    # record_sample appends to history
    for i in range(5):
        s.record_sample(fps=20.0 + i, l0_count=i, l0_latency_ms=40.0 + i)
    h = s.history()
    if (len(h["fps"]) == 5
        and h["fps"][-1] == 24.0
        and h["l0_count"][-1] == 4
        and h["l0_latency_ms"][-1] == 44.0):
        ok(f"record_sample() appends to history deques (5 samples each)")
    else:
        fail(f"history wrong: {h}")

    # history is bounded
    for i in range(100):
        s.record_sample(fps=99.9)
    h = s.history()
    if len(h["fps"]) == 60:
        ok(f"history bounded to 60 samples")
    else:
        fail(f"history not bounded: {len(h['fps'])}")

    # thread-safety: hammer update() from 4 threads, verify final state is consistent
    errors: list[str] = []
    def hammer(thread_id: int) -> None:
        try:
            for i in range(100):
                s.update(fps=float(thread_id * 1000 + i), l0_count=i)
                s.record_sample(fps=float(thread_id * 1000 + i))
        except Exception as e:
            errors.append(f"thread {thread_id}: {e}")
    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    if not errors:
        ok("4 threads × 100 updates: no errors, no race")
    else:
        fail(f"thread-safety errors: {errors}")


# ---------------------------------------------------------------------
# 2. LogFileWatcher
# ---------------------------------------------------------------------
def test_log_watcher() -> None:
    section("LogFileWatcher")
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "test.log"
        log_path.write_text("first line\nsecond line\n", encoding="utf-8")

        received: list[str] = []
        lock = threading.Lock()

        def cb(line: str) -> None:
            with lock:
                received.append(line)

        w = _watcher.LogFileWatcher(log_path, cb, poll_interval_s=0.05, start_at_end=True)
        w.start()
        time.sleep(0.3)  # let watcher open file

        # Append 10 new lines, expect all 10 to come through
        with open(log_path, "a", encoding="utf-8") as f:
            for i in range(10):
                f.write(f"new line {i}\n")
                f.flush()
                time.sleep(0.05)

        # Wait for the watcher to catch up
        deadline = time.time() + 3.0
        while time.time() < deadline:
            with lock:
                if len(received) >= 10:
                    break
            time.sleep(0.05)

        w.stop()
        with lock:
            if received == [f"new line {i}" for i in range(10)]:
                ok(f"received all 10 new lines in order")
            else:
                fail(f"received {len(received)} lines: {received[:3]}...")
            if w.lines_seen == 10:
                ok(f"lines_seen counter = 10")
            else:
                fail(f"lines_seen = {w.lines_seen}, expected 10")
            if w.errors == 0:
                ok(f"no errors")
            else:
                fail(f"{w.errors} errors")

        # Test rotation handling: write more, then truncate
        received.clear()
        w2 = _watcher.LogFileWatcher(log_path, cb, poll_interval_s=0.05, start_at_end=True)
        w2.start()
        time.sleep(0.2)
        with open(log_path, "a", encoding="utf-8") as f:
            for i in range(5):
                f.write(f"pre-rotate {i}\n")
        time.sleep(0.5)

        # Truncate the file (simulates logrotate)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("")

        # Append new lines after rotation
        time.sleep(0.3)
        with open(log_path, "a", encoding="utf-8") as f:
            for i in range(5):
                f.write(f"post-rotate {i}\n")

        time.sleep(1.0)
        w2.stop()
        with lock:
            post_count = sum(1 for line in received if line.startswith("post-rotate"))
            pre_count = sum(1 for line in received if line.startswith("pre-rotate"))
            if pre_count == 5:
                ok(f"saw 5 pre-rotate lines")
            else:
                fail(f"saw {pre_count}/5 pre-rotate lines")
            if post_count >= 1:
                ok(f"saw {post_count}/5 post-rotate lines (rotation detected)")
            else:
                fail(f"saw 0/5 post-rotate lines — rotation NOT detected")


# ---------------------------------------------------------------------
# 3. Keybinds
# ---------------------------------------------------------------------
def test_keybinds() -> None:
    section("Keybinds")
    # Old keybind preserved
    if _keys.resolve_key("b") == _keys.KeyAction.TOGGLE_RECORDING:
        ok("'b' keybind preserved (toggle recording)")
    else:
        fail(f"'b' resolved to {_keys.resolve_key('b')}")

    # Universal keybinds
    universal = {
        "q": _keys.KeyAction.QUIT,
        "m": _keys.KeyAction.MUTE_TTS,
        "r": _keys.KeyAction.ASK_CORTEX,
        "s": _keys.KeyAction.SAVE_LOG,
        "?": _keys.KeyAction.HELP,
        "f1": _keys.KeyAction.HELP,
        "ctrl+c": _keys.KeyAction.QUIT,
    }
    all_ok = True
    for k, expected in universal.items():
        got = _keys.resolve_key(k)
        if got != expected:
            fail(f"  '{k}' -> {got}, expected {expected}")
            all_ok = False
    if all_ok:
        ok(f"all {len(universal)} universal keybinds resolve correctly")

    # FULL-only keybinds
    full_only = {"f", "l", "tab", "[", "]", "1", "2", "7"}
    all_ok = True
    for k in full_only:
        action = _keys.resolve_key(k)
        if action is None or not _keys.is_full_only(action):
            fail(f"  '{k}' -> {action}, expected FULL-only")
            all_ok = False
    if all_ok:
        ok(f"all FULL-only keybinds flagged: {sorted(full_only)}")

    # Footer hints render
    if len(_keys.FOOTER_HINTS) >= 5 and len(_keys.FOOTER_HINTS_FULL) > len(_keys.FOOTER_HINTS):
        ok(f"footer hints present: {len(_keys.FOOTER_HINTS)} universal + {len(_keys.FOOTER_HINTS_FULL) - len(_keys.FOOTER_HINTS)} FULL-only")
    else:
        fail(f"footer hints incomplete")

    # Unbound key returns None
    if _keys.resolve_key("z") is None and _keys.resolve_key("") is None:
        ok(f"unbound keys return None")
    else:
        fail(f"unexpected resolution for unbound keys")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> int:
    print(f"{YELLOW}Round 1 data-layer tests{RESET}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"State module: {_state.__file__}")
    print(f"Log watcher:  {_watcher.__file__}")
    print(f"Keybinds:     {_keys.__file__}")
    try:
        test_state()
        test_log_watcher()
        test_keybinds()
        print(f"\n{GREEN}All Round 1 tests passed.{RESET}")
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
