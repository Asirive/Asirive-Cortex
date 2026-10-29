"""Manifest and artifact verification. Mirrors infra/gateway/internal/ota Verify (same rules).

The device runs this BEFORE downloading or applying anything. The gateway and the
app are untrusted transport: only the signature, the anti-rollback counter and
the ring cap decide what may be installed.
"""
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from cortex_core.contracts import common_pb2, ota_pb2


class OtaError(Exception):
    outcome = ota_pb2.OTA_OUTCOME_REJECTED


class BadSignature(OtaError): ...
class Rollback(OtaError): ...
class RingNotAllowed(OtaError): ...
class TooEarly(OtaError): ...
class BadArtifact(OtaError): ...


def signing_bytes(m: ota_pb2.Manifest) -> bytes:
    """Deterministic encoding with the signature cleared (identical to Go signingBytes)."""
    c = ota_pb2.Manifest()
    c.CopyFrom(m)
    c.ClearField("manifest_signature")
    return c.SerializeToString(deterministic=True)


def verify_manifest(m: ota_pb2.Manifest, pub: bytes, device_ring: int, device_counter: int, now_ms: int) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(m.manifest_signature, signing_bytes(m))
    except (InvalidSignature, ValueError):
        raise BadSignature("manifest signature invalid") from None
    if m.version_counter < device_counter:
        raise Rollback("version counter below device counter")
    # rings are ordered ALPHA < BETA < STABLE; an unspecified max_ring (0) allows nothing
    if device_ring > m.max_ring or m.max_ring == common_pb2.RING_UNSPECIFIED:
        raise RingNotAllowed("release not allowed for this ring")
    if m.not_before_ms > now_ms:
        raise TooEarly("release not yet valid")


def verify_artifact(a: ota_pb2.Artifact, data: bytes) -> None:
    if len(data) != a.size_bytes or hashlib.sha256(data).digest() != a.sha256:
        raise BadArtifact("artifact hash or size mismatch")
