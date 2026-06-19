"""Clear Python caches and re-run the screenshot test on RPi5."""
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()

def main():
    client = get_ssh_client()
    client.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)
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
