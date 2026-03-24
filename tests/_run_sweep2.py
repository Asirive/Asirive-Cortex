"""
Fixed non-interactive binaural 3D test via SSH.
Temporary script - delete after use.
"""
import paramiko, time

HOST = "10.206.44.31"
USER = "cortex"
PASS = "Haziqshah21"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

def run(cmd, timeout=60):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err

python = "/home/cortex/ProjectCortex/venv/bin/python"

sweep_code = '''
import sys, time
sys.path.insert(0, "/home/cortex/ProjectCortex/rpi5")
sys.path.insert(0, "/home/cortex/ProjectCortex")

from rpi5.layer3_guide.spatial_audio.binaural_engine import BinauralEngine

engine = BinauralEngine(sr=48000, gain=0.5)
engine.start()

print("Starting 360-degree sweep... LISTEN with earphones!")
print()

# Start continuous tone at front
engine.start_continuous(azimuth_deg=0, elevation_deg=0, freq=500, loop_duration_s=2.0)

# Sweep 360 degrees over 10 seconds
duration = 10.0
steps = 250
for i in range(steps):
    az = -180 + (360 * i / steps)
    engine.update_position(az, 0)
    label = ""
    if abs(az) < 5:
        label = ">>> FRONT"
    elif 85 < az < 95:
        label = ">>> RIGHT"
    elif abs(az) > 175:
        label = ">>> BEHIND"
    elif -95 < az < -85:
        label = ">>> LEFT"
    if label:
        print(f"  {label:15s} (az={az:+6.1f})")
    time.sleep(duration / steps)

engine.stop_continuous()
time.sleep(0.5)

# Also test static positions
print()
print("Static position test: LEFT, then RIGHT, then FRONT")
positions = [
    ("LEFT", -90, 0),
    ("RIGHT", 90, 0),
    ("FRONT", 0, 0),
]
for name, az, el in positions:
    print(f"  Playing at {name} (az={az})")
    engine.play_at(az, el, duration_s=1.0, freq=800)
    time.sleep(0.3)

engine.stop()
print()
print("All tests complete!")
'''

# Upload via SFTP
sftp = ssh.open_sftp()
with sftp.file("/tmp/binaural_sweep.py", "w") as f:
    f.write(sweep_code)
sftp.close()

print("=== Binaural 3D sweep test ===")
print("Listen with CMF Buds for:")
print("  1) Tone sweeping 360 degrees")
print("  2) Pings at LEFT, RIGHT, FRONT")
print()

out, err = run(f"{python} /tmp/binaural_sweep.py", timeout=45)
print(f"{out}")
if "Traceback" in err or "Error" in err:
    print(f"\nError:\n{err[-600:]}")

ssh.close()
print("\nDone!")
