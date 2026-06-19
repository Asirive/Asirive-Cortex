"""Run a Python command on RPi5 over SSH and return the output."""
import sys
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()
CMD = sys.argv[1] if len(sys.argv) > 1 else "ls -la"

def main():
    client = get_ssh_client()
    client.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)
    try:
        stdin, stdout, stderr = client.exec_command(CMD, timeout=60)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        print("STDOUT:")
        print(out)
        if err.strip():
            print("STDERR:")
            print(err)
        print(f"EXIT={stdout.channel.recv_exit_status()}")
    finally:
        client.close()

if __name__ == "__main__":
    main()
