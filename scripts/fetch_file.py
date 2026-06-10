"""Fetch a file from RPi5 to local via SFTP."""
import paramiko
import sys
from pathlib import Path

HOST = "172.26.13.31"
USER = "cortex"
PASS = "Haziqshah21"
REMOTE = sys.argv[1]
LOCAL = sys.argv[2]

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    sftp = client.open_sftp()
    try:
        Path(LOCAL).parent.mkdir(parents=True, exist_ok=True)
        sftp.get(REMOTE, LOCAL)
        print(f"OK: {REMOTE} -> {LOCAL}")
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    main()
