"""link service entry point. STUB: heartbeats only; the real transport loop is not built yet."""
import os
import signal
import time
from pathlib import Path


def main() -> None:
    hb = Path(os.environ.get("CORTEX_HB_DIR", "/run/cortex/hb")) / "link"
    hb.parent.mkdir(parents=True, exist_ok=True)
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    while not stop:
        hb.touch()
        time.sleep(1)


if __name__ == "__main__":
    main()
