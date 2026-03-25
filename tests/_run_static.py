"""
Quick static position test - plays chirps at LEFT, RIGHT, FRONT, BEHIND.
Temporary script - delete after use.
"""
import paramiko, time

HOST = "10.207.144.31"
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

test_code = '''
import sys, time
sys.path.insert(0, "/home/cortex/ProjectCortex/rpi5")
sys.path.insert(0, "/home/cortex/ProjectCortex")

from rpi5.layer3_guide.spatial_audio.binaural_engine import BinauralEngine

engine = BinauralEngine(sr=48000, gain=0.6)
engine.start()

print("Static position test - listen for direction!")
print()

positions = [
    ("LEFT",   -90, 0),
    ("RIGHT",   90, 0),
    ("FRONT",    0, 0),
    ("BEHIND", 180, 0),
    ("LEFT",   -90, 0),
    ("RIGHT",   90, 0),
]

for name, az, el in positions:
    print(f"  >>> Playing at {name} (az={az:+d})")
    engine.play_at(az, el, sound="chirp", duration_s=0.5)
    time.sleep(0.5)

engine.stop()
print()
print("Done! Could you tell the direction of each ping?")
'''

sftp = ssh.open_sftp()
with sftp.file("/tmp/binaural_static.py", "w") as f:
    f.write(test_code)
sftp.close()

print("=== Static position test: LEFT, RIGHT, FRONT, BEHIND ===\n")
out, err = run(f"{python} /tmp/binaural_static.py", timeout=30)
# Filter out import noise
for line in out.split('\n'):
    if any(k in line for k in ['Playing', 'Done', 'Static', 'direction', 'BinauralEngine']):
        print(line)
if "Traceback" in err:
    print(f"\nError:\n{err[-400:]}")

ssh.close()
print("\nDone!")
