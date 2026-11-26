import io

import pytest

from cortex_core.engine import capture


def test_camera_cmd_scales_mjpeg_to_rgb_on_cpu1_3():
    cmd = capture.camera_cmd("/dev/video2", 640, 360, fps=5)
    assert cmd[:3] == ["taskset", "-c", "1-3"]
    s = " ".join(cmd)
    assert "-f v4l2" in s and "-input_format mjpeg" in s and "-i /dev/video2" in s
    assert "fps=5,scale=640:360" in s and "-pix_fmt rgb24" in s and s.endswith("-")


def test_mic_cmd_resamples_to_16k_mono_s16():
    s = " ".join(capture.mic_cmd("hw:1,0"))
    assert "-f alsa" in s and "-i hw:1,0" in s
    assert "-ac 1" in s and "-ar 16000" in s and "-f s16le" in s and s.endswith("-")


def test_read_exact_returns_whole_frames_then_none():
    data = bytes(range(10)) * 3  # 30 bytes
    f = io.BytesIO(data)
    assert capture.read_exact(f, 12) == data[:12]
    assert capture.read_exact(f, 12) == data[12:24]
    assert capture.read_exact(f, 12) is None  # 6 bytes left: a torn frame is dropped


class Trickle(io.RawIOBase):
    """A pipe that hands out at most 5 bytes per read."""

    def __init__(self, data):
        self.data = data

    def readinto(self, b):
        n = min(5, len(b), len(self.data))
        b[:n], self.data = self.data[:n], self.data[n:]
        return n

    def readable(self):
        return True


def test_read_exact_joins_short_pipe_reads():
    assert capture.read_exact(Trickle(b"abcdefghijkl"), 12) == b"abcdefghijkl"


def test_find_camera_skips_codec_nodes(tmp_path):
    for n, name in (("video0", "qcom-iris-decoder"), ("video1", "qcom-iris-encoder"), ("video2", "ZV-1F"),
                    ("video3", "ZV-1F")):
        (tmp_path / n).mkdir()
        (tmp_path / n / "name").write_text(name + "\n")
    assert capture.find_camera(tmp_path) == "/dev/video2"
    assert capture.find_camera(tmp_path / "none") is None


def test_find_mic_takes_the_first_usb_card(tmp_path):
    cards = tmp_path / "cards"
    cards.write_text(" 0 [SC8280XPRadxaDr]: sc8280xp - SC8280XP-Radxa-Dragon-Q8B\n"
                     "                      Radxa...\n"
                     " 1 [ZV1F           ]: USB-Audio - ZV-1F\n"
                     "                      Sony ZV-1F at usb-xhci-hcd.1-1.2, high speed\n")
    assert capture.find_mic(cards, pipewire=False) == "plughw:CARD=ZV1F"
    cards.write_text(" 0 [SC8280XPRadxaDr]: sc8280xp - SC8280XP-Radxa-Dragon-Q8B\n")
    assert capture.find_mic(cards, pipewire=False) is None


def test_find_mic_prefers_pipewire_which_owns_the_card(tmp_path):
    # PipeWire holds USB mics open; ALSA direct then fails with "Device or resource busy"
    assert capture.find_mic(tmp_path / "cards", pipewire=True) == "pw:"


def test_mic_cmd_pipewire_is_raw_16k_mono():
    s = " ".join(capture.mic_cmd("pw:"))
    assert "pw-record --raw --rate 16000 --channels 1 --format s16" in s and s.endswith(" -")
    assert "--target" not in s
    assert "--target ZV-1F" in " ".join(capture.mic_cmd("pw:ZV-1F"))


def test_rms_dbfs():
    np = pytest.importorskip("numpy")
    assert capture.rms_dbfs(np.zeros(320, dtype=np.int16)) == -96.0
    full = np.full(320, 32767, dtype=np.int16)
    assert capture.rms_dbfs(full) == pytest.approx(0.0, abs=0.01)
    half = np.full(320, 16384, dtype=np.int16)
    assert capture.rms_dbfs(half) == pytest.approx(-6.02, abs=0.05)


def test_pipewire_only_when_its_socket_exists(tmp_path, monkeypatch):
    """A boot service has no login session: pw-record installed but no PipeWire running -> ALSA direct."""
    monkeypatch.setattr(capture.shutil, "which", lambda n: "/usr/bin/pw-record")
    assert capture.pipewire_running({"XDG_RUNTIME_DIR": str(tmp_path)}) is False
    assert capture.pipewire_running({}) is False
    (tmp_path / "pipewire-0").touch()
    assert capture.pipewire_running({"XDG_RUNTIME_DIR": str(tmp_path)}) is True
    monkeypatch.setattr(capture.shutil, "which", lambda n: None)
    assert capture.pipewire_running({"XDG_RUNTIME_DIR": str(tmp_path)}) is False
