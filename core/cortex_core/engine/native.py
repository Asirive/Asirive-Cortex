"""ctypes binding for libcortex_engine.so (core/tools/cortex-engine): the NPU vision encoder and the LM in one
native runtime. The latest frame is encoded and read into the LM in the background; an ask only reads the question.

    eng = Engine("/opt/cortex/build/cortex-engine/libcortex_engine.so", {"model": ..., "mmproj": ...,
                 "split_dir": ..., "qnn_lib_dir": ...})
    eng.push_frame(rgb, frame_id=1); eng.refresh(); eng.wait_view()
    for ev in eng.ask("What is in front of me?"): ...   # token events, then done (or error)

Hands-free: the button only toggles listening; the engine's VAD finds where speech starts and ends.

    eng.set_listening(True)
    eng.push_audio(mic_chunk)          # 16 kHz mono, float [-1, 1] or int16, any chunk size, real time
    ev = eng.next_voice(timeout=...)   # speech_start, speech_end, token (voice), done (voice), or a voice error

Events come from engine threads through a C callback that only parses and enqueues (it holds the GIL briefly).
"""
from __future__ import annotations

import ctypes
import json
import queue
import threading
from pathlib import Path
from typing import Iterator

EVENT_TYPES = {"token", "done", "view", "error", "speech_start", "speech_end"}
_CB = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)


def route_event(ev: dict, asking: bool) -> str:
    """Which queue an event belongs to: "voice" (hands-free), "answer" (the running typed ask) or "views"."""
    t = ev["type"]
    if t in ("speech_start", "speech_end") or ev.get("voice"):
        return "voice"
    if t == "error" and str(ev.get("what", "")).startswith(("voice:", "audio:")):
        return "voice"
    if t in ("token", "done") or (t == "error" and asking):
        return "answer"
    return "views"


def pcm16k_float(pcm):
    """Mono 16 kHz audio -> contiguous float32 in [-1, 1]. int16 input is scaled by 1/32768."""
    import numpy as np

    a = np.asarray(pcm)
    if a.ndim != 1:
        raise ValueError(f"expected mono audio [n], got shape {a.shape}")
    if a.dtype == np.int16:
        return np.ascontiguousarray(a, dtype=np.float32) / np.float32(32768.0)
    return np.ascontiguousarray(a, dtype=np.float32)


def parse_event(line: str) -> dict:
    """One engine event line -> dict. Raises ValueError for anything that is not a known event object."""
    try:
        ev = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"engine event is not JSON: {line[:80]!r}") from e
    if not isinstance(ev, dict) or ev.get("type") not in EVENT_TYPES:
        raise ValueError(f"unknown engine event: {line[:80]!r}")
    return ev


class Engine:
    def __init__(self, lib: str | Path, config: dict):
        path = Path(lib)
        if not path.is_file():
            raise OSError(f"cortex engine library not found: {lib}")
        self._lib = ctypes.CDLL(str(path))
        L = self._lib
        L.ce_open.restype, L.ce_open.argtypes = ctypes.c_void_p, [ctypes.c_char_p, _CB, ctypes.c_void_p]
        L.ce_last_error.restype = ctypes.c_char_p
        L.ce_push_frame.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_long]
        for fn in ("ce_refresh", "ce_cancel", "ce_reset_history"):
            getattr(L, fn).argtypes = [ctypes.c_void_p]
        L.ce_ask.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        L.ce_status.restype, L.ce_status.argtypes = ctypes.c_char_p, [ctypes.c_void_p]
        L.ce_close.argtypes = [ctypes.c_void_p]
        L.ce_set_listening.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.ce_push_audio.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]

        self._views: queue.Queue[dict] = queue.Queue()  # view events, and errors while no ask runs
        self._answer: queue.Queue[dict] = queue.Queue()  # token / done, and errors during an ask
        self._voice: queue.Queue[dict] = queue.Queue()  # speech_start / speech_end and the spoken answers
        self._asking = threading.Event()
        self._cb = _CB(self._on_event)  # kept alive for the engine's lifetime
        self._h = L.ce_open(json.dumps(config).encode(), self._cb, None)
        if not self._h:
            raise RuntimeError(f"ce_open: {L.ce_last_error().decode(errors='replace')}")

    def _on_event(self, line: bytes, _user) -> None:
        try:
            ev = parse_event(line.decode(errors="replace"))
        except ValueError:
            return
        where = route_event(ev, self._asking.is_set())
        {"voice": self._voice, "answer": self._answer, "views": self._views}[where].put(ev)

    def set_listening(self, on: bool) -> None:
        """The button: automatic (VAD) listening on or off. Off drops a question still being spoken."""
        if self._lib.ce_set_listening(self._h, 1 if on else 0):
            raise RuntimeError(f"listening unavailable: {self.status().get('listen_error', '?')}")

    def push_audio(self, pcm) -> None:
        """Microphone audio, 16 kHz mono (float [-1, 1] or int16). Ignored while listening is off."""
        a = pcm16k_float(pcm)
        if a.size and self._lib.ce_push_audio(self._h, a.ctypes.data, int(a.size)):
            raise RuntimeError("ce_push_audio refused the audio")

    def next_voice(self, timeout: float | None = None) -> dict:
        """The next hands-free event: speech_start, speech_end, a voice token, the voice done, or a voice error.
        Raises queue.Empty on timeout."""
        return self._voice.get(timeout=timeout)

    def push_frame(self, rgb, frame_id: int) -> None:
        """rgb: uint8 array [h, w, 3] (copied by the engine)."""
        import numpy as np

        a = np.ascontiguousarray(rgb, dtype=np.uint8)
        if a.ndim != 3 or a.shape[2] != 3:
            raise ValueError(f"expected an [h, w, 3] RGB frame, got {a.shape}")
        if self._lib.ce_push_frame(self._h, a.ctypes.data, a.shape[1], a.shape[0], frame_id):
            raise RuntimeError("ce_push_frame refused the frame")

    def refresh(self) -> None:
        self._lib.ce_refresh(self._h)

    def wait_view(self, timeout: float = 30.0) -> dict:
        """The next view (or refresh error) event."""
        return self._views.get(timeout=timeout)

    def ask(self, text: str, max_tokens: int = 60, timeout: float = 60.0) -> Iterator[dict]:
        """Yields token events and ends with the done (or error) event."""
        self._asking.set()
        try:
            if self._lib.ce_ask(self._h, text.encode(), max_tokens):
                yield {"type": "error", "what": "busy"}
                return
            while True:
                ev = self._answer.get(timeout=timeout)
                yield ev
                if ev["type"] in ("done", "error"):
                    if ev["type"] == "error":  # the done that follows an ask error
                        try:
                            self._answer.get(timeout=timeout)
                        except queue.Empty:
                            pass
                    return
        finally:
            self._asking.clear()

    def cancel(self) -> None:
        self._lib.ce_cancel(self._h)

    def reset_history(self) -> None:
        self._lib.ce_reset_history(self._h)

    def status(self) -> dict:
        return json.loads(self._lib.ce_status(self._h).decode())

    def close(self) -> None:
        if self._h:
            self._lib.ce_close(self._h)
            self._h = None

    def __enter__(self) -> "Engine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
