"""Headless Cortex: the user build's brain service (cortex-brain.service). No screen, no SSH, nobody managing it.

    python -m cortex_core.brain        (systemd starts it at boot; scripts/engine/qnn.env sets the NPU paths)

It is the live session (engine + camera + mic + agent harness, cortex_core.tui.live.LiveSession) without the TUI:

  button   one line per press on the named pipe <run_dir>/button.fifo ("tap 12.345" / "long 12.345"), written by
           the safety service (the glasses button) or the link (the app's talk button). tap = the one button: listen
           on/off, or cut Cortex off while it talks. long is not assigned yet and is ignored.
  app      the owner's pause / mic mute from the phone are flag files in run_dir (link.phone_link.FileControls):
           assistant.paused stops listening and ignores the button; mic.muted drops the mic.
  voice    "Cortex ready." once it can listen; problems the user must know about (no mic, no camera, no map) are
           spoken, because the user cannot see a screen. Nothing the user says or sees is logged.
  systemd  READY=1 after start; WATCHDOG=1 on each tick only while the session's threads are alive, so a wedged
           voice or vision loop gets the service restarted.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import select
import stat
import threading
from pathlib import Path
from typing import Mapping, Optional

log = logging.getLogger("cortex.brain")

READY = "Cortex ready."
PAUSED = "Cortex paused."
RESUMED = "Cortex is back."
NO_MIC = "I can't hear you: no microphone is connected."
NO_CAMERA = "I can't see: no camera is connected."
NO_NAV = "Navigation is off: no map is installed."
LIB = "/opt/cortex/build/cortex-engine/libcortex_engine.so"
CONFIG = "/var/lib/cortex/bench/engine/engine.json"


def problems(cam_dev, mic_dev, nav_bundle) -> list[str]:
    out = []
    if not mic_dev:
        out.append(NO_MIC)
    if not cam_dev:
        out.append(NO_CAMERA)
    if not nav_bundle:
        out.append(NO_NAV)
    return out


class Headless:
    def __init__(self, session, engine, run_dir: str = "/run/cortex", watchdog=None):
        self.s, self.eng, self.run_dir = session, engine, run_dir
        self.dog = watchdog
        self.fifo = os.path.join(run_dir, "button.fifo")
        self.paused = False
        self.mic_muted = False
        self._stop = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ---- outputs
    def _say(self, text: str) -> None:
        try:
            for _ in self.eng.say(text):
                pass
        except Exception as e:  # noqa: BLE001 - a failed sentence must not stop the service
            log.warning("say failed: %s", type(e).__name__)

    # ---- inputs
    def on_button(self, kind: str) -> None:
        with self._lock:
            paused = self.paused
        if paused:
            return
        if kind == "tap":
            log.info("button: %s", self.s.button())

    def on_mic(self, pcm) -> None:
        if not self.mic_muted:
            self.s.on_mic(pcm)

    def _make_fifo(self) -> None:
        os.makedirs(self.run_dir, exist_ok=True)
        try:
            if not stat.S_ISFIFO(os.stat(self.fifo).st_mode):
                os.remove(self.fifo)
                os.mkfifo(self.fifo, 0o660)
        except FileNotFoundError:
            os.mkfifo(self.fifo, 0o660)

    def _read_buttons(self) -> None:
        rfd = os.open(self.fifo, os.O_RDONLY | os.O_NONBLOCK)
        wfd = os.open(self.fifo, os.O_WRONLY)  # our own writer: no EOF spin when the safety service reopens
        buf = b""
        try:
            while not self._stop.is_set():
                r, _, _ = select.select([rfd], [], [], 0.2)
                if not r:
                    continue
                try:
                    data = os.read(rfd, 4096)
                except BlockingIOError:
                    continue
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    parts = line.decode("ascii", "replace").split()
                    if parts and parts[0] in ("tap", "long"):
                        try:
                            self.on_button(parts[0])
                        except Exception:  # noqa: BLE001
                            log.exception("button handler failed")
                buf = buf[-256:]
        finally:
            os.close(rfd)
            os.close(wfd)

    # ---- lifecycle
    def start(self, problems: list[str]) -> None:
        self._make_fifo()
        self._reader = threading.Thread(target=self._read_buttons, name="button", daemon=True)
        self._reader.start()
        self.tick(pet=False)
        self._say(READY)
        for p in problems:
            self._say(p)
        if self.dog is not None:
            self.dog.ready()

    def alive(self) -> bool:
        return all(t.is_alive() for t in self.s._threads) and (self._reader is None or self._reader.is_alive())

    def tick(self, pet: bool = True) -> None:
        paused = os.path.exists(os.path.join(self.run_dir, "assistant.paused"))
        self.mic_muted = os.path.exists(os.path.join(self.run_dir, "mic.muted"))
        with self._lock:
            was, self.paused = self.paused, paused
        if paused and not was:
            if self.s.state.talking:
                self.eng.cancel()
            if self.s.state.listening:
                self.s.toggle_listening()
            self._say(PAUSED)
        elif was and not paused:
            self._say(RESUMED)
        if pet and self.dog is not None and self.alive():
            self.dog.pet()

    def run(self, problems: list[str], stop: threading.Event, tick_s: float = 2.0) -> None:
        self.start(problems)
        while not stop.wait(tick_s):
            self.tick()

    def close(self) -> None:
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=2)


def main(argv: Optional[list[str]] = None, env: Mapping[str, str] = os.environ) -> int:
    p = argparse.ArgumentParser(prog="python -m cortex_core.brain")
    p.add_argument("--lib", default=LIB)
    p.add_argument("--engine-config", default=CONFIG)
    p.add_argument("--camera", default="auto")
    p.add_argument("--mic", default="auto")
    p.add_argument("--run-dir", default="/run/cortex")
    p.add_argument("--native-log", type=Path, default=Path("/var/lib/cortex/log/engine_native.log"))
    p.add_argument("--nav-bundles", default="/var/lib/cortex/nav/bundles")
    p.add_argument("--saved-places", default="/var/lib/cortex/nav/saved_places.json")
    p.add_argument("--identity-dir", default="/var/lib/cortex/identity")
    p.add_argument("--tools", default="")
    p.add_argument("--gps-sock", default="/run/cortex/gps.sock")
    p.add_argument("--memory-db", default="/var/lib/cortex/memory/memory.db")
    p.add_argument("--max-tokens", type=int, default=0)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not os.path.exists(a.lib):
        print(f"engine library missing: {a.lib}")
        return 2

    import signal

    from cortex_core.engine import capture
    from cortex_core.engine.native import Engine
    from cortex_core.link import gps
    from cortex_core.nav import bundle as B
    from cortex_core.supervisor.supervisor import SdNotifyWatchdog
    from cortex_core.tui.__main__ import make_brain, native_output_to
    from cortex_core.tui.live import LiveSession

    cam_dev = capture.find_camera() if a.camera == "auto" else a.camera
    mic_dev = capture.find_mic() if a.mic == "auto" else a.mic
    native_output_to(a.native_log)
    try:
        bundle = B.latest(a.nav_bundles)
    except Exception:  # noqa: BLE001 - no map: Cortex still talks
        bundle = None
    eng = Engine(a.lib, json.loads(Path(a.engine_config).read_text()))
    cam = mic = listener = session = h = None
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        cam = capture.Camera(cam_dev) if cam_dev else None
        brain = make_brain(eng, a, cam) if bundle is not None else None
        session = LiveSession(eng, cam, max_tokens=a.max_tokens, brain=brain)
        if brain is not None:
            listener = gps.GpsListener(a.gps_sock, session.on_fix).start()
        h = Headless(session, eng, run_dir=a.run_dir, watchdog=SdNotifyWatchdog())
        if mic_dev:
            mic = capture.Mic(mic_dev, h.on_mic)
        session.start()
        h.run(problems(cam_dev, mic_dev, bundle), stop)
    finally:
        if h is not None:
            h.close()
        for x in (mic, cam):
            if x is not None:
                x.close()
        if listener is not None:
            listener.stop()
        if session is not None:
            session.close()
        eng.close()
    return 0
