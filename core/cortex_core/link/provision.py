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
