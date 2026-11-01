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
    env = dict(os.environ, CORTEX_DEV_TOKEN="boot")
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
