"""split_stages() cuts a graph into NPU segments and CPU islands; chaining the pieces must equal the whole."""
import pytest

np = pytest.importorskip("numpy")
onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")
from onnx import TensorProto, helper, numpy_helper  # noqa: E402

from cortex_core.npu.split import run_stages, split_stages  # noqa: E402

F = TensorProto.FLOAT


def _model():
    # x -> a=Mul(x,w) -> [cpu: b=Relu(a), c=Neg(b)] -> d=Add(c, a)  (a is a residual crossing the island)
    #   -> [cpu: e=Sigmoid(d)] -> y=Mul(e, a)
    w = numpy_helper.from_array(np.full((2, 3), 1.5, np.float32), "w")
    nodes = [
        helper.make_node("Mul", ["x", "w"], ["a"], name="pre/mul"),
        helper.make_node("Relu", ["a"], ["b"], name="L1/attn/relu"),
        helper.make_node("Neg", ["b"], ["c"], name="L1/attn/neg"),
        helper.make_node("Add", ["c", "a"], ["d"], name="mid/add"),
        helper.make_node("Sigmoid", ["d"], ["e"], name="L2/attn/sig"),
        helper.make_node("Mul", ["e", "a"], ["y"], name="post/mul"),
    ]
    g = helper.make_graph(nodes, "t", [helper.make_tensor_value_info("x", F, (2, 3))],
                          [helper.make_tensor_value_info("y", F, (2, 3))], [w])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 21)])
    m.ir_version = 10
    return m


def _ort_runner(stage):
    s = ort.InferenceSession(stage.model.SerializeToString(), providers=["CPUExecutionProvider"])
    return lambda feed: dict(zip(stage.outputs, s.run(stage.outputs, feed)))


def test_stage_kinds_and_order():
    st = split_stages(_model(), ["L1/attn/", "L2/attn/"])
    assert [s.kind for s in st] == ["npu", "cpu", "npu", "cpu", "npu"]


def test_residual_crosses_cpu_island():
    st = split_stages(_model(), ["L1/attn/", "L2/attn/"])
    assert set(st[0].outputs) == {"a"}
    assert set(st[2].inputs) == {"c", "a"}
    assert set(st[4].inputs) == {"e", "a"}
    assert st[4].outputs == ["y"]


def test_each_stage_is_a_valid_model():
    for s in split_stages(_model(), ["L1/attn/", "L2/attn/"]):
        onnx.checker.check_model(s.model)
        assert [i.name for i in s.model.graph.input] == s.inputs


def test_chain_equals_whole_model():
    m = _model()
    x = np.random.default_rng(0).standard_normal((2, 3)).astype(np.float32)
    want = ort.InferenceSession(m.SerializeToString(), providers=["CPUExecutionProvider"]).run(None, {"x": x})[0]
    st = split_stages(m, ["L1/attn/", "L2/attn/"])
    got = run_stages(st, {"x": x}, [_ort_runner(s) for s in st])
    np.testing.assert_allclose(got["y"], want, rtol=1e-6)


def test_unmatched_prefix_raises():
    with pytest.raises(ValueError):
        split_stages(_model(), ["nope/"])
