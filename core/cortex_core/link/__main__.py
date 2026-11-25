"""link service: the glasses' connection to the cloud (plus, later, the phone link).

Unprovisioned devices (never paired) just heartbeat to the supervisor and wait. Once the paired
reply is on disk, this dials the gateway over mTLS and stays connected.
"""
import asyncio
import logging
import os
import signal
from pathlib import Path

from cortex_core.contracts.gen.cortex.v1 import session_pb2
from cortex_core.link import gps, identity, provision
from cortex_core.link.cmdverify import CommandVerifier
from cortex_core.link.owner_control import OwnerControl
from cortex_core.link.phone_link import FileControls, PhoneLink, RuntimeHooks
from cortex_core.link.session import DeviceInfo, GatewayClient, Handlers

log = logging.getLogger("cortex.link")
STATE_DIR = os.environ.get("CORTEX_STATE_DIR", "/var/lib/cortex/identity")
NAV_STATE = os.environ.get("CORTEX_NAV_STATE", "/var/lib/cortex/nav")  # dev GPS recordings (never leave the box)


def telemetry() -> session_pb2.Heartbeat:
    # TODO(core): fill from the safety/supervisor status files once those publish them.
    return session_pb2.Heartbeat(safety=session_pb2.SafetyState.SAFETY_STATE_DEGRADED)


def location_sink(fwd: "gps.GpsForwarder", rec: "gps.GpsRecorder"):
    """The phone's fixes: on to the brain (dropped if it isn't listening), and to disk on dev builds only."""
    def on_location(fix: dict) -> None:
        fwd.send(fix)
        try:
            rec.write(fix)
        except OSError as e:
            log.warning("gps recording failed: %s", e)
    return on_location


async def serve(hb: Path, stop: asyncio.Event) -> None:
    async def beat():
        while not stop.is_set():
            hb.touch()
            await asyncio.sleep(1)

    beater = asyncio.create_task(beat())
    phone = PhoneLink(STATE_DIR, None, RuntimeHooks(STATE_DIR), os.environ.get("CORTEX_GATEWAY_WS", ""))  # type: ignore[arg-type]
    phone.control = OwnerControl(FileControls(), phone.paired)
    phone.on_location = location_sink(gps.GpsForwarder(os.environ.get("CORTEX_GPS_SOCK", gps.SOCK)),
                                      gps.GpsRecorder(NAV_STATE))
    phone_task = asyncio.create_task(phone.serve(stop=stop))  # answers the app even while unpaired
    phone_task.add_done_callback(lambda t: t.cancelled() or t.exception() is None or log.error("phone link stopped: %r", t.exception()))
    client = None
    task = None
    while not stop.is_set():
        p = provision.load(STATE_DIR)
        if p is None:
            await asyncio.sleep(2)  # not paired yet
            continue
        try:
            provision.renew_if_due(p)
        except Exception as e:
            log.warning("certificate renewal failed: %s", e)
        verifier = None
        if p.command_public_key_hex and os.environ.get("CORTEX_ALPHA_BUILD") == "1":  # production builds never accept commands
            verifier = CommandVerifier(bytes.fromhex(p.command_public_key_hex), p.device_id)
        client = GatewayClient(p.gateway_ws_url, p.device_id, p.token, identity.ssl_context(p.key_path, p.cert_path, p.server_ca_path),
                               DeviceInfo(), Handlers(telemetry=telemetry), verifier=verifier)
        task = asyncio.create_task(client.run_forever())
        await stop.wait()
        client.stop()
        task.cancel()
    beater.cancel()
    try:
        await phone_task
    except Exception:
        pass  # already logged when it failed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    hb = Path(os.environ.get("CORTEX_HB_DIR", "/run/cortex/hb")) / "link"
    hb.parent.mkdir(parents=True, exist_ok=True)
    stop = asyncio.Event()
    loop = asyncio.new_event_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.run_until_complete(serve(hb, stop))


if __name__ == "__main__":
    main()
