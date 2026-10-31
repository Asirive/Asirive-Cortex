import asyncio
import base64
import json
import os

import websockets

from cortex_core.contracts import local_pb2 as lp
from cortex_core.link import phone_link as pl
from cortex_core.link.owner_control import OwnerControl


class Rec:
    def __init__(self): self.calls = []
    def __getattr__(self, n): return lambda *a: self.calls.append((n, *a))


class Hooks:
    def __init__(self): self.tests, self.net, self.installed = [], True, []
    def internet_ok(self): return self.net
    def play_test(self, k): self.tests.append(k); return True
    def install_update(self, m): self.installed.append(m); return True
    def code_tail(self): return "4TXD"
    def claim_code(self): return "K7Q2-4TXD"


def cert_for(key) -> str:
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID
    n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "d1")])
    now = datetime.now(timezone.utc)
    c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(key.public_key())
         .serial_number(1).not_valid_before(now).not_valid_after(now + timedelta(days=30)).sign(key, hashes.SHA256()))
    return c.public_bytes(serialization.Encoding.PEM).decode()


def reply_for(link):
    from cortex_core.link import identity
    key = identity.load_or_create_key(os.path.join(link.dir, "device.key"))
    return {"device_id": "d1", "device_token": "tok", "device_cert_pem": cert_for(key), "command_public_key": "ab"}


REPLY = {"device_id": "d1", "device_token": "tok", "device_cert_pem": "CERT", "command_public_key": "ab"}
SECRET = b"s" * 32


def mk(tmp_path):
    rec = Rec()
    link = pl.PhoneLink(str(tmp_path), None, Hooks(), "wss://gw.example:8443/ws/device")
    link.control = OwnerControl(rec, link.paired)
    return link, rec


def req(rid, op, args=None, secret=None, nonce="n"):
    r = {"id": rid, "op": op, "args": args or {}}
    if secret:
        r["mac"] = pl.sign(secret, nonce, rid, op, r["args"])
    return json.dumps(r)


def provision(link, rid=1):
    return link.handle(req(rid, "provision", {"reply": reply_for(link), "link_secret": base64.b64encode(SECRET).decode(), "claim_code": "k7q2-4txd"}), "n", {})


def test_hello_gives_key_and_tail_and_is_unpaired(tmp_path):
    link, _ = mk(tmp_path)
    h = link.hello("n")["hello"]
    assert h["paired"] is False and h["box_tail"] == "4TXD" and base64.b64decode(h["public_key"])


def test_unpaired_refuses_commands(tmp_path):
    link, rec = mk(tmp_path)
    assert link.handle(req(1, "pause", {"confirmed": True}), "n", {})["error"] == "not paired" and rec.calls == []


def test_provision_once_then_locked(tmp_path):
    link, _ = mk(tmp_path)
    assert provision(link)["ok"] and link.paired()
    assert os.stat(tmp_path / "link.secret").st_mode & 0o777 == 0o600
    other = {"reply": reply_for(link), "link_secret": base64.b64encode(b"x" * 32).decode(), "claim_code": "K7Q2-4TXD"}
    assert link.handle(req(2, "provision", other), "n", {})["error"] == "already paired"


def test_bad_provision_is_rejected_and_stores_nothing(tmp_path):
    link, _ = mk(tmp_path)
    assert not link.handle(req(1, "provision", {"reply": REPLY, "link_secret": base64.b64encode(b"short").decode(), "claim_code": "K7Q24TXD"}), "n", {})["ok"]
    assert not link.paired()


def test_a_certificate_for_another_key_is_refused(tmp_path):
    link, _ = mk(tmp_path)
    from cryptography.hazmat.primitives.asymmetric import ec
    other = dict(reply_for(link), device_cert_pem=cert_for(ec.generate_private_key(ec.SECP256R1())))
    r = link.handle(req(1, "provision", {"reply": other, "link_secret": base64.b64encode(SECRET).decode(), "claim_code": "k7q2-4txd"}), "n", {})
    assert r["error"] == "certificate is not for this box" and not link.paired()


def test_wrong_or_missing_claim_code_is_refused(tmp_path):
    link, _ = mk(tmp_path)
    for code in ("ZZZZ-ZZZZ", None):
        a = {"reply": reply_for(link), "link_secret": base64.b64encode(SECRET).decode()}
        if code: a["claim_code"] = code
        assert link.handle(req(1, "provision", a), "n", {})["error"] == "wrong claim code"
    assert not link.paired()


def test_repeating_the_same_provision_is_fine_a_different_one_is_not(tmp_path):
    link, _ = mk(tmp_path)
    r = reply_for(link)
    a = {"reply": r, "link_secret": base64.b64encode(SECRET).decode(), "claim_code": "K7Q2-4TXD"}
    assert link.handle(req(1, "provision", a), "n", {})["ok"]
    assert link.handle(req(2, "provision", a), "n", {})["ok"]
    b = dict(a, link_secret=base64.b64encode(b"t" * 32).decode())
    assert link.handle(req(3, "provision", b), "n", {})["error"] == "already paired"


