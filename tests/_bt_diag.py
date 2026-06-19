"""Quick SSH diagnostic for Bluetooth audio on RPi5."""
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
