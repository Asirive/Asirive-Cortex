"""Re-run the RPi5 test with longer timeout and output streaming."""
import io
import sys
import time
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

require_credentials()
c = get_ssh_client()
c.connect(RPI_HOST, 22, RPI_USER, RPI_PASSWORD, timeout=10, allow_agent=False, look_for_keys=False)
print(f"[OK] Connected to {RPI_USER}@{RPI_HOST}")

# Run with streaming output, longer timeout
print("\n>>> Running test on RPi5 (max 90s)...")
cmd = "cd ~/ProjectCortex && source venv/bin/activate && timeout 90 python scripts/test_live_now.py 2>&1"
stdin, stdout, stderr = c.exec_command(cmd, timeout=120)

# Stream line by line
start = time.time()
buffer = ""
try:
    while True:
        if time.time() - start > 100:
            print("\n[TIMEOUT] Killing process")
            break
        if stdout.channel.recv_ready():
            chunk = stdout.channel.recv(4096).decode("utf-8", errors="replace")
            sys.stdout.write(chunk)
            sys.stdout.flush()
        elif stdout.channel.exit_status_ready():
            # Drain remaining
            chunk = stdout.channel.recv(4096).decode("utf-8", errors="replace")
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()
            break
        else:
            time.sleep(0.5)
except Exception as e:
    print(f"\n[ERROR] {e}")

rc = stdout.channel.recv_exit_status()
print(f"\n[exit code: {rc}]")
c.close()
