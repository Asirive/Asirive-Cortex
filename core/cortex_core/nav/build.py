"""Assembles bundle arrays from plain lists. The server builder (infra/navbundle) parses OSM / LTA into these lists;
tests build small cities the same way, so the assembly is tested once.

    arrays = assemble(nodes_lat, nodes_lon, ways, stops, patterns, places)
    bundle.write(root, version, arrays, sources)

ways:     [(u, v, flags, name)]  undirected footpath segments between node indices
stops:    [{"code": 59009 | 0, "ref": "NS13" | "", "name", "lat", "lon", "kind": K_BUS|K_MRT|K_LRT}]
patterns: [{"service": "858", "mode": K_BUS, "stops": [stop index...], "headway": [4 x minutes],
            "dist": [metres from first stop] (optional: straight-line sum), "speed": m/s (optional)}]
places:   [{"name", "kind", "lat", "lon", "postal": int (optional)}]
"""
from __future__ import annotations

import numpy as np

from cortex_core.nav import bundle as B
from cortex_core.nav import geo, places as P
from cortex_core.nav.walk import Walker

DEFAULT_SPEED = {B.K_BUS: 5.0, B.K_MRT: 11.0, B.K_LRT: 7.0}  # m/s including dwell (bus ~18 km/h, MRT ~40 km/h)
TRANSFER_M = 400.0


