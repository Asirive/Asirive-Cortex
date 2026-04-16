"""Quick BT diagnostic - self-contained."""
import sys
sys.path.insert(0, r"C:\Users\Haziq\Documents\ProjectCortex")
import paramiko, time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('10.245.247.31', username='cortex', password='REDACTED-RPI-PASSWORD')

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

# LinkKey  
i, o, e = c.exec_command('echo REDACTED-RPI-PASSWORD | sudo -S grep LinkKey /var/lib/bluetooth/2C:CF:67:A7:D2:45/2C:BE:EE:2D:9E:E6/info 2>/dev/null')
print("LINKKEY:", o.read().decode().strip() or "(missing)")

c.close()
print("DONE")
