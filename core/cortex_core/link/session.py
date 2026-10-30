"""Gateway session: the glasses' outbound connection to the cloud.

Dials wss with a client certificate (mTLS) plus the device token, says Hello, sends a heartbeat
every few seconds, accepts signed debug commands (alpha builds) and OTA offers, and reconnects
with backoff. It never blocks safety: this runs in the link service, a different process.
"""
from __future__ import annotations

import asyncio
import logging
import random
import ssl
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import websockets

from cortex_core.contracts.gen.cortex.v1 import alpha_pb2, common_pb2, ota_pb2, session_pb2
from cortex_core.link.cmdverify import CommandRefused, CommandVerifier

log = logging.getLogger("cortex.link.session")
SCHEMA_VERSION = 1
PT = common_pb2.PayloadType


@dataclass
class DeviceInfo:
    firmware: str = "0.0.0"
    mcu: str = ""
    model: str = ""
    hardware: str = "dragon-q8b"
    version_counter: int = 0


@dataclass
class Handlers:
    telemetry: Callable[[], session_pb2.Heartbeat]
    on_offer: Optional[Callable[[ota_pb2.Manifest], Awaitable[ota_pb2.OtaResult]]] = None
    # alpha builds only: run an already-verified command, return (ok, output)
    on_command: Optional[Callable[[alpha_pb2.DebugCommand], Awaitable[tuple[bool, str]]]] = None


@dataclass
class GatewayClient:
    url: str                       # wss://device.example.com:8443/ws/device
    device_id: str
    token: str
    ssl_context: ssl.SSLContext
    info: DeviceInfo
    handlers: Handlers
    verifier: Optional[CommandVerifier] = None   # None on production builds: commands are refused outright
    clock: Callable[[], float] = time.time
    _seq: int = field(default=0, init=False)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    connected: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    # -- framing --
    def _env(self, ptype: int, msg) -> bytes:
        self._seq += 1
        h = common_pb2.Header(schema_version=SCHEMA_VERSION, device_id=self.device_id, seq=self._seq, ts_ms=int(self.clock() * 1000))
        return common_pb2.Envelope(header=h, type=ptype, payload=msg.SerializeToString()).SerializeToString()

    async def _send(self, ws, ptype: int, msg) -> None:
        await ws.send(self._env(ptype, msg))

    async def send_ota_result(self, ws, result: ota_pb2.OtaResult) -> None:
        await self._send(ws, PT.PAYLOAD_TYPE_OTA_RESULT, result)

    # -- one connection --
    async def _session(self) -> None:
        headers = {"Authorization": f"Bearer {self.token}", "X-Device-Id": self.device_id}
        async with websockets.connect(self.url, ssl=self.ssl_context, additional_headers=headers,
                                      open_timeout=10, max_size=1 << 20) as ws:
            self._seq = 0
            hello = session_pb2.Hello(firmware_version=self.info.firmware, mcu_version=self.info.mcu, model_version=self.info.model,
                                      hardware=self.info.hardware, heartbeat_interval_s=5, version_counter=self.info.version_counter)
            await self._send(ws, PT.PAYLOAD_TYPE_HELLO, hello)
            ack = await self._read(ws, timeout=10)
            if ack is None or ack.type != PT.PAYLOAD_TYPE_HELLO_ACK:
                raise ConnectionError("no HelloAck")
            a = session_pb2.HelloAck()
            a.ParseFromString(ack.payload)
            if not a.accepted:
                raise ConnectionError(f"gateway refused: {a.reason}")
            interval = max(2, min(60, a.heartbeat_interval_s or 5))
            self.connected.set()
            hb = asyncio.create_task(self._heartbeats(ws, interval))
            try:
                async for raw in ws:
                    await self._handle(ws, raw)
            finally:
                hb.cancel()
                self.connected.clear()

    async def _read(self, ws, timeout: float):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout)
        except Exception:
            return None
        env = common_pb2.Envelope()
        env.ParseFromString(raw)
        return env

    async def _heartbeats(self, ws, interval: float) -> None:
        while True:
            try:
                await self._send(ws, PT.PAYLOAD_TYPE_HEARTBEAT, self.handlers.telemetry())
            except Exception:
                log.exception("telemetry failed; sending a minimal heartbeat")
                await self._send(ws, PT.PAYLOAD_TYPE_HEARTBEAT, session_pb2.Heartbeat(safety=session_pb2.SafetyState.SAFETY_STATE_DEGRADED))
            await asyncio.sleep(interval)

    async def _handle(self, ws, raw: bytes) -> None:
        env = common_pb2.Envelope()
        try:
            env.ParseFromString(raw)
        except Exception:
            return  # garbage from the network is ignored, never fatal
        if env.type == PT.PAYLOAD_TYPE_OTA_OFFER and self.handlers.on_offer:
            offer = ota_pb2.OtaOffer()
            offer.ParseFromString(env.payload)
            res = await self.handlers.on_offer(offer.manifest)
            await self.send_ota_result(ws, res)
        elif env.type == PT.PAYLOAD_TYPE_DEBUG_COMMAND:
            await self._command(ws, env)

    async def _command(self, ws, env) -> None:
        cmd = alpha_pb2.DebugCommand()
        cmd.ParseFromString(env.payload)
        res = alpha_pb2.DebugResult(command_id=cmd.command_id)
        if self.verifier is None or self.handlers.on_command is None:
            res.ok, res.output = False, "refused: this build does not accept debug commands"
        else:
            try:
                self.verifier.verify(cmd, int(self.clock() * 1000))
                res.ok, res.output = await self.handlers.on_command(cmd)
            except CommandRefused as e:
                res.ok, res.output = False, f"refused: {e}"
        await self._send(ws, PT.PAYLOAD_TYPE_DEBUG_RESULT, res)

    # -- lifecycle --
    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self, backoff_min: float = 1.0, backoff_max: float = 60.0) -> None:
        delay = backoff_min
        while not self._stop.is_set():
            started = self.clock()
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # network down, gateway restarting, cert expired...
                log.warning("gateway session ended: %s", e)
            if self.clock() - started > 30:
                delay = backoff_min   # it was healthy for a while, so retry quickly
            try:
                await asyncio.wait_for(self._stop.wait(), delay * (0.5 + random.random()))
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, backoff_max)
