"""infra/navbundle/lta_fetch.py against a local stand-in for DataMall (paging, key handling, atomic files)."""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("lta_fetch", ROOT / "infra" / "navbundle" / "lta_fetch.py")
LF = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LF)

KEY = "k3y-for-tests"
DATA = {"BusServices": [{"ServiceNo": str(i), "AM_Peak_Freq": "08-10"} for i in range(1203)],
        "BusStops": [{"BusStopCode": "59009"}]}


@pytest.fixture()
def server():
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            name = u.path.rsplit("/", 1)[-1]
            seen.append((name, self.headers.get("AccountKey")))
            if self.headers.get("AccountKey") != KEY:
                self.send_response(401)
                self.end_headers()
                return
            if name not in DATA:
                self.send_response(500)
                self.end_headers()
                return
            skip = int(parse_qs(u.query).get("$skip", ["0"])[0])
            body = json.dumps({"value": DATA[name][skip:skip + LF.PAGE]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_port}/ltaodataservice/", seen
    srv.shutdown()


def test_pages_until_a_short_page(server):
    base, seen = server
    rows = LF.fetch_all("BusServices", KEY, base=base)
    assert len(rows) == 1203 and rows[-1]["ServiceNo"] == "1202"
    assert [s[0] for s in seen] == ["BusServices"] * 3 and all(k == KEY for _, k in seen)


def test_bad_key_error_never_contains_the_key(server):
    base, _ = server
    with pytest.raises(LF.FetchError) as e:
        LF.fetch_all("BusServices", "wrong-key", base=base)
    assert "401" in str(e.value) and "wrong-key" not in str(e.value)


def test_key_from_env_or_private_file(tmp_path):
    assert LF.load_key(tmp_path / "none", env={"LTA_ACCOUNT_KEY": " abc "}) == "abc"
    with pytest.raises(LF.FetchError):
        LF.load_key(tmp_path / "none", env={})
    f = tmp_path / "lta_key"
    f.write_text("xyz\n")
    f.chmod(0o644)
    with pytest.raises(LF.FetchError, match="chmod 600"):
        LF.load_key(f, env={})
    f.chmod(0o600)
    assert LF.load_key(f, env={}) == "xyz"


def test_main_writes_files_and_keeps_old_ones_on_failure(server, tmp_path, monkeypatch, capsys):
    base, _ = server
    out = tmp_path / "lta"
    out.mkdir()
    (out / "BusRoutes.json").write_text('{"value": ["old"]}')
    monkeypatch.setenv("LTA_ACCOUNT_KEY", KEY)
    rc = LF.main(["--out", str(out)], base=base)  # BusRoutes fails (500 here)
    assert rc == 1
    assert json.loads((out / "BusRoutes.json").read_text()) == {"value": ["old"]}
    assert len(json.loads((out / "BusServices.json").read_text())["value"]) == 1203
    assert not list(out.glob("*.tmp"))
    assert KEY not in capsys.readouterr().err


def test_builder_reads_what_the_fetch_wrote(server, tmp_path, monkeypatch):
    base, _ = server
    monkeypatch.setenv("LTA_ACCOUNT_KEY", KEY)
    out = tmp_path / "lta"
    LF.main(["--out", str(out), "--datasets", "BusServices"], base=base)
    bspec = importlib.util.spec_from_file_location("nb_build", ROOT / "infra" / "navbundle" / "build.py")
    NB = importlib.util.module_from_spec(bspec)
    bspec.loader.exec_module(NB)
    hw, src = NB.lta_headways(out)
    assert hw["7"] == [9.0, 0.0, 0.0, 0.0] and src == "LTA BusServices (1203 services)"
