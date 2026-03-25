"""
Force CMF Buds 2 Plus to A2DP (stereo) profile via SSH.
Temporary script - delete after use.
"""
import paramiko, sys

HOST = "10.207.144.31"
USER = "cortex"
PASS = "Haziqshah21"
CARD = "bluez_card.2C_BE_EE_2D_9E_E6"

# Try LDAC first (best quality), fall back to SBC-XQ, then SBC, then generic a2dp-sink
PROFILES = [
    "a2dp-sink-ldac",
    "a2dp-sink-sbc_xq",
    "a2dp-sink-sbc",
    "a2dp-sink",
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

def run(cmd):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=10)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err

# Step 1: Show current state
print("=== Current profile ===")
out, _ = run(f"pactl list cards short")
print(out)
out, _ = run(f"pactl list sinks short")
print(f"Current sink: {out}")

# Step 2: Try each A2DP profile
success = False
for profile in PROFILES:
    print(f"\n--- Trying profile: {profile} ---")
    out, err = run(f"pactl set-card-profile {CARD} {profile}")
    if err:
        print(f"  Error: {err}")
        continue
    
    # Verify it took effect
    out, _ = run("pactl list sinks short")
    print(f"  Sink now: {out}")
    
    if "2ch" in out or "44100" in out or "48000" in out:
        print(f"  SUCCESS! Stereo A2DP active with {profile}")
        success = True
        break
    else:
        print(f"  Profile set but sink doesn't look stereo, trying next...")

if not success:
    print("\nWARNING: Could not confirm stereo output. Check manually.")
    
# Step 3: Show final state
print("\n=== Final state ===")
out, _ = run(f"pactl list cards 2>/dev/null | grep -E 'Active Profile|Name.*bluez'")
print(out)
out, _ = run("pactl list sinks short")
print(f"Sinks: {out}")

ssh.close()
print("\nDone.")
