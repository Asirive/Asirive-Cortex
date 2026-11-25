"""Builds the Singapore nav bundle on the home server from an OSM extract (+ LTA DataMall when a key is set).

    python infra/navbundle/build.py --pbf ~/cortex-data/osm/malaysia-singapore-brunei-latest.osm.pbf \
        --out ~/cortex-data/navbundle [--lta-dir DIR]

Reads the OSM file once (pyosmium, node locations in C++, only tagged objects reach Python), clipped to Singapore:
  walking graph   footways, paths, steps, crossings, pedestrian areas' outlines, and roads (flagged F_ROAD when
                  they have no sidewalk); every way node is kept so the follower's polyline matches the street.
  bus             stops (highway=bus_stop with a 5-digit LTA ref) and route relations (one per direction).
  MRT/LRT         stations (railway=station nodes or areas with subway / light_rail / monorail or an MRT/LRT
                  network) and route relations (subway, train, light_rail, monorail: Punggol / Bukit Panjang LRT,
                  Sentosa Express; not the airport Skytrain). Stop positions join the station of their name (within
                  600 m), unnamed ones the nearest within 350 m, else a named one becomes a station. A station any
                  MRT line calls at is an MRT station (Sengkang, Punggol are tagged light_rail too).
  places          named amenities, shops, malls, hawker centres, schools, parks...; HDB blocks / buildings with
                  addresses (Block 101 Yishun Avenue 5, postal code; not unit numbers). Areas (closed ways and
                  multipolygons, e.g. VivoCity) are reached by their outline + mapped entrances.
Headways: LTA BusServices frequency bands when `--lta-dir` holds DataMall JSON (BusServices.json); otherwise
defaults (bus 10/12/10/15 min, MRT 3/5/3/6, LRT 4/6/4/8), recorded in the manifest's sources.
The LTA key never enters this repo: a separate fetch job writes the DataMall JSON into --lta-dir.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))
from cortex_core.nav import bundle as B  # noqa: E402
from cortex_core.nav import build as NB  # noqa: E402

SG = (1.15, 103.59, 1.475, 104.10)  # lat0, lon0, lat1, lon1
WALK = {"footway", "path", "pedestrian", "steps", "living_street", "residential", "service", "unclassified",
        "tertiary", "tertiary_link", "secondary", "secondary_link", "primary", "primary_link", "corridor",
        "track", "cycleway", "bridleway", "road"}
MAJOR = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link"}
SIDEWALK_OK = {"both", "left", "right", "yes"}
NO_FOOT = {"no", "private"}
NOT_OURS = {"Skytrain"}  # Changi Airport's terminal shuttles (airside / landside), not a way across town
DEFAULT_HW = {B.K_BUS: [10, 12, 10, 15], B.K_MRT: [3, 5, 3, 6], B.K_LRT: [4, 6, 4, 8]}
PLACE_KEYS = {
    "amenity": {"hospital": "hospital", "clinic": "clinic", "doctors": "clinic", "school": "school",
                "college": "school", "university": "university", "library": "library",
                "community_centre": "community_centre", "place_of_worship": "place_of_worship",
                "marketplace": "market", "food_court": "hawker_centre", "police": "police",
                "post_office": "post_office", "bank": "bank", "pharmacy": "pharmacy", "toilets": "toilets",
                "restaurant": "restaurant", "fast_food": "restaurant", "cafe": "cafe", "cinema": "cinema",
                "townhall": "government", "courthouse": "government", "bus_station": "bus_interchange"},
    "shop": {"mall": "mall", "supermarket": "supermarket", "department_store": "mall"},
    "leisure": {"park": "park", "sports_centre": "sports_centre", "stadium": "stadium", "swimming_pool": "pool"},
    "tourism": {"attraction": "attraction", "museum": "museum", "hotel": "hotel", "zoo": "attraction"},
    "building": {"hospital": "hospital", "school": "school", "retail": "mall", "commercial": "building"},
}


def is_station(t) -> bool:
    """MRT/LRT stations are tagged several ways in Singapore's OSM."""
    if t.get("railway") not in ("station", "halt") and t.get("public_transport") != "station":
        return False
    if t.get("station") in ("subway", "light_rail", "monorail") or t.get("subway") == "yes" \
            or t.get("light_rail") == "yes":
        return True
    net = (t.get("network") or "") + " " + (t.get("operator") or "")
    return t.get("railway") == "station" and any(k in net for k in ("MRT", "LRT", "SMRT", "SBS Transit"))


