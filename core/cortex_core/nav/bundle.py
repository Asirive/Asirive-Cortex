"""The nav bundle: versioned NumPy arrays, memory-mapped at load (no parsing at start), plus a manifest.

Layout (a directory, `<root>/<version>/`):
    manifest.json        {"format": 1, "version", "built", "sources", "files": {name: {"sha256", "dtype", "shape"}}}
    <name>.npy           one array per name below

Walking graph (directed CSR, both directions of a way are stored; x/y are local metres, geo.to_xy):
    node_x, node_y        float32 [N]
    edge_off              int32 [N+1]      edges of node i are edge_off[i]:edge_off[i+1]
    edge_to               int32 [E]
    edge_len              float32 [E]      metres
    edge_flags            uint8 [E]        F_* below
    edge_name             int32 [E]        string id (-1 = unnamed)
Stops (bus stops and MRT/LRT stations):
    stop_code             int32 [S]        LTA bus stop code; stations: 0 (their code is in stop_ref)
    stop_ref              int32 [S]        string id: the station code ("NS13") or the code as text
    stop_name             int32 [S]        string id
    stop_x, stop_y        float32 [S]
    stop_node             int32 [S]        nearest walking node
    stop_kind             uint8 [S]        K_BUS, K_MRT, K_LRT
Patterns (one direction of one service, its stops in order):
    pat_off               int32 [P+1]
    pat_stop              int32 [sum]      stop ids
    pat_dist              float32 [sum]    metres from the pattern's first stop
    pat_service           int32 [P]        string id ("858", "NSL")
    pat_mode              uint8 [P]        K_BUS, K_MRT, K_LRT
    pat_headway           float32 [P, 4]   minutes: AM peak, AM off-peak, PM peak, PM off-peak (0 = no service)
    pat_speed             float32 [P]      mean m/s including dwell
    sp_off                int32 [S+1]      the patterns calling at stop s: sp_pat/sp_idx[sp_off[s]:sp_off[s+1]]
    sp_pat, sp_idx        int32
Transfers between stops on foot (<= 400 m):
    tr_off                int32 [S+1]
    tr_to                 int32
    tr_len                float32          walking metres
Places:
    place_name            int32 [Q]        string id
    place_kind            int32 [Q]        string id ("mall", "mrt_station", "bus_stop", "postcode", ...)
    place_x, place_y      float32 [Q]
    place_node            int32 [Q]
    place_postal          int32 [Q]        6-digit postal code, 0 = none
    pacc_off              int32 [Q+1]      walking nodes you can reach the place by (an area's entrances / edge):
    pacc_node             int32            pacc_node[pacc_off[i]:pacc_off[i+1]]; routes end at the quickest one
    tri_key               int32 [T]        sorted trigram keys (see places.trigrams)
    tri_off               int32 [T+1]
    tri_ids               int32            place ids per trigram
Strings:
    str_blob              uint8            UTF-8, concatenated
    str_off               int64 [n+1]
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

FORMAT = 1
F_CROSSING, F_SIGNALS, F_STEPS, F_COVERED, F_BRIDGE, F_ROAD, F_RAMP = 1, 2, 4, 8, 16, 32, 64
K_BUS, K_MRT, K_LRT = 0, 1, 2
BANDS = ("am_peak", "am_off", "pm_peak", "pm_off")

REQUIRED = ("node_x", "node_y", "edge_off", "edge_to", "edge_len", "edge_flags", "edge_name",
            "stop_code", "stop_ref", "stop_name", "stop_x", "stop_y", "stop_node", "stop_kind",
            "pat_off", "pat_stop", "pat_dist", "pat_service", "pat_mode", "pat_headway", "pat_speed",
            "sp_off", "sp_pat", "sp_idx", "tr_off", "tr_to", "tr_len",
            "place_name", "place_kind", "place_x", "place_y", "place_node", "place_postal", "pacc_off", "pacc_node",
            "tri_key", "tri_off", "tri_ids", "str_blob", "str_off")


class BundleError(RuntimeError):
    pass


def band_of(hour: float) -> int:
    """LTA's frequency bands: AM peak 06:30-08:30, AM off-peak 08:31-16:59, PM peak 17:00-19:00, PM off-peak after."""
    if 6.5 <= hour < 8.5:
        return 0
    if 8.5 <= hour < 17:
        return 1
    if 17 <= hour < 19:
        return 2
    return 3


class Strings:
    """Interning table while building."""

    def __init__(self):
        self._ids: dict[str, int] = {}
        self.items: list[str] = []

    def id(self, s: str | None) -> int:
        if not s:
            return -1
        i = self._ids.get(s)
        if i is None:
            i = self._ids[s] = len(self.items)
            self.items.append(s)
        return i

    def pack(self) -> dict[str, np.ndarray]:
        enc = [s.encode() for s in self.items]
        off = np.zeros(len(enc) + 1, np.int64)
        off[1:] = np.cumsum([len(b) for b in enc])
        return {"str_blob": np.frombuffer(b"".join(enc), np.uint8).copy(), "str_off": off}


