"""Push Round 2a files to RPi5 and run tests."""
import io, os, sys
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

require_credentials()
c = get_ssh_client()
c.connect(RPI_HOST, 22, RPI_USER, RPI_PASSWORD, timeout=10, allow_agent=False, look_for_keys=False)

sftp = c.open_sftp()
LOCAL_DIR = r"C:\Users\Haziq\Documents\ProjectCortex\rpi5\live_dashboard"
REMOTE_DIR = "/home/cortex/ProjectCortex/rpi5/live_dashboard"

for root, _, files in os.walk(LOCAL_DIR):
    for f in files:
        if not f.endswith(".py"):
            continue
        local = os.path.join(root, f)
        rel = os.path.relpath(local, LOCAL_DIR).replace("\\", "/")
        with open(local, "rb") as fp:
            sftp.putfo(fp, REMOTE_DIR + "/" + rel)
        print(f"[push] {rel}")
sftp.close()

si, so, se = c.exec_command(
    "bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && timeout 30 python -m rpi5.live_dashboard.tests.round2a 2>&1'",
    timeout=45,
)
print(so.read().decode("utf-8", errors="replace"))
err = se.read().decode("utf-8", errors="replace")
if err.strip():
    print("STDERR:", err[-2000:])
c.close()
