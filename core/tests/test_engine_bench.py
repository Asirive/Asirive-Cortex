import json

import pytest

from cortex_core.engine.bench import Case, load_cases, run_bench, summarise, write_report
from cortex_core.engine.llama_client import RunResult


def ok(ttft, decode=20.0, ttfa=None, wall=1.0):
    return RunResult(True, None, 200, ttft, ttfa, "x", 300.0, decode, 10, wall)


def fail(status=None, error="connection refused"):
    return RunResult(False, error, status, None, None, "", None, None, None, 0.01)


def scripted(results):
    it = iter(results)
    calls = []

    def chat(base_url, messages, **kw):
        calls.append((base_url, messages, kw))
        return next(it)
    chat.calls = calls
    return chat


CASE = Case("text_short", "hello", None, None, False)


def test_warmup_discarded_and_medians():
    chat = scripted([ok(9.0), ok(0.4), ok(0.5), ok(0.6)])
    r = run_bench([CASE], "http://x", reps=3, warmup=1, chat=chat)
    s = r["cases"]["text_short"]
    assert s["n_ok"] == 3 and s["n_failed"] == 0
    assert s["ttft_s"]["median"] == 0.5
    assert s["ttft_s"]["p90"] == 0.6
    assert len(chat.calls) == 4


def test_failed_runs_excluded_from_medians():
    s = summarise([ok(0.4), ok(0.5), ok(0.6), fail(), fail()])
    assert (s["n_ok"], s["n_failed"]) == (3, 2)
    assert s["ttft_s"]["median"] == 0.5
    assert s["unsupported"] is None


def test_all_400_marks_unsupported():
    s = summarise([fail(400, "image input is not supported")] * 3)
    assert s["n_ok"] == 0
    assert "not supported" in s["unsupported"]
    assert s["ttft_s"] == {"median": None, "p90": None}


def test_over_target_flag():
    r = run_bench([CASE], "http://x", reps=2, warmup=0, chat=scripted([ok(1.4), ok(1.4)]))
    assert r["cases"]["text_short"]["over_target"] is True
    assert r["target_s"] == 1.0


def test_over_target_uses_first_audio_when_present():
    c = Case("speak", "hi", None, None, True)
    r = run_bench([c], "http://x", reps=1, warmup=0, chat=scripted([ok(0.3, ttfa=1.2)]))
    assert r["cases"]["speak"]["over_target"] is True
    chat = scripted([ok(0.3, ttfa=0.5)])
    r = run_bench([c], "http://x", reps=1, warmup=0, chat=chat)
    assert r["cases"]["speak"]["over_target"] is False
    assert chat.calls[0][2]["audio_out"] is True


def test_bench_continues_after_failed_case():
    c2 = Case("second", "hi", None, None, False)
    r = run_bench([CASE, c2], "http://x", reps=2, warmup=0, chat=scripted([fail(), fail(), ok(0.3), ok(0.3)]))
    assert r["cases"]["text_short"]["n_ok"] == 0
    assert r["cases"]["second"]["n_ok"] == 2
    assert r["cases"]["text_short"]["over_target"] is None


def test_sys_numbers_recorded(tmp_path):
    proc = tmp_path / "proc"
    (proc / "7").mkdir(parents=True)
    (proc / "7" / "status").write_text("VmHWM: 4096 kB\n")
    thermal = tmp_path / "thermal" / "thermal_zone0"
    thermal.mkdir(parents=True)
    (thermal / "type").write_text("cpu")
    (thermal / "temp").write_text("51000")
    r = run_bench([CASE], "http://x", reps=1, warmup=0, pid=7, chat=scripted([ok(0.2)]),
                  proc=proc, thermal=tmp_path / "thermal", power=tmp_path / "none")
    s = r["cases"]["text_short"]
    assert s["peak_rss_mb"] == 4.0 and s["max_temp_c"] == 51.0 and s["power_w"] is None


