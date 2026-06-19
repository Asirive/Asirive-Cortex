"""Push a single local file to RPi5 via SFTP."""
import sys
from pathlib import Path
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()
LOCAL = sys.argv[1]
REMOTE = sys.argv[2]

def main():
    client = get_ssh_client()
    client.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)
    sftp = client.open_sftp()
    try:
        sftp.put(LOCAL, REMOTE)
        print(f"OK: {LOCAL} -> {REMOTE}")
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    main()
