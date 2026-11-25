import json
import socket
import threading
import time

import pytest

from cortex_core.link import gps
from cortex_core.link import phone_link as pl
from cortex_core.link.__main__ import location_sink

from tests.test_phone_link import SECRET, mk, provision, req

FIX = {"lat": 1.4295, "lon": 103.8355, "acc_m": 6, "speed": 1.2, "course": 90, "t": 1764000000.5}


def test_parse_fix_normalises_and_defaults_time():
    f = gps.parse_fix({"lat": 1.43, "lon": 103.83, "acc_m": 5}, now=lambda: 42.0)
    assert f == {"lat": 1.43, "lon": 103.83, "acc_m": 5.0, "speed": None, "course": None, "t": 42.0}
    assert gps.parse_fix(FIX)["t"] == 1764000000.5


@pytest.mark.parametrize("bad", [
    None, [], {}, {"lat": 1.4, "lon": 103.8}, {"lat": 91, "lon": 0, "acc_m": 5}, {"lat": 1, "lon": 181, "acc_m": 5},
    {"lat": "1.4", "lon": 103.8, "acc_m": 5}, {"lat": True, "lon": 103.8, "acc_m": 5},
    {"lat": float("nan"), "lon": 103.8, "acc_m": 5}, {"lat": 1.4, "lon": 103.8, "acc_m": -1},
    {"lat": 1.4, "lon": 103.8, "acc_m": 5, "speed": -1}, {"lat": 1.4, "lon": 103.8, "acc_m": 5, "course": 400},
])
def test_parse_fix_refuses(bad):
    with pytest.raises(gps.FixError):
        gps.parse_fix(bad)


def test_forward_and_listen_round_trip(tmp_path):
    path = str(tmp_path / "run" / "gps.sock")
    got, ev = [], threading.Event()
    lis = gps.GpsListener(path, lambda f: (got.append(f), ev.set())).start()
    try:
        fwd = gps.GpsForwarder(path)
        # garbage first: dropped, the listener keeps going
        socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM).sendto(b"not json", path)
        socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM).sendto(json.dumps({"lat": 99}).encode(), path)
        assert fwd.send(gps.parse_fix(FIX))
        assert ev.wait(2)
        assert got == [gps.parse_fix(FIX)]
    finally:
        lis.stop()
    assert not (tmp_path / "run" / "gps.sock").exists()


def test_listener_survives_a_failing_callback(tmp_path):
    path = str(tmp_path / "gps.sock")
    n, ev = [0], threading.Event()

    def cb(f):
        n[0] += 1
        if n[0] == 1:
            raise RuntimeError("nav bug")
        ev.set()
    lis = gps.GpsListener(path, cb).start()
    try:
        fwd = gps.GpsForwarder(path)
        fwd.send(gps.parse_fix(FIX))
        fwd.send(gps.parse_fix(FIX))
        assert ev.wait(2) and n[0] == 2
    finally:
        lis.stop()


def test_forwarder_drops_when_nobody_listens(tmp_path):
    fwd = gps.GpsForwarder(str(tmp_path / "nobody.sock"))
    t0 = time.monotonic()
    assert fwd.send(gps.parse_fix(FIX)) is False and fwd.dropped == 1
    assert time.monotonic() - t0 < 0.5  # never blocks the link
    fwd.close()


def test_recorder_only_on_dev_builds(tmp_path, monkeypatch):
    monkeypatch.delenv("CORTEX_DEV_BUILD", raising=False)
    assert gps.GpsRecorder(tmp_path).write(gps.parse_fix(FIX)) is None
    assert not (tmp_path / "recordings").exists()
    monkeypatch.setenv("CORTEX_DEV_BUILD", "1")
    r = gps.GpsRecorder(tmp_path)
    p = r.write(gps.parse_fix(FIX))
    r.write(gps.parse_fix({**FIX, "t": FIX["t"] + 1}))
    assert p.parent == tmp_path / "recordings" and p.name.startswith("gps-") and p.suffix == ".jsonl"
    assert [f["t"] for f in gps.replay(p)] == [FIX["t"], FIX["t"] + 1]


def test_replay_skips_blanks_and_paces(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text("\n".join(json.dumps({**FIX, "t": FIX["t"] + i * 0.1}) for i in range(3)) + "\n\n")
    t0 = time.monotonic()
    assert len(list(gps.replay(p, speed=1.0))) == 3
    assert time.monotonic() - t0 >= 0.18


def test_location_op_is_signed_and_validated(tmp_path):
    link, _ = mk(tmp_path)
    got = []
    assert link.handle(req(1, "location", FIX), "n", {})["error"] == "not paired"
    provision(link)
    st: dict = {}
    assert link.handle(req(2, "location", FIX, SECRET), "n", st)["error"] == "location not wanted"
    link.on_location = got.append
    assert link.handle(req(3, "location", FIX), "n", st)["error"] == "bad signature"  # unsigned: nobody else's GPS
    assert link.handle(req(4, "location", FIX, SECRET), "n", st)["ok"]
    r = link.handle(req(5, "location", {"lat": 1.4}, SECRET), "n", st)
    assert not r["ok"] and r["error"].startswith("bad fix")
    assert got == [gps.parse_fix(FIX)]


def test_location_sink_forwards_and_records(tmp_path, monkeypatch):
    path = str(tmp_path / "gps.sock")
    got, ev = [], threading.Event()
    lis = gps.GpsListener(path, lambda f: (got.append(f), ev.set())).start()
    try:
        rec = gps.GpsRecorder(tmp_path / "nav", enabled=True)
        sink = location_sink(gps.GpsForwarder(path), rec)
        sink(gps.parse_fix(FIX))
        assert ev.wait(2) and got[0]["lat"] == FIX["lat"]
        assert len(list((tmp_path / "nav" / "recordings").glob("gps-*.jsonl"))) == 1
        # a read-only disk must not break forwarding
        bad = gps.GpsRecorder(tmp_path / "nav", enabled=True)
        bad.write = lambda f: (_ for _ in ()).throw(OSError("ro"))
        location_sink(gps.GpsForwarder(path), bad)(gps.parse_fix(FIX))
    finally:
        lis.stop()
