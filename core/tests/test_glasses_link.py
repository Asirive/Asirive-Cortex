"""The glasses safety channel (cortex_core/safety/glasses.py) against the firmware's own framing code
(firmware/glasses/main/proto.c, compiled here with the host C compiler) and over a real pseudo-terminal."""
import math
import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from cortex_core.safety import glasses as G
from cortex_core.safety.engine import SafetyService, SensorError

FW = Path(__file__).resolve().parents[2] / "firmware" / "glasses"


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("no C compiler")
    exe = tmp_path_factory.mktemp("fw") / "proto_host"
    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-o", str(exe),
                    str(FW / "test" / "proto_host.c"), str(FW / "main" / "proto.c")], check=True)
    return exe


# ------------------------------------------------------------------ framing
def test_crc_is_ccitt_false():
    assert G.crc16(b"123456789") == 0x29B1


@pytest.mark.parametrize("data", [b"", b"\x00", b"\x00\x00", b"abc", bytes(range(256)) * 3, b"\x01" * 254,
                                  b"\x01" * 255, b"\x01" * 253 + b"\x00", bytes(600)])
def test_cobs_round_trip_has_no_zero(data):
    enc = G.cobs_encode(data)
    assert 0 not in enc and G.cobs_decode(enc) == data


def test_deframer_any_chunking_and_drops_corruption():
    frames = [G.packet(G.T_BEAT, i, bytes([i, 0, 255])) for i in range(20)]
    bad = bytearray(frames[3])
    bad[2] ^= 0x40
    stream = b"\x00garbage\x00" + b"".join(frames[:3]) + bytes(bad) + b"".join(frames[4:])
    for chunk in (1, 3, 7, 64, len(stream)):
        d = G.Deframer()
        got = [p for k in range(0, len(stream), chunk) for p in d.feed(stream[k:k + chunk])]
        assert [p[1] for p in got] == [i for i in range(20) if i != 3]
        assert d.bad == 2  # the garbage and the flipped bit


def test_firmware_frames_decode_in_python(harness):
    out = subprocess.run([str(harness), "encode"], capture_output=True, check=True).stdout
    pk = list(G.Deframer().feed(out))
    assert [p[0] for p in pk] == [G.T_HELLO, G.T_TOF, G.T_STATUS, G.T_BUTTON]
    pv, fw, build = struct.unpack(G.HELLO_FMT, pk[0][2])
    assert (pv, fw, build.rstrip(b"\0")) == (G.PROTO_VERSION, 7, b"a1-test")
    f = G.decode_tof(pk[1][2])
    assert f.t_us == 4294967000 and f.imu_n == 14
    assert [round(v, 3) for v in f.accel] == [0.01, -0.25, 0.97] and round(f.dtheta[2], 3) == 0.05
    assert f.mm[5] == 0 and f.mm[4] == 656 and f.mm[63] == 6300 + 0 and f.status[7] == 255 and f.status[8] == 5
    assert struct.unpack(G.STATUS_FMT, pk[2][2]) == (7, G.FLAG_TOF | G.FLAG_IMU | G.FLAG_HOST, 123456, 1, 0, 3)
    assert struct.unpack(G.BUTTON_FMT, pk[3][2]) == (1000000, G.BUTTON_TAP)


def test_python_frames_decode_in_firmware(harness):
    prio, steps = G.pattern("close", "left")
    stream = (G.packet(G.T_BEAT, 9) + G.packet(G.T_HAPTIC, 10, G.haptic_payload(prio, steps))
              + b"\x01\x02\x03\x00"  # junk frame
              + G.packet(G.T_HAPTIC, 11, b"\x01\x05"))  # claims 5 steps, has none
    out = subprocess.run([str(harness), "decode"], input=stream, capture_output=True, check=True).stdout.decode()
    lines = out.split("\n")
    assert lines[0] == "17 9 "
    assert lines[1] == "16 10 prio=1 220,0,80 0,0,60 220,0,80 0,0,60 220,0,80"
    assert lines[2] == "16 11 bad"
    assert lines[3] == "bad 1"


