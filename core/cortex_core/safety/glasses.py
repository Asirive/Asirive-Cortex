"""The glasses' safety channel: ToF + IMU frames in, vibration out, over the ESP32-S3's dedicated USB serial (CDC)
port. Wire format: docs/architecture/GLASSES-USB.md (firmware side: firmware/glasses/main/proto.c).

Safety owns this port alone. Camera (UVC) and audio (UAC) are separate USB interfaces of the same device, read by
the brain, so nothing else can delay a ToF frame. The glasses button arrives here too and is passed on to the brain
through a FIFO that is written without ever blocking (dropped when nobody listens).

Stdlib only (the safety import guard): os, termios, select, struct.
"""
import errno
import math
import os
import select
import struct
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Optional, Sequence

from cortex_core.safety.engine import Frame, SensorError

PROTO_VERSION = 1

# glasses -> box
T_TOF, T_STATUS, T_BUTTON, T_HELLO = 0x01, 0x02, 0x03, 0x04
# box -> glasses
T_HAPTIC, T_BEAT = 0x10, 0x11

TOF_FMT = "<I3f3fH64H64B"        # t_us, accel g (chip axes), dtheta rad (chip axes), imu samples, mm, ULD status
TOF_LEN = struct.calcsize(TOF_FMT)
STATUS_FMT = "<HHIHHH"           # fw version, flags, uptime ms, tof errors, imu errors, usb tx drops
HELLO_FMT = "<HH16s"             # protocol version, fw version, build id
BUTTON_FMT = "<IB"               # t_us, kind

FLAG_TOF, FLAG_IMU, FLAG_CAM, FLAG_MIC, FLAG_AMP, FLAG_HOST, FLAG_FAILSAFE = (1 << i for i in range(7))
BUTTON_TAP, BUTTON_LONG = 1, 2

VALID_STATUS = (5, 9)            # ST: 5 and 9 are fully valid ranges; the rest are < 50 % reliable
MAX_STEPS = 12
BEAT_S = 0.5                     # the glasses vibrate "degraded" on their own if beats stop for 1.5 s

# Mounting, board rev A1 (proposed, see firmware/glasses/README.md). NOT YET CHECKED ON HARDWARE: the first wiring
# session runs `python -m cortex_core.safety.glasses --grid` (hand on the left must light the left columns) and
# `--imu` (still and level: +1 g on z; nod down: pitch goes negative) and fixes these.
ZONE_FLIP_LR = False     # ULD zone index -> our row 0 = top, column 0 = user's left
ZONE_FLIP_UD = False
ZONE_TRANSPOSE = False
IMU_AXES = ((0, 1.0), (1, 1.0), (2, 1.0))   # ours x,y,z = sign * chip[axis]; ours: x right, y forward, z up


# ------------------------------------------------------------------ framing
def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF): the same function as proto.c."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def cobs_encode(data: bytes) -> bytes:
    out, code_i, code = bytearray([0]), 0, 1
    for b in data:
        if b == 0:
            out[code_i] = code
            code_i, code = len(out), 1
            out.append(0)
            continue
        out.append(b)
        code += 1
        if code == 0xFF:
            out[code_i] = code
            code_i, code = len(out), 1
            out.append(0)
    out[code_i] = code
    return bytes(out)


def cobs_decode(data: bytes) -> Optional[bytes]:
    out, i, n = bytearray(), 0, len(data)
    while i < n:
        code = data[i]
        end = i + code
        if code == 0 or end > n:
            return None
        chunk = data[i + 1:end]
        if 0 in chunk:
            return None
        out += chunk
        i = end
        if code != 0xFF and i < n:
            out.append(0)
    return bytes(out)


def packet(ptype: int, seq: int, payload: bytes = b"") -> bytes:
    """One frame on the wire: COBS(type, seq, payload, crc16 LE) + 0x00."""
    body = bytes([ptype, seq & 0xFF]) + payload
    return cobs_encode(body + struct.pack("<H", crc16(body))) + b"\x00"


