"""Place search: prefix + trigram matching over names, Singapore aliases, postal codes; ranked by match and distance.

    idx = Places(bundle)
    idx.search("northpoint", x, y)  -> [Hit(id, name, kind, score, dist_m), ...]
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

# spoken / short forms -> what names in the data say. Applied to the query word by word (and whole-phrase).
ALIASES = {
    "amk": "ang mo kio", "blk": "block", "bt": "bukit", "jln": "jalan", "lor": "lorong", "ave": "avenue",
    "st": "street", "rd": "road", "dr": "drive", "ctr": "centre", "center": "centre", "opp": "opposite",
    "stn": "station", "mrt": "mrt station", "int": "interchange", "cc": "community club", "hdb": "",
    "npc": "neighbourhood police centre", "ntuc": "", "fairprice": "fairprice", "kpt": "khoo teck puat",
    "ktph": "khoo teck puat hospital", "sgh": "singapore general hospital", "nus": "national university of singapore",
    "ntu": "nanyang technological university", "cbd": "raffles place", "jem": "jem", "vivo": "vivocity",
    "northpoint": "northpoint city", "causeway": "causeway point", "tamp": "tampines", "cck": "choa chu kang",
    "bp": "bukit panjang", "pasir ris": "pasir ris", "sengkang": "sengkang", "the": "",
}
# a station or a landmark is what people mean far more often than a shop unit or a bus stop of the same name
KIND_BONUS = {"mrt_station": 0.08, "lrt_station": 0.06, "mall": 0.04, "hospital": 0.04, "bus_interchange": 0.03,
              "address": -0.05, "bus_stop": -0.02}
_WORD = re.compile(r"[a-z0-9]+")
_POSTAL = re.compile(r"^\d{6}$")


def normalize(s: str) -> str:
    """Lower-case words, aliases expanded, punctuation dropped: 'Blk 101 Yishun Ave 5' -> 'block 101 yishun avenue 5'."""
    words = _WORD.findall(s.lower().replace("'", ""))
    out = []
    for w in words:
        a = ALIASES.get(w, w)
        if a:
            out.append(a)
    return " ".join(out)


def trigrams(s: str) -> set[int]:
    """Trigram keys of normalized text, each word padded ('  ab'), packed into an int (3 x 21 bits of code point)."""
    keys = set()
    for w in s.split():
        p = f"  {w} "
        for i in range(len(p) - 2):
            a, b, c = (ord(ch) & 0x1FFFFF for ch in p[i:i + 3])
            keys.add(((a & 0x3FF) << 20) | ((b & 0x3FF) << 10) | (c & 0x3FF))
    return keys


def build_index(names: list[str]) -> dict[str, np.ndarray]:
    """tri_key / tri_off / tri_ids for the bundle."""
    pairs: dict[int, list[int]] = {}
    for i, n in enumerate(names):
        for k in trigrams(normalize(n)):
            pairs.setdefault(k, []).append(i)
    keys = np.array(sorted(pairs), np.int32)
    off = np.zeros(len(keys) + 1, np.int32)
    ids = []
    for j, k in enumerate(keys):
        ids.extend(pairs[int(k)])
        off[j + 1] = len(ids)
    return {"tri_key": keys, "tri_off": off, "tri_ids": np.array(ids, np.int32)}


@dataclass
class Hit:
    id: int
    name: str
    kind: str
    score: float
    dist_m: float | None
    x: float
    y: float
    postal: int = 0

    def brief(self) -> dict:
        d = {"place_id": f"p_{self.id}", "name": self.name, "kind": self.kind}
        if self.dist_m is not None:
            d["distance_m"] = int(round(self.dist_m, -1))
        if self.postal:
            d["postal"] = f"{self.postal:06d}"
        return d


class Places:
    def __init__(self, b):
        self.b = b
        self._names: list[str] | None = None
        self._kind: list[str] | None = None

    def name(self, i: int) -> str:
        return self.b.s(int(self.b.place_name[i]))

    def _norm_names(self) -> list[str]:
        if self._names is None:  # built on the first search, kept (normalized names of every place)
            self._names = [normalize(self.name(i)) for i in range(self.b.n_places)]
        return self._names

    def warm(self) -> "Places":
        """Build the name and kind lists now (about 0.3 s on the server for 99k places) so the first search is fast;
        call it on a thread at startup."""
        self._norm_names()
        self._kinds()
        return self

    def _kinds(self) -> list[str]:
        if self._kind is None:
            ks = {int(k) for k in np.unique(self.b.place_kind)}
            names = {k: self.b.s(k) for k in ks}
            self._kind = [names[int(k)] for k in self.b.place_kind]
        return self._kind

    def _candidates(self, q: str) -> np.ndarray:
        keys = self.b.tri_key
        counts: dict[int, int] = {}
        qk = trigrams(q)
        for k in qk:
            j = int(np.searchsorted(keys, k))
            if j < len(keys) and int(keys[j]) == k:
                for i in self.b.tri_ids[self.b.tri_off[j]:self.b.tri_off[j + 1]]:
                    counts[int(i)] = counts.get(int(i), 0) + 1
        if not counts:
            return np.zeros(0, np.int64), np.zeros(0)
        ids = np.fromiter(counts.keys(), np.int64)
        share = np.fromiter(counts.values(), float) / max(1, len(qk))
        keep = share >= 0.45
        return ids[keep], share[keep]

    def search(self, query: str, x: float | None = None, y: float | None = None, limit: int = 3) -> list[Hit]:
        q = normalize(query)
        if not q:
            return []
        b = self.b
        if _POSTAL.match(q.replace(" ", "")):
            code = int(q.replace(" ", ""))
            ids = np.nonzero(np.asarray(b.place_postal) == code)[0]
            return [self._hit(int(i), 1.0, x, y) for i in ids[:limit]]
        ids, share = self._candidates(q)
        if len(ids) == 0:
            return []
        names = self._norm_names()
        kinds = self._kinds()
        scores = []
        for i, sh in zip(ids, share):
            n = names[int(i)]
            s = float(sh)
            if n == q:
                s += 1.0
            elif n.startswith(q):
                s += 0.6
            elif q in n:
                s += 0.35
            # whole query words present in the name
            qw = q.split()
            s += 0.2 * sum(w in n.split() for w in qw) / len(qw)
            s -= 0.01 * max(0, len(n) - len(q)) / 10  # prefer the tighter name
            s += KIND_BONUS.get(kinds[int(i)], 0.0)
            scores.append(s)
        scores = np.array(scores)
        if x is not None:
            d = np.hypot(np.asarray(b.place_x)[ids] - x, np.asarray(b.place_y)[ids] - y)
            scores = scores - 0.15 * np.log10(1 + d / 500)  # 5 km away costs ~0.15
        order = np.argsort(-scores)
        hits, seen = [], set()
        for j in order:
            h = self._hit(int(ids[j]), float(scores[j]), x, y)
            key = (h.name.lower(), h.kind)
            if key in seen:  # the same mall mapped twice, or a station's several exits
                continue
            seen.add(key)
            hits.append(h)
            if len(hits) == limit:
                break
        return hits

    def _hit(self, i: int, score: float, x, y) -> Hit:
        b = self.b
        px, py = float(b.place_x[i]), float(b.place_y[i])
        d = None if x is None else float(np.hypot(px - x, py - y))
        return Hit(i, self.name(i), b.s(int(b.place_kind[i])), score, d, px, py, int(b.place_postal[i]))

    @staticmethod
    def parse_id(place_id: str) -> int:
        m = re.fullmatch(r"\s*p_?(\d+)\s*", str(place_id))
        if not m:
            raise ValueError(f"not a place id: {place_id!r}")
        return int(m.group(1))
