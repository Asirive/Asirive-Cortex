"""Install textual on RPi5 and verify."""
import io, sys
import paramiko

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("172.26.13.31", 22, "cortex", "Haziqshah21", timeout=10, allow_agent=False, look_for_keys=False)
si, so, se = c.exec_command(
    "bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && pip install --quiet textual 2>&1 && python -c \"import textual; print(\\\"textual version:\\\", textual.__version__)\"'",
    timeout=120,
)
print(so.read().decode("utf-8", errors="replace"))
err = se.read().decode("utf-8", errors="replace")
if err.strip():
    print("STDERR:", err[-2000:])
c.close()
