"""Is the Hexagon NPU reachable from this Linux? Checks the FastRPC device nodes, the compute DSP's
remoteproc state, and whether Qualcomm's QNN HTP library is installed.

    python -m cortex_core.engine.npu_probe [--out /var/lib/cortex/bench/npu.json]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

LIB_DIRS = (Path("/usr/lib"), Path("/usr/lib/aarch64-linux-gnu"), Path("/opt/qcom"))


@dataclass
class NpuReport:
    fastrpc_nodes: list[str] = field(default_factory=list)
    dsp: list[dict] = field(default_factory=list)
    qnn_libs: list[str] = field(default_factory=list)
    reachable: bool = False
    notes: list[str] = field(default_factory=list)


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def _find_libs(root: Path, depth: int = 3) -> list[str]:
    found: list[str] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    for e in entries:
        try:
            if e.is_file() and e.name.startswith("libQnnHtp") and e.name.endswith(".so"):
                found.append(str(e))
            elif e.is_dir() and not e.is_symlink() and depth > 0:
                found.extend(_find_libs(e, depth - 1))
        except OSError:
            continue
    return found


def probe(dev: Path = Path("/dev"), remoteproc: Path = Path("/sys/class/remoteproc"),
          lib_dirs: tuple[Path, ...] = LIB_DIRS) -> NpuReport:
    r = NpuReport()
    try:
        r.fastrpc_nodes = sorted(p.name for p in dev.iterdir()
                                 if p.name.startswith("fastrpc-") or p.name.startswith("adsprpc-smd"))
    except OSError:
        pass
    try:
        for rp in sorted(remoteproc.glob("remoteproc*")):
            r.dsp.append({"name": _read(rp / "name"), "state": _read(rp / "state")})
    except OSError:
        pass
    for d in lib_dirs:
        r.qnn_libs.extend(_find_libs(d, 3))
    cdsp = [d for d in r.dsp if "cdsp" in d["name"].lower()]
    cdsp_up = any(d["state"] == "running" for d in cdsp)
    if not r.fastrpc_nodes:
        r.notes.append("No fastrpc device node in /dev: the kernel's FastRPC driver is missing or not loaded, "
                       "so nothing in user space can send work to the DSP.")
    if not cdsp:
        r.notes.append("No remoteproc named cdsp: the compute DSP (where the NPU lives) is not described to Linux.")
    elif not cdsp_up:
        r.notes.append("The cdsp remoteproc exists but is not running (firmware not loaded or failed to boot).")
    if not r.qnn_libs:
        r.notes.append("No libQnnHtp*.so found: Qualcomm's QNN/QAIRT runtime is not installed (needed for the "
                       "QNN path; llama.cpp's Hexagon backend may still work without it).")
    r.reachable = bool(r.fastrpc_nodes) and cdsp_up
    return r


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m cortex_core.engine.npu_probe")
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    text = json.dumps(asdict(probe()), indent=2)
    print(text)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
