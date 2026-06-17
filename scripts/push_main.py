"""Push local main.py to RPi5 via SFTP."""
import paramiko

HOST = "10.<REDACTED-RPI-IP>"
USER = "cortex"
PASS = "REDACTED-RPI-PASSWORD"
LOCAL = r"C:\Users\Haziq\Documents\ProjectCortex\rpi5\main.py"
REMOTE = "/home/cortex/ProjectCortex/rpi5/main.py"

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
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
