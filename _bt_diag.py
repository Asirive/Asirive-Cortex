"""Quick BT diagnostic on RPi5 - connect, check device state."""
import sys
import time
from pathlib import Path

# Make scripts package importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()
c = get_ssh_client()
c.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)

# Kill cortex
c.exec_command('pkill -9 -f "python.*rpi5" 2>/dev/null')
time.sleep(1)
print("KILLED")

# Check CMF
i, o, e = c.exec_command('bluetoothctl info 2C:BE:EE:2D:9E:E6 2>/dev/null')
info = o.read().decode()
if not info.strip():
    print("CMF: NOT IN CACHE")
else:
    for line in info.split("\n"):
        line = line.strip()
        if any(k in line for k in ['Name:', 'Paired:', 'Bonded:', 'Trusted:', 'Connected:']):
            print(line)

# Paired list
i, o, e = c.exec_command('bluetoothctl devices Paired')
print("PAIRED:", o.read().decode().strip() or "(none)")

# LinkKey — sudo uses the SSH user's password, so we need to keep RPI_PASSWORD
# accessible. Never hardcode it (see scripts/_rpi_ssh.py).
i, o, e = c.exec_command(
    f"echo {RPI_PASSWORD} | sudo -S grep LinkKey "
    "/var/lib/bluetooth/2C:CF:67:A7:D2:45/2C:BE:EE:2D:9E:E6/info 2>/dev/null"
)
print("LINKKEY:", o.read().decode().strip() or "(missing)")

c.close()
print("DONE")
