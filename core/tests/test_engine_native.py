import pytest

from cortex_core.engine import native
from cortex_core.engine.native_bench import row_from_events


def test_parse_event_types():
    for t in ("token", "done", "view", "error"):
        assert native.parse_event('{"type": "%s", "x": 1}' % t) == {"type": t, "x": 1}


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


def test_bench_row_error_is_no_match():
    case = {"image": "t.jpg", "question": "q", "expect": ["x"]}
    row = row_from_events(case, [{"type": "error", "what": "encode: boom"}])
    assert row["match"] is False and row["answer"].startswith("ERROR: encode: boom")
