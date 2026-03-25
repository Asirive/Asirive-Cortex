"""Quick SSH diagnostic for Bluetooth audio on RPi5."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.207.144.31', username='cortex', password='Haziqshah21', timeout=10)

commands = [
    'bluetoothctl show',
    'bluetoothctl devices Connected',
    'pactl list cards short',
    'pactl list sinks short',
    'pactl list cards 2>/dev/null | grep -A 30 "bluez"',
    'pipewire --version 2>/dev/null; pulseaudio --version 2>/dev/null; echo done',
    'systemctl --user is-active pipewire 2>/dev/null; systemctl --user is-active pulseaudio 2>/dev/null; echo done',
    'dpkg -l 2>/dev/null | grep -E "pipewire|pulseaudio|bluez" | awk "{print \\$2, \\$3}"',
]

for cmd in commands:
    print(f'\n=== {cmd[:60]} ===')
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out.strip():
        print(out.strip())
    if err.strip() and 'not found' not in err and 'No such' not in err:
        print(f'  ERR: {err.strip()[:200]}')

ssh.close()
print("\nDone.")
