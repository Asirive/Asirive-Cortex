"""Push app_textual.py + style.tcss + screenshot script to RPi5 and run."""
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
LOCAL_DIR = r"C:\Users\Haziq\Documents\ProjectCortex\rpi5\live_dashboard"
REMOTE_DIR = "/home/cortex/ProjectCortex/rpi5/live_dashboard"

# Push everything in live_dashboard
for root, _, files in os.walk(LOCAL_DIR):
    for f in files:
        if not f.endswith((".py", ".tcss")):
            continue
        local = os.path.join(root, f)
        rel = os.path.relpath(local, LOCAL_DIR).replace("\\", "/")
        with open(local, "rb") as fp:
            sftp.putfo(fp, REMOTE_DIR + "/" + rel)
        print(f"[push] {rel}")
sftp.close()

# Run the screenshot test
si, so, se = c.exec_command(
    "bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && timeout 30 python -m rpi5.live_dashboard.tests.round2b_screenshot 2>&1'",
    timeout=45,
)
print(so.read().decode("utf-8", errors="replace"))
err = se.read().decode("utf-8", errors="replace")
if err.strip():
    print("STDERR:", err[-2500:])

# Pull the screenshot back
sftp = c.open_sftp()
try:
    with sftp.open("/tmp/cortex_full_screenshot.svg", "rb") as f:
        svg_data = f.read()
    with open(r"C:\Users\Haziq\Documents\ProjectCortex\scripts\cortex_full_screenshot.svg", "wb") as f:
        f.write(svg_data)
    print(f"\n=== Saved screenshot ({len(svg_data)} bytes) to scripts/cortex_full_screenshot.svg ===")
except Exception as e:
    print(f"\n[screenshot] not available: {e}")
sftp.close()
c.close()
