"""python -m cortex_core.tui [--state-dir DIR]                       (needs CORTEX_DEV_BUILD=1)
python -m cortex_core.tui --live [--camera DEV] [--mic DEV] ...       talk to Cortex with the real camera and mic
python -m cortex_core.tui --live --nav ...                            ... through the agent harness (tools, modes,
                                                                      navigation; GPS from the link's socket)

--live opens the engine (libcortex_engine.so) in this process: run it through core/scripts/engine/live_tui.sh on the
box, which sets the QNN library paths."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Mapping, Optional

REFUSAL = "The terminal UI is for developer builds only (set CORTEX_DEV_BUILD=1)."
LIB = "/opt/cortex/build/cortex-engine/libcortex_engine.so"
CONFIG = "/var/lib/cortex/bench/engine/engine.json"


def native_output_to(path: Path) -> None:
    """llama.cpp and QNN print to fd 1/2 from native threads, which would tear the screen. Send fds 1 and 2 to a log
    file and give Python (and Textual, which draws on sys.__stderr__) copies of the terminal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tty_out, tty_err = os.dup(1), os.dup(2)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    sys.stdout = sys.__stdout__ = os.fdopen(tty_out, "w", buffering=1)
    sys.stderr = sys.__stderr__ = os.fdopen(tty_err, "w", buffering=1)


def gateway_arrivals(identity_dir: str | None):
    """Live bus arrivals through the gateway when this box is claimed (else None: headway estimates)."""
    from cortex_core.link import provision

    try:
        p = provision.load(identity_dir) if identity_dir else None
    except (OSError, ValueError, KeyError):  # unreadable as this user, half-written
        p = None
    return provision.arrivals_client(p) if p is not None else None


def make_brain(eng, a: argparse.Namespace):
    """The agent harness over the engine: the newest nav bundle, the box's saved places, the tools contract."""
    from cortex_core.brain import tools as T
    from cortex_core.brain.brain import Brain
    from cortex_core.nav import bundle as B
    from cortex_core.nav.service import NavService

    b = B.Bundle(B.latest(a.nav_bundles))
    nav = NavService(b, saved=a.saved_places, arrivals=gateway_arrivals(a.identity_dir))
    reg = T.load(a.tools) if a.tools else T.load()
    return Brain(eng, nav, reg)


def live(a: argparse.Namespace) -> int:
    from cortex_core.engine import capture
    from cortex_core.engine.native import Engine
    from cortex_core.tui.live import LiveSession
    from cortex_core.tui.live_app import LiveTUI  # Textual is a dev-only dependency
    from cortex_core.tui.state import Collector

    cam_dev = capture.find_camera() if a.camera == "auto" else a.camera
    mic_dev = capture.find_mic() if a.mic == "auto" else a.mic
    native_output_to(a.native_log)
    print(f"camera {cam_dev or 'none'} · mic {mic_dev or 'none'} · opening the engine (about 10 s)…\n"
          f"engine messages: {a.native_log}", flush=True)
    config = json.loads(Path(a.engine_config).read_text())
    eng = Engine(a.lib, config)
    cam = mic = None
    session = listener = None
    try:
        cam = capture.Camera(cam_dev) if cam_dev else None
        brain = make_brain(eng, a) if a.nav else None
        session = LiveSession(eng, cam, refresh_s=a.refresh_s, max_tokens=a.max_tokens, brain=brain)
        if brain is not None:
            from cortex_core.link import gps
            listener = gps.GpsListener(a.gps_sock, session.on_fix).start()  # fixes forwarded by the link service
            session.note(f"agent harness on · nav bundle {brain.nav.b.path.name} · GPS from {a.gps_sock}")
        if mic_dev:
            mic = capture.Mic(mic_dev, session.on_mic)
        else:
            session.note("no USB mic found: listening has nothing to hear (use --mic)")
        if cam is None:
            session.note("no camera found: answers have no view (use --camera)")
        session.start()
        LiveTUI(session, Collector(a.state_dir)).run()
    finally:
        for p in (mic, cam):
            if p is not None:
                p.close()
        if listener is not None:
            listener.stop()
        if session is not None:
            session.close()
        eng.close()
    return 0


def main(argv: Optional[list[str]] = None, env: Mapping[str, str] = os.environ) -> int:
    if env.get("CORTEX_DEV_BUILD") != "1":
        print(REFUSAL)
        return 2
    p = argparse.ArgumentParser(prog="python -m cortex_core.tui")
    p.add_argument("--state-dir", type=Path, default=Path("/var/lib/cortex"))
    p.add_argument("--live", action="store_true", help="talk to the engine with the real camera and mic")
    p.add_argument("--lib", default=LIB)
    p.add_argument("--engine-config", default=CONFIG)
    p.add_argument("--camera", default="auto", help="V4L2 device, auto = first non-codec node")
    p.add_argument("--mic", default="auto", help="ALSA capture device, auto = first USB audio card")
    p.add_argument("--refresh-s", type=float, default=1.0, help="at most one view refresh per this many seconds")
    p.add_argument("--max-tokens", type=int, default=0, help="0: the engine's limit")
    p.add_argument("--native-log", type=Path, default=Path("/var/lib/cortex/bench/engine/live_native.log"),
                   help="where llama.cpp / QNN messages go in --live")
    p.add_argument("--nav", action="store_true", help="host the agent harness: tools, modes, navigation, GPS")
    p.add_argument("--nav-bundles", default="/var/lib/cortex/nav/bundles", help="newest bundle here is used")
    p.add_argument("--saved-places", default="/var/lib/cortex/nav/saved_places.json")
    p.add_argument("--identity-dir", default="/var/lib/cortex/identity",
                   help="claimed-box identity; live bus arrivals go through its gateway (missing = headway estimates)")
    p.add_argument("--tools", default="", help="tools.json (default: the contract the package finds)")
    p.add_argument("--gps-sock", default="/run/cortex/gps.sock")
    a = p.parse_args(argv)
    if a.live:
        return live(a)
    from cortex_core.tui.app import CortexTUI
    from cortex_core.tui.state import Collector
    CortexTUI(Collector(a.state_dir)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
