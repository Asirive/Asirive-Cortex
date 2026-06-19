"""Quick script to make BT pairable permanent on RPi5."""
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

require_credentials()
c = get_ssh_client()
c.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD)

# Set AlwaysPairable = true in BlueZ config (sudo uses SSH password from env)
sed_cmd = f'echo {RPI_PASSWORD} | sudo -S sed -i "s/^#AlwaysPairable = false/AlwaysPairable = true/" /etc/bluetooth/main.conf'
stdin, stdout, stderr = c.exec_command(sed_cmd)
print("sed:", stderr.read().decode().strip()[:200])

# Verify
stdin, stdout, stderr = c.exec_command('grep -i pairable /etc/bluetooth/main.conf')
print("Config:", stdout.read().decode().strip())

# Restart bluetooth
stdin, stdout, stderr = c.exec_command(f'echo {RPI_PASSWORD} | sudo -S systemctl restart bluetooth')
time.sleep(3)
print("Bluetooth restarted")

# Check pairable
stdin, stdout, stderr = c.exec_command('bluetoothctl show | grep Pairable')
print(stdout.read().decode().strip())

# Verify CMF still paired
stdin, stdout, stderr = c.exec_command('bluetoothctl devices Paired')
print("Paired:", stdout.read().decode().strip())

c.close()
