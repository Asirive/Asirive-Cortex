import os
import random

from cortex_core.contracts import local_pb2 as lp
from cortex_core.link.owner_control import OwnerControl


class Rec:
    def __init__(self): self.calls = []
    def __getattr__(self, n): return lambda *a: self.calls.append((n, *a))


def mk(paired=True, busy=False):
    r = Rec()
    return OwnerControl(r, lambda: paired, lambda: busy), r


def stop(mode, confirmed=True, rid="r1"):
    return lp.AppToDevice(stop=lp.StopRequest(mode=mode, request_id=rid, user_confirmed=confirmed))


def test_unconfirmed_stop_is_refused_and_does_nothing():
    oc, r = mk()
    a = oc.handle(stop(lp.STOP_MODE_SHUTDOWN, confirmed=False)).ack
    assert not a.ok and "confirmation" in a.error and r.calls == [] and oc.mode == lp.STOP_MODE_UNSPECIFIED


def test_unpaired_phone_cannot_stop_anything():
    oc, r = mk(paired=False)
    for m in (stop(lp.STOP_MODE_PAUSE), lp.AppToDevice(resume=lp.ResumeRequest(request_id="x")),
              lp.AppToDevice(mic_mute=lp.MicMuteRequest(muted=True, request_id="y"))):
        assert oc.handle(m).ack.error == "not paired"
    assert r.calls == []


def test_pause_stops_assistant_only_then_resume():
    oc, r = mk()
    a = oc.handle(stop(lp.STOP_MODE_PAUSE)).ack
    assert a.ok and a.state == lp.STOP_MODE_PAUSE and r.calls == [("pause_assistant",)]
    assert not hasattr(OwnerControl, "safety") and all("safety" not in c[0] for c in r.calls)
    assert oc.handle(lp.AppToDevice(resume=lp.ResumeRequest(request_id="r2"))).ack.state == lp.STOP_MODE_UNSPECIFIED
    assert not oc.handle(lp.AppToDevice(resume=lp.ResumeRequest(request_id="r3"))).ack.ok  # not paused


def test_shutdown_announces_before_power_off_and_blocks_further_commands():
    oc, r = mk()
    assert oc.handle(stop(lp.STOP_MODE_SHUTDOWN)).ack.ok
    assert [c[0] for c in r.calls] == ["announce_shutdown", "power_off"]
    assert oc.handle(stop(lp.STOP_MODE_PAUSE, rid="again")).ack.error == "shutting down"


def test_replayed_request_id_acts_once():
    oc, r = mk()
    oc.handle(stop(lp.STOP_MODE_PAUSE, rid="same"))
    oc.handle(stop(lp.STOP_MODE_PAUSE, rid="same"))
    assert len(r.calls) == 1


def test_refused_while_self_test_running_and_for_bad_input():
    oc, r = mk(busy=True)
    assert oc.handle(stop(lp.STOP_MODE_PAUSE)).ack.error == "safety self-test running"
    oc2, _ = mk()
    assert not oc2.handle(stop(lp.STOP_MODE_UNSPECIFIED)).ack.ok
    assert not oc2.handle(stop(lp.STOP_MODE_PAUSE, rid="")).ack.ok
    assert not oc2.handle(lp.AppToDevice()).ack.ok


def test_mic_mute_works_and_garbage_bytes_never_raise():
    oc, r = mk()
    assert oc.handle(lp.AppToDevice(mic_mute=lp.MicMuteRequest(muted=True, request_id="m"))).ack.ok
    assert r.calls == [("set_mic_muted", True)]
    rng = random.Random(1)
    for _ in range(500):
        raw = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40)))
        out = lp.DeviceToApp.FromString(oc.handle_bytes(raw))
        assert out.WhichOneof("body") == "ack"
    assert oc.mode in (lp.STOP_MODE_UNSPECIFIED, lp.STOP_MODE_PAUSE, lp.STOP_MODE_SHUTDOWN)
