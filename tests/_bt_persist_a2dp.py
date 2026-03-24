"""
Make A2DP the default Bluetooth profile on RPi5 via PipeWire/WirePlumber config.
Disables HFP/HSP so the system always uses A2DP (stereo) for the CMF Buds.
Temporary script - delete after use.
"""
import paramiko

HOST = "10.206.44.31"
USER = "cortex"
PASS = "Haziqshah21"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

def run(cmd):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=15)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err

# --- Method 1: WirePlumber / PipeWire media-session bluez config ---
# Check if wireplumber or pipewire-media-session is in use
wpm, _ = run("systemctl --user is-active wireplumber 2>/dev/null")
pms, _ = run("systemctl --user is-active pipewire-media-session 2>/dev/null")
print(f"wireplumber: {wpm}, pipewire-media-session: {pms}")

if pms == "active":
    # pipewire-media-session uses /etc/pipewire/media-session.d/bluez-monitor.conf
    config_path = "/home/cortex/.config/pipewire/media-session.d/bluez-monitor.conf"
    config_content = """{
    "bluez5.enable-hw-volume": true,
    "bluez5.default.rate": 48000,
    "bluez5.default.channels": 2,
    "bluez5.headset-roles": [],
    "bluez5.hfphsp-backend": "none",
    "bluez5.profiles": [ "a2dp_sink", "a2dp_source" ],
    "bluez5.codecs": [ "ldac", "sbc_xq", "sbc" ],
    "bluez5.autoswitch-profile": false
}
"""
    print(f"\nWriting pipewire-media-session config: {config_path}")
    # Create directory
    run(f"mkdir -p /home/cortex/.config/pipewire/media-session.d")
    # Write config
    # Use heredoc via bash to avoid escaping issues
    cmd = f"cat > {config_path} << 'BLUEZEOF'\n{config_content}BLUEZEOF"
    out, err = run(cmd)
    if err:
        print(f"Error writing config: {err}")
    else:
        out, _ = run(f"cat {config_path}")
        print(f"Written config:\n{out}")

elif wpm == "active":
    # WirePlumber uses Lua-based config
    config_path = "/home/cortex/.config/wireplumber/bluetooth.lua.d/51-a2dp-only.lua"
    config_content = """-- Force A2DP profile, disable HFP/HSP
bluez_monitor.properties = {
  ["bluez5.headset-roles"] = "[ ]",
  ["bluez5.hfphsp-backend"] = "none",
  ["bluez5.default.rate"] = 48000,
  ["bluez5.default.channels"] = 2,
  ["bluez5.codecs"] = "[ ldac sbc_xq sbc ]",
  ["bluez5.autoswitch-profile"] = false,
  ["bluez5.enable-hw-volume"] = true,
}
"""
    print(f"\nWriting wireplumber config: {config_path}")
    run("mkdir -p /home/cortex/.config/wireplumber/bluetooth.lua.d")
    cmd = f"cat > {config_path} << 'BLUEZEOF'\n{config_content}BLUEZEOF"
    out, err = run(cmd)
    if err:
        print(f"Error writing config: {err}")
    else:
        out, _ = run(f"cat {config_path}")
        print(f"Written config:\n{out}")
else:
    print("Neither wireplumber nor pipewire-media-session is active!")
    print("Falling back to PulseAudio module-bluetooth-policy config")

# --- Method 2: Also set PulseAudio bluetooth policy (pipewire-pulse compat) ---
pa_config_path = "/home/cortex/.config/pulse/default.pa"
pa_content = """.include /etc/pulse/default.pa

# Disable automatic profile switch to HSP/HFP when something records
unload-module module-bluetooth-policy
load-module module-bluetooth-policy auto_switch=false
"""
print(f"\nWriting PulseAudio config: {pa_config_path}")
run("mkdir -p /home/cortex/.config/pulse")
cmd = f"cat > {pa_config_path} << 'PAEOF'\n{pa_content}PAEOF"
out, err = run(cmd)
if err:
    print(f"Error: {err}")
else:
    out, _ = run(f"cat {pa_config_path}")
    print(f"Written:\n{out}")

# --- Restart services ---
print("\n=== Restarting PipeWire services ===")
for svc in ["pipewire", "pipewire-pulse", "pipewire-media-session", "wireplumber"]:
    out, err = run(f"systemctl --user restart {svc} 2>/dev/null")
    status, _ = run(f"systemctl --user is-active {svc} 2>/dev/null")
    print(f"  {svc}: {status}")

# Wait for BT to reconnect
import time
print("\nWaiting 5s for Bluetooth to reconnect...")
time.sleep(5)

# Check final state
print("\n=== Final state after restart ===")
out, _ = run("pactl list cards 2>/dev/null | grep -E 'Active Profile|Name.*bluez'")
print(out if out else "(no bluez card found yet - buds may need manual reconnect)")
out, _ = run("pactl list sinks short")
print(f"Sinks: {out}")

ssh.close()
print("\nDone. A2DP should now be the default profile on reconnect.")
