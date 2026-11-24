import json

import pytest

np = pytest.importorskip("numpy")

from cortex_core.npu.compare import cosine_rows, load_feat, save_feat  # noqa: E402


def _rand(n=220, d=64, seed=0):
    return np.random.default_rng(seed).standard_normal((n, d)).astype(np.float32)


def test_cosine_identical():
    a = _rand()
    mean, mn = cosine_rows(a, a.copy())
    assert mean == pytest.approx(1.0, abs=1e-6)
    assert mn == pytest.approx(1.0, abs=1e-6)


def test_cosine_catches_shuffled_tokens():
    a = _rand()
    b = a[np.random.default_rng(1).permutation(len(a))]
    _, mn = cosine_rows(a, b)
    assert mn < 0.9


def test_cosine_shape_mismatch_raises():
    with pytest.raises(ValueError):
        cosine_rows(_rand(220), _rand(219))


def test_feat_roundtrip(tmp_path):
    a = _rand(220, 2048)
    p = tmp_path / "x.f32"
    save_feat(p, a)
    meta = json.loads((tmp_path / "x.f32.json").read_text())
    assert meta["n_tokens"] == 220 and meta["n_embd"] == 2048
    b = load_feat(p)
    assert b.shape == (220, 2048) and b.dtype == np.float32
    assert np.array_equal(a, b)


def test_load_reads_task2_format(tmp_path):
    # the C++ tool writes extra keys (encode_ms, image_w, image_h); load must accept them
    a = _rand(4, 8)
    p = tmp_path / "c.f32"
    p.write_bytes(a.tobytes())
    (tmp_path / "c.f32.json").write_text('{"n_tokens": 4, "n_embd": 8, "encode_ms": 1.0, "image_w": 640, "image_h": 360}\n')
    assert np.array_equal(load_feat(p), a)


def test_load_rejects_truncated_file(tmp_path):
    p = tmp_path / "t.f32"
    p.write_bytes(_rand(4, 8).tobytes()[:-4])
    (tmp_path / "t.f32.json").write_text('{"n_tokens": 4, "n_embd": 8}')
    with pytest.raises(ValueError):
        load_feat(p)