def test_load_cases(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    f = tmp_path / "cases.json"
    f.write_text(json.dumps([{"id": "img", "text": "t", "image": "a.jpg", "audio": None, "audio_out": False}]))
    [c] = load_cases(f, tmp_path)
    assert c.id == "img" and c.image == tmp_path / "a.jpg" and c.audio is None and c.audio_out is False


def test_load_cases_missing_media(tmp_path):
    f = tmp_path / "cases.json"
    f.write_text(json.dumps([{"id": "voice_q", "text": "t", "image": None, "audio": "q.wav", "audio_out": False}]))
    with pytest.raises(ValueError, match="voice_q"):
        load_cases(f, tmp_path)


def test_report_files(tmp_path):
    r = run_bench([CASE], "http://x", reps=1, warmup=0, chat=scripted([ok(0.2)]),
                  proc=tmp_path, thermal=tmp_path, power=tmp_path)
    meta = {"backend": "cpu", "llama_cpp": "b12000", "model": "m.gguf", "mmproj": "p.gguf", "quant": "Q4_K_M",
            "date": "2026-11-24", "host": "q8b"}
    oj, om, state = tmp_path / "o.json", tmp_path / "o.md", tmp_path / "state"
    write_report(r, meta, oj, om, state)
    md = om.read_text(encoding="utf-8")
    assert ("| case | ok/failed | first token s (med/p90) | first audio s (med/p90) | prefill tok/s | decode tok/s "
            "| prompt tok / cached | server peak RAM MB (so far) | max temp °C | power W (mean/max) | < 1 s? |") in md
    assert "n/a" in md and "text_short" in md
    data = json.loads(oj.read_text(encoding="utf-8"))
    assert data["meta"]["backend"] == "cpu" and "text_short" in data["cases"]
    assert json.loads((state / "bench" / "latest.json").read_text(encoding="utf-8")) == data


def test_example_cases_file_is_valid():
    from importlib.resources import files
    data = json.loads(files("cortex_core.engine").joinpath("cases.example.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in data] == ["text_short", "image_describe", "audio_question", "audio_image"]


# --- final-review fixes ---
import time

from cortex_core.engine.bench import main as bench_main


def test_audio_out_case_without_audio_has_no_verdict():
    c = Case("speak", "hi", None, None, True)
    r = run_bench([c], "http://x", reps=1, warmup=0, chat=scripted([ok(0.3)]))
    s = r["cases"]["speak"]
    assert s["over_target"] is None and s["no_audio"] is True


def test_cache_counts_summarised():
    a = ok(0.3)
    a.prompt_n, a.cache_n = 800, 0
    b = ok(0.3)
    b.prompt_n, b.cache_n = 800, 12
    s = summarise([a, b])
    assert s["prompt_n"] == 800 and s["cache_n_max"] == 12


def test_temperature_and_power_sampled_while_running(tmp_path):
    zone = tmp_path / "thermal" / "thermal_zone0"
    zone.mkdir(parents=True)
    (zone / "type").write_text("cpu")
    (zone / "temp").write_text("40000")
    supply = tmp_path / "power" / "bat"
    supply.mkdir(parents=True)
    (supply / "power_now").write_text("1000000")

    def chat(base_url, messages, **kw):  # hot and hungry only while "inferring"
        (zone / "temp").write_text("70000")
        (supply / "power_now").write_text("9000000")
        time.sleep(0.15)
        (zone / "temp").write_text("40000")
        (supply / "power_now").write_text("1000000")
        return ok(0.2)

    r = run_bench([CASE], "http://x", reps=1, warmup=0, chat=chat, proc=tmp_path, thermal=tmp_path / "thermal",
                  power=tmp_path / "power", sample_s=0.01)
    s = r["cases"]["text_short"]
    assert s["max_temp_c"] == 70.0
    assert s["power_max_w"] == 9.0 and s["power_w"] > 1.0


def test_state_dir_unwritable_still_writes_md(tmp_path, capsys):
    r = run_bench([CASE], "http://x", reps=1, warmup=0, chat=scripted([ok(0.2)]),
                  proc=tmp_path, thermal=tmp_path, power=tmp_path)
    blocker = tmp_path / "state"
    blocker.write_text("i am a file, not a directory")
    om = tmp_path / "o.md"
    write_report(r, {"backend": "cpu"}, tmp_path / "o.json", om, blocker)
    assert "text_short" in om.read_text(encoding="utf-8")
    assert "latest.json" in capsys.readouterr().err


def test_md_says_ram_is_server_peak_so_far(tmp_path):
    r = run_bench([CASE], "http://x", reps=1, warmup=0, chat=scripted([ok(0.2)]),
                  proc=tmp_path, thermal=tmp_path, power=tmp_path)
    om = tmp_path / "o.md"
    write_report(r, {"backend": "cpu"}, tmp_path / "o.json", om, None)
    assert "server peak RAM MB (so far)" in om.read_text(encoding="utf-8")


def test_interrupt_keeps_finished_cases(tmp_path):
    f = tmp_path / "cases.json"
    f.write_text(json.dumps([{"id": "first", "text": "a", "image": None, "audio": None},
                             {"id": "second", "text": "b", "image": None, "audio": None}]))
    calls = []

    def chat(base_url, messages, **kw):
        calls.append(1)
        if len(calls) > 1:
            raise KeyboardInterrupt
        return ok(0.2)

    oj, om = tmp_path / "o.json", tmp_path / "o.md"
    rc = bench_main(["--cases", str(f), "--media", str(tmp_path), "--backend", "cpu", "--llama-tag", "t",
                     "--model", "m", "--mmproj", "p", "--reps", "1", "--warmup", "0",
                     "--out-json", str(oj), "--out-md", str(om)], chat=chat)
    assert rc == 130
    data = json.loads(oj.read_text(encoding="utf-8"))
    assert list(data["cases"]) == ["first"] and data["meta"]["partial"] is True
