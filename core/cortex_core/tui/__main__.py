"""python -m cortex_core.tui [--state-dir DIR]   (needs CORTEX_DEV_BUILD=1)"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Mapping, Optional

REFUSAL = "The terminal UI is for developer builds only (set CORTEX_DEV_BUILD=1)."


def main(argv: Optional[list[str]] = None, env: Mapping[str, str] = os.environ) -> int:
    if env.get("CORTEX_DEV_BUILD") != "1":
        print(REFUSAL)
        return 2
    p = argparse.ArgumentParser(prog="python -m cortex_core.tui")
    p.add_argument("--state-dir", type=Path, default=Path("/var/lib/cortex"))
    a = p.parse_args(argv)
    from cortex_core.tui.app import CortexTUI  # Textual is a dev-only dependency
    from cortex_core.tui.state import Collector
    CortexTUI(Collector(a.state_dir)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
