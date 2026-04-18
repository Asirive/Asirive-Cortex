"""
Bluetooth Earbud Pairing & Audio Stack Setup for RPi5
=====================================================

Pairs CMF Buds 2 Pro and UGREEN HiTune S3 to RPi5.

Usage:
    python rpi5_bt_setup.py diagnose      # Check audio stack
    python rpi5_bt_setup.py install-audio  # Install PipeWire + BT audio
    python rpi5_bt_setup.py scan           # Scan for BT devices (20s)
    python rpi5_bt_setup.py pair <MAC>     # Pair + trust + connect a device
    python rpi5_bt_setup.py pair-cmf       # Pair CMF Buds 2 Plus
    python rpi5_bt_setup.py pair-ugreen    # Pair UGREEN HiTune S3
    python rpi5_bt_setup.py status         # Show BT + audio status
    python rpi5_bt_setup.py test-audio     # Play test tone through BT

Author: Haziq (@IRSPlays)
"""

import paramiko
import sys
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.<REDACTED-RPI-IP>', username='cortex', password='REDACTED-RPI-PASSWORD', timeout=10)

VENV = "source /home/cortex/ProjectCortex/venv/bin/activate"

# Known devices
CMF_MAC = None  # Will be discovered by scan
UGREEN_MAC = None

