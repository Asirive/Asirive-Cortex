"""Provisioning files and certificate renewal.

After the app pairs the glasses (claim), the cloud's reply is stored here, atomically and owner-only.
The link service reads it at boot. USB framing between phone and glasses is not built yet; this is
the part that runs once the claim reply has reached the device.
"""
from __future__ import annotations

import json
import os
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from cortex_core.link import identity


@dataclass
class Provisioning:
    device_id: str
    token: str
    gateway_ws_url: str          # wss://device.example.com:8443/ws/device
    command_public_key_hex: str
    key_path: str
    cert_path: str
    server_ca_path: Optional[str] = None


def _atomic_write(path: str, data: bytes, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".w-")
    try:
        os.fchmod(fd, mode)
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def save(dir_: str, claim_reply: dict, gateway_ws_url: str, server_ca_pem: Optional[bytes] = None) -> Provisioning:
    """Store the cloud's /v1/claim reply. The device key already lives in dir_/device.key."""
    os.makedirs(dir_, mode=0o700, exist_ok=True)
    cert_path, key_path = os.path.join(dir_, "device.crt"), os.path.join(dir_, "device.key")
    _atomic_write(cert_path, claim_reply["device_cert_pem"].encode(), 0o644)
    ca_path = None
    if server_ca_pem:
        ca_path = os.path.join(dir_, "server-ca.pem")
        _atomic_write(ca_path, server_ca_pem, 0o644)
    meta = {"device_id": claim_reply["device_id"], "token": claim_reply["device_token"], "gateway_ws_url": gateway_ws_url,
            "command_public_key": claim_reply.get("command_public_key", ""), "server_ca": ca_path}
    _atomic_write(os.path.join(dir_, "device.json"), json.dumps(meta).encode(), 0o600)  # holds the token
    return load(dir_)  # type: ignore[return-value]


def load(dir_: str) -> Optional[Provisioning]:
    try:
        with open(os.path.join(dir_, "device.json")) as f:
            m = json.load(f)
    except FileNotFoundError:
        return None
    return Provisioning(m["device_id"], m["token"], m["gateway_ws_url"], m.get("command_public_key", ""),
                        os.path.join(dir_, "device.key"), os.path.join(dir_, "device.crt"), m.get("server_ca"))


def renew_certificate(p: Provisioning, timeout: float = 15) -> bool:
    """Ask the cloud for a fresh certificate over mTLS. Returns True if the file was replaced."""
    ctx: ssl.SSLContext = identity.ssl_context(p.key_path, p.cert_path, p.server_ca_path)
    base = p.gateway_ws_url.replace("wss://", "https://", 1).rsplit("/ws/device", 1)[0]
    req = urllib.request.Request(base + "/device/renew", method="POST", data=b"{}")
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
        body = json.loads(r.read())
    pem = body["device_cert_pem"].encode()
    key = identity.load_or_create_key(p.key_path)
    if not identity.cert_matches_key(pem, key):
        return False  # never install a certificate that does not fit our key
    _atomic_write(p.cert_path, pem, 0o644)
    return True


def renew_if_due(p: Provisioning) -> bool:
    with open(p.cert_path, "rb") as f:
        if not identity.needs_renewal(f.read()):
            return False
    return renew_certificate(p)


class ArrivalsError(RuntimeError):
    pass


def arrivals_client(p: Provisioning, timeout: float = 3.0):
    """The nav service's `arrivals(stop_code, service|None)`: live bus arrivals from the gateway over mTLS
    (GET /device/bus-arrivals; the gateway holds the LTA key and caches each stop ~20 s). Returns
    [{"service", "minutes": [..], "live": GPS-tracked?}]; raises ArrivalsError when offline, refused or
    unconfigured, so the caller falls back to headways. The SSL context is built per call, so a renewed
    certificate is used at once."""
    base = p.gateway_ws_url.replace("wss://", "https://", 1).rsplit("/ws/device", 1)[0]

    def arrivals(stop_code: int, service: Optional[str] = None) -> list[dict]:
        q = {"stop": f"{int(stop_code):05d}"}
        if service:
            q["service"] = service
        url = base + "/device/bus-arrivals?" + urllib.parse.urlencode(q)
        try:
            ctx = identity.ssl_context(p.key_path, p.cert_path, p.server_ca_path)
            with urllib.request.urlopen(url, context=ctx, timeout=timeout) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ArrivalsError(f"gateway HTTP {e.code}") from None
        except (OSError, ValueError) as e:  # offline, TLS refused, timeout, bad JSON
            raise ArrivalsError(f"gateway unreachable: {type(e).__name__}") from None
        return [{"service": s["service"], "minutes": [int(m) for m in s.get("minutes", [])],
                 "live": bool((s.get("monitored") or [False])[0])} for s in body.get("services", [])]

    return arrivals



def second_opinion_client(p: Provisioning, connect_s: float = 3.0, answer_s: float = 30.0):
    """The brain's takeover `ask(question, frames, say=None) -> answer` (frames: JPEGs, oldest first, [] with the
    camera off): Gemini Live through the gateway over mTLS (POST /device/second-opinion; the gateway holds the key and
    caps requests per device). The answer streams (NDJSON): say gets each sentence Gemini has finished and moved on
    from, as it arrives; the return value is the whole answer. answer_s caps the wait for each line. Raises
    brain.takeover.OpinionError: online False when the gateway cannot be reached (connect_s caps that, so
    "not sure" comes quickly offline), True when it answered with an error (rate limit, Gemini down, not set up)."""
    import base64
    import http.client

    from cortex_core.brain.takeover import OpinionError

    u = urllib.parse.urlsplit(p.gateway_ws_url.replace("wss://", "https://", 1))
    path = u.path.rsplit("/ws/device", 1)[0] + "/device/second-opinion"

    def ask(question: str, frames: list[bytes], say=None) -> str:
        body = json.dumps({"question": question,
                           "frames_jpeg": [base64.b64encode(f).decode() for f in frames or []]}).encode()
        conn = None
        try:
            ctx = identity.ssl_context(p.key_path, p.cert_path, p.server_ca_path)
            conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=connect_s, context=ctx)
            conn.connect()
        except (OSError, ValueError) as e:  # no internet, DNS, refused, TLS refused, timeout
            if conn is not None:
                conn.close()
            raise OpinionError(f"gateway unreachable: {type(e).__name__}", online=False) from None
        try:
            conn.sock.settimeout(answer_s)
            conn.request("POST", path, body, {"Content-Type": "application/json", "Accept": "application/x-ndjson"})
            r = conn.getresponse()
            if r.status != 200:
                data = json.loads(r.read() or b"{}")
                raise OpinionError(f"gateway HTTP {r.status}: {data.get('error_code', '')}")
            if not r.getheader("Content-Type", "").startswith("application/x-ndjson"):  # an older gateway
                data = json.loads(r.read() or b"{}")
            else:
                data = {}
                while True:
                    raw = r.readline(64 << 10)
                    if not raw:
                        raise OpinionError("gateway failed: stream ended early")
                    if not raw.strip():
                        continue
                    m = json.loads(raw)
                    if "sentence" in m:
                        if say is not None:
                            say(str(m["sentence"]))
                    elif m.get("error"):
                        raise OpinionError(f"gateway failed: {m['error']}")
                    elif m.get("done"):
                        data = m
                        break
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise OpinionError(f"gateway failed: {type(e).__name__}") from None
        finally:
            conn.close()
        ans = str(data.get("answer") or "").strip()
        if not ans:
            raise OpinionError("empty answer")
        return ans

    return ask
