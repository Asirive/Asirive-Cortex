"""Streaming client for llama.cpp's OpenAI-compatible server, with the timings the baseline needs.

Measures time to first text token and time to first audio chunk from the client's side, and reads the
server's own prefill/decode speeds from the `timings` object. Never raises: failures come back as a
RunResult with ok=False so a benchmark run keeps going.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class RunResult:
    ok: bool
    error: Optional[str]
    status: Optional[int]
    ttft_s: Optional[float]
    ttfa_s: Optional[float]
    text: str
    prefill_tps: Optional[float]
    decode_tps: Optional[float]
    tokens_out: Optional[int]
    wall_s: float


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def user_message(text: str, image: Optional[Path] = None, audio: Optional[Path] = None) -> dict:
    """An OpenAI chat user message: image part, audio part, then the text."""
    parts: list[dict] = []
    if image is not None:
        parts.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + _b64(image)}})
    if audio is not None:
        parts.append({"type": "input_audio", "input_audio": {"data": _b64(audio), "format": "wav"}})
    parts.append({"type": "text", "text": text})
    return {"role": "user", "content": parts}


def stream_chat(base_url: str, messages: list[dict], *, max_tokens: int = 128, audio_out: bool = False,
                timeout_s: float = 60.0, clock: Callable[[], float] = time.monotonic,
                open_url: Callable = urllib.request.urlopen) -> RunResult:
    body: dict = {"messages": messages, "max_tokens": max_tokens, "stream": True}
    if audio_out:
        body["modalities"] = ["text", "audio"]
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    start = clock()
    ttft = ttfa = prefill = decode = None
    tokens: Optional[int] = None
    text: list[str] = []

    def result(ok: bool, error: Optional[str] = None, status: Optional[int] = None) -> RunResult:
        return RunResult(ok, error, status, ttft, ttfa, "".join(text), prefill, decode, tokens, clock() - start)

    try:
        with open_url(req, timeout=timeout_s) as resp:
            status = getattr(resp, "status", None)
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                now = clock()
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue  # malformed line: keep what we have
                choices = chunk.get("choices") or [{}]
                d = (choices[0] or {}).get("delta") or {}
                if d.get("audio") and ttfa is None:
                    ttfa = now - start
                if d.get("content"):
                    if ttft is None:
                        ttft = now - start
                    text.append(d["content"])
                t = chunk.get("timings")
                if isinstance(t, dict):
                    prefill = t.get("prompt_per_second", prefill)
                    decode = t.get("predicted_per_second", decode)
                    tokens = t.get("predicted_n", tokens)
            return result(True, status=status)
    except urllib.error.HTTPError as e:
        try:
            msg = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            msg = str(e)
        return result(False, msg or str(e), e.code)
    except Exception as e:  # connection refused, timeout, reset mid-stream
        return result(False, str(e) or type(e).__name__)
