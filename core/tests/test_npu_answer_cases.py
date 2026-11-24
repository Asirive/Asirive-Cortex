"""answer_cases: re-answer the test cases from saved NPU features with any model / thread setting."""
import json
import sys

import pytest

from cortex_core.npu.answer_cases import answer, main  # noqa: E402

FAKE = """import json, sys
print("answer for " + " ".join(sys.argv[1:]))
print(json.dumps({"ttft_s": 0.5, "decode_tps": 20.0, "n_out": 9}))
"""
FAILING = """import sys
sys.stderr.write("cortex-embd: feature has 220 tokens, the prompt expects 112\\n")
sys.exit(1)
"""


@pytest.fixture
def fake_embd(tmp_path):
    p = tmp_path / "fake_embd.py"
    p.write_text(FAKE)
    return str(p)


@pytest.fixture
def failing_embd(tmp_path):
    p = tmp_path / "failing_embd.py"
    p.write_text(FAILING)
    return str(p)


def test_answer_passes_threads_and_prefix(fake_embd, tmp_path):
    text, stats = answer(fake_embd, "m.gguf", "mm.gguf", tmp_path / "f.npu.f32", "Q?", threads=4,
                         prefix=[sys.executable])
    assert "-t 4" in text
    assert "--feat" in text and "answer" in text
    assert stats["ttft_s"] == 0.5


def test_answer_without_threads_passes_no_t(fake_embd, tmp_path):
    text, _ = answer(fake_embd, "m.gguf", "mm.gguf", tmp_path / "f.npu.f32", "Q?", prefix=[sys.executable])
    assert "-t" not in text.split()


def test_answer_reports_embd_failure(failing_embd, tmp_path):
    text, stats = answer(failing_embd, "m.gguf", "mm.gguf", tmp_path / "f.npu.f32", "Q?", prefix=[sys.executable])
    assert text.startswith("ERROR:")
    assert "the prompt expects 112" in text
    assert stats == {}


def _cases(tmp_path, names):
    d = tmp_path / "cases"
    d.mkdir()
    cases = [{"image": f"{n}.jpg", "question": "What is it?", "expect": ["answer"]} for n in names]
    (d / "cases.json").write_text(json.dumps(cases))
    return d / "cases.json"


def _args(fake_embd, cases, feat_dir, out):
    return ["--cases", str(cases), "--feat-dir", str(feat_dir), "--embd", fake_embd, "--model", "m.gguf",
            "--mmproj", "mm.gguf", "--out", str(out), "--threads", "4", "--prefix", sys.executable]


def test_cli_rows_and_match_count(fake_embd, tmp_path, capsys):
    cases = _cases(tmp_path, ["t001", "t002"])
    feats = tmp_path / "feats"
    feats.mkdir()
    for n in ("t001", "t002"):
        (feats / f"{n}.npu.f32").write_bytes(b"\0" * 8)
    out = tmp_path / "out.json"
    assert main(_args(fake_embd, cases, feats, out)) == 0
    rows = json.loads(out.read_text())
    assert [r["image"] for r in rows] == ["t001.jpg", "t002.jpg"]
    assert all(r["match"] and r["threads"] == 4 and r["taskset"] is None and r["model"] == "m.gguf" for r in rows)
    assert rows[0]["ttft_s"] == 0.5
    assert capsys.readouterr().out.strip().endswith("matched 2/2")


def test_cli_missing_feature_is_a_row_not_a_crash(fake_embd, tmp_path):
    cases = _cases(tmp_path, ["t009"])
    feats = tmp_path / "feats"
    feats.mkdir()
    out = tmp_path / "out.json"
    assert main(_args(fake_embd, cases, feats, out)) == 0
    row = json.loads(out.read_text())[0]
    assert row["answer"].startswith("ERROR: no feature")
    assert row["match"] is False
