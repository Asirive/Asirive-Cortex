"""The live session behind the TUI: engine + camera + mic, each on its own thread, folded into one LiveState.

    vision thread  latest camera frame -> push_frame + refresh, waits for the view, at most every refresh_s
    mic            every 20 ms of audio -> push_audio (the engine ignores it while listening is off) + level
    voice thread   speech_start / speech_end / spoken answer / sound_start / sound_end events -> state
    ask            a typed question runs on its own thread

With a brain (cortex_core.brain.Brain) the session hosts the agent harness: typed questions and spoken tool calls
go through the brain's dispatcher, on_fix() feeds GPS to it, and the camera follows the mode's cadence
(brain.vision_s; None = one view when the user starts talking or types).

The engine is duck-typed (cortex_core.engine.native.Engine), so tests run with a fake."""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from cortex_core.tui.live_state import LiveState


class LiveSession:
    def __init__(self, engine, camera=None, refresh_s: float = 1.0, max_tokens: int = 0, brain=None):
        self.eng, self.camera, self.refresh_s, self.max_tokens = engine, camera, refresh_s, max_tokens
        self.brain = brain
        self.state = LiveState()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.want_view = threading.Event()  # "on talk" modes: one view for the question being asked
        if brain is not None:
            brain.on_event = self._brain_event
            self.state.mode = brain.mode
        self._threads = [threading.Thread(target=self._voice_loop, name="voice", daemon=True)]
        if camera is not None:
            self._threads.append(threading.Thread(target=self._vision_loop, name="vision", daemon=True))

    def start(self) -> "LiveSession":
        for t in self._threads:
            t.start()
        return self

    def _apply(self, ev: dict) -> None:
        with self.lock:
            self.state.apply(ev)

    def _brain_event(self, kind: str, data: dict) -> None:
        with self.lock:
            if kind in ("token", "done"):
                self.state.apply(data)
            else:
                self.state.brain(kind, data)

    def on_fix(self, fix: dict) -> None:
        """A GPS fix (gps.parse_fix'd) from the link: to the brain, and the panel."""
        with self.lock:
            self.state.brain("gps", fix)
        if self.brain is not None:
            self.brain.on_fix(fix["lat"], fix["lon"], fix["acc_m"], fix.get("t"), fix.get("speed"))

    def note(self, line: str) -> None:
        with self.lock:
            self.state.log.append(line)

    # ---- inputs
    def on_mic(self, pcm) -> None:
        from cortex_core.engine.capture import rms_dbfs

        level = rms_dbfs(pcm)
        with self.lock:
            self.state.mic_dbfs = level
        try:
            self.eng.push_audio(pcm)
        except RuntimeError as e:
            self.note(f"mic: {e}")

    def toggle_listening(self) -> bool:
        with self.lock:
            on = not self.state.listening
        try:
            self.eng.set_listening(on)
        except RuntimeError as e:
            self.note(str(e))
            return False
        with self.lock:
            self.state.listening = on
            if not on:
                self.state.speaking = False
            self.state.log.append("listening " + ("ON" if on else "off"))
        return on

    def button(self) -> str:
        """The one button: while Cortex talks it cuts the answer ("cut"); otherwise listening on/off."""
        with self.lock:
            talking = self.state.talking
        if talking:
            self.eng.cancel()  # the engine sends sound_end (cut) at once; the voice thread clears talking
            self.note("cut off")
            return "cut"
        return "listen" if self.toggle_listening() else "stop listening"

    def ask(self, question: str) -> None:
        question = question.strip()
        if not question:
            return
        with self.lock:
            if self.state.asking:
                self.state.log.append("busy: an answer is still running")
                return
            self.state.asking = True
            self.state.typed(question)
        self.want_view.set()
        threading.Thread(target=self._ask, args=(question,), name="ask", daemon=True).start()

    def _ask(self, question: str) -> None:
        if self.brain is not None:
            try:
                t = self.brain.ask(question, self.max_tokens)
                if t.said:  # a fixed sentence ended the turn: show it as the answer
                    with self.lock:
                        a = self.state._answer()
                        a.text, a.done = t.said, True
            except queue.Empty:
                self.note("ask: no answer (timeout)")
            except Exception as e:  # noqa: BLE001 - keep the screen alive
                self.note(f"ask: {type(e).__name__}: {e}")
            finally:
                with self.lock:
                    self.state.asking = False
            return
        try:
            for ev in self.eng.ask(question, self.max_tokens):
                if ev.get("type") == "error" and ev.get("what") == "busy":
                    self.note("busy: the engine is answering or you are speaking")
                    continue
                self._apply(ev)
        except queue.Empty:
            self.note("ask: no answer (timeout)")
        finally:
            with self.lock:
                self.state.asking = False

    def reset_history(self) -> None:
        self.eng.reset_history()
        self.note("history cleared")

    # ---- loops
    def _voice_loop(self) -> None:
        while not self.stop.is_set():
            try:
                ev = self.eng.next_voice(timeout=0.2)
            except queue.Empty:
                continue
            if ev.get("type") == "speech_start":
                self.want_view.set()
            self._apply(ev)
            if self.brain is not None:
                try:
                    t = self.brain.voice_event(ev)
                except Exception as e:  # noqa: BLE001
                    self.note(f"brain: {type(e).__name__}: {e}")
                    continue
                if t is not None and t.said:
                    with self.lock:
                        a = self.state._answer()
                        a.text, a.done = t.said, True

    def _interval(self) -> float | None:
        return self.refresh_s if self.brain is None else self.brain.vision_s

    def _vision_loop(self) -> None:
        last_id: Optional[int] = None
        while not self.stop.is_set():
            t0 = time.monotonic()
            every = self._interval()
            if every is None:  # this mode looks only when the user talks
                if not self.want_view.wait(0.1):
                    continue
                self.want_view.clear()
                last_id = None  # the newest frame even if it was seen before
            f = self.camera.latest()
            if f is None or f[0] == last_id:
                if every is None:
                    self.want_view.set()  # no frame yet: keep the request
                self.stop.wait(0.05)
                continue
            last_id, rgb = f
            with self.lock:
                self.state.camera_frames = last_id
            try:
                self.eng.push_frame(rgb, frame_id=last_id)
                self.eng.refresh()
                ev = self.eng.wait_view(timeout=10.0)
            except queue.Empty:
                self.note("vision: no view in 10 s")
                continue
            except (RuntimeError, ValueError) as e:
                self.note(f"vision: {e}")
                self.stop.wait(1.0)
                continue
            self._apply(ev)
            if self.brain is not None:
                self.brain.on_view(ev)  # memory may scan this view while the brain is idle
            self.stop.wait(max(0.0, (every or 0.0) - (time.monotonic() - t0)))

    def close(self) -> None:
        self.stop.set()
        for t in self._threads:
            t.join(timeout=12)