def assemble(lat, lon, ways, stops, patterns, places, log=print) -> dict[str, np.ndarray]:
    S = B.Strings()
    nx, ny = geo.to_xy(np.asarray(lat, np.float64), np.asarray(lon, np.float64))
    n = len(nx)
    w = np.array([(u, v) for u, v, _, _ in ways], np.int64).reshape(-1, 2)
    fl = np.array([f for _, _, f, _ in ways], np.uint8)
    nm = np.array([S.id(name) for _, _, _, name in ways], np.int32)
    ln = np.hypot(nx[w[:, 0]] - nx[w[:, 1]], ny[w[:, 0]] - ny[w[:, 1]]).astype(np.float32)
    src = np.concatenate([w[:, 0], w[:, 1]])
    dst = np.concatenate([w[:, 1], w[:, 0]])
    off, to, el, ef, en = B.csr(n, src, dst.astype(np.int32), np.concatenate([ln, ln]),
                                np.concatenate([fl, fl]), np.concatenate([nm, nm]))
    a: dict[str, np.ndarray] = {
        "node_x": nx.astype(np.float32), "node_y": ny.astype(np.float32),
        "edge_off": off, "edge_to": to.astype(np.int32), "edge_len": el.astype(np.float32),
        "edge_flags": ef.astype(np.uint8), "edge_name": en.astype(np.int32),
    }
    log(f"walk graph: {n} nodes, {len(to)} directed edges")

    # a walker over what we have so far (stops and places need nearest nodes and walking distances)
    class _G:
        pass

    g = _G()
    for k, v in a.items():
        setattr(g, k, v)
    g.s = S.items.__getitem__
    wk = Walker(g)

    sx, sy = geo.to_xy(np.array([s["lat"] for s in stops], np.float64), np.array([s["lon"] for s in stops], np.float64))
    stop_node = np.array([wk.nearest(float(x), float(y), 400.0) for x, y in zip(sx, sy)], np.int32)
    a.update({
        "stop_code": np.array([int(s.get("code") or 0) for s in stops], np.int32),
        "stop_ref": np.array([S.id(s.get("ref") or (f"{int(s['code']):05d}" if s.get("code") else "")) for s in stops], np.int32),
        "stop_name": np.array([S.id(s["name"]) for s in stops], np.int32),
        "stop_x": sx.astype(np.float32), "stop_y": sy.astype(np.float32), "stop_node": stop_node,
        "stop_kind": np.array([s["kind"] for s in stops], np.uint8),
    })
    log(f"stops: {len(stops)} ({int((stop_node < 0).sum())} without a walking node within 400 m)")

    # patterns
    poff = np.zeros(len(patterns) + 1, np.int32)
    pstop, pdist, psvc, pmode, phw, pspd = [], [], [], [], [], []
    for i, p in enumerate(patterns):
        st = list(p["stops"])
        if p.get("dist") is not None:
            d = list(map(float, p["dist"]))
        else:
            seg = np.hypot(np.diff(sx[st]), np.diff(sy[st])) * 1.25  # roads wind: straight line x 1.25
            d = [0.0] + list(np.cumsum(seg))
        pstop += st
        pdist += d
        poff[i + 1] = len(pstop)
        psvc.append(S.id(p["service"]))
        pmode.append(p["mode"])
        phw.append(list(p.get("headway") or [10, 12, 10, 15]))
        pspd.append(float(p.get("speed") or DEFAULT_SPEED[p["mode"]]))
    a.update({"pat_off": poff, "pat_stop": np.array(pstop, np.int32), "pat_dist": np.array(pdist, np.float32),
              "pat_service": np.array(psvc, np.int32), "pat_mode": np.array(pmode, np.uint8),
              "pat_headway": np.array(phw, np.float32).reshape(-1, 4), "pat_speed": np.array(pspd, np.float32)})
    sp_src = a["pat_stop"].astype(np.int64)
    sp_pat = np.repeat(np.arange(len(patterns), dtype=np.int32), np.diff(poff))
    sp_idx = np.concatenate([np.arange(k, dtype=np.int32) for k in np.diff(poff)]) if len(patterns) else np.zeros(0, np.int32)
    a["sp_off"], a["sp_pat"], a["sp_idx"] = B.csr(len(stops), sp_src, sp_pat, sp_idx)
    log(f"patterns: {len(patterns)}, {len(pstop)} stop calls")

    # transfers: walking metres between stops within TRANSFER_M (by the graph; straight line if a stop has no node)
    node_stops: dict[int, list[int]] = {}
    for s, nd in enumerate(stop_node):
        if nd >= 0:
            node_stops.setdefault(int(nd), []).append(s)
    tsrc, tdst, tlen = [], [], []
    for s, nd in enumerate(stop_node):
        if nd < 0:
            continue
        for v, d in wk.reach(int(nd), TRANSFER_M).items():
            for t in node_stops.get(v, ()):
                if t != s:
                    tsrc.append(s), tdst.append(t), tlen.append(d)
    a["tr_off"], a["tr_to"], a["tr_len"] = B.csr(len(stops), np.array(tsrc, np.int64),
                                                np.array(tdst, np.int32), np.array(tlen, np.float32))
    log(f"transfers: {len(tsrc)}")

    # places (stops and stations are places too)
    names, kinds, qx, qy, post = [], [], [], [], []
    for p in places:
        x, y = geo.to_xy(p["lat"], p["lon"])
        names.append(p["name"]), kinds.append(p["kind"]), qx.append(float(x)), qy.append(float(y))
        post.append(int(p.get("postal") or 0))
    for s in stops:
        if s["kind"] == B.K_BUS:
            nm_ = s["name"] + (f" bus stop {int(s['code']):05d}" if s.get("code") else " bus stop")
            kind = "bus_stop"
        else:
            nm_ = s["name"] if "station" in s["name"].lower() else f"{s['name']} station"
            kind = "mrt_station" if s["kind"] == B.K_MRT else "lrt_station"
        x, y = geo.to_xy(s["lat"], s["lon"])
        names.append(nm_), kinds.append(kind), qx.append(float(x)), qy.append(float(y)), post.append(0)
    qx_, qy_ = np.array(qx), np.array(qy)
    a.update({
        "place_name": np.array([S.id(x) for x in names], np.int32),
        "place_kind": np.array([S.id(k) for k in kinds], np.int32),
        "place_x": qx_.astype(np.float32), "place_y": qy_.astype(np.float32),
        "place_node": np.array([wk.nearest(float(x), float(y), 500.0) for x, y in zip(qx_, qy_)], np.int32),
        "place_postal": np.array(post, np.int32),
    })
    a.update(P.build_index(names))
    log(f"places: {len(names)}")
    a.update(S.pack())
    return a
