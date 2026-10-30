import shutil
import subprocess
import os
import stat
import ssl
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

from cortex_core.contracts.gen.cortex.v1 import alpha_pb2
from cortex_core.link import identity
from cortex_core.link.cmdverify import CommandRefused, CommandVerifier, signing_bytes

GW = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "gateway")


def test_key_is_created_once_owner_only_and_public_form_is_pkix_p256(tmp_path):
    p = str(tmp_path / "device.key")
    k1 = identity.load_or_create_key(p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    k2 = identity.load_or_create_key(p)
    assert identity.public_key_der(k1) == identity.public_key_der(k2)  # stable across boots
    pub = serialization.load_der_public_key(identity.public_key_der(k1))
    assert isinstance(pub, ec.EllipticCurvePublicKey) and pub.curve.name == "secp256r1"


def _cert(key, days):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "BETA-0001")])
    now = datetime.now(timezone.utc)
    return (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - timedelta(hours=1)).not_valid_after(now + timedelta(days=days))
            .sign(key, __import__("cryptography").hazmat.primitives.hashes.SHA256()).public_bytes(serialization.Encoding.PEM))


def test_renewal_window_and_key_match(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    assert not identity.needs_renewal(_cert(key, 80))
    assert identity.needs_renewal(_cert(key, 10))
    assert identity.cert_matches_key(_cert(key, 80), key)
    assert not identity.cert_matches_key(_cert(key, 80), ec.generate_private_key(ec.SECP256R1()))


def test_ssl_context_is_tls13_and_verifies_server(tmp_path):
    kp = str(tmp_path / "k")
    key = identity.load_or_create_key(kp)
    cp = tmp_path / "c.pem"
    cp.write_bytes(_cert(key, 80))
    ctx = identity.ssl_context(kp, str(cp), str(cp))
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def _signed(priv, device="ALPHA-0001", now=None, ttl=60_000, nonce=b"n" * 16, name="reboot"):
    import time
    now = int(time.time() * 1000) if now is None else now
    c = alpha_pb2.DebugCommand(command_id="c", name=name, device_id=device, issued_ms=now, expires_ms=now + ttl, nonce=nonce, issuer="omar")
    c.args["a"] = "b"
    c.signature = priv.sign(signing_bytes(c))
    return c


def _pub(priv):
    return priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def test_command_rules():
    priv = Ed25519PrivateKey.generate()
    v = CommandVerifier(_pub(priv), "ALPHA-0001")
    c = _signed(priv)
    v.verify(c)
    with pytest.raises(CommandRefused, match="replayed"):
        v.verify(c)
    t = _signed(priv, nonce=b"t" * 16)
    t.name = "restart_service"
    with pytest.raises(CommandRefused, match="signature"):
        v.verify(t)
    with pytest.raises(CommandRefused, match="another device"):
        v.verify(_signed(priv, device="ALPHA-0002", nonce=b"d" * 16))
    with pytest.raises(CommandRefused, match="expired"):
        v.verify(_signed(priv, nonce=b"e" * 16), now_ms=int(__import__("time").time() * 1000) + 120_000)
    with pytest.raises(CommandRefused, match="expired"):
        v.verify(_signed(priv, nonce=b"f" * 16, ttl=10 * 60_000))  # lifetime too long
    with pytest.raises(CommandRefused, match="signature"):
        CommandVerifier(_pub(Ed25519PrivateKey.generate()), "ALPHA-0001").verify(_signed(priv, nonce=b"g" * 16))


def test_nonce_memory_is_bounded():
    priv = Ed25519PrivateKey.generate()
    v = CommandVerifier(_pub(priv), "ALPHA-0001")
    for i in range(300):
        v.verify(_signed(priv, nonce=i.to_bytes(16, "big")))
    assert len(v._seen) == 256


@pytest.mark.skipif(not shutil.which("go"), reason="go toolchain not available")
def test_command_signed_by_the_gateways_go_code_verifies_here():
    """Cross-check: same signing bytes in Go (cmdsign) and Python."""
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    go_priv = (raw + _pub(priv)).hex()  # Go's ed25519.PrivateKey is seed||public
    out = subprocess.run(["go", "run", "./cmd/cortex-sign", "sign-command", "-key", go_priv, "-device", "ALPHA-0001", "-name", "reboot",
                          "-arg", "z=1", "-arg", "a=2"], cwd=GW, capture_output=True, text=True, check=True).stdout.strip()
    cmd = alpha_pb2.DebugCommand()
    cmd.ParseFromString(bytes.fromhex(out))
    CommandVerifier(_pub(priv), "ALPHA-0001").verify(cmd)
