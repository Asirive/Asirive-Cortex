import asyncio

import pytest

pytest.importorskip("textual")
pytest.importorskip("numpy")

from textual.widgets import Static  # noqa: E402

from cortex_core.tui.live import LiveSession  # noqa: E402
from cortex_core.tui.live_app import LiveTUI  # noqa: E402
from cortex_core.tui.state import Collector  # noqa: E402
from tests.test_live_session import FakeEngine  # noqa: E402


def test_space_toggles_listening_and_typed_question_is_answered(tmp_path):
    eng = FakeEngine()
    session = LiveSession(eng).start()

    async def go():
        app = LiveTUI(session, Collector(tmp_path, tmp_path, tmp_path, tmp_path))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.press("space")
            await pilot.pause(0.3)
            assert eng.listening == [True]
            assert "LISTENING" in str(app.query_one("#status", Static).render())
            await pilot.press("slash")
            await pilot.press(*"what is this", "enter")
            for _ in range(30):
                await pilot.pause(0.1)
                if "A cup." in str(app.query_one("#conv", Static).render()):
                    break
            conv = str(app.query_one("#conv", Static).render())
            assert "what is this" in conv and "A cup." in conv
            await pilot.press("space")  # focus left the box after enter: space is the button again
            await pilot.pause(0.2)
            assert eng.listening == [True, False]

    try:
        asyncio.run(go())
    finally:
        session.close()


def test_space_while_talking_cuts_the_answer(tmp_path):
    eng = FakeEngine()
    session = LiveSession(eng).start()
    eng.voice.put({"type": "sound_start", "at_ms": 1.0})  # Cortex is talking

    async def go():
        app = LiveTUI(session, Collector(tmp_path, tmp_path, tmp_path, tmp_path))
        async with app.run_test(size=(100, 32)) as pilot:
            for _ in range(20):
                await pilot.pause(0.1)
                if "SPEAKING" in str(app.query_one("#status", Static).render()):
                    break
            assert "SPEAKING" in str(app.query_one("#status", Static).render())
            await pilot.press("space")
            await pilot.pause(0.3)
            assert eng.cancelled == 1
            assert eng.listening == []  # the button cut the answer, it did not toggle listening
            assert "SPEAKING" not in str(app.query_one("#status", Static).render())

    try:
        asyncio.run(go())
    finally:
        session.close()


def test_trip_panel_shows_mode_tools_and_gps(tmp_path):
    from cortex_core.tui.live_app import trip
    from cortex_core.tui.live_state import LiveState
    s = LiveState()
    assert "no agent harness" in str(trip(s))
    s.brain("state", {"line": "mode=OUTDOOR_NAV; trip: walk to Yishun MRT Station"})
    s.brain("tool_run", {"name": "plan_trip", "args": {"place_id": "p12"}, "result": {"minutes": 9}, "say": None,
                         "ms": 61.0, "checking": False, "error": None})
    s.brain("nav", {"type": "step", "text": "Turn left onto Yishun Avenue 2."})
    s.brain("gps", {"lat": 1.42951, "lon": 103.83512, "acc_m": 6.0, "t": 100.0})
    out = str(trip(s, now=103.0))
    assert "OUTDOOR_NAV" in out and "walk to Yishun" in out
    assert "plan_trip(place_id='p12') -> {\"minutes\":9}  61 ms" in out
    assert "Turn left onto Yishun Avenue 2." in out and "±6 m  3 s ago" in out


def test_brain_session_on_screen(tmp_path):
    from cortex_core.brain.brain import Brain
    from tests.test_live_session import BrainEngine, FakeNav, call
    eng = BrainEngine(call("nearby_bus_stops"))
    session = LiveSession(eng, brain=Brain(eng, FakeNav())).start()

    async def go():
        app = LiveTUI(session, Collector(tmp_path, tmp_path, tmp_path, tmp_path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("slash")
            await pilot.press(*"bus stop", "enter")
            for _ in range(30):
                await pilot.pause(0.1)
                if "nearby_bus_stops" in str(app.query_one("#trip", Static).render()):
                    break
            assert "IDLE" in str(app.query_one("#trip", Static).render())
            assert "nearby_bus_stops()" in str(app.query_one("#trip", Static).render())
            assert "80 metres" in str(app.query_one("#conv", Static).render())

    try:
        asyncio.run(go())
    finally:
        session.close()
