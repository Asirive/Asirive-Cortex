"""
Run the binaural 3D audio sweep test on RPi5 via SSH.
Plays a tone that rotates 360 degrees around your head.
Temporary script - delete after use.
"""
from scripts._rpi_ssh import (
    RPI_HOST,
    RPI_PASSWORD,
    RPI_USER,
    get_ssh_client,
    require_credentials,
)
require_credentials()
import paramiko  # noqa: E402  (imported after env check)

ssh = get_ssh_client()
ssh.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)

def run(cmd, timeout=60):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err

python = "/home/cortex/ProjectCortex/venv/bin/python"

# Run the binaural 3D test - sweep mode (360° rotation)
print("=== Running binaural 3D sweep test ===")
print("You should hear a sound rotating around your head.\n")

out, err = run(
    f"cd /home/cortex/ProjectCortex && {python} tests/test_binaural_3d.py --sweep",
    timeout=45
)
print(f"Output:\n{out}")
if err:
    # Filter out normal warnings
    important = [l for l in err.split('\n') if 'error' in l.lower() or 'traceback' in l.lower() or 'import' in l.lower()]
    if important:
        print(f"\nErrors:\n" + '\n'.join(important))
    elif 'Traceback' in err:
        print(f"\nFull stderr:\n{err}")

ssh.close()
print("\nDone. Did you hear the sound rotating around your head?")
