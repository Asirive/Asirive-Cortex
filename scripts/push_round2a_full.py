"""Push all Round 2a files (including integration) and run unit test."""
import io, os, sys
import paramiko

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("172.26.13.31", 22, "cortex", "Haziqshah21", timeout=10, allow_agent=False, look_for_keys=False)

sftp = c.open_sftp()

# Push live_dashboard package
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
print("[push] live_dashboard/* (4 files)")

# Push the integration changes in rpi5/main.py and rpi5/__main__.py
for local_path, remote_path in [
    (r"C:\Users\Haziq\Documents\ProjectCortex\rpi5\main.py", "/home/cortex/ProjectCortex/rpi5/main.py"),
    (r"C:\Users\Haziq\Documents\ProjectCortex\rpi5\__main__.py", "/home/cortex/ProjectCortex/rpi5/__main__.py"),
]:
    with open(local_path, "rb") as fp:
        sftp.putfo(fp, remote_path)
    print(f"[push] {os.path.basename(local_path)}")

sftp.close()

# 1. Sanity import check
print("\n=== import check ===")
si, so, se = c.exec_command(
    "bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && python -c \"from rpi5.live_dashboard.state import DashboardState; from rpi5.live_dashboard.app_console import ConsoleApp; from rpi5.main import CortexSystem; print(\\\"[OK] all imports ok\\\")\"'",
    timeout=20,
)
print(so.read().decode("utf-8", errors="replace"))
err = se.read().decode("utf-8", errors="replace")
if err.strip():
    print("STDERR:", err[-2000:])

# 2. Verify --2.4 arg was added
print("\n=== --2.4 flag registered ===")
si, so, se = c.exec_command(
    "bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && python -m rpi5 all --help 2>&1 | grep -A1 -- --2.4 || echo NOT_FOUND'",
    timeout=20,
)
print(so.read().decode("utf-8", errors="replace"))
err = se.read().decode("utf-8", errors="replace")
if err.strip():
    print("STDERR:", err[-1500:])

# 3. Run round2a test
print("\n=== Round 2a unit test ===")
si, so, se = c.exec_command(
    "bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && timeout 30 python -m rpi5.live_dashboard.tests.round2a 2>&1 | tail -50'",
    timeout=45,
)
print(so.read().decode("utf-8", errors="replace"))
err = se.read().decode("utf-8", errors="replace")
if err.strip():
    print("STDERR:", err[-1500:])

c.close()
