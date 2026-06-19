"""
Shared SSH helper for ProjectCortex.

Loads RPi5 credentials from environment variables (or the project's
``.env`` file) — NEVER from a hardcoded default. If a credential is
missing, the helper raises an actionable error instead of silently
falling back to a known-bad value.

Usage from any script:

    from scripts._rpi_ssh import get_ssh_client, require_credentials, RPI_HOST, RPI_USER

    require_credentials()          # raises if RPI_PASSWORD is unset
    c = get_ssh_client()
    c.connect(...)
    ...

Or use the one-liner:

    from scripts._rpi_ssh import RPiConnection
    with RPiConnection() as c:
        stdin, stdout, stderr = c.exec_command("uptime")

Environment variables (all required unless noted):
    RPI_HOST        RPi5 IP / hostname (default: read from rpi5/config/config.yaml)
    RPI_USER        SSH user           (default: "cortex")
    RPI_PASSWORD    SSH password       (NO default — must be set)
    RPI_PORT        SSH port           (default: 22)
    RPI_KEY_FILE    Path to private key (optional — uses SSH agent if set)
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

# Project layout
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "rpi5" / "config" / "config.yaml"
DOTENV_PATH = PROJECT_ROOT / ".env"


def _load_dotenv_into_environ() -> None:
    """
    Minimal .env loader. We don't depend on python-dotenv at import time
    so that ``scripts/_rpi_ssh.py`` is usable from minimal CI environments.
    Idempotent — does not overwrite existing env vars.
    """
    if not DOTENV_PATH.exists():
        return
    try:
        for raw in DOTENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)
    except Exception:
        # If .env is unreadable, env vars may still be set externally
        pass


def _load_host_from_yaml() -> Optional[str]:
    """
    Best-effort load of the RPi5 IP from rpi5/config/config.yaml.
    Returns None if the file is missing or unreadable.
    """
    if not CONFIG_PATH.exists():
        return None
    try:
        # Avoid requiring PyYAML at import time
        import yaml  # type: ignore
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return (
            cfg.get("rpi5_device", {}).get("host")
            or cfg.get("network", {}).get("rpi5_host")
        )
    except Exception:
        return None


_load_dotenv_into_environ()

# --- Resolved credentials ---------------------------------------------------
RPI_HOST: str = os.environ.get("RPI_HOST") or _load_host_from_yaml() or ""
RPI_USER: str = os.environ.get("RPI_USER", "cortex")
RPI_PORT: int = int(os.environ.get("RPI_PORT", "22") or "22")
RPI_PASSWORD: Optional[str] = os.environ.get("RPI_PASSWORD") or None
RPI_KEY_FILE: Optional[str] = os.environ.get("RPI_KEY_FILE") or None

# Backwards-compat alias for the historic variable name
if RPI_PASSWORD is None:
    RPI_PASSWORD = os.environ.get("RPI_SSH_PASSWORD") or None


class CredentialError(RuntimeError):
    """Raised when a required credential is missing."""


def require_credentials() -> None:
    """
    Verify that the required credentials are present.

    RPI_HOST can come from the YAML config, but RPI_PASSWORD must always
    come from the environment. We refuse to guess.
    """
    missing: list[str] = []
    if not RPI_HOST:
        missing.append("RPI_HOST (or rpi5_device.host in rpi5/config/config.yaml)")
    if not RPI_USER:
        missing.append("RPI_USER")
    if not RPI_PASSWORD and not RPI_KEY_FILE:
        missing.append(
            "RPI_PASSWORD (set in .env or shell — never hardcoded)"
        )
    if missing:
        raise CredentialError(
            "Missing required RPi5 credentials:\n  - "
            + "\n  - ".join(missing)
            + "\n\nSet them in your .env (gitignored) or shell, then retry.\n"
            "Example .env entries:\n"
            "    RPI_HOST=10.202.14.31\n"
            "    RPI_USER=cortex\n"
            "    RPI_PASSWORD=...    # never commit this\n"
        )


def get_ssh_client():
    """
    Construct a configured paramiko.SSHClient.

    Caller is responsible for calling .connect() with the resolved
    credentials (see ``connect()`` below for the one-shot helper).
    """
    try:
        import paramiko  # type: ignore
    except ImportError as e:
        raise CredentialError(
            "paramiko is not installed. Run: pip install paramiko"
        ) from e

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def connect(client=None):
    """
    One-shot SSH connect using the resolved credentials.
    Returns the connected paramiko.SSHClient.
    """
    require_credentials()
    if client is None:
        client = get_ssh_client()
    connect_kwargs: dict = {
        "hostname": RPI_HOST,
        "port": RPI_PORT,
        "username": RPI_USER,
        "timeout": 10,
        "banner_timeout": 10,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if RPI_KEY_FILE:
        connect_kwargs["key_filename"] = RPI_KEY_FILE
        # Key auth → no password
    else:
        connect_kwargs["password"] = RPI_PASSWORD
    client.connect(**connect_kwargs)
    return client


@contextmanager
def RPiConnection():
    """
    Context manager that yields a connected paramiko.SSHClient and
    always closes it on exit.
    """
    client = get_ssh_client()
    try:
        yield connect(client)
    finally:
        try:
            client.close()
        except Exception:
            pass


def _self_check() -> int:
    """CLI: print resolved credentials (with password masked) and exit 0/1."""
    print(f"RPI_HOST     = {RPI_HOST or '(unset)'}")
    print(f"RPI_USER     = {RPI_USER or '(unset)'}")
    print(f"RPI_PORT     = {RPI_PORT}")
    masked = "(unset)" if not RPI_PASSWORD else "*" * len(RPI_PASSWORD)
    print(f"RPI_PASSWORD = {masked}")
    print(f"RPI_KEY_FILE = {RPI_KEY_FILE or '(unused)'}")
    try:
        require_credentials()
        print("\n[OK] All required credentials are present.")
        return 0
    except CredentialError as e:
        print(f"\n[FAIL] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(_self_check())
