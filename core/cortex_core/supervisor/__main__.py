"""Supervisor entry point (systemd Type=notify, WatchdogSec)."""
import os
import signal
import time
from pathlib import Path

from cortex_core.supervisor.supervisor import FileHeartbeats, SdNotifyWatchdog, SubprocessLauncher, Supervisor, SystemdLauncher, default_specs


def main() -> None:
    wd = SdNotifyWatchdog()
    sup = Supervisor(default_specs(), SystemdLauncher() if os.environ.get("NOTIFY_SOCKET") else SubprocessLauncher(), FileHeartbeats(Path(os.environ.get("CORTEX_HB_DIR", "/run/cortex/hb"))), wd,
                     on_degraded=lambda n: print(f"DEGRADED {n}", flush=True))  # TODO: wire to the hardware haptic fail-safe cue
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    wd.ready()
    while not stop:
        sup.tick()
        time.sleep(0.25)


if __name__ == "__main__":
    main()
