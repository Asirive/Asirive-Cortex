import pytest

from cortex_core.engine import native
from cortex_core.engine.native_bench import row_from_events


def test_parse_event_types():
    for t in ("token", "done", "view", "error", "speech_start", "speech_end"):
        assert native.parse_event('{"type": "%s", "x": 1}' % t) == {"type": t, "x": 1}


@pytest.mark.parametrize(
    "ev, asking, where",
    [
        ({"type": "speech_start", "at_ms": 10.0}, False, "voice"),
        ({"type": "speech_end", "at_ms": 900.0}, True, "voice"),
        ({"type": "token", "text": "Hi", "voice": True}, True, "voice"),  # a spoken answer, even during an ask
        ({"type": "done", "voice": True}, False, "voice"),
        ({"type": "error", "what": "voice: decode failed"}, True, "voice"),
        ({"type": "error", "what": "audio: encode failed"}, False, "voice"),
        ({"type": "token", "text": "Hi"}, True, "answer"),
        ({"type": "done", "cancelled": True}, True, "answer"),  # the typed ask a barge-in cancelled
        ({"type": "error", "what": "ask: busy"}, True, "answer"),
        ({"type": "error", "what": "encode: boom"}, False, "views"),
        ({"type": "view", "frame_id": 1}, False, "views"),
    ],
)
def test_route_event(ev, asking, where):
    assert native.route_event(ev, asking) == where


def test_sound_events_are_known_and_routed():
    for t in ("sound_start", "sound_end"):
        assert native.parse_event('{"type": "%s"}' % t)["type"] == t
    # sound outlives the ask that made it: always the voice queue, which the session always drains
    assert native.route_event({"type": "sound_end", "voice": True}, False) == "voice"
    assert native.route_event({"type": "sound_start"}, True) == "voice"
    assert native.route_event({"type": "sound_end", "cut": True}, False) == "voice"
    assert native.route_event({"type": "error", "what": "speaker: plughw:9,9: no device"}, False) == "voice"


def test_pcm16k_float_accepts_int16_and_float():
    np = pytest.importorskip("numpy")
    f = native.pcm16k_float(np.array([0, 16384, -32768], dtype=np.int16))
    assert f.dtype == np.float32 and f.tolist() == [0.0, 0.5, -1.0]
    g = native.pcm16k_float([0.25, -0.5])
    assert g.dtype == np.float32 and g.tolist() == [0.25, -0.5]
    with pytest.raises(ValueError):
        native.pcm16k_float(np.zeros((2, 2), dtype=np.float32))


def test_parse_event_rejects_unknown_type():
    with pytest.raises(ValueError):
        native.parse_event('{"type": "nope"}')
    with pytest.raises(ValueError):
        native.parse_event("not json")
    with pytest.raises(ValueError):
        native.parse_event("[1, 2]")


def test_engine_missing_lib_is_clear_error():
    with pytest.raises(OSError, match="nope.so"):
        native.Engine("nope.so", {})


def test_bench_row_from_events():
    case = {"image": "test/t001.jpg", "question": "What is it?", "expect": ["shark"]}
    events = [
        {"type": "view", "frame_id": 1, "skipped": False, "cos": 0.0, "prep_ms": 2.5, "encode_ms": 282.0,
         "read_ms": 1120.0, "preempted": 0},
        {"type": "token", "text": "<think></think>A plush"},
        {"type": "token", "text": " Shark."},
        {"type": "done", "ttft_ms": 117.0, "total_ms": 700.0, "n_out": 4, "view_frame_id": 1, "view_age_ms": 3.0,
         "cancelled": False},
    ]
    row = row_from_events(case, events)
    assert row["answer"] == "A plush Shark."
    assert row["match"] is True
    assert row["ttft_ms"] == 117.0
    assert (row["prep_ms"], row["encode_ms"], row["read_ms"]) == (2.5, 282.0, 1120.0)
    assert row["refresh_ms"] == pytest.approx(2.5 + 282.0 + 1120.0)
    assert row["view_age_ms"] == 3.0 and row["view_frame_id"] == 1


def test_bench_row_speech_fields():
    case = {"image": "t.jpg", "question": "q", "expect": ["cup"]}
    row = row_from_events(case, [
        {"type": "view", "frame_id": 1},
        {"type": "token", "text": "A cup."},
        {"type": "sound_start", "at_ms": 1000.0},
        {"type": "done", "ttft_ms": 150.0, "frames": 40, "frame_ms": 64.0, "codec_ms": 19.0, "sound_ms": 3200.0},
        {"type": "sound_end", "at_ms": 4500.0, "sound_ms": 3200.0, "gaps": 0, "cut": False},
    ])
    assert row["match"] is True
    assert (row["frames"], row["frame_ms"], row["codec_ms"]) == (40, 64.0, 19.0)
    assert (row["sound_ms"], row["played_ms"], row["gaps"], row["cut"]) == (3200.0, 3200.0, 0, False)


def test_bench_row_error_is_no_match():
    case = {"image": "t.jpg", "question": "q", "expect": ["x"]}
    row = row_from_events(case, [{"type": "error", "what": "encode: boom"}])
    assert row["match"] is False and row["answer"].startswith("ERROR: encode: boom")


def test_tool_call_events_are_known_and_routed():
    assert native.parse_event('{"type": "tool_call", "text": "<tool_call>"}')["type"] == "tool_call"
    assert native.route_event({"type": "tool_call", "text": "x"}, True) == "answer"
    assert native.route_event({"type": "tool_call", "text": "x", "voice": True}, False) == "voice"
