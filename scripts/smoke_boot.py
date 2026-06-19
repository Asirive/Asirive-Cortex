"""Boot smoke test: run 'python -m rpi5 all' on the Pi for N seconds, kill it, dump logs."""
import sys
import time
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()
TIMEOUT_S = 12

c = get_ssh_client()
c.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)
cmd = (
    f"bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && "
    f"timeout --signal=INT {TIMEOUT_S} python -m rpi5 all 2>&1' "
    f"| tail -80"
)
print(f"Running: timeout {TIMEOUT_S}s on Pi...")
si, so, se = c.exec_command(cmd, timeout=TIMEOUT_S + 10)
print("=== STDOUT ===")
print(so.read().decode("utf-8", errors="replace"))
err = se.read().decode("utf-8", errors="replace")
if err.strip():
    print("=== STDERR (last 2000) ===")
    print(err[-2000:])
c.close()
