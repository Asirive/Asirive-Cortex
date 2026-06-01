#!/usr/bin/env python3
"""
DEPRECATED: Use the new sync tool instead:

    python -m scripts.sync <command>
    cortex sync <command>          (recommended)

This file is kept for backwards compatibility.
"""
import sys
import warnings

warnings.warn(
    "sync_rpi5.py is deprecated. Use 'python -m scripts.sync' or 'cortex sync' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Delegate to new sync tool
sys.argv[0] = "scripts.sync"
from scripts.sync import main
sys.exit(main())
