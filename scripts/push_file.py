"""Push a single local file to RPi5 via SFTP."""
import paramiko
import sys
from pathlib import Path

HOST = "10.202.14.31"
USER = "cortex"
PASS = "REDACTED-RPI-PASSWORD"
LOCAL = sys.argv[1]
REMOTE = sys.argv[2]

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    sftp = client.open_sftp()
    try:
        Path(REMOTE.rsplit("/", 1)[0]).__str__()  # noop for dir
        sftp.put(LOCAL, REMOTE)
        print(f"OK: {LOCAL} -> {REMOTE}")
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    main()
