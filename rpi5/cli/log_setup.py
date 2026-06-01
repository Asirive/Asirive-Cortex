"""
Shared logging setup for Cortex CLI tools.

Provides the same RichHandler-based colored logs that
`python -m rpi5 all` uses, with the compact `[HH:MM:SS] INFO     ` format.

Usage:
    from rpi5.cli.log_setup import setup_logging
    setup_logging(level="INFO")
"""
import logging
import sys
from pathlib import Path

# Rich library for colored logs + interactive status display
try:
    from rich.console import Console
    from rich.logging import RichHandler
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    RichHandler = None
    Console = None

# Shared console so RichHandler doesn't conflict with Live displays
_shared_console = Console() if RICH_AVAILABLE else None


def setup_logging(
    level: str = "INFO",
    log_file: str = "logs/cortex.log",
    use_rich: bool = True,
) -> None:
    """
    Configure root logger with RichHandler (compact colored format).
    
    Format produced:
        [15:48:59] INFO     Loaded environment variables from .env
        [15:48:59] WARNING  ⚠️ Layer 0 latency: 111.4ms (exceeds 100ms safety target!)
        [15:48:59] ERROR    ❌ Camera startup failed
    
    Falls back to plain format if Rich isn't installed.
    """
    # Ensure log directory exists
    log_path = Path(log_file)
    if log_path.parent and not log_path.parent.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Reset any existing handlers
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    
    if use_rich and RICH_AVAILABLE and RichHandler:
        handlers.append(
            RichHandler(
                console=_shared_console,
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
                tracebacks_show_locals=False,
                markup=False,
            )
        )
    else:
        handlers.append(logging.StreamHandler(sys.stdout))
    
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )
    
    # Quiet noisy libraries
    for noisy in ["urllib3", "httpx", "httpcore", "requests", "PIL"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a logger with the given name."""
    return logging.getLogger(name)
