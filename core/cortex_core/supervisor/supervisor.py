"""Starts services in order (safety first), restarts them with backoff, detects heartbeat stalls,
and pets the hardware watchdog only while safety and link are healthy.

If the supervisor itself dies the watchdog stops being petted and the board resets: that is intended.
"""
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol

BACKOFF_START_S, BACKOFF_MAX_S, STABLE_AFTER_S = 1.0, 30.0, 60.0


@dataclass
class Spec:
    name: str
    argv: List[str]
    heartbeat_timeout_s: Optional[float] = None  # None = process liveness only
    required_for_watchdog: bool = False          # safety and link


class Handle(Protocol):
    def poll(self) -> Optional[int]: ...
    def kill(self) -> None: ...


class Launcher(Protocol):
    def start(self, spec: Spec) -> Handle: ...


class SubprocessLauncher:
    def start(self, spec: Spec) -> Handle:
        return subprocess.Popen(spec.argv)  # type: ignore[return-value]


class _UnitHandle:
    def __init__(self, unit: str, run: Callable[[List[str]], int]): self.unit, self.run = unit, run
    def poll(self) -> Optional[int]:
        return None if self.run(["systemctl", "is-active", "--quiet", self.unit]) == 0 else 1
    def kill(self) -> None: self.run(["systemctl", "kill", "--signal=SIGKILL", self.unit])


class SystemdLauncher:
    """On the device systemd owns the processes (boot order, sandboxing, cgroups); the supervisor
    only asks it to (re)start units and polls their state, so the two never fight over a service."""
    def __init__(self, run: Callable[[List[str]], int] = lambda a: subprocess.call(a)): self.run = run
    def start(self, spec: Spec) -> Handle:
        unit = f"cortex-{spec.name}.service"
        self.run(["systemctl", "restart", unit])
        return _UnitHandle(unit, self.run)


class Watchdog(Protocol):
    def pet(self) -> None: ...


class SdNotifyWatchdog:
    """systemd WatchdogSec= keeper: sends WATCHDOG=1 on NOTIFY_SOCKET (also READY=1)."""
    def __init__(self) -> None:
        self.addr = os.environ.get("NOTIFY_SOCKET", "")

    def _send(self, msg: bytes) -> None:
        if not self.addr:
            return
        a = "\0" + self.addr[1:] if self.addr.startswith("@") else self.addr
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(msg, a)

    def ready(self) -> None: self._send(b"READY=1")
    def pet(self) -> None: self._send(b"WATCHDOG=1")


class FileHeartbeats:
    """Services touch <dir>/<name>; the supervisor reads the mtime. No sockets, no shared memory."""
    def __init__(self, directory: Path): self.dir = Path(directory); self.dir.mkdir(parents=True, exist_ok=True)
    def beat(self, name: str) -> None: (self.dir / name).touch()
    def last(self, name: str) -> Optional[float]:
        try: return (self.dir / name).stat().st_mtime
        except FileNotFoundError: return None


@dataclass
class _Run:
    spec: Spec
    handle: Optional[Handle] = None
    started: float = 0.0
    next_start: float = 0.0
    backoff: float = BACKOFF_START_S
    restarts: int = 0
    healthy: bool = False


class Supervisor:
    def __init__(self, specs: List[Spec], launcher: Launcher, heartbeats, watchdog: Watchdog,
                 on_degraded: Callable[[str], None] = lambda name: None, clock: Callable[[], float] = time.time):
        self.runs: Dict[str, _Run] = {s.name: _Run(s) for s in specs}  # dict keeps start order: safety first
        self.launcher, self.hb, self.wd, self.on_degraded, self.clock = launcher, heartbeats, watchdog, on_degraded, clock

    def _restart(self, r: _Run, now: float, why: str) -> None:
        if r.handle is not None and r.handle.poll() is None:
            r.handle.kill()
        r.handle, r.healthy = None, False
        if now - r.started > STABLE_AFTER_S:
            r.backoff = BACKOFF_START_S
        r.next_start = now + r.backoff
        r.backoff = min(r.backoff * 2, BACKOFF_MAX_S)
        r.restarts += 1
        if r.spec.required_for_watchdog:
            self.on_degraded(r.spec.name)  # fail-safe cue goes out right away, before the restart completes

    def tick(self) -> None:
        now = self.clock()
        for r in self.runs.values():
            if r.handle is None:
                if now >= r.next_start:
                    r.handle, r.started = self.launcher.start(r.spec), now
                r.healthy = False
                continue
            if r.handle.poll() is not None:
                self._restart(r, now, "exited")
                continue
            t = r.spec.heartbeat_timeout_s
            if t is not None:
                last = self.hb.last(r.spec.name)
                grace = now - r.started < t  # a fresh process gets one timeout to report in
                if (last is None or now - last > t) and not grace:
                    self._restart(r, now, "heartbeat stalled")
                    continue
            r.healthy = True
        if all(r.healthy for r in self.runs.values() if r.spec.required_for_watchdog):
            self.wd.pet()

    def status(self) -> Dict[str, dict]:
        return {n: {"running": r.handle is not None, "healthy": r.healthy, "restarts": r.restarts} for n, r in self.runs.items()}


def default_specs(py: str = "python3") -> List[Spec]:
    """Boot order: safety, link, then ota. The AI-side services join as they are built."""
    return [
        Spec("safety", [py, "-m", "cortex_core.safety"], heartbeat_timeout_s=1.0, required_for_watchdog=True),
        Spec("link", [py, "-m", "cortex_core.link"], heartbeat_timeout_s=5.0, required_for_watchdog=True),
        Spec("ota", [py, "-m", "cortex_core.ota"], heartbeat_timeout_s=60.0),
    ]
