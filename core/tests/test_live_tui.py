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