_CODE = re.compile(r"\s*\(?\b[A-Z]{2}\d{1,2}\b\)?\s*")


def station_name(name: str) -> str:
    """'Bishan (NS17 / CC15)' / 'NS17 Bishan' / 'Bishan MRT Station' / 'Bishan - Loop' -> 'Bishan'."""
    n = name.split(" - ")[0]  # "Sengkang - West Loop Clockwise": a stop position named after its route
    n = re.sub(r"\(.*?\)", "", n)
    n = _CODE.sub(" ", n)
    n = re.sub(r"\b(MRT|LRT)\b|\bstation\b|\bStation\b|/", " ", n)
    return " ".join(n.split())


def in_sg(lat: float, lon: float) -> bool:
    return SG[0] <= lat <= SG[2] and SG[1] <= lon <= SG[3]


def place_kind(tags) -> str | None:
    for k, m in PLACE_KEYS.items():
        v = tags.get(k)
        if v in m:
            return m[v]
    if tags.get("amenity") == "food_court" or "hawker" in tags.get("name", "").lower():
        return "hawker_centre"
    return None


def address_name(tags) -> str | None:
    hn, st = tags.get("addr:housenumber"), tags.get("addr:street")
    if not hn or not st or "#" in hn or "," in hn:  # unit numbers (#01-03) are shops inside a block, not places
        return None
    return f"Block {hn} {st}" if re.fullmatch(r"\d+[A-Za-z]?", hn) else f"{hn} {st}"


def postal(tags) -> int:
    p = (tags.get("addr:postcode") or "").strip()
    return int(p) if re.fullmatch(r"\d{6}", p) else 0


