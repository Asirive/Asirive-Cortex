"""Quick BT check on RPi5 — connect, kill cortex, list paired devices."""
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()
c = get_ssh_client()
c.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD)

# Kill the running cortex process
stdin, stdout, stderr = c.exec_command('pkill -f "python -m rpi5"')
time.sleep(1)
print("Killed cortex process")

# Disconnect any active BT
stdin, stdout, stderr = c.exec_command('bluetoothctl disconnect 2C:BE:EE:2D:9E:E6')
print("Disconnect:", stdout.read().decode().strip())
time.sleep(1)

# Check CMF status
stdin, stdout, stderr = c.exec_command('bluetoothctl info 2C:BE:EE:2D:9E:E6')
info = stdout.read().decode()
for line in info.split("\n"):
    if any(k in line for k in ['Name', 'Paired', 'Bonded', 'Trusted', 'Connected']):
        print(line.strip())

print()
stdin, stdout, stderr = c.exec_command('bluetoothctl devices Paired')
print("Paired list:", stdout.read().decode().strip())

# Check show for pairable
stdin, stdout, stderr = c.exec_command('bluetoothctl show | grep Pairable')
print(stdout.read().decode().strip())

c.close()