def parse(frame: bytes) -> Optional[tuple[int, int, bytes]]:
    """A frame without its 0x00 -> (type, seq, payload), or None if corrupt."""
    raw = cobs_decode(frame)
    if raw is None or len(raw) < 4:
        return None
    body, (crc,) = raw[:-2], struct.unpack("<H", raw[-2:])
    if crc16(body) != crc:
        return None
    return body[0], body[1], body[2:]


class Deframer:
    """Bytes in any chunking -> packets. Garbage and corrupt frames are counted and dropped."""

    MAX_FRAME = 1024

    def __init__(self):
        self.buf = bytearray()
        self.bad = 0

    def feed(self, data: bytes) -> Iterator[tuple[int, int, bytes]]:
        self.buf += data
        while True:
            k = self.buf.find(0)
            if k < 0:
                if len(self.buf) > self.MAX_FRAME:  # no delimiter in far too long: resync
                    self.buf.clear()
                    self.bad += 1
                return
            frame = bytes(self.buf[:k])
            del self.buf[:k + 1]
            if not frame:
                continue
            p = parse(frame)
            if p is None:
                self.bad += 1
                continue
            yield p


# ------------------------------------------------------------------ payloads
@dataclass
class TofFrame:
    t_us: int
    accel: tuple[float, float, float]
    dtheta: tuple[float, float, float]
    imu_n: int
    mm: tuple[int, ...]
    status: tuple[int, ...]


def decode_tof(payload: bytes) -> Optional[TofFrame]:
    if len(payload) != TOF_LEN:
        return None
    v = struct.unpack(TOF_FMT, payload)
    return TofFrame(v[0], tuple(v[1:4]), tuple(v[4:7]), v[7], tuple(v[8:72]), tuple(v[72:136]))


def encode_tof(f: TofFrame) -> bytes:  # used by tests and the bench replayer
    return struct.pack(TOF_FMT, f.t_us, *f.accel, *f.dtheta, f.imu_n, *f.mm, *f.status)


def zone_map() -> list[int]:
    """our index (row 0 top, column 0 left) -> ULD zone index."""
    out = []
    for r in range(8):
        for c in range(8):
            rr, cc = (7 - r if ZONE_FLIP_UD else r), (7 - c if ZONE_FLIP_LR else c)
            out.append(cc * 8 + rr if ZONE_TRANSPOSE else rr * 8 + cc)
    return out


_ZONES = zone_map()


def to_frame(f: TofFrame, t: float) -> Frame:
    dist: list[Optional[float]] = []
    for z in _ZONES:
        mm, st = f.mm[z], f.status[z]
        dist.append(float(mm) if mm > 0 and st in VALID_STATUS else None)
    ax = tuple(s * f.accel[i] for i, s in IMU_AXES)
    dt = tuple(s * f.dtheta[i] for i, s in IMU_AXES)
    return Frame(t, dist, ax, dt)


def haptic_payload(prio: int, steps: Sequence[tuple[int, int, int]]) -> bytes:
    """steps: (left 0-255, right 0-255, ms). A pattern of equal or higher priority replaces the one playing."""
    steps = list(steps)[:MAX_STEPS]
    out = bytearray([prio & 0xFF, len(steps)])
    for left, right, ms in steps:
        out += struct.pack("<BBH", max(0, min(255, left)), max(0, min(255, right)), max(0, min(65535, ms)))
    return bytes(out)


# Patterns (learned by the user; first proposal, to be tuned with users). Priority: 0 info, 1 warning, 2 degraded.
_ON = 220


def pattern(name: str, side: str) -> tuple[int, list[tuple[int, int, int]]]:
    left = _ON if side in ("left", "both") else 0
    right = _ON if side in ("right", "both") else 0
    if name == "ahead":     # one firm pulse on the obstacle's side
        return 1, [(left, right, 150)]
    if name == "close":     # three quick pulses
        return 1, [(left, right, 80), (0, 0, 60)] * 2 + [(left, right, 80)]
    if name == "degraded":  # long - short - long, both sides: "I can't see"
        return 2, [(_ON, _ON, 400), (0, 0, 150), (_ON, _ON, 120), (0, 0, 150), (_ON, _ON, 400)]
    return 0, [(left, right, 30)]   # tick


