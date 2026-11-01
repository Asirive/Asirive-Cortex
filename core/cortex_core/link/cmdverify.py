"""Verify a signed alpha debug command before acting on it (see contracts alpha.proto, DebugCommand).

A command is refused unless: the ed25519 signature is valid, it names THIS device, it has not
expired (and its lifetime is at most 60 s), and its nonce has not been seen in the last 256.
"""
from __future__ import annotations

import time
from collections import OrderedDict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from cortex_core.contracts.gen.cortex.v1 import alpha_pb2

MAX_TTL_MS = 60_000
SKEW_MS = 5_000
NONCE_MEMORY = 256


class CommandRefused(Exception):
    pass


def signing_bytes(cmd: alpha_pb2.DebugCommand) -> bytes:
    c = alpha_pb2.DebugCommand()
    c.CopyFrom(cmd)
    c.ClearField("signature")
    return c.SerializeToString(deterministic=True)


class CommandVerifier:
    def __init__(self, command_public_key: bytes, device_id: str):
        self._pub = Ed25519PublicKey.from_public_bytes(command_public_key)
        self._device_id = device_id
        self._seen: OrderedDict[bytes, None] = OrderedDict()

    def verify(self, cmd: alpha_pb2.DebugCommand, now_ms: int | None = None) -> None:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        try:
            self._pub.verify(bytes(cmd.signature), signing_bytes(cmd))
        except InvalidSignature:
            raise CommandRefused("bad signature") from None
        if cmd.device_id != self._device_id:
            raise CommandRefused("for another device")
        if now_ms >= cmd.expires_ms or now_ms < cmd.issued_ms - SKEW_MS or cmd.expires_ms - cmd.issued_ms > MAX_TTL_MS:
            raise CommandRefused("expired or not yet valid")
        nonce = bytes(cmd.nonce)
        if len(nonce) < 8 or nonce in self._seen:
            raise CommandRefused("nonce missing or replayed")
        self._seen[nonce] = None
        while len(self._seen) > NONCE_MEMORY:
            self._seen.popitem(last=False)
