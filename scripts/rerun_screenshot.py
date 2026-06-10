"""Clear Python caches and re-run the screenshot test on RPi5."""
import paramiko

HOST = "172.26.13.31"
USER = "cortex"
PASS = "Haziqshah21"

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    try:
        commands = [
            "find ~/ProjectCortex/rpi5/live_dashboard -name __pycache__ -exec rm -rf {} + 2>/dev/null; find ~/ProjectCortex/rpi5 -name __pycache__ -exec rm -rf {} + 2>/dev/null; echo caches_cleared",
            "cd ~/ProjectCortex && source venv/bin/activate && python -m rpi5.live_dashboard.tests.round2b_screenshot 2>&1 | tail -10",
        ]
        for cmd in commands:
            print(f"=== {cmd}")
            stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
            print(stdout.read().decode("utf-8", errors="replace"))
            err = stderr.read().decode("utf-8", errors="replace")
            if err.strip():
                print("STDERR:", err)
    finally:
        client.close()

if __name__ == "__main__":
    main()