class Reader:
    def __init__(self):
        self.node_ix: dict[int, int] = {}
        self.lat: list[float] = []
        self.lon: list[float] = []
        self.ways: list[tuple[int, int, int, str]] = []
        self.cross_nodes: dict[int, int] = {}  # osm node -> flags (crossing, signals)
        self.bus_stops: dict[int, dict] = {}  # osm node -> stop
        self.stations: dict[int, dict] = {}  # osm node -> station
        self.stop_pos: dict[int, tuple[float, float, str]] = {}  # stop_position / platform nodes
        self.routes: list[dict] = []
        self.places: list[dict] = []
        self.entrances: set[int] = set()  # osm nodes tagged entrance=* (malls, stations, blocks)
        self.counts = defaultdict(int)

    def _ix(self, nid: int, lat: float, lon: float) -> int:
        i = self.node_ix.get(nid)
        if i is None:
            i = self.node_ix[nid] = len(self.lat)
            self.lat.append(lat), self.lon.append(lon)
        return i

    def node(self, n):
        lat, lon = n.location.lat, n.location.lon
        if not in_sg(lat, lon):
            return
        t = n.tags
        if t.get("entrance") or t.get("railway") == "subway_entrance":
            self.entrances.add(n.id)
        hw = t.get("highway")
        if hw in ("crossing", "traffic_signals") or t.get("crossing"):
            f = B.F_CROSSING
            if hw == "traffic_signals" or t.get("crossing") in ("traffic_signals",) or t.get("crossing_signals") == "yes":
                f |= B.F_SIGNALS
            self.cross_nodes[n.id] = f
        if hw == "bus_stop" or (t.get("public_transport") == "platform" and t.get("bus") == "yes"):
            ref = (t.get("ref") or t.get("asset_ref") or "").strip()
            name = t.get("name") or t.get("description") or ""
            if re.fullmatch(r"\d{5}", ref) and name:
                self.bus_stops[n.id] = {"code": int(ref), "name": name, "lat": lat, "lon": lon, "kind": B.K_BUS}
        if is_station(t):
            kind = B.K_LRT if (t.get("station") in ("light_rail", "monorail") or t.get("light_rail") == "yes") \
                else B.K_MRT
            name = station_name(t.get("name:en") or t.get("name") or "")
            if name:
                self.stations[n.id] = {"code": 0, "ref": t.get("ref", ""), "name": name, "lat": lat, "lon": lon,
                                       "kind": kind}
        if t.get("public_transport") in ("stop_position", "platform") or t.get("railway") in ("stop", "platform"):
            self.stop_pos[n.id] = (lat, lon, t.get("name", ""))
        self._place(t, lat, lon)

    def _place(self, t, lat, lon, access=None):
        name = t.get("name:en") or t.get("name")
        kind = place_kind(t) if name else None
        if name and kind:
            self.places.append({"name": name, "kind": kind, "lat": lat, "lon": lon, "postal": postal(t),
                                "access": access})
            self.counts["place"] += 1
        a = address_name(t)
        if a:
            self.places.append({"name": a, "kind": "address", "lat": lat, "lon": lon, "postal": postal(t),
                                "access": access})
            self.counts["address"] += 1

    def way(self, w):
        t = w.tags
        nodes = w.nodes
        if len(nodes) < 2:
            return
        try:
            lat0, lon0 = nodes[0].location.lat, nodes[0].location.lon
        except Exception:  # noqa: BLE001 - missing location
            return
        hw = t.get("highway")
        if hw in WALK and t.get("foot") not in NO_FOOT and t.get("access") not in ("no",) and in_sg(lat0, lon0):
            if hw == "track" and t.get("foot") != "yes":
                hw = None
        if hw in WALK and t.get("foot") not in NO_FOOT and in_sg(lat0, lon0):
            f = 0
            if hw == "steps":
                f |= B.F_STEPS
            if t.get("footway") == "crossing" or t.get("crossing"):
                f |= B.F_CROSSING
                if t.get("crossing") == "traffic_signals" or t.get("crossing_signals") == "yes":
                    f |= B.F_SIGNALS
            if t.get("covered") in ("yes", "arcade") or hw == "corridor" or t.get("tunnel") == "building_passage":
                f |= B.F_COVERED
            if t.get("bridge") == "yes":
                f |= B.F_BRIDGE
            if hw in MAJOR and t.get("sidewalk", "") not in SIDEWALK_OK and t.get("foot") != "yes":
                f |= B.F_ROAD
            if t.get("ramp") == "yes" or t.get("incline") and hw == "footway" and t.get("wheelchair") == "yes":
                f |= B.F_RAMP
            name = t.get("name:en") or t.get("name") or ""
            prev = None
            for nd in nodes:
                try:
                    loc = nd.location
                    i = self._ix(nd.ref, loc.lat, loc.lon)
                except Exception:  # noqa: BLE001
                    prev = None
                    continue
                if prev is not None and prev != i:
                    ef = f
                    cf = self.cross_nodes.get(nd.ref, 0) | self.cross_nodes.get(self._osm_of_prev, 0)
                    if cf and not (f & B.F_CROSSING) and hw not in ("footway", "path", "pedestrian"):
                        pass  # a crossing node on the road itself: the footway crossing it carries the flag
                    elif cf:
                        ef |= cf
                    self.ways.append((prev, i, ef, name))
                prev = i
                self._osm_of_prev = nd.ref
            self.counts["walk_way"] += 1

    def area(self, a):
        """Closed ways and multipolygon relations (VivoCity is one): named places and station buildings."""
        t = a.tags
        name = t.get("name:en") or t.get("name")
        station = bool(name) and is_station(t)
        kind = place_kind(t) if name else None
        addr = address_name(t)
        if not (station or kind or addr):
            return
        pts, refs = [], []
        try:
            for ring in a.outer_rings():
                for nr in ring:
                    pts.append((nr.lat, nr.lon))
                    refs.append(nr.ref)
        except Exception:  # noqa: BLE001 - a broken ring
            return
        if not pts:
            return
        c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        if not in_sg(*c):
            return
        if station:
            kind_ = B.K_LRT if (t.get("station") in ("light_rail", "monorail") or t.get("light_rail") == "yes") \
                else B.K_MRT
            nm = station_name(name)
            if nm:  # keyed below zero: never a route member (those are nodes)
                self.stations[-int(a.id)] = {"code": 0, "ref": t.get("ref", ""), "name": nm, "lat": c[0],
                                             "lon": c[1], "kind": kind_}
            return
        # where you walk in: the outline (sampled) plus every mapped entrance, routes end at the quickest. Not the
        # middle of the building, which snaps to whichever footway is nearest, often across a road; not entrances
        # alone: SG malls have few mapped (Northpoint City 2, Causeway Point 1), so they sent people round it.
        ent = [p for p, r in zip(pts, refs) if r in self.entrances]
        step = max(1, len(pts) // 24)
        access = list(dict.fromkeys(ent + pts[::step]))
        self._place(t, *c, access=access)

    def relation(self, r):
        t = r.tags
        if t.get("type") != "route" or t.get("route") not in ("bus", "subway", "light_rail", "train", "monorail"):
            return
        ref = t.get("ref") or t.get("name") or ""
        if not ref or ref in NOT_OURS:
            return
        members = [(m.ref, m.role) for m in r.members if m.type == "n" and m.role.startswith(("stop", "platform"))]
        # Punggol / Bukit Panjang LRT and Sentosa Express are route=monorail in OSM
        mode = {"bus": B.K_BUS, "subway": B.K_MRT, "train": B.K_MRT, "light_rail": B.K_LRT,
                "monorail": B.K_LRT}[t["route"]]
        self.routes.append({"ref": ref, "mode": mode, "members": members, "name": t.get("name", ""),
                            "interval": t.get("interval")})


def read_osm(pbf: Path) -> Reader:
    import osmium

    rd = Reader()
    fp = (osmium.FileProcessor(str(pbf))
          .with_locations()
          .with_areas()
          .with_filter(osmium.filter.KeyFilter("highway", "railway", "public_transport", "amenity", "shop",
                                               "leisure", "tourism", "building", "addr:housenumber", "type", "route",
                                               "entrance")))
    t0 = time.time()
    for o in fp:
        if o.is_node():
            rd.node(o)
        elif o.is_way():
            rd.way(o)
        elif o.is_relation():
            rd.relation(o)
        elif o.is_area():
            rd.area(o)
    print(f"read {pbf.name} in {time.time() - t0:.0f} s: {len(rd.lat)} walk nodes, {len(rd.ways)} segments, "
          f"{len(rd.bus_stops)} bus stops, {len(rd.stations)} stations, {len(rd.routes)} route relations, "
          f"{len(rd.places)} places", flush=True)
    return rd


def _dist(a, b) -> float:
    return math.hypot((a[0] - b[0]) * 110_574, (a[1] - b[1]) * 111_320 * math.cos(math.radians(1.35)))


def assemble_transit(rd: Reader, headways: dict[str, list[float]]):
    stops: list[dict] = []
    bus_ix: dict[int, int] = {}
    code_ix: dict[int, int] = {}
    for nid, s in rd.bus_stops.items():
        if s["code"] in code_ix:  # the same LTA stop mapped twice
            bus_ix[nid] = code_ix[s["code"]]
            continue
        bus_ix[nid] = code_ix[s["code"]] = len(stops)
        stops.append(s)
    st_ix: dict[int, int] = {}
    for nid, s in rd.stations.items():
        dup = next((st_ix[o] for o, q in rd.stations.items() if o in st_ix and q["name"] == s["name"]
                    and q["kind"] == s["kind"] and _dist((q["lat"], q["lon"]), (s["lat"], s["lon"])) < 400), None)
        if dup is not None:  # interchange stations mapped once per line: one stop per station
            st_ix[nid] = dup
            continue
        st_ix[nid] = len(stops)
        stops.append(s)
    station_list = [(i, (stops[i]["lat"], stops[i]["lon"])) for i in set(st_ix.values())]

    patterns, used = [], defaultdict(int)
    for r in rd.routes:
        seq: list[int] = []
        for nid, _role in r["members"]:
            if r["mode"] == B.K_BUS:
                s = bus_ix.get(nid)
                if s is None and nid in rd.stop_pos:  # a stop position beside the stop: nearest bus stop by code
                    s = None
            else:
                s = st_ix.get(nid)
                if s is None and nid in rd.stop_pos:
                    p = rd.stop_pos[nid][:2]
                    nm = station_name(rd.stop_pos[nid][2]).lower()
                    same = [q for q in station_list if nm and stops[q[0]]["name"].lower() == nm
                            and _dist(q[1], p) < 600]  # the station of its name first (interchanges are big)
                    best = min(same or station_list, key=lambda q: _dist(q[1], p), default=None)
                    if best is not None and (same or (not nm and _dist(best[1], p) < 350)):
                        s = best[0]
                    elif nm:  # no station mapped: the named stop position is one
                        s = st_ix[nid] = len(stops)
                        stops.append({"code": 0, "ref": "", "name": station_name(rd.stop_pos[nid][2]), "lat": p[0],
                                      "lon": p[1], "kind": r["mode"]})
                        station_list.append((s, p))
            if s is not None and (not seq or seq[-1] != s):
                seq.append(s)
        if len(seq) < 2:
            continue
        svc = r["ref"]
        hw = headways.get(svc.upper()) or DEFAULT_HW[r["mode"]]
        patterns.append({"service": svc, "mode": r["mode"], "stops": seq, "headway": hw})
        used[r["mode"]] += 1
        if r["mode"] == B.K_MRT:
            for s_ in seq:  # Sengkang / Punggol are tagged light_rail but the NEL calls there: an MRT station
                if stops[s_]["kind"] == B.K_LRT:
                    stops[s_] = {**stops[s_], "kind": B.K_MRT}
    print(f"transit: {len(stops)} stops, patterns bus {used[B.K_BUS]}, MRT {used[B.K_MRT]}, LRT {used[B.K_LRT]}",
          flush=True)
    return stops, patterns


def lta_headways(lta_dir: Path | None) -> tuple[dict[str, list[float]], str]:
    """BusServices.json (DataMall 'value' list): AM_Peak_Freq '06-08' -> mean minutes per band."""
    if lta_dir is None or not (lta_dir / "BusServices.json").is_file():
        return {}, "default headways (no LTA BusServices)"
    raw = json.loads((lta_dir / "BusServices.json").read_text())
    rows = raw.get("value", raw) if isinstance(raw, dict) else raw
    out: dict[str, list[float]] = {}

    def mean(s):
        nums = [float(x) for x in re.findall(r"\d+", s or "")]
        return sum(nums) / len(nums) if nums else 0.0
    for r in rows:
        hw = [mean(r.get(k)) for k in ("AM_Peak_Freq", "AM_Offpeak_Freq", "PM_Peak_Freq", "PM_Offpeak_Freq")]
        svc = str(r.get("ServiceNo", "")).upper()
        if svc:
            prev = out.get(svc)
            out[svc] = hw if prev is None else [min(a, b) if a and b else a or b for a, b in zip(prev, hw)]
    return out, f"LTA BusServices ({len(out)} services)"


def dedupe_places(places: list[dict]) -> list[dict]:
    seen, out = set(), []
    for p in places:
        k = (p["name"].lower(), p["kind"], round(p["lat"], 3), round(p["lon"], 3))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--lta-dir", type=Path)
    ap.add_argument("--version", default=time.strftime("%Y%m%d-%H%M"))
    a = ap.parse_args(argv)
    t0 = time.time()
    rd = read_osm(a.pbf)
    hw, hw_src = lta_headways(a.lta_dir)
    stops, patterns = assemble_transit(rd, hw)
    places = dedupe_places(rd.places)
    arrays = NB.assemble(rd.lat, rd.lon, rd.ways, stops, patterns, places,
                         log=lambda m: print(m, flush=True))
    a.out.mkdir(parents=True, exist_ok=True)
    sources = {"osm": a.pbf.name, "osm_mtime": time.strftime("%Y-%m-%d", time.gmtime(a.pbf.stat().st_mtime)),
               "headways": hw_src, "bbox": SG}
    path = B.write(a.out, a.version, arrays, sources)
    size = sum(f.stat().st_size for f in path.iterdir())
    print(f"bundle {path} {size / 1e6:.1f} MB in {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