def test_a_failed_save_leaves_nothing_half_done(tmp_path, monkeypatch):
    link, _ = mk(tmp_path)
    monkeypatch.setattr(pl.provision, "save", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    a = {"reply": reply_for(link), "link_secret": base64.b64encode(SECRET).decode(), "claim_code": "K7Q2-4TXD"}
    assert link.handle(req(1, "provision", a), "n", {})["error"] == "box could not save"
    assert not os.path.exists(tmp_path / "link.secret")


def test_unsigned_or_wrongly_signed_commands_do_nothing(tmp_path):
    link, rec = mk(tmp_path)
    provision(link)
    st = {}
    assert link.handle(req(2, "pause", {"confirmed": True}), "n", st)["error"] == "bad signature"
    assert link.handle(req(2, "pause", {"confirmed": True}, secret=b"x" * 32), "n", st)["error"] == "bad signature"
    assert link.handle(req(2, "pause", {"confirmed": True}, secret=SECRET, nonce="other"), "n", st)["error"] == "bad signature"
    assert rec.calls == []


def test_pause_needs_confirmation_and_replay_is_refused(tmp_path):
    link, rec = mk(tmp_path)
    provision(link)
    st = {}
    assert link.handle(req(2, "pause", {}, SECRET), "n", st)["error"] == "user confirmation required"
    ok = link.handle(req(3, "pause", {"confirmed": True}, SECRET), "n", st)
    assert ok["ok"] and ok["paused"] and rec.calls == [("pause_assistant",)]
    assert link.handle(req(3, "pause", {"confirmed": True}, SECRET), "n", st)["error"] == "replayed request"
    assert link.handle(req(4, "status", {}, SECRET), "n", st)["paused"] is True
    assert link.handle(req(5, "resume", {}, SECRET), "n", st)["ok"]


def test_test_internet_install_ops(tmp_path):
    link, _ = mk(tmp_path)
    provision(link)
    st = {}
    assert link.handle(req(2, "test", {"kind": "sound"}, SECRET), "n", st)["ok"]
    assert not link.handle(req(3, "test", {"kind": "boom"}, SECRET), "n", st)["ok"]
    link.hooks.net = False
    assert link.handle(req(4, "internet", {}, SECRET), "n", st)["internet"] is False
    assert link.handle(req(5, "install", {"manifest": {"release_id": "r1"}}, SECRET), "n", st)["ok"]
    assert link.hooks.installed == [{"release_id": "r1"}]


def test_garbage_never_raises(tmp_path):
    link, _ = mk(tmp_path)
    for raw in ["", "{", "[]", '{"id":"x","op":1}', '{"id":1}']:
        assert link.handle(raw, "n", {})["ok"] is False


def test_over_a_real_socket(tmp_path):
    async def go():
        link, _ = mk(tmp_path)
        stop = asyncio.Event()
        srv = asyncio.create_task(link.serve("127.0.0.1", 18765, stop))
        await asyncio.sleep(0.2)
        async with websockets.connect("ws://127.0.0.1:18765") as ws:
            hello = json.loads(await ws.recv())["hello"]
            await ws.send(req(1, "provision", {"reply": reply_for(link), "link_secret": base64.b64encode(SECRET).decode(), "claim_code": "k7q2-4txd"}))
            assert json.loads(await ws.recv())["ok"]
            await ws.send(req(2, "status", {}, SECRET, hello["nonce"]))
            assert json.loads(await ws.recv())["internet"] is True
        stop.set()
        await srv
    asyncio.run(go())


def test_beacon_announces_the_port_without_secrets(tmp_path):
    import socket
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 18766))
    rx.settimeout(3)

    async def go():
        link, _ = mk(tmp_path)
        stop = asyncio.Event()
        srv = asyncio.create_task(link.serve("127.0.0.1", 18767, stop, 18766, "127.0.0.1"))
        data = await asyncio.to_thread(lambda: rx.recvfrom(512)[0])
        stop.set()
        await srv
        return json.loads(data)
    assert asyncio.run(go()) == {"cortex": 1, "port": 18767}


def test_file_controls_set_and_clear_flags(tmp_path):
    from cortex_core.link.phone_link import FileControls
    c = FileControls(str(tmp_path))
    c.pause_assistant()
    assert (tmp_path / "assistant.paused").exists()
    c.resume_assistant()
    assert not (tmp_path / "assistant.paused").exists()


def test_signature_vectors_shared_with_the_app():
    # apps/mobile/test/box_link_test.dart asserts the same strings; change both together.
    s = b"s" * 32
    assert pl.sign(s, "n", 2, "pause", {"confirmed": True}) == "C0GUpVRfHtxaaR7wwcwbuAkTC2kYH4SEvCkmahdjKH8="
    m = {"manifest": {"b": [1, {"z": 'é"', "a": None}], "a": 1.5}}
    assert pl.sign(s, "n", 3, "install", m) == "y3iE7zQCJ7qkRBNjs+XilTXBAe89c26sTR9P1dhSP6s="