def csr(n: int, src: np.ndarray, *cols: np.ndarray) -> tuple[np.ndarray, ...]:
    """Group rows by src (0..n-1): (offsets [n+1], each col sorted by src)."""
    src = np.asarray(src, np.int64)
    order = np.argsort(src, kind="stable")
    off = np.zeros(n + 1, np.int32)
    np.add.at(off, src + 1, 1)
    off = np.cumsum(off).astype(np.int32)
    return (off,) + tuple(np.asarray(c)[order] for c in cols)


def write(root: Path, version: str, arrays: dict[str, np.ndarray], sources: dict | None = None) -> Path:
    """Writes <root>/<version>/ atomically (a temp dir renamed into place)."""
    missing = [k for k in REQUIRED if k not in arrays]
    if missing:
        raise BundleError(f"bundle misses {missing}")
    root = Path(root)
    final = root / version
    tmp = root / f".{version}.tmp"
    if tmp.exists():
        for f in tmp.iterdir():
            f.unlink()
    tmp.mkdir(parents=True, exist_ok=True)
    files = {}
    for k, a in arrays.items():
        a = np.ascontiguousarray(a)
        np.save(tmp / f"{k}.npy", a, allow_pickle=False)
        files[k] = {"sha256": hashlib.sha256((tmp / f"{k}.npy").read_bytes()).hexdigest(),
                    "dtype": str(a.dtype), "shape": list(a.shape)}
    man = {"format": FORMAT, "version": version, "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "sources": sources or {}, "files": files}
    (tmp / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True))
    if final.exists():
        raise BundleError(f"{final} exists; versions are never overwritten")
    tmp.rename(final)
    return final


class Bundle:
    """A loaded bundle: every array is a read-only memory map; attribute access by name (b.node_x)."""

    def __init__(self, path: str | Path, verify: bool = False):
        self.path = Path(path)
        mp = self.path / "manifest.json"
        if not mp.is_file():
            raise BundleError(f"no manifest in {self.path}")
        self.manifest = json.loads(mp.read_text())
        if self.manifest.get("format") != FORMAT:
            raise BundleError(f"bundle format {self.manifest.get('format')} (this code reads {FORMAT})")
        self.version = self.manifest["version"]
        self._a: dict[str, np.ndarray] = {}
        for k, meta in self.manifest["files"].items():
            f = self.path / f"{k}.npy"
            if verify and hashlib.sha256(f.read_bytes()).hexdigest() != meta["sha256"]:
                raise BundleError(f"{k}.npy does not match the manifest")
            a = np.load(f, mmap_mode="r", allow_pickle=False)
            if list(a.shape) != meta["shape"] or str(a.dtype) != meta["dtype"]:
                raise BundleError(f"{k}.npy shape/dtype differ from the manifest")
            self._a[k] = a
        missing = [k for k in REQUIRED if k not in self._a]
        if missing:
            raise BundleError(f"bundle misses {missing}")
        self.n_nodes = len(self._a["node_x"])
        self.n_stops = len(self._a["stop_x"])
        self.n_patterns = len(self._a["pat_service"])
        self.n_places = len(self._a["place_x"])

    def __getattr__(self, k: str) -> np.ndarray:
        try:
            return self.__dict__["_a"][k]
        except KeyError:
            raise AttributeError(k) from None

    def s(self, i: int) -> str:
        """String i ('' for -1)."""
        if i < 0:
            return ""
        o = self._a["str_off"]
        return bytes(self._a["str_blob"][int(o[i]):int(o[i + 1])]).decode()

    def pattern_stops(self, p: int) -> np.ndarray:
        return self._a["pat_stop"][self._a["pat_off"][p]:self._a["pat_off"][p + 1]]

    def pattern_dist(self, p: int) -> np.ndarray:
        return self._a["pat_dist"][self._a["pat_off"][p]:self._a["pat_off"][p + 1]]

    def place_nodes(self, i: int) -> list[int]:
        """Every walking node the place can be reached by (at least its own node)."""
        a = self._a["pacc_node"][self._a["pacc_off"][i]:self._a["pacc_off"][i + 1]]
        out = [int(n) for n in a if n >= 0]
        n0 = int(self._a["place_node"][i])
        return out or ([n0] if n0 >= 0 else [])

    def stop_label(self, s: int) -> str:
        name = self.s(int(self._a["stop_name"][s]))
        code = int(self._a["stop_code"][s])
        return f"{name} ({code:05d})" if code else name


def latest(root: str | Path) -> Path:
    """The newest version directory under root (names sort by build time: YYYYMMDD-HHMM...)."""
    vs = sorted(p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith(".")
                and (p / "manifest.json").is_file())
    if not vs:
        raise BundleError(f"no nav bundle in {root}")
    return vs[-1]
