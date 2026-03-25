"""Quick IMU check via SSH to RPi5."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.207.144.31', username='cortex', password='Haziqshah21', timeout=10)

cmds = [
    "fuser /dev/i2c-1 2>&1 || echo 'no process using i2c-1'",
    "ps aux | grep -i 'main.py\\|cortex' | grep -v grep",
    # Try all available I2C buses
    "for bus in 1 4 11 13 14; do echo \"=== Bus $bus ===\"; python3 -c \"import smbus2; b=smbus2.SMBus($bus); [print(f'  0x{a:02x}: {hex(b.read_byte_data(a,0x0f))}') for a in range(0x08,0x78) if (lambda addr: (b.read_byte_data(addr,0x0f) is not None) if True else False)]\" 2>&1 | head -5 || echo '  no devices or bus error'; done",
    # Simpler scan: just try common IMU addresses on all buses
    "python3 -c '\nimport smbus2\nfor bus_num in [1, 4, 11, 13, 14]:\n    print(f\"Bus {bus_num}:\")\n    try:\n        bus = smbus2.SMBus(bus_num)\n        for addr in [0x28, 0x29, 0x68, 0x69, 0x6a, 0x6b, 0x1e, 0x53, 0x77]:\n            try:\n                val = bus.read_byte(addr)\n                print(f\"  Found device at 0x{addr:02x} (read: {hex(val)})\")\n            except:\n                pass\n        bus.close()\n    except Exception as e:\n        print(f\"  Error: {e}\")\n' 2>&1",
    "sudo i2cdetect -y 1 2>&1 || echo 'needs i2c-tools'",
]

for cmd in cmds:
    print(f"--- {cmd.split('|')[0].strip()[:60]} ---")
    _, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    if err:
        print(f"ERR: {err}")
    print()

ssh.close()
print("Done.")
