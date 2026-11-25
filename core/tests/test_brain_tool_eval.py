import json
import numpy as np

from cortex_core.brain import tool_eval as E
from cortex_core.brain import tools

CALL = "<tool_call>\n<function=bus_arrivals>\n<parameter=service>\n858\n</parameter>\n</function>\n</tool_call>"


def test_cases_load_and_name_real_tools():
    names = {t.name for t in tools.load().tools}
    cases = E.load_cases()
    assert len(cases) >= 40
    assert all(c["expect"] is None or c["expect"] in names for c in cases)
    assert sum(c["expect"] is None for c in cases) >= 6
    assert sum(bool(c.get("sg")) for c in cases) >= 10


def test_score_right_tool_and_args():
    r = E.score({"q": "x", "expect": "bus_arrivals", "args": {"service": "858"}}, CALL)
    assert r["tool_ok"] and r["args_ok"]


def test_score_wrong_arg():
    r = E.score({"q": "x", "expect": "bus_arrivals", "args": {"service": "969"}}, CALL)
    assert r["tool_ok"] and not r["args_ok"]


def test_score_chitchat():
    assert E.score({"q": "hi", "expect": None}, None)["args_ok"]
    r = E.score({"q": "hi", "expect": None}, CALL)
    assert not r["tool_ok"] and r["got"] == "bus_arrivals"


def test_summarize_gate():
    rows = [E.score({"q": "a", "expect": "bus_arrivals", "args": {"service": "858"}}, CALL)] * 9 + \
           [E.score({"q": "b", "expect": None}, None)]
    s = E.summarize(rows)
    assert s["tool"] == 1.0 and s["args"] == 1.0 and s["chitchat_calls"] == 0 and s["pass"]
    rows.append(E.score({"q": "c", "expect": None}, CALL))
    assert not E.summarize(rows)["pass"]


def test_resample_and_split():
    t = np.arange(24000) / 24000
    x = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    y = E.resample_24k_to_16k(x)
    assert len(y) == 16000
    f = np.abs(np.fft.rfft(y)).argmax()
    assert abs(f - 440) <= 1
    clips = E.split_wav(np.arange(48000), [1000.0, 500.0])
    assert [len(c) for c in clips] == [24000, 12000]


def test_llama_server_backend_scores_structured_and_raw_calls():
    """run_server against a stand-in llama-server: OpenAI tool_calls and raw LFM XML in content both score."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append(req)
            q = req["messages"][-1]["content"]
            if "858" in q:
                msg = {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {
                    "name": "bus_arrivals", "arguments": json.dumps({"service": "858"})}}]}
            elif "Northpoint" in q:
                msg = {"role": "assistant", "content": "<tool_call>\n<function=search_places>\n<parameter=query>\n"
                       "Northpoint\n</parameter>\n</function>\n</tool_call>"}
            else:
                msg = {"role": "assistant", "content": "Hello!"}
            body = json.dumps({"choices": [{"message": msg}], "timings": {"prompt_ms": 5.0, "predicted_ms": 7.0}})
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cases = [{"q": "When is bus 858 coming?", "expect": "bus_arrivals", "args": {"service": "858"}},
                 {"q": "Take me to Northpoint", "expect": "search_places", "args": {"query": "northpoint"}},
                 {"q": "Good morning", "expect": None}]
        rep = E.run_server(cases, f"http://127.0.0.1:{srv.server_port}", model="stub")
    finally:
        srv.shutdown()
    s = rep["typed"]
    assert s["tool"] == 1.0 and s["args"] == 1.0 and s["chitchat_calls"] == 0 and s["pass"]
    assert rep["model"] == "stub" and rep["backend"].startswith("llama-server")
    req = seen[0]
    assert req["messages"][0] == {"role": "system", "content": E.prompt.SYSTEM}
    assert {t["function"]["name"] for t in req["tools"]} >= {"search_places", "bus_arrivals"}
    assert req["temperature"] == 0
