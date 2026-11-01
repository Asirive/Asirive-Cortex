"""Device identity: an ECDSA P-256 key made on the device, the certificate the cloud issued for it,
and the TLS context used for the mutual-TLS connection.

The private key is generated here and never sent anywhere; only the public half goes to the
cloud at claim time. On production hardware the key should live in a secure element or TPM;
this file-backed version (mode 0600) is the fallback and the one tests use.
"""
from __future__ import annotations

import os
import ssl
import tempfile
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

RENEW_BEFORE = timedelta(days=30)


def load_or_create_key(path: str) -> ec.EllipticCurvePrivateKey:
    """Return the device key, creating it (atomically, owner-only) on first boot."""
    try:
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)  # type: ignore[return-value]
    except FileNotFoundError:
        pass
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".key-")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, pem)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return key


def public_key_der(key: ec.EllipticCurvePrivateKey) -> bytes:
    """PKIX (SubjectPublicKeyInfo) DER: what the cloud's /v1/claim expects as device_public_key."""
    return key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def cert_expires(cert_pem: bytes) -> datetime:
    return x509.load_pem_x509_certificate(cert_pem).not_valid_after_utc


def needs_renewal(cert_pem: bytes, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return cert_expires(cert_pem) - now < RENEW_BEFORE


def cert_matches_key(cert_pem: bytes, key: ec.EllipticCurvePrivateKey) -> bool:
    c = x509.load_pem_x509_certificate(cert_pem)
    fmt = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return c.public_key().public_bytes(*fmt) == key.public_key().public_bytes(*fmt)


def ssl_context(key_path: str, cert_path: str, server_ca_path: str | None = None) -> ssl.SSLContext:
    """TLS 1.3 client context presenting our certificate. server_ca_path pins the gateway's
    server certificate/CA; None uses the system trust store."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    if server_ca_path:
        ctx.load_verify_locations(server_ca_path)
    ctx.load_cert_chain(cert_path, key_path)
    return ctx
