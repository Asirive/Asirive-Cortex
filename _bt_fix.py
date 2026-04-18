"""Fix BT state - kill app, verify pairing, clean state."""
import paramiko, time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('10.131.52.31', username='cortex', password='Haziqshah21')

# 1. Kill any running cortex processes
print("=== Killing cortex processes ===")
stdin, stdout, stderr = c.exec_command('pkill -9 -f "python.*rpi5" 2>/dev/null; echo done')
print(stdout.read().decode().strip())
time.sleep(2)

# 2. Check current BT state
print("\n=== Current BT State ===")
stdin, stdout, stderr = c.exec_command('bluetoothctl show | grep -E "Powered|Pairable|Discovering"')
print(stdout.read().decode().strip())

stdin, stdout, stderr = c.exec_command('bluetoothctl info 2C:BE:EE:2D:9E:E6 2>/dev/null')
info = stdout.read().decode()
if "not available" in info.lower() or not info.strip():
    print("CMF Buds: NOT in BT cache (need scan + pair)")
else:
    for line in info.split("\n"):
        if any(k in line for k in ['Name', 'Paired', 'Bonded', 'Trusted', 'Connected']):
            print(line.strip())

# Check paired list
stdin, stdout, stderr = c.exec_command('bluetoothctl devices Paired')
paired = stdout.read().decode().strip()
print("Paired list:", paired if paired else "(empty)")

# 3. Check LinkKey
stdin, stdout, stderr = c.exec_command(
    'echo Haziqshah21 | sudo -S grep LinkKey /var/lib/bluetooth/2C:CF:67:A7:D2:45/2C:BE:EE:2D:9E:E6/info 2>/dev/null'
)
linkkey = stdout.read().decode().strip()
print("LinkKey:", linkkey if linkkey else "(missing)")

# If paired + bonded, just ensure clean disconnect for app
if "2C:BE:EE:2D:9E:E6" in paired:
    print("\n=== CMF is paired! Disconnecting for app to manage ===")
    stdin, stdout, stderr = c.exec_command('bluetoothctl disconnect 2C:BE:EE:2D:9E:E6')
    print(stdout.read().decode().strip())
    print("Ready for: python -m rpi5 all --earbuds in")
else:
    # Need to re-pair
    print("\n=== CMF NOT paired - need to scan and pair ===")
    print("Put CMF Buds in pairing mode, then run this again.")

c.close()
