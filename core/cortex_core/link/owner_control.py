"""Owner stop / resume / mic-mute over the LOCAL phone link.

Never reachable from the cloud (the gateway has no handler for these messages). The
device refuses anything the user did not confirm in the app, and PAUSE turns off the
assistant only: this module has no handle on the safety service at all.
"""
from typing import Callable, Dict, Protocol

from google.protobuf.message import DecodeError

from cortex_core.contracts import local_pb2 as lp


class Controls(Protocol):
    """What the owner may switch. Deliberately has no safety method."""
    def pause_assistant(self) -> None: ...
    def resume_assistant(self) -> None: ...
    def announce_shutdown(self) -> None: ...   # voice + haptic, blocks until done
    def power_off(self) -> None: ...
    def set_mic_muted(self, muted: bool) -> None: ...


class OwnerControl:
    def __init__(self, controls: Controls, is_paired: Callable[[], bool], busy: Callable[[], bool] = lambda: False):
        self.c, self.is_paired, self.busy = controls, is_paired, busy
        self.mode = lp.STOP_MODE_UNSPECIFIED  # UNSPECIFIED = running normally
        self._seen: Dict[str, bytes] = {}      # request_id -> ack, so a replayed request does nothing twice

    def _ack(self, rid: str, ok: bool, err: str = "") -> lp.DeviceToApp:
        return lp.DeviceToApp(ack=lp.ControlAck(request_id=rid, ok=ok, error=err, state=self.mode))

    def handle_bytes(self, raw: bytes) -> bytes:
        """Wire entry point: never raises, always answers."""
        try:
            msg = lp.AppToDevice.FromString(raw)
        except (DecodeError, ValueError):
            return self._ack("", False, "malformed").SerializeToString()
        return self.handle(msg).SerializeToString()

    def handle(self, msg: lp.AppToDevice) -> lp.DeviceToApp:
        kind = msg.WhichOneof("body")
        if kind is None:
            return self._ack("", False, "empty request")
        req = getattr(msg, kind)
        rid = req.request_id
        if not rid:
            return self._ack("", False, "request_id required")
        if rid in self._seen:
            return lp.DeviceToApp.FromString(self._seen[rid])
        ack = self._do(kind, req, rid)
        if len(self._seen) > 256:
            self._seen.pop(next(iter(self._seen)))
        self._seen[rid] = ack.SerializeToString()
        return ack

    def _do(self, kind: str, req, rid: str) -> lp.DeviceToApp:
        if not self.is_paired():
            return self._ack(rid, False, "not paired")
        if self.mode == lp.STOP_MODE_SHUTDOWN:
            return self._ack(rid, False, "shutting down")
        if kind == "mic_mute":
            self.c.set_mic_muted(req.muted)
            return self._ack(rid, True)
        if kind == "resume":
            if self.mode != lp.STOP_MODE_PAUSE:
                return self._ack(rid, False, "not paused")
            self.c.resume_assistant()
            self.mode = lp.STOP_MODE_UNSPECIFIED
            return self._ack(rid, True)
        # stop
        if not req.user_confirmed:
            return self._ack(rid, False, "user confirmation required")
        if req.mode not in (lp.STOP_MODE_PAUSE, lp.STOP_MODE_SHUTDOWN):
            return self._ack(rid, False, "unknown stop mode")
        if self.busy():
            return self._ack(rid, False, "safety self-test running")
        if req.mode == lp.STOP_MODE_PAUSE:
            self.c.pause_assistant()
            self.mode = lp.STOP_MODE_PAUSE
            return self._ack(rid, True)
        self.mode = lp.STOP_MODE_SHUTDOWN
        ack = self._ack(rid, True)  # the ack goes out before power drops; announce then power off follow
        self.c.announce_shutdown()
        self.c.power_off()
        return ack
