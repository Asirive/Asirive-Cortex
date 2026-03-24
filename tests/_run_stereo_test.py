"""
Run stereo test on RPi5 via SSH.
Plays a tone in left ear only, then right ear only.
You should hear L then R. If both ears sound the same, still mono.
Temporary script - delete after use.
"""
import paramiko

HOST = "10.206.44.31"
USER = "cortex"
PASS = "Haziqshah21"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

def run(cmd, timeout=30):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err

# First check the audio sink is stereo
print("=== Current sink ===")
out, _ = run("pactl list sinks short")
print(out)

# Run the stereo test 
print("\n=== Running stereo test ===")
print("Listen carefully: you should hear LEFT ear only, then RIGHT ear only.")
print("If both ears sound the same, the BT profile is still mono.\n")

# Use the venv python
python = "/home/cortex/ProjectCortex/venv/bin/python"
test_script = "/home/cortex/ProjectCortex/tests/test_stereo_raw.py"

# Check if test exists
out, _ = run(f"ls -la {test_script}")
print(f"Test file: {out}")

# Run it
out, err = run(f"cd /home/cortex/ProjectCortex && {python} {test_script}", timeout=30)
print(f"\nOutput:\n{out}")
if err:
    print(f"\nStderr:\n{err}")

ssh.close()
print("\nDone. Did you hear L then R?")
