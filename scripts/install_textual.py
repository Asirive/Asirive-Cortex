"""Install textual on RPi5 and verify."""
import io, sys
from scripts._rpi_ssh import RPI_HOST, RPI_USER, RPI_PASSWORD, require_credentials, get_ssh_client

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

require_credentials()
c = get_ssh_client()
c.connect(RPI_HOST, 22, RPI_USER, RPI_PASSWORD, timeout=10, allow_agent=False, look_for_keys=False)
si, so, se = c.exec_command(
    "bash -lc 'cd ~/ProjectCortex && source venv/bin/activate && pip install --quiet textual 2>&1 && python -c \"import textual; print(\\\"textual version:\\\", textual.__version__)\"'",
    timeout=120,
)
print(so.read().decode("utf-8", errors="replace"))
err = se.read().decode("utf-8", errors="replace")
if err.strip():
    print("STDERR:", err[-2000:])
c.close()
