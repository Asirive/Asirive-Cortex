"""The phone app's real GPS code (Dart, apps/mobile/lib/location_stream.dart) against the box's real phone link,
forwarder and listener: catches any drift between the two sides of the `location` op.

Needs Flutter (`flutter` on PATH or ~/.local/flutter). Without it the test is skipped, and says so."""
import asyncio
import base64
import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from cortex_core.link import gps

from tests.test_phone_link import SECRET, mk, provision

APP = Path(__file__).resolve().parents[2] / "apps" / "mobile"


def _flutter():
    return shutil.which("flutter") or next(
        (p for p in [os.path.expanduser("~/.local/flutter/bin/flutter")] if os.path.exists(p)), None)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(_flutter() is None, reason="Flutter not installed: the app side of GPS is not cross-checked")
def test_app_gps_reaches_the_box_listener(tmp_path):
    link, _ = mk(tmp_path)
    assert provision(link)["ok"]
    sock = str(tmp_path / "gps.sock")
    got = []
    lis = gps.GpsListener(sock, got.append).start()
    fwd = gps.GpsForwarder(sock)
    link.on_location = fwd.send  # what link/__main__ wires (minus the dev recorder)

    port = _free_port()
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(link.serve("127.0.0.1", port, stop, beacon_port=_free_port(), beacon_dest="127.0.0.1"))

    th = threading.Thread(target=run, daemon=True)
    th.start()
    try:
        env = dict(os.environ, CORTEX_BOX_PORT=str(port), CORTEX_BOX_SECRET=base64.b64encode(SECRET).decode())
        r = subprocess.run([_flutter(), "test", "--reporter", "expanded", "test/real_box_location_test.dart"],
                           cwd=APP, env=env, capture_output=True, text=True, timeout=600)
        assert r.returncode == 0 and "CROSS-OK" in r.stdout, r.stdout[-3000:] + r.stderr[-2000:]
        for _ in range(100):
            if len(got) == 3:
                break
            threading.Event().wait(0.02)
    finally:
        loop.call_soon_threadsafe(stop.set)
        th.join(5)
        lis.stop()
        fwd.close()

    assert [round(f["lat"], 4) for f in got] == [1.4295, 1.4296, 1.4297]
    assert got[0]["speed"] is None and got[0]["course"] is None  # the phone's -1 = unknown, left out
    assert got[1]["speed"] == 1.3 and got[1]["course"] == 90
    assert got[2]["speed"] is None and got[2]["course"] == 359.9  # NaN dropped, the rest kept
    assert got[0]["t"] == 1795658400.0 and got[1]["t"] == 1795658401.5  # seconds, not milliseconds
