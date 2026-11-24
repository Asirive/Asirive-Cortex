"""python -m cortex_core.tui [--state-dir DIR]                       (needs CORTEX_DEV_BUILD=1)
python -m cortex_core.tui --live [--camera DEV] [--mic DEV] ...       talk to Cortex with the real camera and mic

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
    session = None
    try:
        cam = capture.Camera(cam_dev) if cam_dev else None
        session = LiveSession(eng, cam, refresh_s=a.refresh_s, max_tokens=a.max_tokens)
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
    p.add_argument("--max-tokens", type=int, default=60)
    p.add_argument("--native-log", type=Path, default=Path("/var/lib/cortex/bench/engine/live_native.log"),
                   help="where llama.cpp / QNN messages go in --live")
    a = p.parse_args(argv)
    if a.live:
        return live(a)
    from cortex_core.tui.app import CortexTUI
    from cortex_core.tui.state import Collector
    CortexTUI(Collector(a.state_dir)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