def test_firmware_survives_oversized_garbage(harness):
    stream = b"\x07" * 5000 + b"\x00" + G.packet(G.T_BEAT, 1)
    out = subprocess.run([str(harness), "decode"], input=stream, capture_output=True, check=True).stdout.decode()
    assert out.split("\n")[:2] == ["17 1 ", "bad 1"]


# ------------------------------------------------------------------ payload mapping
def tof(t_us=0, mm=None, st=None, accel=(0.0, 0.0, 1.0), dtheta=(0.0, 0.0, 0.0)):
    return G.TofFrame(t_us, accel, dtheta, 14, tuple(mm or [1000] * 64), tuple(st or [5] * 64))


def test_invalid_zones_are_none():
    mm = [1000] * 64
    mm[3] = 0
    st = [5] * 64
    st[4], st[5], st[6] = 9, 4, 255
    f = G.to_frame(tof(mm=mm, st=st), 0.0)
    assert f.dist_mm[3] is None and f.dist_mm[4] == 1000.0 and f.dist_mm[5] is None and f.dist_mm[6] is None


def test_zone_and_imu_mount_maps(monkeypatch):
    monkeypatch.setattr(G, "ZONE_FLIP_LR", True)
    monkeypatch.setattr(G, "IMU_AXES", ((1, -1.0), (0, 1.0), (2, 1.0)))
    monkeypatch.setattr(G, "_ZONES", G.zone_map())
    mm = list(range(1, 65))
    f = G.to_frame(tof(mm=mm, accel=(0.1, 0.2, 0.9)), 0.0)
    assert f.dist_mm[0] == 8.0 and f.dist_mm[7] == 1.0     # row 0 mirrored
    assert f.accel == (-0.2, 0.1, 0.9)
    assert sorted(G.zone_map()) == list(range(64))


def test_haptic_payload_clamps_and_limits():
    p = G.haptic_payload(1, [(300, -5, 70000)] * 20)
    assert p[:2] == bytes([1, 12]) and len(p) == 2 + 48 and p[2:6] == bytes([255, 0]) + struct.pack("<H", 65535)


