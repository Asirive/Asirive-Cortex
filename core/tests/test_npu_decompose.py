"""decompose() must give the same numbers as onnxruntime's own contrib ops, using only standard ONNX ops."""
import pytest

np = pytest.importorskip("numpy")
onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")
from onnx import TensorProto, helper, numpy_helper  # noqa: E402

from cortex_core.npu.decompose import CONTRIB_OPS, decompose, fix_input_shape  # noqa: E402

F = TensorProto.FLOAT
RNG = np.random.default_rng(0)


def _model(nodes, inputs, outputs, inits=()):
    g = helper.make_graph(nodes, "t", inputs, outputs, list(inits))
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 21), helper.make_opsetid("com.microsoft", 1)])
    m.ir_version = 10
    return m


def _run(m, feed):
    s = ort.InferenceSession(m.SerializeToString(), providers=["CPUExecutionProvider"])
    return s.run(None, feed)[0]


def _assert_same(m, feed, atol=1e-5):
    want = _run(m, feed)
    d = decompose(m)
    left = {(n.domain, n.op_type) for n in d.graph.node} & CONTRIB_OPS
    assert not left, left
    onnx.checker.check_model(d)
    np.testing.assert_allclose(_run(d, feed), want, atol=atol, rtol=1e-4)


def test_rms_norm_matches_ort():
    x = RNG.standard_normal((1, 6, 4, 8)).astype(np.float32)
    w = numpy_helper.from_array(RNG.standard_normal(8).astype(np.float32), "w")
    n = helper.make_node("SimplifiedLayerNormalization", ["x", "w"], ["y"], epsilon=1e-5)
    m = _model([n], [helper.make_tensor_value_info("x", F, x.shape)],
               [helper.make_tensor_value_info("y", F, x.shape)], [w])
    _assert_same(m, {"x": x})


def test_rotary_matches_ort():
    s, heads, hd = 6, 2, 8
    x = RNG.standard_normal((1, s, heads * hd)).astype(np.float32)
    ang = RNG.standard_normal((s, hd // 2)).astype(np.float32)
    pos = np.arange(s, dtype=np.int64)[None][:, ::-1].copy()  # not identity: proves Gather by position
    n = helper.make_node("RotaryEmbedding", ["x", "pos", "cos", "sin"], ["y"], domain="com.microsoft",
                         interleaved=0, num_heads=0, rotary_embedding_dim=0)
    m = _model([n], [helper.make_tensor_value_info("x", F, x.shape),
                     helper.make_tensor_value_info("pos", TensorProto.INT64, pos.shape),
                     helper.make_tensor_value_info("cos", F, ang.shape),
                     helper.make_tensor_value_info("sin", F, ang.shape)],
               [helper.make_tensor_value_info("y", F, x.shape)])
    _assert_same(m, {"x": x, "pos": pos, "cos": np.cos(ang), "sin": np.sin(ang)})


def test_mha_matches_ort():
    s, heads, hd = 7, 4, 8
    q, k, v = (RNG.standard_normal((1, s, heads * hd)).astype(np.float32) for _ in range(3))
    n = helper.make_node("MultiHeadAttention", ["q", "k", "v"], ["y"], domain="com.microsoft",
                         num_heads=heads, scale=0.3)
    m = _model([n], [helper.make_tensor_value_info(i, F, q.shape) for i in "qkv"],
               [helper.make_tensor_value_info("y", F, q.shape)])
    _assert_same(m, {"q": q, "k": k, "v": v})


def test_mha_default_scale_is_inverse_sqrt_head():
    s, heads, hd = 5, 2, 16
    q, k, v = (RNG.standard_normal((1, s, heads * hd)).astype(np.float32) for _ in range(3))
    n = helper.make_node("MultiHeadAttention", ["q", "k", "v"], ["y"], domain="com.microsoft", num_heads=heads)
    m = _model([n], [helper.make_tensor_value_info(i, F, q.shape) for i in "qkv"],
               [helper.make_tensor_value_info("y", F, q.shape)])
    _assert_same(m, {"q": q, "k": k, "v": v})


def test_unknown_contrib_op_raises():
    n = helper.make_node("FusedGemm", ["x", "x"], ["y"], domain="com.microsoft")
    m = _model([n], [helper.make_tensor_value_info("x", F, (2, 2))], [helper.make_tensor_value_info("y", F, (2, 2))])
    with pytest.raises(NotImplementedError):
        decompose(m)


def test_fix_input_shape():
    n = helper.make_node("Identity", ["x"], ["y"])
    x = helper.make_tensor_value_info("x", F, ["a", "b", 3])
    m = _model([n], [x], [helper.make_tensor_value_info("y", F, (2, 2))])
    fixed = fix_input_shape(m, "x", (11, 20, 3))
    dims = [d.dim_value for d in fixed.graph.input[0].type.tensor_type.shape.dim]
    assert dims == [11, 20, 3]
