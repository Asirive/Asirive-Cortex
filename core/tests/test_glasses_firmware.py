"""The glasses firmware's portable parts, built with the host C compiler: the haptic player, the heartbeat
fail-safe and the button debouncer (firmware/glasses/main/logic.c), and the composite USB descriptors
(main/usb_desc.c, against TinyUSB's headers from firmware/glasses/scripts/fetch_tinyusb_headers.sh).
What this cannot cover: anything that touches the ESP32-S3's hardware. That needs the ESP-IDF build and the glasses."""
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from cortex_core.safety import glasses as G

FW = Path(__file__).resolve().parents[2] / "firmware" / "glasses"
TUSB = FW / ".deps" / "tinyusb" / "src"


def _cc():
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("no C compiler")
    return cc


@pytest.fixture(scope="module")
def logic(tmp_path_factory):
    exe = tmp_path_factory.mktemp("fw") / "logic_host"
    subprocess.run([_cc(), "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", f"-I{FW / 'main'}", "-o", str(exe),
                    str(FW / "test" / "logic_host.c"), str(FW / "main" / "logic.c")], check=True)

    def run(*cmds):
        out = subprocess.run([str(exe)], input="\n".join(cmds) + "\n", capture_output=True, text=True, check=True)
        return out.stdout.splitlines()
    return run


# ------------------------------------------------------------------ haptic player
def test_pattern_plays_step_by_step_then_stops(logic):
    assert logic("offer 0 1 220,0,100 0,0,50", "out 0", "out 99", "out 100", "out 149", "out 150") == [
        "accept", "220 0 100", "220 0 1", "0 0 50", "0 0 1", "0 0 -1"]


def test_late_poll_skips_steps_it_slept_through(logic):
    assert logic("offer 0 1 1,1,10 2,2,10 3,3,10", "out 25")[1] == "3 3 5"


def test_priority_equal_or_higher_replaces_lower_is_dropped(logic):
    assert logic("offer 0 1 9,9,500", "offer 10 0 1,1,30", "out 10",
                 "offer 20 1 7,0,100", "out 20", "offer 30 2 5,5,40", "out 30") == [
        "accept", "reject", "9 9 490", "accept", "7 0 100", "accept", "5 5 40"]


def test_low_priority_plays_once_the_pattern_is_over(logic):
    assert logic("offer 0 2 9,9,50", "out 60", "offer 60 0 1,1,30", "out 60") == ["accept", "0 0 -1", "accept",
                                                                                  "1 1 30"]


def test_local_patterns_match_the_box(logic):
    for name in ("tick", "degraded"):
        prio, steps = G.pattern(name, "both")
        assert logic(f"pat 0 {name}") == [" ".join([str(prio)] + [f"{a},{b},{c}" for a, b, c in steps])]


# ------------------------------------------------------------------ fail-safe
def test_failsafe_needs_a_first_beat(logic):
    assert logic("fs 0", "fs 100000") == ["quiet", "quiet"]  # box never ran the safety service: no false alarm


def test_failsafe_alarms_after_silence_and_repeats_every_5s(logic):
    assert logic("beat 1000", "beat 1500", "fs 2999", "fs 3000", "fs 3100", "fs 7999", "fs 8000", "beat 8200",
                 "fs 8300", "fs 9699", "fs 9700") == [
        "ok", "ok", "quiet", "alarm", "quiet", "quiet", "alarm", "ok", "quiet", "quiet", "alarm"]


def test_failsafe_matches_the_box_beat_period():
    assert G.BEAT_S * 3 == pytest.approx(1.5)  # FAILSAFE_MS in logic.h: three beats missed


# ------------------------------------------------------------------ button
def test_bounce_is_ignored_and_a_tap_reports_on_release(logic):
    out = logic("btn 0 1", "btn 5 0", "btn 10 1", "btn 39 1", "btn 40 1", "btn 200 0", "btn 229 0", "btn 230 0")
    assert out == ["0", "0", "0", "0", "0", "0", "0", "1"]


