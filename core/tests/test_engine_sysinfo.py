from cortex_core.engine.sysinfo import (cpu_load, read_cpu_times, read_mem_used_mb, read_peak_rss_mb,
                                        read_power_w, read_temps_c)


def test_temps_read_millidegrees(tmp_path):
    z = tmp_path / "thermal_zone0"
    z.mkdir()
    (z / "type").write_text("cpu-0\n")
    (z / "temp").write_text("48500\n")
    assert read_temps_c(tmp_path) == {"cpu-0": 48.5}


def test_temps_skip_unreadable_zone(tmp_path):
    (tmp_path / "thermal_zone1").mkdir()  # no files
    assert read_temps_c(tmp_path) == {}


def test_temps_missing_root(tmp_path):
    assert read_temps_c(tmp_path / "nope") == {}


def test_peak_rss(tmp_path):
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "status").write_text("Name:\tx\nVmHWM:\t  2048 kB\n")
    assert read_peak_rss_mb(42, tmp_path) == 2.0


def test_peak_rss_missing_pid(tmp_path):
    assert read_peak_rss_mb(99, tmp_path) is None


def test_mem_used(tmp_path):
    (tmp_path / "meminfo").write_text("MemTotal: 8192 kB\nMemFree: 1 kB\nMemAvailable: 2048 kB\n")
    assert read_mem_used_mb(tmp_path) == 6.0


def test_mem_used_missing(tmp_path):
    assert read_mem_used_mb(tmp_path) is None


def test_cpu_times(tmp_path):
    (tmp_path / "stat").write_text("cpu  10 0 10 70 10 0 0 0\ncpu0 1 2 3 4 5 6 7 8\n")
    assert read_cpu_times(tmp_path) == (20, 100)


def test_cpu_times_missing(tmp_path):
    assert read_cpu_times(tmp_path) is None


def test_cpu_load():
    assert cpu_load((100, 200), (150, 300)) == 0.5
    assert cpu_load((100, 200), (100, 200)) == 0.0


def test_power_now(tmp_path):
    b = tmp_path / "battery"
    b.mkdir()
    (b / "power_now").write_text("4500000\n")
    assert read_power_w(tmp_path) == 4.5


def test_power_from_voltage_current(tmp_path):
    b = tmp_path / "usb"
    b.mkdir()
    (b / "voltage_now").write_text("5000000\n")
    (b / "current_now").write_text("1000000\n")
    assert read_power_w(tmp_path) == 5.0


def test_power_absent(tmp_path):
    assert read_power_w(tmp_path) is None
    assert read_power_w(tmp_path / "nope") is None
