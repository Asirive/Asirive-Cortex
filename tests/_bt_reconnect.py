"""
Reconnect CMF Buds and verify A2DP profile.
Temporary script - delete after use.
"""
import paramiko, time

HOST = "10.206.44.31"
USER = "cortex"
PASS = "Haziqshah21"
BT_MAC = "2C:BE:EE:2D:9E:E6"
CARD = "bluez_card.2C_BE_EE_2D_9E_E6"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

def run(cmd):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err

# Check if already connected
out, _ = run("bluetoothctl devices Connected")
print(f"Currently connected: {out}")

if BT_MAC not in out:
    print(f"\nReconnecting to {BT_MAC}...")
    run(f"bluetoothctl disconnect {BT_MAC}")
    time.sleep(2)
    out, err = run(f"bluetoothctl connect {BT_MAC}")
    print(f"Connect result: {out}")
    if err:
        print(f"Connect stderr: {err}")
    time.sleep(5)
    
    # Check connection
    out, _ = run("bluetoothctl devices Connected")
    print(f"Connected devices: {out}")
else:
    print("Buds already connected.")

# Wait a moment for audio profile to settle
time.sleep(3)

# Check what profile was auto-selected
print("\n=== Card profile ===")
out, _ = run(f"pactl list cards 2>/dev/null | grep -A 5 'bluez_card'")
print(out)

out, _ = run(f"pactl list cards 2>/dev/null | grep 'Active Profile'")
print(f"Active profiles: {out}")

print("\n=== Sinks ===")
out, _ = run("pactl list sinks short")
print(out)

# If still not A2DP, force it
if "headset-head-unit" in out or "1ch" in out:
    print("\nStill on HFP! Force-setting A2DP...")
    for profile in ["a2dp-sink-ldac", "a2dp-sink-sbc_xq", "a2dp-sink-sbc", "a2dp-sink"]:
        _, err = run(f"pactl set-card-profile {CARD} {profile}")
        if not err:
            print(f"Set to {profile}")
            break

    time.sleep(2)
    out, _ = run("pactl list sinks short")
    print(f"Sinks after fix: {out}")

ssh.close()
print("\nDone.")
