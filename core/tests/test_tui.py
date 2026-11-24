import asyncio
import json

import pytest

pytest.importorskip("textual")  # dev-only dependency: skip, never break the core suite

from textual.widgets import Static  # noqa: E402

from cortex_core.tui.__main__ import main  # noqa: E402
from cortex_core.tui.app import CortexTUI, _engine, _npu  # noqa: E402
from cortex_core.tui.state import Collector, Snapshot, fmt  # noqa: E402


def collector(tmp_path):
    return Collector(tmp_path, tmp_path, tmp_path, tmp_path)


def baseline():
    case = {"n_ok": 5, "n_failed": 0, "ttft_s": {"median": 0.42, "p90": 0.5}, "ttfa_s": {"median": None, "p90": None},
            "prefill_tps": {"median": 300.0, "p90": 310.0}, "decode_tps": {"median": 21.7, "p90": 22.0},
            "wall_s": {"median": 1.0, "p90": 1.1}, "unsupported": None, "peak_rss_mb": 2100.0,
            "max_temp_c": 55.0, "power_w": None, "over_target": False}
    return {"meta": {"backend": "cpu", "model": "lfm3-omni-q4.gguf"}, "cases": {"image_describe": case},
            "target_s": 1.0}


def write(tmp_path, name, text):
    (tmp_path / "bench").mkdir(exist_ok=True)
    (tmp_path / "bench" / name).write_text(text, encoding="utf-8")


def test_refuses_outside_dev_build(capsys):
    assert main([], env={}) == 2
    assert capsys.readouterr().out.strip() == \
        "The terminal UI is for developer builds only (set CORTEX_DEV_BUILD=1)."


def test_snapshot_without_files(tmp_path):
    s = collector(tmp_path).snapshot()
    assert s.baseline is None and s.npu is None and s.cpu_load is None and s.temps_c == {}


def test_snapshot_reads_latest_and_npu(tmp_path):
    write(tmp_path, "latest.json", json.dumps(baseline()))
    write(tmp_path, "npu.json", json.dumps({"reachable": False, "notes": ["no fastrpc"]}))
    s = collector(tmp_path).snapshot()
    assert s.baseline["meta"]["backend"] == "cpu" and s.npu["reachable"] is False


def test_bad_json_is_none(tmp_path):
    write(tmp_path, "latest.json", "{")
    assert collector(tmp_path).snapshot().baseline is None


def test_cpu_load_from_second_snapshot(tmp_path):
    c = collector(tmp_path)
    (tmp_path / "stat").write_text("cpu  10 0 10 70 10 0 0 0\n")
    assert c.snapshot().cpu_load is None
    (tmp_path / "stat").write_text("cpu  60 0 10 110 20 0 0 0\n")
    assert c.snapshot().cpu_load == 0.5


def test_fmt():
    assert fmt(48.46, "°C") == "48.5 °C"
    assert fmt(None, "W") == "n/a"
    assert fmt(2.0, "W", 2) == "2.00 W"


def panel_text(app, pid):
    return str(app.query_one(pid, Static).render())


def test_app_shows_no_baseline_and_quits(tmp_path):
    async def run():
        app = CortexTUI(collector(tmp_path), refresh_s=0.05)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "no baseline yet" in panel_text(app, "#engine")
            assert "not probed yet" in panel_text(app, "#npu")
            assert "n/a" in panel_text(app, "#system")
            await pilot.press("q")
        return app
    app = asyncio.run(run())
    assert app.return_code in (0, None)


def test_app_shows_baseline(tmp_path):
    write(tmp_path, "latest.json", json.dumps(baseline()))
    write(tmp_path, "npu.json", json.dumps({"reachable": True, "notes": []}))

    async def run():
        app = CortexTUI(collector(tmp_path), refresh_s=0.05)
        async with app.run_test() as pilot:
            await pilot.pause()
            eng = panel_text(app, "#engine")
            assert "image_describe" in eng and "21.7" in eng and "0.42" in eng
            assert "yes" in panel_text(app, "#npu").lower()
            await pilot.press("q")
    asyncio.run(run())


# --- final-review fixes ---

def snap(baseline=None, npu=None):
    return Snapshot({}, None, None, None, baseline, npu)


@pytest.mark.parametrize("b", [{"cases": [1, 2]}, {"cases": {"x": "str"}},
                               {"cases": {"x": {"ttft_s": "bad", "unsupported": 5, "decode_tps": [1]}}},
                               {"meta": "odd", "cases": {}}])
def test_engine_panel_survives_odd_json(b):
    assert isinstance(str(_engine(snap(baseline=b))), str)


@pytest.mark.parametrize("n", [{"notes": "str"}, {"notes": [1, None]}, {"reachable": "maybe"}])
def test_npu_panel_survives_odd_json(n):
    assert isinstance(str(_npu(snap(npu=n))), str)


def test_engine_lines_fit_a_80_column_terminal():
    b = baseline()
    b["cases"]["a_rather_long_case_name_here"] = b["cases"]["image_describe"]
    assert max(len(line) for line in str(_engine(snap(baseline=b))).splitlines()) <= 74


def test_engine_panel_is_full_width_at_80x24(tmp_path):
    async def run():
        app = CortexTUI(collector(tmp_path), refresh_s=0.05)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one("#engine").size.width >= 70
            await pilot.press("q")
    asyncio.run(run())
