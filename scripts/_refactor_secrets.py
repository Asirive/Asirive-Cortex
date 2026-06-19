"""One-shot refactor: replace hardcoded RPi SSH credentials in tests/*.py
and root-level _*.py / rpi5_*.py / setup_rpi5_deps.py with the shared
`scripts._rpi_ssh` helper.

This script is safe to re-run (idempotent on already-fixed files).
"""
import re
from pathlib import Path

# All files we need to scrub (relative to repo root)
ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    "tests/_bt_diag.py",
    "tests/_bt_fix_a2dp.py",
    "tests/_bt_persist_a2dp.py",
    "tests/_bt_reconnect.py",
    "tests/_check_imu.py",
    "tests/_install_deps.py",
    "tests/_run_binaural_test.py",
    "tests/_run_static.py",
    "tests/_run_stereo_test.py",
    "tests/_run_sweep.py",
    "tests/_run_sweep2.py",
]

# Regex to find the credential block. We try to handle the common patterns:
#   HOST = "..."
#   USER = "..."
#   PASS = "..."
#   c.connect(HOST, ..., PASS, ...)
# and the direct inline form:
#   c.connect('IP', username='u', password='p')
CRED_RE = re.compile(
    r"^(?:HOST|USER|PASS)\s*=\s*['\"][^'\"]+['\"]\s*\n",
    re.MULTILINE,
)

INLINE_CRED_RE = re.compile(
    r"c\.connect\((?:['\"]?[^,)\n]+['\"]?\s*,\s*){1,5}username\s*=\s*['\"][^'\"]+['\"][^)]*password\s*=\s*['\"][^'\"]+['\"][^)]*\)"
)

ADDED_IMPORT_BLOCK = (
    "from scripts._rpi_ssh import (\n"
    "    RPI_HOST,\n"
    "    RPI_PASSWORD,\n"
    "    RPI_USER,\n"
    "    get_ssh_client,\n"
    "    require_credentials,\n"
    ")\n"
    "require_credentials()\n"
    "import paramiko  # noqa: E402  (imported after env check)\n"
)

CONNECT_REPLACEMENT = (
    "ssh = get_ssh_client()\n"
    "ssh.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)"
)

INLINE_CONNECT_REPLACEMENT = (
    "ssh = get_ssh_client()\n"
    "ssh.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)"
)

# Special case: a few files use `c.connect(HOST, 22, USER, PASS, ...)`
CONNECT_KW_RE = re.compile(
    r"c\.connect\((HOST|10\.\d+\.\d+\.\d+)\s*,\s*(\d+|22)\s*,\s*(USER|['\"]cortex['\"])\s*,\s*(PASS|['\"][^'\"]+['\"])[^)]*\)"
)


def refactor_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    # 1. Drop the credential constants (HOST, USER, PASS = "...") — they will
    #    come from the helper module instead.
    text = CRED_RE.sub("", text)

    # 2. Replace paramiko client construction + hardcoded connect.
    #    Pattern A: explicit constants
    text = re.sub(
        r"ssh\s*=\s*paramiko\.SSHClient\(\)\s*\n"
        r"\s*ssh\.set_missing_host_key_policy\(paramiko\.AutoAddPolicy\(\)\)\s*\n"
        r"\s*ssh\.connect\(\s*HOST\s*,\s*username\s*=\s*USER\s*,\s*password\s*=\s*PASS[^)]*\)",
        CONNECT_REPLACEMENT,
        text,
    )
    # Pattern B: numeric host
    text = re.sub(
        r"ssh\s*=\s*paramiko\.SSHClient\(\)\s*\n"
        r"\s*ssh\.set_missing_host_key_policy\(paramiko\.AutoAddPolicy\(\)\)\s*\n"
        r"\s*ssh\.connect\(['\"]?[\d.]+['\"]?\s*,\s*username\s*=\s*['\"][^'\"]+['\"]\s*,\s*password\s*=\s*['\"][^'\"]+['\"][^)]*\)",
        CONNECT_REPLACEMENT,
        text,
    )
    # Pattern C: c.connect('IP', 22, USER, PASS, ...)
    text = CONNECT_KW_RE.sub(
        "ssh.connect(RPI_HOST, 22, RPI_USER, RPI_PASSWORD, timeout=10, allow_agent=False, look_for_keys=False)",
        text,
    )
    # Pattern D: c.connect('IP', username=..., password=...)
    text = re.sub(
        r"c\.connect\(['\"]?[\d.]+['\"]?\s*,\s*username\s*=\s*['\"][^'\"]+['\"]\s*,\s*password\s*=\s*['\"][^'\"]+['\"][^)]*\)",
        INLINE_CONNECT_REPLACEMENT,
        text,
    )
    # Pattern E: SSH-over-WS c.connect(HOST, username=USER, password=PASS, ...)
    text = re.sub(
        r"c\.connect\(HOST\s*,\s*username\s*=\s*USER\s*,\s*password\s*=\s*PASS[^)]*\)",
        "ssh.connect(RPI_HOST, username=RPI_USER, password=RPI_PASSWORD, timeout=10)",
        text,
    )

    # 3. Prepend the helper import block if not already present.
    if "from scripts._rpi_ssh import" not in text and "scripts/_rpi_ssh" not in text:
        # Find a good spot: after the docstring ("""...""") and the
        # `import paramiko` line, OR right after the leading docstring.
        if "import paramiko" in text:
            text = re.sub(
                r"import paramiko\n",
                ADDED_IMPORT_BLOCK,
                text,
                count=1,
            )
        else:
            # Insert after the module docstring
            m = re.match(r"(\s*\"\"\".*?\"\"\"\s*\n)", text, re.DOTALL)
            if m:
                text = text[: m.end()] + "\n" + ADDED_IMPORT_BLOCK + text[m.end():]
            else:
                text = ADDED_IMPORT_BLOCK + "\n" + text

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    fixed = []
    skipped = []
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            skipped.append((rel, "missing"))
            continue
        if refactor_file(p):
            fixed.append(rel)
        else:
            skipped.append((rel, "no change"))
    print(f"Fixed {len(fixed)} file(s):")
    for f in fixed:
        print(f"  + {f}")
    print(f"\nSkipped {len(skipped)}:")
    for f, why in skipped:
        print(f"  - {f} ({why})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
