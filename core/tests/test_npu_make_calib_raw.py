import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

from cortex_core.npu.make_calib_raw import make_calib_raw  # noqa: E402
from cortex_core.npu.vision_prep import INPUT_H, INPUT_W, prepare  # noqa: E402

RAW_BYTES = (INPUT_H // 32) * (INPUT_W // 32) * 2 * 2 * 1536 * 4


def _frames(d, n):
    d.mkdir()
    rng = np.random.default_rng(0)
    for i in range(n):
        Image.fromarray(rng.integers(0, 256, (360, 640, 3), dtype=np.uint8)).save(d / f"c{i:03d}.jpg", quality=95)


def test_make_calib_raw(tmp_path):
    _frames(tmp_path / "calib", 2)
    lst = make_calib_raw(tmp_path / "calib", tmp_path / "raw")
    lines = lst.read_text().splitlines()
    assert len(lines) == 2
    raws = sorted((tmp_path / "raw").glob("*.raw"))
    assert len(raws) == 2
    assert all(r.stat().st_size == RAW_BYTES for r in raws)


def test_raw_is_prepared_frame(tmp_path):
    _frames(tmp_path / "calib", 1)
    make_calib_raw(tmp_path / "calib", tmp_path / "raw")
    raw = np.fromfile(next((tmp_path / "raw").glob("*.raw")), dtype="<f4")
    want = prepare(np.asarray(Image.open(tmp_path / "calib" / "c000.jpg").convert("RGB")))
    assert np.array_equal(raw, want.ravel())


def test_list_lines_name_the_input_and_absolute_files(tmp_path):
    _frames(tmp_path / "calib", 1)
    line = make_calib_raw(tmp_path / "calib", tmp_path / "raw").read_text().strip()
    name, path = line.split(":=")
    assert name == "pixel_values"
    assert path.endswith(".raw") and (tmp_path / "raw").resolve().as_posix() in path


def test_empty_dir_raises(tmp_path):
    (tmp_path / "calib").mkdir()
    with pytest.raises(ValueError):
        make_calib_raw(tmp_path / "calib", tmp_path / "raw")
