"""Phone <-> box link service (LOCAL only, never cloud).

The USB-C cable between phone and box carries the phone's tethered network, so the app reaches
this service over plain TCP/WebSocket on the tether subnet. Spec: docs/architecture/PHONE-BOX-LINK.md.

Trust model:
  * Unpaired box: answers `hello` and accepts ONE `provision` (the cable is the proof of presence).
  * Paired box: every request carries an HMAC with the link secret handed over at provision time,
    bound to a per-connection nonce and a rising request id (no replay, no forging from the hotspot).
  * Stop/pause goes through OwnerControl, which refuses unconfirmed requests and has no safety handle.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import subprocess
import urllib.parse
from typing import Any, Callable, Optional, Protocol

import websockets

from cortex_core.contracts import local_pb2 as lp
from cortex_core.link import identity, provision
from cortex_core.link.owner_control import OwnerControl

log = logging.getLogger("cortex.phonelink")
PORT = 8765
VERSION = 1
BEACON_PORT = 8766  # UDP broadcast so the phone can find the box on the tether subnet


class BoxHooks(Protocol):
    """Hardware and services the link needs; faked in tests."""
    def internet_ok(self) -> bool: ...
    def play_test(self, kind: str) -> bool: ...          # 'sound' | 'vibrate' | 'voice'
    def install_update(self, manifest: dict) -> bool: ...  # start the OTA agent; False if it cannot
    def code_tail(self) -> Optional[str]: ...             # last 4 characters of the printed box code


def canonical(args: dict) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(secret: bytes, nonce: str, rid: int, op: str, args: dict) -> str:
    msg = f"{nonce}|{rid}|{op}|{canonical(args)}".encode()
    return base64.b64encode(hmac.new(secret, msg, hashlib.sha256).digest()).decode()


class PhoneLink:
    def __init__(self, state_dir: str, control: OwnerControl, hooks: BoxHooks, default_ws_url: str = ""):
        self.dir, self.control, self.hooks, self.default_ws_url = state_dir, control, hooks, default_ws_url
        self._secret_path = os.path.join(state_dir, "link.secret")

    # ---- state ----
    def _secret(self) -> Optional[bytes]:
        try:
            with open(self._secret_path, "rb") as f:
                return f.read() or None
        except FileNotFoundError:
            return None

    def paired(self) -> bool:
        return provision.load(self.dir) is not None and self._secret() is not None

    def _public_key(self) -> str:
        key = identity.load_or_create_key(os.path.join(self.dir, "device.key"))
        return base64.b64encode(identity.public_key_der(key)).decode()

    # ---- one connection ----
    def hello(self, nonce: str) -> dict:
        return {"hello": {"v": VERSION, "nonce": nonce, "paired": self.paired(), "public_key": self._public_key(),
                          "box_tail": self.hooks.code_tail()}}

    def handle(self, raw: str, nonce: str, state: dict) -> dict:
        """One request in, one reply out. Never raises."""
        try:
            req = json.loads(raw)
            rid, op, args = req["id"], str(req["op"]), req.get("args") or {}
            if not isinstance(rid, int) or not isinstance(args, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return {"id": -1, "ok": False, "error": "malformed"}
        if op == "provision":
            return self._provision(rid, args)
        secret = self._secret()
        if secret is None or provision.load(self.dir) is None:
            return {"id": rid, "ok": False, "error": "not paired"}
        mac = req.get("mac", "")
        if not isinstance(mac, str) or not hmac.compare_digest(mac, sign(secret, nonce, rid, op, args)):
            return {"id": rid, "ok": False, "error": "bad signature"}
        if rid <= state.get("last", 0):
            return {"id": rid, "ok": False, "error": "replayed request"}
        state["last"] = rid
        try:
            return {"id": rid, **self._op(op, args, rid)}
        except Exception as e:  # a hardware fault must not kill the link
            log.exception("op %s failed", op)
            return {"id": rid, "ok": False, "error": f"box error: {type(e).__name__}"}

    def _provision(self, rid: int, a: dict) -> dict:
        if self.paired():
            return {"id": rid, "ok": False, "error": "already paired"}
        try:
            reply = a["reply"]
            secret = base64.b64decode(a["link_secret"], validate=True)
            if len(secret) < 32 or not isinstance(reply, dict):
                raise ValueError
            ws = a.get("gateway_ws_url") or self.default_ws_url
            if not ws.startswith("wss://"):
                return {"id": rid, "ok": False, "error": "gateway address missing"}
            ca = reply.get("ca_cert_pem")
            provision.save(self.dir, reply, ws, ca.encode() if ca else None)
        except (KeyError, ValueError, TypeError):
            return {"id": rid, "ok": False, "error": "bad provision"}
        fd = os.open(self._secret_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secret)
        return {"id": rid, "ok": True}

    def _control(self, msg: lp.AppToDevice) -> dict:
        ack = self.control.handle(msg).ack
        return {"ok": ack.ok, "error": ack.error, "paused": ack.state == lp.STOP_MODE_PAUSE}

    def _op(self, op: str, a: dict, rid: int) -> dict:
        req_id = f"link-{rid}-{secrets.token_hex(4)}"
        if op == "status":
            return {"ok": True, "paused": self.control.mode == lp.STOP_MODE_PAUSE, "internet": self.hooks.internet_ok()}
        if op == "pause":
            return self._control(lp.AppToDevice(stop=lp.StopRequest(mode=lp.STOP_MODE_PAUSE, request_id=req_id, user_confirmed=a.get("confirmed") is True)))
        if op == "resume":
            return self._control(lp.AppToDevice(resume=lp.ResumeRequest(request_id=req_id)))
        if op == "internet":
            return {"ok": True, "internet": self.hooks.internet_ok()}
        if op == "test":
            kind = a.get("kind")
            if kind not in ("sound", "vibrate", "voice"):
                return {"ok": False, "error": "unknown test"}
            return {"ok": self.hooks.play_test(kind)}
        if op == "install":
            m = a.get("manifest")
            return {"ok": isinstance(m, dict) and self.hooks.install_update(m)}
        return {"ok": False, "error": "unknown op"}

    async def _conn(self, ws) -> None:
        nonce = base64.b64encode(secrets.token_bytes(16)).decode()
        state: dict = {}
        await ws.send(json.dumps(self.hello(nonce)))
        async for raw in ws:
            if isinstance(raw, bytes) or len(raw) > 1 << 20:
                continue
            await ws.send(json.dumps(await asyncio.to_thread(self.handle, raw, nonce, state)))

    async def _beacon(self, stop: asyncio.Event, port: int, beacon_port: int, dest: str) -> None:
        # No secrets in the beacon: only "a Cortex box is here, on this port".
        payload = json.dumps({"cortex": VERSION, "port": port}).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        try:
            while not stop.is_set():
                try:
                    await loop.sock_sendto(sock, payload, (dest, beacon_port))
                except OSError:
                    pass  # no network yet (cable out); try again
                try:
                    await asyncio.wait_for(stop.wait(), 2)
                except asyncio.TimeoutError:
                    pass
        finally:
            sock.close()

    async def serve(self, host: str = "0.0.0.0", port: int = PORT, stop: Optional[asyncio.Event] = None,
                    beacon_port: int = BEACON_PORT, beacon_dest: str = "255.255.255.255") -> None:
        stop = stop or asyncio.Event()
        beacon = asyncio.create_task(self._beacon(stop, port, beacon_port, beacon_dest))
        try:
            async with websockets.serve(self._conn, host, port, max_size=1 << 20):
                await stop.wait()
        finally:
            beacon.cancel()


class FileControls:
    """Owner controls as flag files the other services watch. Has no safety method on purpose."""
    def __init__(self, run_dir: str = "/run/cortex"):
        self.run_dir = run_dir

    def _flag(self, name: str, on: bool) -> None:
        os.makedirs(self.run_dir, exist_ok=True)
        path = os.path.join(self.run_dir, name)
        if on:
            open(path, "w").close()
        elif os.path.exists(path):
            os.remove(path)

    def pause_assistant(self) -> None: self._flag("assistant.paused", True)
    def resume_assistant(self) -> None: self._flag("assistant.paused", False)
    def set_mic_muted(self, muted: bool) -> None: self._flag("mic.muted", muted)
    def announce_shutdown(self) -> None: self._flag("shutdown.announce", True)
    def power_off(self) -> None: subprocess.run(["systemctl", "poweroff"], check=False)


class RuntimeHooks:
    """Real hooks where the box can do it today. Sound/touch tests and update install need the
    audio/haptic service and the OTA agent wiring, which are not connected yet: they report False
    so the app says so instead of pretending."""
    def __init__(self, state_dir: str):
        self.dir = state_dir

    def internet_ok(self) -> bool:
        p = provision.load(self.dir)
        u = urllib.parse.urlparse(p.gateway_ws_url) if p else None
        host, port = (u.hostname, u.port or 443) if u and u.hostname else ("1.1.1.1", 443)
        try:
            with socket.create_connection((host, port), timeout=4):
                return True
        except OSError:
            return False

    def play_test(self, kind: str) -> bool:
        log.warning("test %s requested but the audio/haptic service is not connected", kind)
        return False

    def install_update(self, manifest: dict) -> bool:
        log.warning("update requested but the OTA agent is not wired to the phone link yet")
        return False

    def code_tail(self) -> Optional[str]:
        try:
            with open(os.path.join(self.dir, "claim_code")) as f:
                return f.read().strip().replace("-", "")[-4:].upper() or None
        except FileNotFoundError:
            return None