# ------------------------------------------------------------------ the port
def open_serial(path: str) -> int:
    """Raw, non-blocking. termios raw mode so no byte is eaten as a control character."""
    import termios  # noqa: PLC0415 - stdlib; kept local so the module imports on any OS for tests

    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        a = termios.tcgetattr(fd)
        a[0] = 0                                   # iflag
        a[1] = 0                                   # oflag
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[3] = 0                                   # lflag
        a[6][termios.VMIN], a[6][termios.VTIME] = 0, 0
        termios.tcsetattr(fd, termios.TCSANOW, a)
        termios.tcflush(fd, termios.TCIOFLUSH)
    except Exception:
        os.close(fd)
        raise
    return fd


class Link:
    """One open port shared by GlassesSensor (reads) and GlassesOut (writes). Reopens after unplug."""

    def __init__(self, path: str, opener: Callable[[str], int] = open_serial, clock: Callable[[], float] = time.monotonic):
        self.path, self.opener, self.clock = path, opener, clock
        self.fd: Optional[int] = None
        self.deframer = Deframer()
        self.seq = 0
        self.hello: Optional[tuple[int, int, str]] = None
        self.status: Optional[tuple[int, ...]] = None
        self.tx_fail = 0
        self._last_beat = -1e9
        self._next_open = 0.0

    def ensure(self) -> bool:
        if self.fd is not None:
            return True
        now = self.clock()
        if now < self._next_open:
            return False
        self._next_open = now + 0.5
        try:
            self.fd = self.opener(self.path)
            self.deframer = Deframer()
            self._last_beat = -1e9
            return True
        except OSError:
            return False

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None

    def send(self, ptype: int, payload: bytes = b"") -> bool:
        """Never blocks: a full buffer drops the packet (counted). A dead port is closed for reopen."""
        if not self.ensure():
            return False
        self.seq = (self.seq + 1) & 0xFF
        data = packet(ptype, self.seq, payload)
        try:
            n = os.write(self.fd, data)
            if n != len(data):
                self.tx_fail += 1
                return False
            return True
        except BlockingIOError:
            self.tx_fail += 1
            return False
        except OSError:
            self.close()
            return False

    def beat(self) -> None:
        now = self.clock()
        if now - self._last_beat >= BEAT_S:
            if self.send(T_BEAT):
                self._last_beat = now

    def recv(self, timeout: float) -> Iterator[tuple[int, int, bytes]]:
        """Packets that arrive within `timeout`. Raises OSError if the port went away."""
        if not self.ensure():
            return
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return
        except OSError:  # EIO after unplug
            self.close()
            raise
        if not data:  # EOF: unplugged
            self.close()
            raise OSError(errno.ENODEV, "glasses unplugged")
        yield from self.deframer.feed(data)


class ButtonFifo:
    """Button events to the brain: a named pipe written non-blocking. No reader, or a full pipe: dropped."""

    def __init__(self, path: str):
        self.path = path

    def __call__(self, kind: int, t: float) -> None:
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:  # ENXIO: nobody reading; ENOENT: no fifo
            return
        try:
            os.write(fd, f"{'tap' if kind == BUTTON_TAP else 'long'} {t:.3f}\n".encode())
        except OSError:
            pass
        finally:
            os.close(fd)


