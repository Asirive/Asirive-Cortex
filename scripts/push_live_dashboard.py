"""Push local live_dashboard files to RPi5 via SFTP (paramiko)."""
import paramiko
import os
import sys
from pathlib import Path

HOST = "172.26.13.31"
USER = "cortex"
PASS = "REDACTED-RPI-PASSWORD"
REMOTE = "/home/cortex/ProjectCortex/rpi5/live_dashboard"
LOCAL = Path(r"C:\Users\Haziq\Documents\ProjectCortex\rpi5\live_dashboard")

def upload_dir(sftp, local_dir: Path, remote_dir: str):
    """Recursively upload local_dir -> remote_dir."""
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass  # already exists
    for entry in local_dir.iterdir():
        if entry.name == "__pycache__":
            continue
        if entry.name.startswith("."):
            continue
        rp = f"{remote_dir}/{entry.name}"
        if entry.is_file():
            # Only upload .py and .tcss files (skip tests dir contents)
            if entry.suffix not in (".py", ".tcss", ".md"):
                continue
            print(f"  {rp}")
            sftp.put(str(entry), rp)
        elif entry.is_dir():
            if entry.name == "tests":
                continue  # skip tests/ — not needed for the live dashboard on RPi5
            upload_dir(sftp, entry, rp)

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    sftp = client.open_sftp()
    try:
        upload_dir(sftp, LOCAL, REMOTE)
        print(f"OK: pushed {LOCAL} -> {REMOTE}")
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    main()
