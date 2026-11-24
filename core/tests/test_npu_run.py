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
