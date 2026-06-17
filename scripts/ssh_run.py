"""Run a Python command on RPi5 over SSH and return the output."""
import paramiko
import sys

HOST = "10.<REDACTED-RPI-IP>"
USER = "cortex"
PASS = "REDACTED-RPI-PASSWORD"
CMD = sys.argv[1] if len(sys.argv) > 1 else "ls -la"

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
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
