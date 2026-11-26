"""Gemini takeover (spec 6.5): only when the local LM is not sure AND the box can reach the gateway.

"Not sure" is the LM's own call: it calls the silent tool second_opinion(question) instead of guessing (tool calls
are never spoken, so nothing wrong is said first). The brain then sends a short clip of the last few seconds (one
frame a second, oldest first, only when the camera is on; video, so Gemini can judge motion and layout) and the
question to Gemini Live through the gateway, and speaks Gemini's answer in Cortex's voice as is (it is recorded in
the conversation, so follow-ups have it). Without internet, without a claimed identity, or when the gateway refuses
(rate limit, Gemini down), Cortex says it is not sure.

    takeover = Takeover(provision.second_opinion_client(p), clip=lambda since: capture.fresh_clip(cam, since))
    Brain(engine, nav, takeover=takeover)
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

NOT_SURE_OFFLINE = "I'm not sure, and I can't check online right now."
NOT_SURE = "I'm not sure, and I couldn't check that just now."
MAX_FRAMES = 6  # the gateway's gemini.MaxFrames


class OpinionError(Exception):
    """The second opinion failed. online False: no internet / gateway unreachable (vs refused or Gemini down)."""

    def __init__(self, msg: str, online: bool = True):
        super().__init__(msg)
        self.online = online


class Takeover:
    def __init__(self, ask: Callable[[str, list[bytes]], str] | None,
                 clip: Callable[[float], list[bytes] | None] | None = None):
        self.ask = ask
        self.clip = clip

    def _frames(self, camera_on: bool, since: float) -> list[bytes]:
        if not camera_on or self.clip is None:
            return []
        try:
            return list(self.clip(since) or [])[-MAX_FRAMES:]
        except Exception:  # noqa: BLE001 - no video is better than no answer
            log.exception("takeover: clip failed")
            return []

    def run(self, question: str, camera_on: bool, since: float = 0.0) -> tuple[dict, str]:
        """(tool result, sentence to speak). Never raises. since: when the camera was last turned on (monotonic);
        frames from before it (taken while the camera was off) are never sent."""
        if self.ask is None:
            return {"error": "no internet connection to the gateway"}, NOT_SURE_OFFLINE
        q = " ".join(str(question or "").split())
        if not q:
            return {"error": "no question"}, NOT_SURE
        frames = self._frames(camera_on, since)
        try:
            answer = " ".join(str(self.ask(q, frames)).split())
        except OpinionError as e:
            return {"error": str(e)}, NOT_SURE if e.online else NOT_SURE_OFFLINE
        except Exception as e:  # noqa: BLE001
            log.exception("takeover failed")
            return {"error": f"second opinion failed: {type(e).__name__}"}, NOT_SURE
        if not answer:
            return {"error": "empty answer"}, NOT_SURE
        return {"answer": answer, "source": "gemini", "frames": len(frames)}, answer
