"""End to end: the real Go gateway (mTLS device listener) and the Python device client.

Skipped when the go toolchain is missing. Covers: claim over HTTP with a device-made key,
mTLS connect + token, heartbeat shows online, a signed command from the console is verified and
run, a console command to a build without a verifier is refused, revoke drops the device.
"""
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from cortex_core.contracts.gen.cortex.v1 import session_pb2
from cortex_core.link import identity
from cortex_core.link.cmdverify import CommandVerifier
from cortex_core.link.session import DeviceInfo, GatewayClient, Handlers

GW = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "gateway")
pytestmark = pytest.mark.skipif(not shutil.which("go"), reason="go toolchain not available")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(method, url, token=None, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    d = tmp_path_factory.mktemp("gw")
    binp = str(d / "gw")
    subprocess.run(["go", "build", "-o", binp, "./cmd/gateway"], cwd=GW, check=True)
    # server certificate for 127.0.0.1
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "gw")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key()).serial_number(5)
            .not_valid_before(now - timedelta(hours=1)).not_valid_after(now + timedelta(hours=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]), False)
            .sign(k, hashes.SHA256()))
    (d / "s.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "s.key").write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    api, dev = free_port(), free_port()
    log = open(d / "gw.log", "w")
    dm = _fake_datamall()
    gm = _fake_gemini()
    (d / "lta_key").write_text("dm-key\n")
    (d / "gemini_key").write_text("gm-key\n")
    env = dict(os.environ, CORTEX_DEV_TOKEN="boot", CORTEX_LTA_KEY_FILE=str(d / "lta_key"),
               CORTEX_LTA_BASE=f"http://127.0.0.1:{dm.server_port}/BusArrival",
               CORTEX_GEMINI_KEY_FILE=str(d / "gemini_key"), CORTEX_GEMINI_BASE=f"ws://127.0.0.1:{gm.port}/live",
               CORTEX_GEMINI_MODEL="stand-in")
    p = subprocess.Popen([binp, "-addr", f"127.0.0.1:{api}", "-device-addr", f"127.0.0.1:{dev}", "-device-cert", str(d / "s.crt"),
                          "-device-key", str(d / "s.key"), "-pki-dir", str(d / "pki"), "-state", str(d / "st.json")],
                         env=env, stdout=log, stderr=log)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", api), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield {"api": f"http://127.0.0.1:{api}", "dev": f"wss://127.0.0.1:{dev}/ws/device", "dir": d, "log": d / "gw.log"}
    p.terminate()
    p.wait(5)
    dm.shutdown()
    gm.shutdown()


def _fake_gemini():
    """Gemini Live: setupComplete, then the answer as transcription fragments over two utterances (IN_PROGRESS,
    then IDLE). It says how many frames it was given, so the test sees the clip arrive."""
    import threading
    from websockets.sync.server import serve

    def handler(ws):
        if ws.request.headers.get("x-goog-api-key") != "gm-key" or ws.request.path != "/live":
            ws.close(1008)
            return
        setup = json.loads(ws.recv())["setup"]
        assert setup["model"] == "models/stand-in" and setup["generationConfig"]["responseModalities"] == ["AUDIO"]
        ws.send(json.dumps({"setupComplete": {}}))
        parts = json.loads(ws.recv())["clientContent"]["turns"][0]["parts"]
        n = sum("inlineData" in x for x in parts)
        q = parts[-1]["text"]
        script = ((f"With {n} ", None), (f"frames: {q}.", "IN_PROGRESS"), (None, "IDLE"))
        if q.startswith("two"):  # a two-sentence answer: the first streams to the box before the second is done
            script = (("It is bus 858. ", None), ("It is", None), (" stopping.", None), (None, "IDLE"))
        for frag, status in script:
            if frag:
                ws.send(json.dumps({"serverContent": {"outputTranscription": {"text": frag}}}))
            if status:
                ws.send(json.dumps({"serverContent": {"turnComplete": True, "interactionStatus": status}}))
        try:
            ws.recv(5)
        except Exception:  # noqa: BLE001 - the gateway hangs up
            pass

    srv = serve(handler, "127.0.0.1", 0)
    srv.port = srv.socket.getsockname()[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _fake_datamall():
    """LTA DataMall's BusArrival v3 for stop 59009: 858 in 2 and 11 minutes, 969 in 7."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            if self.headers.get("AccountKey") != "dm-key" or q.get("BusStopCode") != ["59009"]:
                self.send_response(404)
                self.end_headers()
                return
            now = datetime.now(timezone(timedelta(hours=8)))
            at = lambda m: (now + timedelta(minutes=m, seconds=30)).isoformat(timespec="seconds")
            body = {"BusStopCode": "59009", "Services": [
                {"ServiceNo": "858", "NextBus": {"EstimatedArrival": at(2), "Monitored": 1},
                 "NextBus2": {"EstimatedArrival": at(11), "Monitored": 1}, "NextBus3": {"EstimatedArrival": ""}},
                {"ServiceNo": "969", "NextBus": {"EstimatedArrival": at(7), "Monitored": 0}}]}
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def login(gw, email):
    http("POST", gw["api"] + "/v1/auth/register", body={"email": email, "password": "correct horse battery"})
    for _ in range(50):
        found = re.findall(r"to=%s .*?verify\?token=(mt_[0-9a-f]+)" % re.escape(email), gw["log"].read_text(), re.S)
        if found:
            break
        time.sleep(0.1)
    http("POST", gw["api"] + "/v1/auth/verify", body={"token": found[-1]})
    _, r = http("POST", gw["api"] + "/v1/auth/login", body={"email": email, "password": "correct horse battery"})
    return r["token"]


def pair(gw, tier, bench):
    tok = login(gw, f"u{time.time_ns()}@example.com")
    _, reg = http("POST", gw["api"] + "/api/registrations", "boot", {"tier": tier, "label": "e2e", "bench": bench})
    d = gw["dir"]
    keyp = str(d / f"dev-{time.time_ns()}.key")
    key = identity.load_or_create_key(keyp)
    code, c = http("POST", gw["api"] + "/v1/claim", tok, {"claim_code": reg["claim_code"],
                   "device_public_key": __import__("base64").b64encode(identity.public_key_der(key)).decode()})
    assert code == 200, c
    certp = keyp + ".crt"
    open(certp, "w").write(c["device_cert_pem"])
    assert identity.cert_matches_key(c["device_cert_pem"].encode(), key)
    return c, keyp, certp


def telemetry():
    return session_pb2.Heartbeat(battery_pct=77, safety=session_pb2.SafetyState.SAFETY_STATE_OK, uptime_s=5)


def test_device_connects_over_mtls_runs_signed_command_and_is_dropped_on_revoke(gateway):
    c, keyp, certp = pair(gateway, "ALPHA", True)
    ctx = identity.ssl_context(keyp, certp, str(gateway["dir"] / "s.crt"))
    ran = []

    async def on_command(cmd):
        ran.append((cmd.name, cmd.issuer))
        return True, "state dumped"

    client = GatewayClient(gateway["dev"], c["device_id"], c["device_token"], ctx, DeviceInfo(firmware="4.0.0"),
                           Handlers(telemetry=telemetry, on_command=on_command),
                           verifier=CommandVerifier(bytes.fromhex(c["command_public_key"]), c["device_id"]))

    async def scenario():
        task = asyncio.create_task(client.run_forever(backoff_min=0.2, backoff_max=1))
        await asyncio.wait_for(client.connected.wait(), 10)
        for _ in range(50):  # the gateway marks it online once the Hello lands
            _, d = await asyncio.to_thread(http, "GET", gateway["api"] + "/api/devices/" + c["device_id"], "boot")
            if d["device"]["online"] and d["device"]["battery_pct"] == 77:
                break
            await asyncio.sleep(0.2)
        assert d["device"]["online"] and d["device"]["firmware"] == "4.0.0"
        code, _ = await asyncio.to_thread(http, "POST", gateway["api"] + f"/api/devices/{c['device_id']}/command", "boot", {"name": "dump_state"})
        assert code == 200
        for _ in range(50):
            if ran:
                break
            await asyncio.sleep(0.1)
        assert ran == [("dump_state", "bootstrap")]
        # revoke: the live connection drops and the next handshake is refused
        await asyncio.to_thread(http, "POST", gateway["api"] + f"/api/registrations/{c['device_id']}/revoke", "boot")
        for _ in range(50):
            if not client.connected.is_set():
                break
            await asyncio.sleep(0.1)
        assert not client.connected.is_set()
        await asyncio.sleep(1.5)
        assert not client.connected.is_set(), "revoked device reconnected"
        client.stop()
        task.cancel()

    asyncio.run(scenario())


def test_build_without_verifier_refuses_commands(gateway):
    c, keyp, certp = pair(gateway, "ALPHA", True)
    ctx = identity.ssl_context(keyp, certp, str(gateway["dir"] / "s.crt"))
    client = GatewayClient(gateway["dev"], c["device_id"], c["device_token"], ctx, DeviceInfo(), Handlers(telemetry=telemetry), verifier=None)

    async def scenario():
        task = asyncio.create_task(client.run_forever(backoff_min=0.2))
        await asyncio.wait_for(client.connected.wait(), 10)
        await asyncio.sleep(0.3)
        await asyncio.to_thread(http, "POST", gateway["api"] + f"/api/devices/{c['device_id']}/command", "boot", {"name": "reboot"})
        for _ in range(50):
            _, d = await asyncio.to_thread(http, "GET", gateway["api"] + "/api/devices/" + c["device_id"], "boot")
            if "refused" in json.dumps(d):
                break
            await asyncio.sleep(0.2)
        assert "refused" in json.dumps(d)
        client.stop()
        task.cancel()

    asyncio.run(scenario())


def test_wrong_certificate_never_connects(gateway):
    c, keyp, certp = pair(gateway, "BETA", False)
    other_key = os.path.join(gateway["dir"], "other.key")
    identity.load_or_create_key(other_key)
    # a device that presents a certificate for a key it does not hold cannot even build its TLS context
    with pytest.raises(Exception):
        identity.ssl_context(other_key, certp, str(gateway["dir"] / "s.crt"))


def test_provisioning_files_and_certificate_renewal(gateway):
    from cortex_core.link import provision
    c, keyp, certp = pair(gateway, "BETA", False)
    d = str(gateway["dir"] / "prov")
    os.makedirs(d, exist_ok=True)
    os.replace(keyp, os.path.join(d, "device.key"))
    p = provision.save(d, c, gateway["dev"], (gateway["dir"] / "s.crt").read_bytes())
    assert provision.load(d).device_id == c["device_id"] and provision.load("/nonexistent") is None
    import stat
    assert stat.S_IMODE(os.stat(os.path.join(d, "device.json")).st_mode) == 0o600
    before = open(p.cert_path).read()
    assert provision.renew_certificate(p) is True
    after = open(p.cert_path).read()
    assert after != before  # a fresh certificate...
    key = identity.load_or_create_key(p.key_path)
    assert identity.cert_matches_key(after.encode(), key)  # ...for the same key
    assert provision.renew_if_due(p) is False  # 90 days left: nothing to do


def test_live_bus_arrivals_through_the_gateway(gateway):
    """Box -> gateway (mTLS) -> DataMall (server key) -> the nav service's bus_arrivals answer."""
    from cortex_core.link import provision
    c, keyp, certp = pair(gateway, "BETA", False)
    d = str(gateway["dir"] / "prov-arr")
    os.makedirs(d, exist_ok=True)
    os.replace(keyp, os.path.join(d, "device.key"))
    p = provision.save(d, c, gateway["dev"], (gateway["dir"] / "s.crt").read_bytes())
    arrivals = provision.arrivals_client(p)
    got = arrivals(59009, None)
    assert got == [{"service": "858", "minutes": [2, 11], "live": True},
                   {"service": "969", "minutes": [7], "live": False}]
    assert arrivals(59009, "858") == [got[0]]
    with pytest.raises(provision.ArrivalsError, match="502|LTA"):
        arrivals(59010, None)  # DataMall has nothing for it

    import nav_city as C
    from cortex_core.nav import bundle as B
    from cortex_core.nav.service import NavService
    b = B.Bundle(C.make(gateway["dir"] / "city"))
    nav = NavService(b, saved={}, arrivals=lambda code, svc: arrivals(59009, svc))  # the city's stops are not 59009
    nav.on_fix(*C.latlon(0, 0), 5.0)
    r = nav.call("bus_arrivals", {})
    assert r.data.get("live") is True, r
    assert "in 2 minutes" in r.say or "in 7 minutes" in r.say, r.say

    # revoked: the box gets an error and the nav service falls back to headways
    http("POST", gateway["api"] + f"/api/registrations/{c['device_id']}/revoke", "boot")
    with pytest.raises(provision.ArrivalsError):
        arrivals(59009, None)
    r = nav.call("bus_arrivals", {})
    assert r.data.get("live") is not True


def test_gemini_takeover_through_the_gateway(gateway):
    """The LM's second_opinion call -> box -> gateway (mTLS, server key) -> Gemini -> spoken answer."""
    from cortex_core.brain import tools as T
    from cortex_core.brain.brain import Brain
    from cortex_core.brain.takeover import NOT_SURE, NOT_SURE_OFFLINE, Takeover
    from cortex_core.link import provision
    from test_brain import FakeEngine, call
    c, keyp, certp = pair(gateway, "BETA", False)
    d = str(gateway["dir"] / "prov-gem")
    os.makedirs(d, exist_ok=True)
    os.replace(keyp, os.path.join(d, "device.key"))
    p = provision.save(d, c, gateway["dev"], (gateway["dir"] / "s.crt").read_bytes())
    jpeg = b"\xff\xd8\xff\xe0" + b"\0" * 64
    ask = provision.second_opinion_client(p)
    assert ask("which bus is this", [jpeg, jpeg, jpeg]) == "With 3 frames: which bus is this."
    assert ask("what day is it", []) == "With 0 frames: what day is it."
    heard = []
    assert ask("two sentences", [], say=heard.append) == "It is bus 858. It is stopping."
    assert heard == ["It is bus 858."]  # streamed early; the last sentence comes with the whole answer
    data, rest = Takeover(ask).run("two sentences", True, say=heard.append)
    assert rest == "It is stopping." and data["answer"] == "It is bus 858. It is stopping."

    eng = FakeEngine(lambda k, t, s: [{"type": "tool_call", "text": call("second_opinion", question="which bus is this")},
                                      {"type": "done", "tool": True}] if k == "ask" else None)
    Brain(eng, None, T.load(), takeover=Takeover(ask, clip=lambda since: [jpeg, jpeg])).ask("which bus is this")
    assert eng.log[1][2] == "With 2 frames: which bus is this."

    # the gateway refuses (revoked): "not sure", never a crash
    http("POST", gateway["api"] + f"/api/registrations/{c['device_id']}/revoke", "boot")
    data, say = Takeover(ask).run("which bus is this", True)
    assert say == NOT_SURE and data["error"]  # refused at TLS or 401, never an answer
    # no route to the gateway: the offline sentence, quickly
    import dataclasses
    import time as _t
    off = provision.second_opinion_client(dataclasses.replace(p, gateway_ws_url="wss://127.0.0.1:1/ws/device"))
    t0 = _t.monotonic()
    assert Takeover(off).run("q", True)[1] == NOT_SURE_OFFLINE and _t.monotonic() - t0 < 4
