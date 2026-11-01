"""Safety service entry point. STUB I/O: no real ToF driver or haptic/audio sinks yet, so on a real
device this reports 'safety degraded' (the honest answer) until the drivers are written."""
import os
import signal
from pathlib import Path

from cortex_core.safety.engine import SafetyService, SensorError


class NoSensor:
    def read(self):
        raise SensorError("ToF driver not implemented")


class LogOut:
    def haptic(self, pattern, clock=None): print("HAPTIC", pattern, clock, flush=True)
    def cue(self, cue_id, clock=None): print("CUE", cue_id, clock, flush=True)


def main() -> None:
    hb = Path(os.environ.get("CORTEX_HB_DIR", "/run/cortex/hb")) / "safety"
    hb.parent.mkdir(parents=True, exist_ok=True)
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    SafetyService(NoSensor(), LogOut(), hb.touch).run(lambda: bool(stop))


if __name__ == "__main__":
    main()
