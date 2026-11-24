import numpy as np
import pytest

pytest.importorskip("PIL")  # dev-only dependency of the npu tools

from cortex_core.npu.vision_prep import INPUT_H, INPUT_W, MEAN, STD, fit_box, prepare  # noqa: E402

SHAPE = (INPUT_H // 32, INPUT_W // 32, 2, 2, 1536)


def frame(w, h, value=128):
    return np.full((h, w, 3), value, dtype=np.uint8)


def test_contract_constants():
    assert (INPUT_W, INPUT_H) == (640, 352)
    assert MEAN == STD == (0.5, 0.5, 0.5)


def test_prepare_shape_and_dtype():
    out = prepare(frame(640, 360))
    assert out.shape == SHAPE == (11, 20, 2, 2, 1536)
    assert out.dtype == np.float32


def test_prepare_normalises():
    out = prepare(frame(640, 360, 128))
    assert np.allclose(out, (128 / 255 - 0.5) / 0.5, atol=1e-6)


@pytest.mark.parametrize("w,h", [(1920, 1080), (480, 640), (100, 100), (640, 352), (4000, 300)])
def test_prepare_other_sizes(w, h):
    assert prepare(frame(w, h)).shape == SHAPE


def test_169_frames_fill_the_input_like_the_model_processor():
    assert fit_box(640, 360) == (640, 352)    # rounded to the 32 px grid, as the model's own processor does
    assert fit_box(1920, 1080) == (640, 352)


def test_portrait_is_padded_not_stretched():
    w, h = fit_box(480, 640)
    assert w <= INPUT_W and h <= INPUT_H
    assert abs((w / h) - 0.75) / 0.75 < 0.02


def test_padding_is_neutral_grey():
    out = prepare(frame(480, 640, 255))  # white portrait -> white middle, neutral (0.0) padding at the sides
    assert np.isclose(out[0, 0].min(), 0.0, atol=1e-6) or np.isclose(out[0, -1].min(), 0.0, atol=1e-6)
    assert np.isclose(out.max(), 1.0, atol=1e-6)


def test_patch_layout_matches_model_processor():
    # each pixel encodes its own position; check one value lands at [block, merge, channel, time, y, x]
    h, w = INPUT_H, INPUT_W
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[37, 70] = (255, 0, 0)  # block (1, 2), merge (0, 0)? 37 // 16 = 2 -> block 1, row-in-block 0; 70 // 16 = 4 -> block 2, col 0
    out = prepare(img)
    v = out[1, 2, 0, 0]  # 1536 = channel(3) x time(2) x 16 x 16
    y, x = 37 % 16, 70 % 16
    red_t0 = v[0 * 512 + 0 * 256 + y * 16 + x]
    red_t1 = v[0 * 512 + 1 * 256 + y * 16 + x]
    green = v[1 * 512 + 0 * 256 + y * 16 + x]
    assert red_t0 == red_t1 == pytest.approx(1.0) and green == pytest.approx(-1.0)
