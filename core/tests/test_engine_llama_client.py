import base64
import io
import json
import urllib.error

import pytest

from cortex_core.engine.llama_client import stream_chat, user_message


class Clock:
    """Advances 0.1 s on every call."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.1
        return round(self.t, 6)


class Resp:
    def __init__(self, lines, status=200):
        self.status = status
        self._lines = [(l + "\n").encode() for l in lines]

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def sse(obj):
    return "data: " + json.dumps(obj)


def delta(**d):
    return {"choices": [{"delta": d}]}


TIMINGS = {"choices": [{"delta": {}}], "timings": {"prompt_per_second": 310.0, "predicted_per_second": 21.5,
                                                    "predicted_n": 2}}


def opener(lines, seen=None):
    def open_url(req, timeout=None):
        if seen is not None:
            seen.append(req)
        return Resp(lines)
    return open_url


def test_measures_first_token_and_timings():
    lines = [sse(delta(role="assistant")), "", sse(delta(content="Hi")), sse(delta(content=" there")),
             sse(TIMINGS), "data: [DONE]"]
    r = stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=opener(lines))
    # clock: start=0.1, role chunk 0.2, "Hi" chunk 0.3 -> ttft 0.2
    assert r.ok and r.text == "Hi there"
    assert r.ttft_s == pytest.approx(0.2)
    assert (r.prefill_tps, r.decode_tps, r.tokens_out) == (310.0, 21.5, 2)
    assert r.ttfa_s is None
    assert r.wall_s > 0


def test_first_audio_chunk_sets_ttfa():
    lines = [sse(delta(audio={"data": "AAAA"})), sse(delta(content="Hi")), "data: [DONE]"]
    r = stream_chat("http://x", [user_message("q")], audio_out=True, clock=Clock(), open_url=opener(lines))
    assert r.ttfa_s == pytest.approx(0.1)
    assert r.ttft_s == pytest.approx(0.2)


def test_malformed_line_and_missing_timings():
    lines = [sse(delta(content="Hi")), "data: {not json", "data: [DONE]"]
    r = stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=opener(lines))
    assert r.ok and r.text == "Hi"
    assert r.decode_tps is None and r.prefill_tps is None and r.tokens_out is None


def test_http_400_is_recorded_not_raised():
    def open_url(req, timeout=None):
        raise urllib.error.HTTPError("http://x", 400, "Bad Request", {},
                                     io.BytesIO(b'{"error":"image input is not supported"}'))
    r = stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=open_url)
    assert not r.ok and r.status == 400 and "not supported" in r.error


def test_connection_refused_is_recorded():
    def open_url(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))
    r = stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=open_url)
    assert not r.ok and r.status is None and r.error


def test_request_body_has_modalities_only_when_audio_out():
    seen = []
    stream_chat("http://x/", [user_message("q")], max_tokens=7, clock=Clock(), open_url=opener(["data: [DONE]"], seen))
    stream_chat("http://x", [user_message("q")], audio_out=True, clock=Clock(), open_url=opener(["data: [DONE]"], seen))
    a, b = (json.loads(r.data) for r in seen)
    assert seen[0].full_url == "http://x/v1/chat/completions"
    assert a["stream"] is True and a["max_tokens"] == 7 and "modalities" not in a
    assert b["modalities"] == ["text", "audio"]


def test_user_message_parts(tmp_path):
    img, wav = tmp_path / "a.jpg", tmp_path / "b.wav"
    img.write_bytes(b"\xff\xd8jpeg")
    wav.write_bytes(b"RIFFwav")
    m = user_message("what is this", image=img, audio=wav)
    assert m["role"] == "user"
    kinds = [p["type"] for p in m["content"]]
    assert kinds == ["image_url", "input_audio", "text"]
    assert m["content"][0]["image_url"]["url"] == "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8jpeg").decode()
    assert m["content"][1]["input_audio"] == {"data": base64.b64encode(b"RIFFwav").decode(), "format": "wav"}
    assert m["content"][2]["text"] == "what is this"


# --- final-review fixes ---

def test_body_disables_prompt_cache():
    seen = []
    stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=opener(["data: [DONE]"], seen))
    assert json.loads(seen[0].data)["cache_prompt"] is False


def test_records_prompt_and_cache_counts():
    t = {"choices": [{"delta": {}}], "timings": {"prompt_n": 812, "cache_n": 0, "predicted_n": 3}}
    r = stream_chat("http://x", [user_message("q")], clock=Clock(),
                    open_url=opener([sse(delta(content="Hi")), sse(t), "data: [DONE]"]))
    assert (r.prompt_n, r.cache_n) == (812, 0)


def test_non_dict_chunks_are_skipped():
    lines = ["data: 5", "data: []", sse({"choices": ["x"]}), sse(delta(content="Hi")), "data: [DONE]"]
    r = stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=opener(lines))
    assert r.ok and r.text == "Hi"


def test_non_str_content_is_ignored():
    lines = [sse(delta(content=["odd"])), sse(delta(content="Hi")), "data: [DONE]"]
    r = stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=opener(lines))
    assert r.ok and r.text == "Hi"


def test_error_inside_stream_marks_failed():
    lines = [sse(delta(content="Hi")), sse({"error": {"message": "context overflow"}}), "data: [DONE]"]
    r = stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=opener(lines))
    assert not r.ok and "context overflow" in r.error


def test_stream_with_no_output_is_failed():
    r = stream_chat("http://x", [user_message("q")], clock=Clock(), open_url=opener(["data: [DONE]"]))
    assert not r.ok and r.error == "no output"