# ------------------------------------------------------------------ over a real pty
class Pty:
    def __init__(self):
        self.master, slave = os.openpty()
        self.path = os.ttyname(slave)
        self._slave = slave  # kept open so the master does not see EOF before the link opens it
        self.rx = G.Deframer()

    def send(self, data: bytes):
        os.write(self.master, data)

    def received(self):
        os.set_blocking(self.master, False)
        try:
            data = os.read(self.master, 65536)
        except BlockingIOError:
            data = b""
        return list(self.rx.feed(data))

    def close(self):
        for fd in (self.master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.fixture
def pty():
    p = Pty()
    yield p
    p.close()


def test_sensor_reads_frames_buttons_and_status_and_beats(pty):
    presses = []
    link = G.Link(pty.path)
    sens = G.GlassesSensor(link, timeout=0.2, on_button=lambda k, t: presses.append((k, t)))
    assert link.ensure()  # opening flushes stale input, so open first
    pty.send(G.packet(G.T_HELLO, 1, struct.pack(G.HELLO_FMT, 1, 7, b"a1"))
             + G.packet(G.T_BUTTON, 2, struct.pack(G.BUTTON_FMT, 2_000_000, G.BUTTON_TAP))
             + G.packet(G.T_STATUS, 3, struct.pack(G.STATUS_FMT, 7, 3, 10, 0, 0, 0))
             + G.packet(G.T_TOF, 4, G.encode_tof(tof(t_us=2_500_000))))
    f = sens.read()
    assert f is not None and f.t == 2.5 and len(f.dist_mm) == 64
    assert presses == [(G.BUTTON_TAP, 2.0)] and link.hello == (1, 7, "a1") and link.status[1] == 3
    assert [p[0] for p in pty.received()] == [G.T_BEAT]
    assert sens.read() is None  # nothing more within the timeout


def test_time_unwraps_past_u32(pty):
    link = G.Link(pty.path)
    sens = G.GlassesSensor(link, timeout=0.2)
    assert link.ensure()
    pty.send(G.packet(G.T_TOF, 1, G.encode_tof(tof(t_us=2 ** 32 - 1000))))
    t1 = sens.read().t
    pty.send(G.packet(G.T_TOF, 2, G.encode_tof(tof(t_us=65_666))))
    assert abs(sens.read().t - t1 - 0.066666) < 1e-6


def test_missing_port_is_a_sensor_error():
    sens = G.GlassesSensor(G.Link("/nonexistent/cortex-glasses"), timeout=0.01)
    with pytest.raises(SensorError):
        sens.read()


def test_unplug_is_a_sensor_error_then_reconnects(pty):
    link = G.Link(pty.path)
    sens = G.GlassesSensor(link, timeout=0.2)
    assert link.ensure()
    pty.send(G.packet(G.T_TOF, 1, G.encode_tof(tof())))
    assert sens.read() is not None
    os.close(pty._slave)
    os.close(pty.master)  # the far end goes away: reads fail with EIO / EOF
    with pytest.raises(SensorError):
        sens.read()
    assert link.fd is None


def test_button_fifo_never_blocks(tmp_path):
    fifo = tmp_path / "button"
    G.ButtonFifo(str(fifo))(G.BUTTON_TAP, 1.0)            # no fifo: dropped
    os.mkfifo(fifo)
    G.ButtonFifo(str(fifo))(G.BUTTON_TAP, 1.0)            # no reader: dropped, not blocked
    r = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    G.ButtonFifo(str(fifo))(G.BUTTON_LONG, 2.5)
    assert os.read(r, 100) == b"long 2.500\n"
    os.close(r)


def test_end_to_end_overhang_vibrates_on_the_glasses(pty):
    """Simulated walker -> wire frames -> pty -> GlassesSensor -> SafetyService -> GlassesOut -> haptic packet."""
    from tests import safety_sim as S

    sc = [s for s in S.scenarios(0) if s.name == "branch ahead"][0]
    frames = S.run(sc, 0)["frames"]
    link = G.Link(pty.path)
    out_log = []
    svc = SafetyService(G.GlassesSensor(link, timeout=0.2), G.GlassesOut(link, out_log.append), lambda: None,
                        {"version": 1, "sensor_height_m": round(sc.walker.h, 2)})
    assert link.ensure()
    haptics = []
    for k, f in enumerate(frames):
        mm = [0 if v is None else int(round(v)) for v in f.dist_mm]
        st = [255 if v is None else 5 for v in f.dist_mm]
        pty.send(G.packet(G.T_TOF, k, G.encode_tof(G.TofFrame(int(f.t * 1e6), tuple(f.accel), tuple(f.dtheta), 14,
                                                              tuple(mm), tuple(st)))))
        svc.step()
        haptics += [p for p in pty.received() if p[0] == G.T_HAPTIC]
    assert haptics, "no warning reached the glasses"
    assert haptics[0][2][0] == 1 and out_log == []  # a warning-priority pattern, nothing dropped


def test_service_runs_blind_without_glasses_and_stops_on_sigterm(tmp_path):
    import signal
    import sys
    import time

    env = dict(os.environ, CORTEX_GLASSES_TTY=str(tmp_path / "no-glasses"), CORTEX_HB_DIR=str(tmp_path / "hb"),
               CORTEX_BUTTON_FIFO=str(tmp_path / "fifo"), CORTEX_SAFETY_CFG=str(tmp_path / "none.json"),
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    p = subprocess.Popen([sys.executable, "-m", "cortex_core.safety"], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    try:
        hb = tmp_path / "hb" / "safety"
        deadline = time.monotonic() + 10
        while not hb.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert hb.exists(), "no heartbeat while blind"
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=5) == 0
    finally:
        if p.poll() is None:
            p.kill()


def test_fit_config_file(tmp_path):
    from cortex_core.safety.__main__ import load_cfg

    f = tmp_path / "safety.json"
    assert load_cfg(str(f)) is None
    f.write_text("{not json")
    assert load_cfg(str(f)) is None
    f.write_text('{"version": 1, "sensor_height_m": 1.62}')
    assert load_cfg(str(f)) == {"version": 1, "sensor_height_m": 1.62}
