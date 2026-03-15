"""
Phase 0 tests: voice pipeline bridge to Gemini Live.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0
"""

import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rpi5.voice_coordinator import VoiceCoordinator  # noqa: E402


class _FakeSTT:
    def transcribe(self, _audio):
        return "hello cortex"


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, pcm_bytes, sample_rate):
        self.calls.append((pcm_bytes, sample_rate))


async def _noop_command(_text: str):
    return None


def test_voice_coordinator_forwards_raw_audio_to_callback():
    vc = VoiceCoordinator(on_command_detected=_noop_command, config={})
    vc.stt = _FakeSTT()

    recorder = _Recorder()
    vc.on_raw_audio = recorder

    # 160ms at 16kHz, normalized float32 mono audio
    audio = (np.ones(2560, dtype=np.float32) * 0.25)
    vc._on_speech_end(audio)

    assert len(recorder.calls) == 1
    pcm_bytes, sample_rate = recorder.calls[0]

    # int16 PCM = 2 bytes per sample
    assert len(pcm_bytes) == audio.size * 2
    assert sample_rate == 16000
