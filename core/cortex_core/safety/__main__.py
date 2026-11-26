"""Safety service entry point: ToF/IMU frames in and haptic patterns out over the glasses' USB safety channel
(cortex_core/safety/glasses.py; the port is /dev/cortex-glasses-safety, made by deploy/udev/70-cortex-glasses.rules).
No glasses, or glasses that stop sending: the service reports "safety degraded" (the engine's blind path), and the
glasses, missing the heartbeat, vibrate "degraded" on their own.

Environment:
  CORTEX_GLASSES_TTY   the port (default /dev/cortex-glasses-safety)
  CORTEX_BUTTON_FIFO   named pipe the brain reads button presses from (default /run/cortex/button.fifo)
  CORTEX_SAFETY_CFG    JSON with the wearer's fit, e.g. {"version": 1, "sensor_height_m": 1.62}; missing or
                       invalid: the defaults (engine config.load)
  CORTEX_HB_DIR        heartbeat directory the supervisor watches"""
import json
import os
import signal
import sys
from pathlib import Path

from cortex_core.safety.engine import SafetyService
from cortex_core.safety.glasses import ButtonFifo, GlassesOut, GlassesSensor, Link


def load_cfg(path: str):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def main() -> None:
    hb = Path(os.environ.get("CORTEX_HB_DIR", "/run/cortex/hb")) / "safety"
    hb.parent.mkdir(parents=True, exist_ok=True)
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    link = Link(os.environ.get("CORTEX_GLASSES_TTY", "/dev/cortex-glasses-safety"))
    sensor = GlassesSensor(link, on_button=ButtonFifo(os.environ.get("CORTEX_BUTTON_FIFO", "/run/cortex/button.fifo")))
    out = GlassesOut(link, lambda line: print(line, file=sys.stderr, flush=True))
    cfg = load_cfg(os.environ.get("CORTEX_SAFETY_CFG", "/etc/cortex/safety.json"))
    SafetyService(sensor, out, hb.touch, cfg).run(lambda: bool(stop))


if __name__ == "__main__":
    main()