class GlassesSensor:
    """engine.Sensor over the link: read() returns the next ToF frame, None on timeout; SensorError when the
    glasses are gone (unplugged, or the port cannot be opened)."""

    def __init__(self, link: Link, timeout: float = 0.1, on_button: Optional[Callable[[int, float], None]] = None):
        self.link, self.timeout, self.on_button = link, timeout, on_button
        self._wrap = 0
        self._last_us: Optional[int] = None

    def _t(self, t_us: int) -> float:
        if self._last_us is not None and t_us < self._last_us and self._last_us - t_us > 1 << 31:
            self._wrap += 1 << 32   # u32 microseconds wraps every 71.6 min
        self._last_us = t_us
        return (self._wrap + t_us) / 1e6

    def read(self) -> Optional[Frame]:
        link = self.link
        if not link.ensure():
            raise SensorError(f"glasses port {link.path} not available")
        link.beat()
        deadline = link.clock() + self.timeout
        while True:
            left = deadline - link.clock()
            try:
                for ptype, _seq, payload in link.recv(max(0.0, left)):
                    if ptype == T_TOF:
                        f = decode_tof(payload)
                        if f is not None:
                            return to_frame(f, self._t(f.t_us))
                    elif ptype == T_BUTTON and len(payload) == struct.calcsize(BUTTON_FMT) and self.on_button:
                        t_us, kind = struct.unpack(BUTTON_FMT, payload)
                        try:
                            self.on_button(kind, self._t(t_us))
                        except Exception:  # noqa: BLE001 - the brain's side must never hurt safety
                            pass
                    elif ptype == T_STATUS and len(payload) == struct.calcsize(STATUS_FMT):
                        link.status = struct.unpack(STATUS_FMT, payload)
                    elif ptype == T_HELLO and len(payload) == struct.calcsize(HELLO_FMT):
                        pv, fw, build = struct.unpack(HELLO_FMT, payload)
                        link.hello = (pv, fw, build.rstrip(b"\x00").decode("ascii", "replace"))
            except OSError as e:
                raise SensorError(str(e)) from e
            if link.clock() >= deadline:
                return None


class GlassesOut:
    """engine.Output over the link. The 'safety_degraded' audio cue is not playable from here (the speaker is the
    UAC sound card, owned by the brain's audio path): the glasses get the degraded vibration, and the cue is logged
    for the supervisor until an audio sink exists."""

    def __init__(self, link: Link, log: Callable[[str], None] = lambda s: print(s, flush=True)):
        self.link, self.log = link, log

    def haptic(self, name: str, side: str = "both") -> None:
        prio, steps = pattern(name, side)
        if not self.link.send(T_HAPTIC, haptic_payload(prio, steps)):
            self.log(f"HAPTIC-DROPPED {name} {side}")

    def cue(self, cue_id: str) -> None:
        self.log(f"CUE {cue_id}")


# ------------------------------------------------------------------ bring-up tools (dev only)
def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Glasses safety channel bring-up")
    ap.add_argument("--port", default=os.environ.get("CORTEX_GLASSES_TTY", "/dev/cortex-glasses-safety"))
    ap.add_argument("--grid", action="store_true", help="print the 8x8 grid (row 0 top, column 0 = user's left)")
    ap.add_argument("--imu", action="store_true", help="print accel / pitch / roll in our axes")
    ap.add_argument("--buzz", choices=["ahead", "close", "degraded", "tick"], help="play one pattern")
    ap.add_argument("--side", default="both", choices=["left", "right", "both"])
    a = ap.parse_args()
    link = Link(a.port)
    sens = GlassesSensor(link, timeout=1.0, on_button=lambda k, t: print("BUTTON", "tap" if k == 1 else "long", t))
    if a.buzz:
        GlassesOut(link).haptic(a.buzz, a.side)
    n = 0
    while True:
        f = sens.read()
        if f is None:
            print("no frame in 1 s", link.hello, link.status)
            continue
        n += 1
        if a.grid and n % 3 == 0:
            print("\x1b[2J\x1b[H", end="")
            for r in range(8):
                print(" ".join("  .  " if v is None else f"{v / 1000:4.2f}m"[:5] for v in f.dist_mm[r * 8:r * 8 + 8]))
        if a.imu and n % 8 == 0:
            ax, ay, az = f.accel
            print(f"accel {ax:+.2f} {ay:+.2f} {az:+.2f} g  pitch {math.degrees(math.atan2(ay, math.hypot(ax, az))):+5.1f}"
                  f"  roll {math.degrees(math.atan2(-ax, az)):+5.1f}  dyaw {math.degrees(f.dtheta[2]) * 15:+6.1f} deg/s")


if __name__ == "__main__":
    _main()
