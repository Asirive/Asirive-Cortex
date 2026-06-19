"""Fetch a file from RPi5 to local via SFTP."""
import sys
from pathlib import Path
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()
REMOTE = sys.argv[1]
LOCAL = sys.argv[2]

def main():
    client = get_ssh_client()
    client.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)
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
