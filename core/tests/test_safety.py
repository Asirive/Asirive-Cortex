import ast
import socket
import subprocess
from pathlib import Path

import pytest

from cortex_core.safety.engine import DEFAULT_THRESHOLDS_MM, SafetyService, load_thresholds

FAR = [None] * 7


class FakeOut:
    def __init__(self): self.haptics, self.cues = [], []
    def haptic(self, p, clock=None): self.haptics.append((p, clock))
    def cue(self, c, clock=None): self.cues.append((c, clock))


class Seq:
    def __init__(self, frames): self.f = list(frames)
    def read(self):
        x = self.f.pop(0) if len(self.f) > 1 else self.f[0]
        if isinstance(x, Exception):
            raise x
        return x


def svc(frames, t=None, out=None):
    out = out or FakeOut()
    beats = []
    t0 = [0.0]
    s = SafetyService(Seq(frames), out, lambda: beats.append(1), clock=lambda: t0.__setitem__(0, t0[0] + 0.1) or t0[0])
    s.beats = beats
    return s, out


def test_hazard_alerts_with_clock_position_and_heartbeat():
    s, out = svc([[None, None, None, 400, None, None, None]])
    a = s.step()
    assert (a.tier, a.clock) == ("T3", 12)
    assert out.haptics[0] == ("T3", 12) and out.cues[0] == ("hazard_t3", 12) and len(s.beats) == 1


def test_clear_path_is_quiet_and_nearest_zone_wins():
    s, out = svc([FAR, [2000, 800, None, None, None, None, 1400]])
    assert s.step() is None and not out.haptics
    assert s.step().clock == 10  # 800 mm (T2) beats 1400 mm (T1)


def test_nan_and_negative_readings_do_not_crash_or_alert():
    s, _ = svc([[float("nan"), -5, None, None, None, None, None]])
    assert s.step() is None


def test_sensor_failure_is_never_silent():
    s, out = svc([RuntimeError("i2c"), RuntimeError("i2c"), RuntimeError("i2c")])
    for _ in range(3):
        s.step()
    assert s.degraded and ("degraded", None) in out.haptics and ("safety_degraded", None) in out.cues
    n = len(out.cues)
    s.step()
    assert len(out.cues) == n  # rate limited, but it repeats every 5 s until the sensor returns


def test_bad_config_falls_back_to_safe_defaults_never_off():
    for bad in (None, {}, {"T0": 0, "T1": 0, "T2": 0, "T3": 0}, {"T0": 100, "T1": 200, "T2": 300, "T3": 400}, {"T0": "x"}, "junk"):
        assert load_thresholds(bad) == DEFAULT_THRESHOLDS_MM
    assert load_thresholds({"T0": 3000, "T1": 2000, "T2": 1000, "T3": 500})["T3"] == 500


def test_alerts_continue_when_network_model_and_phone_are_dead(monkeypatch):
    """Poison every way out of the process; safety must neither touch them nor care."""
    def boom(*a, **k): raise ConnectionError("network/phone/model unavailable")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    s, out = svc([[None, None, None, 300, None, None, None]] * 3)
    for _ in range(3):
        assert s.step().tier == "T3"
    assert len(out.haptics) == 3  # T3 re-alerts every step


def test_output_fault_does_not_kill_the_loop():
    class Flaky(FakeOut):
        n = 0
        def haptic(self, p, clock=None):
            Flaky.n += 1
            if Flaky.n == 1:
                raise OSError("haptic driver busy")
            super().haptic(p, clock)
    s, out = svc([[None, None, None, 300, None, None, None]], out=Flaky())
    stops = iter([False, False, True])
    s.run(lambda: next(stops), sleep=lambda _: None)
    assert out.haptics  # second iteration alerted


def test_safety_package_imports_nothing_but_stdlib_and_itself():
    """Static guard for AGENTS.md rule 1: no agent/voice/perception/link/ota/network/phone imports."""
    forbidden = {"socket", "ssl", "http", "urllib", "requests", "asyncio", "subprocess", "multiprocessing",
                 "cortex_core.link", "cortex_core.ota", "cortex_core.supervisor", "cortex_core.contracts",
                 "agent", "voice", "perception", "grpc", "google"}
    for f in (Path(__file__).resolve().parents[1] / "cortex_core" / "safety").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for m in mods:
                assert not any(m == x or m.startswith(x + ".") for x in forbidden), f"{f.name} imports {m}"
