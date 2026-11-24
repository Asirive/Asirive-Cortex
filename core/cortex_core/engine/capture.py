"""Camera and microphone through ffmpeg, in the formats the engine takes: RGB frames at 640x360 and 16 kHz mono
int16 audio. ffmpeg decodes the camera's MJPEG and resamples the mic, so Python only copies bytes. Both run on
cpu1-3 (never cpu0, the safety core; never cpu4-7, the LM cores)."""
from __future__ import annotations

import math
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import IO, Optional

CPUS = "1-3"


def _pin(cmd: list[str]) -> list[str]:
    return ["taskset", "-c", CPUS] + cmd


def camera_cmd(device: str, width: int = 640, height: int = 360, fps: int = 5,
               in_size: str = "1280x720") -> list[str]:
    return _pin(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2", "-input_format", "mjpeg",
                 "-video_size", in_size, "-i", device, "-vf", f"fps={fps},scale={width}:{height}",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])


def mic_cmd(device: str) -> list[str]:
    """"pw:" / "pw:<node>" records through PipeWire (which holds USB mics open); anything else is an ALSA device."""
    if device.startswith("pw:"):
        target = device[3:]
        return _pin(["pw-record", "--raw", "--rate", "16000", "--channels", "1", "--format", "s16"]
                    + (["--target", target] if target else []) + ["-"])
    return _pin(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "alsa", "-i", device,
                 "-ac", "1", "-ar", "16000", "-f", "s16le", "-"])


def find_camera(v4l=Path("/sys/class/video4linux")) -> Optional[str]:
    """The first V4L2 node that is not one of the SoC's video codec nodes (qcom-iris-*)."""
    try:
        nodes = sorted(v4l.iterdir(), key=lambda p: int(re.sub(r"\D", "", p.name) or 0))
    except OSError:
        return None
    for node in nodes:
        try:
            name = (node / "name").read_text().strip()
        except OSError:
            continue
        if not name.startswith("qcom-"):
            return f"/dev/{node.name}"
    return None


def find_mic(cards=Path("/proc/asound/cards"), pipewire: Optional[bool] = None) -> Optional[str]:
    """PipeWire's default source when PipeWire runs (it holds USB mics open, so ALSA direct is busy); else the
    first USB audio card (the onboard codec's mic input is unused), as an ALSA device name."""
    if pipewire is None:
        pipewire = shutil.which("pw-record") is not None
    if pipewire:
        return "pw:"
    try:
        text = cards.read_text()
    except OSError:
        return None
    for m in re.finditer(r"^\s*\d+\s+\[(\S+)\s*\]:\s+USB-Audio", text, re.M):
        return f"plughw:CARD={m.group(1)}"
    return None


def read_exact(f: IO[bytes], n: int) -> Optional[bytes]:
    """n bytes from a pipe (joining short reads), or None at end of stream (a torn tail is dropped)."""
    buf = bytearray()
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def rms_dbfs(pcm) -> float:
    """Level of an int16 chunk in dBFS (floor -96)."""
    import numpy as np

    a = np.asarray(pcm, dtype=np.float64)
    if a.size == 0:
        return -96.0
    rms = math.sqrt(float(np.mean(a * a))) / 32767.0
    return max(-96.0, 20.0 * math.log10(rms)) if rms > 0 else -96.0


class _Proc:
    def __init__(self, cmd: list[str]):
        if shutil.which(cmd[0]) is None and cmd[0] == "taskset":
            cmd = cmd[3:]  # no taskset: run unpinned
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.stop = threading.Event()

    def error(self) -> str:
        try:
            return (self.p.stderr.read() or b"").decode(errors="replace").strip()[-300:]
        except (OSError, ValueError):
            return ""

    def close(self) -> None:
        self.stop.set()
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.p.kill()


class Camera(_Proc):
    """Keeps the latest frame; latest() returns (frame_id, rgb [h, w, 3] uint8) or None before the first."""

    def __init__(self, device: str, width: int = 640, height: int = 360, fps: int = 5):
        super().__init__(camera_cmd(device, width, height, fps))
        self.w, self.h = width, height
        self._lock = threading.Lock()
        self._latest = None
        self._id = 0
        self.thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        import numpy as np

        n = self.w * self.h * 3
        while not self.stop.is_set():
            b = read_exact(self.p.stdout, n)
            if b is None:
                return
            with self._lock:
                self._id += 1
                self._latest = (self._id, np.frombuffer(b, dtype=np.uint8).reshape(self.h, self.w, 3))

    def latest(self):
        with self._lock:
            return self._latest

    def alive(self) -> bool:
        return self.thread.is_alive()


class Mic(_Proc):
    """Calls on_chunk(int16 array) every 20 ms of audio."""

    def __init__(self, device: str, on_chunk, chunk: int = 320):
        super().__init__(mic_cmd(device))
        self.on_chunk, self.chunk = on_chunk, chunk
        self.thread = threading.Thread(target=self._run, name="mic", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        import numpy as np

        while not self.stop.is_set():
            b = read_exact(self.p.stdout, self.chunk * 2)
            if b is None:
                return
            self.on_chunk(np.frombuffer(b, dtype=np.int16))

    def alive(self) -> bool:
        return self.thread.is_alive()
