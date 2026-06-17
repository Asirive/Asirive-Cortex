"""Push the live_dashboard package to RPi5 and run Round 1 test."""
import io, sys
import paramiko

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("10.<REDACTED-RPI-IP>", 22, "cortex", "REDACTED-RPI-PASSWORD", timeout=10, allow_agent=False, look_for_keys=False)

sftp = c.open_sftp()

LOCAL_DIR = r"C:\Users\Haziq\Documents\ProjectCortex\rpi5\live_dashboard"
REMOTE_DIR = "/home/cortex/ProjectCortex/rpi5/live_dashboard"

# Ensure remote dirs exist
for sub in ("", "/tests"):
    path = REMOTE_DIR + sub
    try:
        sftp.mkdir(path)
    except IOError:
        pass  # already exists

# Upload each file
import os
for root, _, files in os.walk(LOCAL_DIR):
    for f in files:
        if not f.endswith(".py"):
            continue
        local_path = os.path.join(root, f)
        rel = os.path.relpath(local_path, LOCAL_DIR).replace("\\", "/")
        remote_path = REMOTE_DIR + "/" + rel
        with open(local_path, "rb") as fp:
            sftp.putfo(fp, remote_path)
        print(f"[push] {rel}")
sftp.close()

# Run the test
si, so, se = c.exec_command(
    "bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && timeout 60 python -m rpi5.live_dashboard.tests.round1 2>&1'",
    timeout=75,
)
out = (so.read() + se.read()).decode("utf-8", errors="replace")
print(out)
c.close()
