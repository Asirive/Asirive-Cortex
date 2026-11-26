"""Gemini takeover (spec 6.5): only when the local LM is not sure AND the box can reach the gateway.

"Not sure" is the LM's own call: it calls the silent tool second_opinion(question) instead of guessing (tool calls
are never spoken, so nothing wrong is said first). The brain then sends a short clip of the last few seconds (one
frame a second, oldest first, only when the camera is on; video, so Gemini can judge motion and layout) and the
question to Gemini Live through the gateway, and speaks Gemini's answer in Cortex's voice as is (it is recorded in
the conversation, so follow-ups have it). Without internet, without a claimed identity, or when the gateway refuses
(rate limit, Gemini down), Cortex says it is not sure.

The answer streams: ask(question, frames, say) calls say with each sentence Gemini has finished and moved on from,
and the brain speaks those at once (about 3 s sooner on a two-sentence answer); the rest of the answer is the
template, spoken and recorded at the end, so nothing is said twice. Cut off after some sentences: "I lost the rest".

    takeover = Takeover(provision.second_opinion_client(p), clip=lambda since: capture.fresh_clip(cam, since))
    Brain(engine, nav, takeover=takeover)
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

NOT_SURE_OFFLINE = "I'm not sure, and I can't check online right now."
NOT_SURE = "I'm not sure, and I couldn't check that just now."
LOST = "Sorry, I lost the rest of that answer."
MAX_FRAMES = 6  # the gateway's gemini.MaxFrames


class OpinionError(Exception):
    """The second opinion failed. online False: no internet / gateway unreachable (vs refused or Gemini down)."""

    def __init__(self, msg: str, online: bool = True):
        super().__init__(msg)
        self.online = online


class Takeover:
    def __init__(self, ask: Callable[..., str] | None,
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

    def run(self, question: str, camera_on: bool, since: float = 0.0,
            say: Callable[[str], None] | None = None) -> tuple[dict, str]:
        """(tool result, what is left to speak). Never raises. since: when the camera was last turned on
        (monotonic); frames from before it (taken while the camera was off) are never sent. say: hears each early
        sentence while the answer is made (None: everything is in the returned sentence)."""
        if self.ask is None:
            return {"error": "no internet connection to the gateway"}, NOT_SURE_OFFLINE
        q = " ".join(str(question or "").split())
        if not q:
            return {"error": "no question"}, NOT_SURE
        frames = self._frames(camera_on, since)
        said: list[str] = []

        def early(s: str) -> None:
            s = " ".join(str(s).split())
            if s and say is not None:
                said.append(s)
                say(s)

        try:
            answer = " ".join(str(self.ask(q, frames, say=early)).split())
        except OpinionError as e:
            if said:
                return {"error": str(e), "said": " ".join(said)}, LOST
            return {"error": str(e)}, NOT_SURE if e.online else NOT_SURE_OFFLINE
        except Exception as e:  # noqa: BLE001
            log.exception("takeover failed")
            if said:
                return {"error": f"second opinion failed: {type(e).__name__}", "said": " ".join(said)}, LOST
            return {"error": f"second opinion failed: {type(e).__name__}"}, NOT_SURE
        if not answer:
            return {"error": "empty answer"}, NOT_SURE
        head = " ".join(said)
        rest = answer[len(head):].strip() if said and answer.startswith(head) else answer
        if not rest:  # the gateway always keeps the last sentence back; if not, end on something short
            rest = "That's all."
        return {"answer": answer, "source": "gemini", "frames": len(frames)}, rest
