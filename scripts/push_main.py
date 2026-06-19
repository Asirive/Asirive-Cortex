"""Push local main.py to RPi5 via SFTP."""
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()
LOCAL = r"C:\Users\Haziq\Documents\ProjectCortex\rpi5\main.py"
REMOTE = "/home/cortex/ProjectCortex/rpi5/main.py"

def main():
    client = get_ssh_client()
    client.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)
    sftp = client.open_sftp()
    try:
        print(f"Pushing {LOCAL} -> {REMOTE}")
        sftp.put(LOCAL, REMOTE)
        print("OK")
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    main()
