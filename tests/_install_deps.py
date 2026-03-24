"""
Install sounddevice + deps on RPi5 and sync code.
Temporary script - delete after use.
"""
import paramiko

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

# Install libportaudio (required by sounddevice)
print("=== Installing system deps ===")
out, err = run("sudo apt-get install -y libportaudio2 libportaudiocpp0 portaudio19-dev", timeout=120)
# Filter to last few lines
lines = out.split('\n')
for line in lines[-5:]:
    print(f"  {line}")

# Install sounddevice in the venv or globally
print("\n=== Installing sounddevice ===")
# Check if there's a venv
venv, _ = run("ls /home/cortex/ProjectCortex/venv/bin/pip 2>/dev/null")
if venv:
    pip_cmd = "/home/cortex/ProjectCortex/venv/bin/pip"
else:
    pip_cmd = "pip3"

out, err = run(f"{pip_cmd} install sounddevice", timeout=120)
print(out[-500:] if len(out) > 500 else out)
if err and "error" in err.lower():
    print(f"Error: {err[-300:]}")

# Verify import works
print("\n=== Verify import ===")
if venv:
    python_cmd = "/home/cortex/ProjectCortex/venv/bin/python"
else:
    python_cmd = "python3"

out, err = run(f'{python_cmd} -c "import sounddevice; print(sounddevice.query_devices())"')
print(out if out else f"Error: {err}")

ssh.close()
print("\nDone.")
