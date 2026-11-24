"""The in-process NPU runtime: fixed-point (de)quantisation, QNN name matching, and the split chain."""
import pytest

np = pytest.importorskip("numpy")

from cortex_core.npu.qnn import FLOAT_32, UFIXED_8, UFIXED_16, from_fixed, match_names, to_fixed  # noqa: E402
from cortex_core.npu.split_encoder import SplitEncoder  # noqa: E402


def test_ufixed16_round_trip_within_half_step():
    scale, offset = 0.01, -30000  # float = (q + offset) * scale
    x = np.linspace(-300, 355, 1001, dtype=np.float32)
    q = to_fixed(x, UFIXED_16, scale, offset)
    assert q.dtype == np.uint16
    assert np.max(np.abs(from_fixed(q, UFIXED_16, scale, offset) - x)) <= scale / 2 + 1e-4


def test_to_fixed_clips_out_of_range():
    q = to_fixed(np.array([-1e9, 1e9], np.float32), UFIXED_8, 0.1, -128)
    assert q.dtype == np.uint8
    assert q.tolist() == [0, 255]


def test_float_tensors_pass_through():
    x = np.arange(6, dtype=np.float64).reshape(2, 3)
    q = to_fixed(x, FLOAT_32, 0.0, 0)
    assert q.dtype == np.float32
    np.testing.assert_array_equal(from_fixed(q, FLOAT_32, 0.0, 0), x)


def test_unsupported_dtype_raises():
    with pytest.raises(ValueError):
        to_fixed(np.zeros(2, np.float32), 0x0308, 1.0, 0)  # SFIXED_POINT_8


def test_match_names_maps_sanitised_qnn_names_to_onnx():
    onnx_names = ["/vision_encoder/layers.1/Add_2/output_0", "image_features"]
    got = match_names(["_vision_encoder_layers_1_Add_2_output_0", "image_features"], onnx_names)
    assert got == onnx_names


def test_match_names_raises_on_unknown():
    with pytest.raises(KeyError):
        match_names(["nope"], ["image_features"])


def _stage(fn, ins, outs):
    def run(feed):
        assert set(feed) == set(ins)
        return dict(zip(outs, fn(*[feed[i] for i in ins])))
    return ("npu", ins, run)


def test_split_encoder_chains_stages_and_returns_features():
    stages = [
        _stage(lambda pv: (pv * 2, pv + 1), ["pixel_values"], ["a", "res"]),
        ("cpu", ["a"], lambda f: {"b": f["a"] - 1}),
        _stage(lambda b, res: (b + res,), ["b", "res"], ["image_features"]),
    ]
    enc = SplitEncoder(stages)
    pv = np.ones((2, 3), np.float32)
    np.testing.assert_array_equal(enc.encode(pv), pv * 2 - 1 + pv + 1)
    assert [k for k in enc.last_ms] == ["npu0", "cpu1", "npu2"]
    assert all(v >= 0 for v in enc.last_ms.values())


def test_split_encoder_missing_tensor_names_the_stage():
    stages = [("npu", ["pixel_values"], lambda f: {"a": f["pixel_values"]}),
              ("cpu", ["zzz"], lambda f: {"image_features": f["zzz"]})]
    with pytest.raises(KeyError, match="cpu1.*zzz"):
        SplitEncoder(stages).encode(np.zeros(1, np.float32))
