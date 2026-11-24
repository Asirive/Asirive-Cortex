"""open_npu() must fail fast and say what is missing, instead of a ctypes/QNN stack trace."""
import time

import pytest

pytest.importorskip("numpy")

from cortex_core.npu.run_npu import open_npu  # noqa: E402


def _split_dir(tmp_path):
    d = tmp_path / "split"
    d.mkdir()
    (d / "io.json").write_text("{}")
    (d / "npu0.bin").write_bytes(b"x")
    return d


def test_missing_context_is_clear_error(tmp_path):
    t = time.monotonic()
    run = open_npu(tmp_path / "nope", tmp_path / "libcortex_npu.so", tmp_path)
    assert time.monotonic() - t < 5
    assert not run.ok
    assert "nope" in run.error


def test_missing_shim_is_clear_error(tmp_path):
    run = open_npu(_split_dir(tmp_path), tmp_path / "libcortex_npu.so", tmp_path)
    assert not run.ok
    assert "libcortex_npu.so" in run.error and "build.sh" in run.error


def test_missing_runtime_is_clear_error(tmp_path):
    shim = tmp_path / "libcortex_npu.so"
    shim.write_bytes(b"x")
    run = open_npu(_split_dir(tmp_path), shim, tmp_path / "qnnlib")
    assert not run.ok
    assert "libQnnHtp.so" in run.error and "qcom-qnn-sdk-v68" in run.error


# --- final review fixes ---
import json  # noqa: E402
import sys  # noqa: E402

np = pytest.importorskip("numpy")

from cortex_core.npu.run_npu import probe_npu, save_npu_feat, soc_state  # noqa: E402


def test_npu_features_always_record_the_stand_in_size_for_220_tokens(tmp_path):
    # a portrait or 1080p frame is fitted into the fixed 220-token canvas, so cortex-embd must be told the
    # canvas size, not the original photo size (else llama.cpp expects a different token count)
    p = tmp_path / "f.f32"
    save_npu_feat(p, np.zeros((220, 2048), np.float32))
    meta = json.loads((tmp_path / "f.f32.json").read_text())
    assert (meta["image_w"], meta["image_h"], meta["n_tokens"]) == (640, 360, 220)


def _sysfs(tmp_path):
    t = tmp_path / "sys/class/thermal"
    for i, (typ, temp) in enumerate([("cpu-0-0-thermal", "61000"), ("pmc8280c-thermal", "88000"),
                                     ("cpu-1-2-thermal", "64500"), ("broken-thermal", None)]):
        z = t / f"thermal_zone{i}"
        z.mkdir(parents=True)
        (z / "type").write_text(typ + "\n")
        if temp is not None:
            (z / "temp").write_text(temp + "\n")
    for c, f in enumerate(["2016000", "2995200"]):
        d = tmp_path / f"sys/devices/system/cpu/cpu{c}/cpufreq"
        d.mkdir(parents=True)
        (d / "scaling_cur_freq").write_text(f)
    return tmp_path


def test_soc_state_uses_cpu_zones_only_and_survives_unreadable_zones(tmp_path):
    s = soc_state(_sysfs(tmp_path))
    assert s["cpu_temp_c"] == 64.5  # CPU zones only
    assert s["pmic_temp_c"] == 88.0  # power chip reported apart: it ran 88-92 C under load, trips at 95 C
    assert s["cpu_mhz_max"] == 2995 and s["cpu_mhz_min"] == 2016


def test_probe_reports_a_hang_within_the_timeout():
    t = time.monotonic()
    r = probe_npu([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert time.monotonic() - t < 5
    assert not r.ok and "timed out" in r.error


def test_probe_reports_a_crash_with_its_exit_code():
    r = probe_npu([sys.executable, "-c", "import sys; print('boom'); sys.exit(-11 & 0xff)"], timeout=10)
    assert not r.ok and "245" in r.error and "boom" in r.error