def test_long_press_reports_once_and_no_tap_after(logic):
    out = logic("btn 0 1", "btn 30 1", "btn 599 1", "btn 600 1", "btn 900 1", "btn 1000 0", "btn 1030 0")
    assert out == ["0", "0", "0", "2", "0", "0", "0"]


# ------------------------------------------------------------------ USB descriptors
@pytest.fixture(scope="module")
def desc(tmp_path_factory):
    if not (TUSB / "tusb.h").exists():
        pytest.skip("TinyUSB headers missing: run firmware/glasses/scripts/fetch_tinyusb_headers.sh")
    exe = tmp_path_factory.mktemp("fw") / "usb_desc_host"
    subprocess.run([_cc(), "-std=c11", "-w", "-DCFG_TUSB_MCU=OPT_MCU_NONE", "-DCFG_TUSB_OS=OPT_OS_NONE",
                    f"-I{FW / 'main'}", f"-I{TUSB}", "-o", str(exe),
                    str(FW / "test" / "usb_desc_host.c"), str(FW / "main" / "usb_desc.c")], check=True)
    hexline, cdc_name = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.splitlines()
    raw = bytes.fromhex(hexline)
    items, i = [], 0
    while i < len(raw):
        n = raw[i]
        assert n >= 2 and i + n <= len(raw), f"bad descriptor at {i}"
        items.append(raw[i:i + n])
        i += n
    return raw, items, cdc_name


def test_config_descriptor_is_well_formed(desc):
    raw, items, _ = desc
    cfg = items[0]
    assert cfg[1] == 0x02 and struct.unpack_from("<H", cfg, 2)[0] == len(raw)
    itfs = {(d[2], d[3]) for d in items if d[1] == 0x04}
    assert cfg[4] == len({i for i, _ in itfs}) == 7


def test_functions_and_interfaces(desc):
    _, items, cdc_name = desc
    iads = [(d[2], d[3], d[4]) for d in items if d[1] == 0x0B]  # first interface, count, class
    assert iads == [(0, 2, 0x0E), (2, 3, 0x01), (5, 2, 0x02)]  # video, audio, CDC
    classes = {d[2]: d[5] for d in items if d[1] == 0x04 and d[3] == 0}
    assert classes == {0: 0x0E, 1: 0x0E, 2: 0x01, 3: 0x01, 4: 0x01, 5: 0x02, 6: 0x0A}
    assert cdc_name == "Asirive Glasses Safety"


def test_endpoints_fit_the_esp32s3(desc):
    _, items, _ = desc
    eps = [(d[2], d[3] & 3, struct.unpack_from("<H", d, 4)[0]) for d in items if d[1] == 0x05]
    addrs = {a for a, _, _ in eps}
    assert {a & 0x7F for a in addrs} <= set(range(1, 7))            # 6 endpoints besides EP0
    assert len({a for a in addrs if a & 0x80}) + 1 <= 5             # 5 IN FIFOs, EP0 included
    by = {a: (t, size) for a, t, size in eps}
    assert by[0x81] == (2, 64)                                      # video: bulk, full-speed max
    assert by[0x82] == (1, (16 + 1) * 2 * 2)                        # mic: iso, 16 kHz stereo 16-bit + 1 slack
    assert by[0x02] == (1, (16 + 1) * 2)                            # speaker: iso, mono
    assert by[0x84][0] == by[0x04][0] == 2 and by[0x83][0] == 3     # CDC data bulk, notify interrupt
    iso_bytes_per_ms = by[0x82][1] + by[0x02][1]
    assert iso_bytes_per_ms < 1023 * 0.9                            # full-speed periodic budget


def test_video_is_mjpeg_640x480(desc):
    _, items, _ = desc
    frames = [d for d in items if d[1] == 0x24 and d[2] == 0x07]   # VS_FRAME_MJPEG
    assert len(frames) == 1
    w, h = struct.unpack_from("<HH", frames[0], 5)
    interval = struct.unpack_from("<I", frames[0], 21)[0]
    assert (w, h) == (640, 480) and interval == 10_000_000 // 10
