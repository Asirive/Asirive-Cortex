"""Quick script to make BT pairable permanent on RPi5."""
import paramiko
import time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('10.135.122.31', username='cortex', password='REDACTED-RPI-PASSWORD')

# Set AlwaysPairable = true in BlueZ config
sed_cmd = 'echo REDACTED-RPI-PASSWORD | sudo -S sed -i "s/^#AlwaysPairable = false/AlwaysPairable = true/" /etc/bluetooth/main.conf'
stdin, stdout, stderr = c.exec_command(sed_cmd)
print("sed:", stderr.read().decode().strip()[:200])

# Verify
stdin, stdout, stderr = c.exec_command('grep -i pairable /etc/bluetooth/main.conf')
print("Config:", stdout.read().decode().strip())

# Restart bluetooth
stdin, stdout, stderr = c.exec_command('echo REDACTED-RPI-PASSWORD | sudo -S systemctl restart bluetooth')
time.sleep(3)
print("Bluetooth restarted")

# Check pairable
stdin, stdout, stderr = c.exec_command('bluetoothctl show | grep Pairable')
print(stdout.read().decode().strip())

# Verify CMF still paired
stdin, stdout, stderr = c.exec_command('bluetoothctl devices Paired')
print("Paired:", stdout.read().decode().strip())

c.close()
