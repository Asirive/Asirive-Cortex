from cortex_core.tui.live_state import LiveState


def run(s, *evs):
    for e in evs:
        s.apply(e)
    return s


def test_spoken_question_and_streamed_answer():
    s = run(LiveState(),
            {"type": "speech_start", "at_ms": 100.0},
            {"type": "speech_end", "at_ms": 3600.0, "speech_ms": 3500.0},
            {"type": "token", "text": "<think></think>It is", "voice": True},
            {"type": "token", "text": " a shark.", "voice": True},
            {"type": "done", "voice": True, "end_to_first_ms": 150.0, "wait_ms": 60.0, "ttft_ms": 70.0,
             "n_out": 4, "cancelled": False, "stop": "eog", "view_frame_id": 7, "view_age_ms": 900.0})
    assert [t.who for t in s.turns] == ["you", "cortex"]
    assert s.turns[0].text == "(spoke 3.5 s)"
    assert s.turns[1].text == "It is a shark."  # the empty think block is not shown
    assert s.turns[1].done and s.turns[1].note == ""
    assert s.speaking is False
    assert s.last["end_to_first_ms"] == 150.0 and s.last["wait_ms"] == 60.0
    assert s.last["view_frame_id"] == 7


def test_speaking_flag_and_placeholder_while_talking():
    s = run(LiveState(), {"type": "speech_start", "at_ms": 0.0})
    assert s.speaking and s.turns[-1].who == "you" and s.turns[-1].text == "(speaking…)"


def test_barge_in_marks_the_cut_answer():
    s = run(LiveState(),
            {"type": "token", "text": "Long answer", "voice": True},
            {"type": "speech_start", "at_ms": 0.0},
            {"type": "done", "voice": True, "cancelled": True, "stop": "cancel", "n_out": 2})
    cortex = [t for t in s.turns if t.who == "cortex"]
    assert cortex[0].text == "Long answer" and cortex[0].note == "cut off"


def test_typed_question():
    s = LiveState()
    s.typed("What is this?")
    run(s, {"type": "token", "text": "A cup."},
        {"type": "done", "ttft_ms": 110.0, "n_out": 3, "cancelled": False, "stop": "eog"})
    assert [(t.who, t.text) for t in s.turns] == [("you", "What is this?"), ("cortex", "A cup.")]
    assert s.last["ttft_ms"] == 110.0


def test_view_event_and_skip():
    s = run(LiveState(), {"type": "view", "frame_id": 3, "prep_ms": 2.0, "encode_ms": 280.0, "read_ms": 1100.0,
                          "skipped": False})
    assert s.view["frame_id"] == 3 and s.view["refresh_ms"] == 1382.0
    run(s, {"type": "view", "frame_id": 4, "prep_ms": 2.0, "encode_ms": 280.0, "skipped": True, "cos": 0.99})
    assert s.view["frame_id"] == 3 and s.views_skipped == 1  # the LM still holds frame 3


def test_errors_go_to_log_and_turns_are_capped():
    s = run(LiveState(max_turns=4), {"type": "error", "what": "voice: boom"})
    assert s.log[-1] == "error: voice: boom"
    for i in range(6):
        s.typed(f"q{i}")
    assert len(s.turns) == 4 and s.turns[-1].text == "q5"


def test_think_block_split_over_tokens_is_never_shown():
    s = LiveState()
    s.typed("what is this")
    s.apply({"type": "token", "text": "<think>"})
    assert s.turns[-1].text == ""  # an open block shows nothing while it streams
    s.apply({"type": "token", "text": "\n\n"})
    assert s.turns[-1].text == ""
    s.apply({"type": "token", "text": "</think>\n\nA cup"})
    s.apply({"type": "token", "text": "."})
    assert s.turns[-1].text == "A cup."