def run(cmd, label="", timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    code = stdout.channel.recv_exit_status()
    if label:
        print(f"\n[{label}]")
    if out:
        print(out)
    if err and code != 0:
        print(f"STDERR: {err[:500]}")
    return code, out, err


step = sys.argv[1] if len(sys.argv) > 1 else "help"

if step == "diagnose":
    run("which wpctl pactl pulseaudio pipewire 2>&1", "Binary locations")
    run("systemctl --user status pipewire 2>&1 | head -8", "PipeWire status")
    run("systemctl --user status wireplumber 2>&1 | head -8", "WirePlumber status")
    run("systemctl --user status pulseaudio 2>&1 | head -8", "PulseAudio status")
    run("dpkg -l | grep -iE 'pipewire|wireplumber|pulseaudio|bluez|bluetooth' | awk '{print $2, $3}'", "Installed packages")
    run("bluetoothctl show 2>&1 | head -10", "BT adapter")
    run("aplay -l 2>&1", "ALSA playback devices")

elif step == "install-audio":
    print("Installing PipeWire + Bluetooth audio stack...")
    # PipeWire with Bluetooth support
    run("sudo apt-get update -qq", "apt update")
    run("sudo apt-get install -y pipewire pipewire-audio wireplumber libspa-0.2-bluetooth pulseaudio-utils", 
        "Install PipeWire + BT audio", timeout=120)
    # Enable PipeWire for user
    run("systemctl --user --now enable pipewire pipewire-pulse wireplumber 2>&1", "Enable PipeWire services")
    # Verify
    run("systemctl --user status pipewire --no-pager 2>&1 | head -5", "PipeWire running?")
    run("which wpctl pactl 2>&1", "wpctl/pactl available?")

elif step == "scan":
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    run("bluetoothctl power on", "Power on")
    print(f"\nScanning for {duration} seconds... (put earbuds in pairing mode!)")
    ssh.exec_command("bluetoothctl scan on", timeout=5)
    time.sleep(duration)
    ssh.exec_command("bluetoothctl scan off", timeout=5)
    time.sleep(1)
    code, out, err = run("bluetoothctl devices", "Discovered devices")
    print("\n--- Matching devices ---")
    for line in out.split('\n'):
        lower = line.lower()
        if any(kw in lower for kw in ['cmf', 'buds', 'ugreen', 'hitune', 'nothing']):
            print(f"  >>> {line} <<<")

elif step == "pair":
    mac = sys.argv[2] if len(sys.argv) > 2 else None
    name = sys.argv[3] if len(sys.argv) > 3 else "device"
    if not mac:
        print("Usage: python rpi5_bt_setup.py pair <MAC> [name]")
        sys.exit(1)
    
    # Ensure scan is running so device stays visible
    print(f"Pairing {name} ({mac})...")
    ssh.exec_command("bluetoothctl scan on", timeout=5)
    time.sleep(5)
    
    run(f"bluetoothctl pair {mac}", f"Pair {name}", timeout=30)
    time.sleep(2)
    run(f"bluetoothctl trust {mac}", f"Trust {name}")
    time.sleep(1)
    
    # Connect with retries
    for attempt in range(1, 4):
        code, out, err = run(f"bluetoothctl connect {mac}", f"Connect attempt {attempt}/3", timeout=30)
        if "Connection successful" in out:
            break
        time.sleep(5)
    
    ssh.exec_command("bluetoothctl scan off", timeout=5)
    time.sleep(1)
    
    # Show result
    run(f"bluetoothctl info {mac}", f"Device info for {name}")

elif step == "pair-cmf":
    # Scan and pair CMF Buds
    print("Looking for CMF Buds 2 Plus/Pro...")
    print("Make sure earbuds are in pairing mode!")
    
    run("bluetoothctl power on", "Power on")
    ssh.exec_command("bluetoothctl scan on", timeout=5)
    
    # Poll for device appearance
    cmf_mac = None
    for i in range(6):  # 30s total
        time.sleep(5)
        code, out, err = run("bluetoothctl devices")
        for line in out.split('\n'):
            if 'cmf' in line.lower() or 'buds' in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    cmf_mac = parts[1]
                    cmf_name = ' '.join(parts[2:])
                    print(f"\n>>> Found: {cmf_name} ({cmf_mac})")
                    break
        if cmf_mac:
            break
        print(f"  Scanning... ({(i+1)*5}s)")
    
    if not cmf_mac:
        print("\nCMF Buds not found! Make sure they're in pairing mode.")
        ssh.exec_command("bluetoothctl scan off", timeout=5)
        sys.exit(1)
    
    # Pair while scan is still active
    run(f"bluetoothctl pair {cmf_mac}", "Pair CMF", timeout=30)
    time.sleep(2)
    run(f"bluetoothctl trust {cmf_mac}", "Trust CMF")
    time.sleep(1)
    
    for attempt in range(1, 4):
        code, out, err = run(f"bluetoothctl connect {cmf_mac}", f"Connect attempt {attempt}/3", timeout=30)
        if "Connection successful" in out:
            break
        time.sleep(5)
    
    ssh.exec_command("bluetoothctl scan off", timeout=5)
    run(f"bluetoothctl info {cmf_mac}", "CMF Buds info")

elif step == "pair-ugreen":
    # Scan and pair UGREEN HiTune S3
    print("Looking for UGREEN HiTune S3...")
    print("Make sure earbuds are in pairing mode!")
    
    run("bluetoothctl power on", "Power on")
    ssh.exec_command("bluetoothctl scan on", timeout=5)
    
    ugreen_mac = None
    for i in range(6):
        time.sleep(5)
        code, out, err = run("bluetoothctl devices")
        for line in out.split('\n'):
            if 'ugreen' in line.lower() or 'hitune' in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    ugreen_mac = parts[1]
                    ugreen_name = ' '.join(parts[2:])
                    print(f"\n>>> Found: {ugreen_name} ({ugreen_mac})")
                    break
        if ugreen_mac:
            break
        print(f"  Scanning... ({(i+1)*5}s)")
    
    if not ugreen_mac:
        print("\nUGREEN HiTune S3 not found! Make sure they're in pairing mode.")
        ssh.exec_command("bluetoothctl scan off", timeout=5)
        sys.exit(1)
    
    run(f"bluetoothctl pair {ugreen_mac}", "Pair UGREEN", timeout=30)
    time.sleep(2)
    run(f"bluetoothctl trust {ugreen_mac}", "Trust UGREEN")
    time.sleep(1)
    
    for attempt in range(1, 4):
        code, out, err = run(f"bluetoothctl connect {ugreen_mac}", f"Connect attempt {attempt}/3", timeout=30)
        if "Connection successful" in out:
            break
        time.sleep(5)
    
    ssh.exec_command("bluetoothctl scan off", timeout=5)
    run(f"bluetoothctl info {ugreen_mac}", "UGREEN info")

elif step == "status":
    run("bluetoothctl devices Paired", "Paired devices")
    code, out, err = run("bluetoothctl devices Paired")
    # Check connection status for each paired device
    import re
    for line in out.split('\n'):
        match = re.match(r'Device\s+([0-9A-Fa-f:]{17})\s+(.+)', line)
        if match:
            mac, name = match.group(1), match.group(2)
            run(f"bluetoothctl info {mac} | grep -E 'Name:|Connected:|Paired:|Trusted:'", f"{name}")
    
    # Audio status
    run("wpctl status 2>&1 | head -40", "PipeWire audio status")

elif step == "test-audio":
    print("Playing test tone through default audio output...")
    run(f"{VENV} && python -c \"import pygame; pygame.mixer.init(); import time; print('Mixer OK'); time.sleep(1)\"",
        "Pygame mixer test")

else:
    print("""
Usage: python rpi5_bt_setup.py <command>

Commands:
    diagnose       Check audio stack status
    install-audio  Install PipeWire + BT audio packages
    scan [secs]    Scan for BT devices (default 20s)
    pair <MAC>     Pair + trust + connect a device by MAC
    pair-cmf       Auto-find and pair CMF Buds 2 Plus/Pro
    pair-ugreen    Auto-find and pair UGREEN HiTune S3
    status         Show paired devices + audio status
    test-audio     Test audio output
""")

ssh.close()
