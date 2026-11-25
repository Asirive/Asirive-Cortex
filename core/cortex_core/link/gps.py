"""GPS from the phone: validation, link -> brain forwarding over a unix datagram socket, dev recordings, replay.

    fix = parse_fix({"lat": 1.43, "lon": 103.83, "acc_m": 6, "speed": 1.2, "course": 90, "t": 1764000000.5})
    GpsForwarder("/run/cortex/gps.sock").send(fix)      # link side: never blocks, drops when nobody listens
    GpsListener("/run/cortex/gps.sock", on_fix).start()  # brain side: on_fix(fix dict) on its own thread
    GpsRecorder(state_dir).write(fix)                    # dev builds only: <state>/recordings/gps-YYYYMMDD.jsonl
    for fix in replay(path, speed=0): ...                # tests / bench: a real walk again

Positions are private (the user's home is in them): recordings stay on the box and are written only when
CORTEX_DEV_BUILD=1.
"""
from __future__ import annotations

import json
import logging
import math
import os
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

log = logging.getLogger("cortex.gps")
SOCK = "/run/cortex/gps.sock"


class FixError(ValueError):
    pass


def _num(a: dict, k: str, lo: float, hi: float, required: bool = True) -> float | None:
    v = a.get(k)
    if v is None:
        if required:
            raise FixError(f"{k} missing")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise FixError(f"{k} is not a number")
    if not lo <= v <= hi:
        raise FixError(f"{k} out of range")
    return float(v)


def parse_fix(a: dict, now: Callable[[], float] = time.time) -> dict:
    """The app's {lat, lon, acc_m, speed?, course?, t?} checked and normalised (t defaults to now)."""
    if not isinstance(a, dict):
        raise FixError("not an object")
    fix = {"lat": _num(a, "lat", -90, 90), "lon": _num(a, "lon", -180, 180), "acc_m": _num(a, "acc_m", 0, 10_000)}
    sp = _num(a, "speed", 0, 100, False)  # m/s; the phone sends -1 when unknown: refused as out of range
    co = _num(a, "course", 0, 360, False)
    t = _num(a, "t", 0, 1e11, False)
    fix["speed"] = sp
    fix["course"] = co
    fix["t"] = t if t is not None else now()
    return fix


class GpsForwarder:
    def __init__(self, path: str = SOCK):
        self.path = path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.dropped = 0

    def send(self, fix: dict) -> bool:
        try:
            self.sock.sendto(json.dumps(fix, separators=(",", ":")).encode(), self.path)
            return True
        except (FileNotFoundError, ConnectionRefusedError, BlockingIOError, OSError):
            self.dropped += 1  # nobody listening (brain restarting): the next fix comes in a second
            return False

    def close(self) -> None:
        self.sock.close()


class GpsListener:
    def __init__(self, path: str, on_fix: Callable[[dict], None]):
        self.path = path
        self.on_fix = on_fix
        self._stop = threading.Event()
        self._th: threading.Thread | None = None
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(path)
        self.sock.settimeout(0.2)

    def start(self) -> "GpsListener":
        self._th = threading.Thread(target=self._run, name="gps-listen", daemon=True)
        self._th.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                fix = parse_fix(json.loads(raw))
            except (ValueError, FixError):
                log.warning("bad fix datagram dropped")
                continue
            try:
                self.on_fix(fix)
            except Exception:  # noqa: BLE001 - a nav bug must not stop GPS
                log.exception("on_fix failed")

    def stop(self) -> None:
        self._stop.set()
        if self._th:
            self._th.join(1)
        self.sock.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


class GpsRecorder:
    def __init__(self, state_dir: str | Path, enabled: bool | None = None):
        self.dir = Path(state_dir) / "recordings"
        self.enabled = os.environ.get("CORTEX_DEV_BUILD") == "1" if enabled is None else enabled

    def write(self, fix: dict) -> Path | None:
        if not self.enabled:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.dir / time.strftime("gps-%Y%m%d.jsonl", time.localtime(fix["t"]))
        with p.open("a") as f:
            f.write(json.dumps(fix, separators=(",", ":")) + "\n")
        return p


def replay(path: str | Path, speed: float = 0.0) -> Iterator[dict]:
    """Fixes from a recording; speed 1 = real time, 0 = as fast as possible."""
    prev = None
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        fix = parse_fix(json.loads(line))
        if speed > 0 and prev is not None and fix["t"] > prev:
            time.sleep((fix["t"] - prev) / speed)
        prev = fix["t"]
        yield fix
