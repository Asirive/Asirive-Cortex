"""
Minimal test to reproduce and isolate Gemini Live API 1007 error.
Sends audio chunks / video frames / context to find which triggers 1007.

Usage (on RPi5):
    source venv/bin/activate
    python test_gemini_1007.py                 # Phase 1: audio only
    python test_gemini_1007.py --phase 2       # Phase 2: audio + video
    python test_gemini_1007.py --phase 3       # Phase 3: audio + video + context

Author: Haziq (@IRSPlays)
"""

import asyncio
import argparse
import logging
import os
import time
import struct
import math

from pathlib import Path
from google import genai
from google.genai import types

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_1007")

# Load API key from .env file (same as main system)
API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY:
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip().strip("'\"")
                break
MODEL = "gemini-3.1-flash-live-preview"


def generate_silent_pcm(duration_ms: int = 32, sample_rate: int = 16000) -> bytes:
    """Generate silent PCM audio chunk (16-bit mono)."""
    n_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * n_samples


def generate_tone_pcm(freq: float = 440.0, duration_ms: int = 32, sample_rate: int = 16000) -> bytes:
    """Generate a sine tone PCM chunk (16-bit mono, for non-silent test)."""
    n_samples = int(sample_rate * duration_ms / 1000)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        val = int(16000 * math.sin(2 * math.pi * freq * t))
        samples.append(struct.pack("<h", val))
    return b"".join(samples)


def generate_test_jpeg() -> bytes:
    """Generate a tiny valid JPEG (1x1 red pixel)."""
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.new("RGB", (320, 240), (128, 128, 128))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=50)
        return buf.getvalue()
    except ImportError:
        logger.warning("PIL not available, skipping video test")
        return b""


async def run_test(phase: int, duration: int = 30):
    """Run the 1007 reproduction test."""
    if not API_KEY:
        logger.error("Set GEMINI_API_KEY environment variable")
        return

    logger.info(f"=== Phase {phase} test (duration={duration}s) ===")
    logger.info(f"  Phase 1: audio only")
    logger.info(f"  Phase 2: audio + video")
    logger.info(f"  Phase 3: audio + video + context")

    client = genai.Client(
        api_key=API_KEY,
        http_options={"api_version": "v1beta"},
    )

    # Use the EXACT same config as gemini_live_handler.py
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="You are a helpful assistant. Stay silent unless spoken to.",
        temperature=0.7,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr")
            )
        ),
        media_resolution="MEDIA_RESOLUTION_MEDIUM",
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=104857,
            sliding_window=types.SlidingWindow(target_tokens=52428),
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(),
        tools=[
            types.Tool(google_search=types.GoogleSearch()),
            types.Tool(function_declarations=[
                {
                    "name": "get_navigation_state",
                    "description": "Get current navigation state.",
                },
                {
                    "name": "report_obstacle",
                    "description": "Report an obstacle.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "direction": {
                                "type": "string",
                                "enum": ["left", "center", "right", "ahead"],
                            },
                        },
                        "required": ["direction"],
                    },
                },
            ]),
        ],
    )

    logger.info(f"Config: model={MODEL}, tools=google_search + 2 functions")
    logger.info(f"  compression: trigger=104857, target=52428")
    logger.info(f"  input_transcription=True, output_transcription=True")

    audio_sent = 0
    video_sent = 0
    context_sent = 0
    connect_time = time.time()

    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            connect_time = time.time()
            logger.info("CONNECTED OK")

            # Receive task — runs in background
            async def receive_loop():
                msg_count = 0
                try:
                    async for resp in session.receive():
                        msg_count += 1
                        populated = []
                        for attr in ['data', 'text', 'server_content', 'go_away',
                                     'session_resumption_update', 'tool_call']:
                            if getattr(resp, attr, None) is not None:
                                populated.append(attr)
                        elapsed = time.time() - connect_time
                        logger.info(f"  [RECV #{msg_count}] {populated} @ {elapsed:.1f}s")

                        sru = getattr(resp, 'session_resumption_update', None)
                        if sru and getattr(sru, 'resumable', False):
                            logger.info(f"  Session resumption handle received")

                        sc = getattr(resp, 'server_content', None)
                        if sc:
                            if getattr(sc, 'input_transcription', None):
                                logger.info(f"  Gemini heard: {sc.input_transcription.text}")
                            if getattr(sc, 'output_transcription', None):
                                logger.info(f"  Gemini said: {sc.output_transcription.text}")
                            if getattr(sc, 'interrupted', False):
                                logger.info("  Barge-in detected")
                            tc = getattr(sc, 'turn_complete', None)
                            if tc is not None:
                                logger.info(f"  Turn complete")

                except Exception as e:
                    elapsed = time.time() - connect_time
                    logger.error(
                        f"  RECEIVE ERROR @ {elapsed:.1f}s: {type(e).__name__}: {e} "
                        f"(audio={audio_sent}, video={video_sent}, context={context_sent})"
                    )

            recv_task = asyncio.create_task(receive_loop())

            # Generate test data
            silent_chunk = generate_silent_pcm(32, 16000)  # 32ms of silence
            jpeg_frame = generate_test_jpeg() if phase >= 2 else b""

            start = time.time()
            last_video = start
            last_context = start

            logger.info(f"Streaming for {duration}s... (audio={'yes'}, video={phase>=2}, context={phase>=3})")

            while time.time() - start < duration:
                now = time.time()
                elapsed = now - connect_time

                # Send audio chunk every ~32ms
                try:
                    await session.send_realtime_input(
                        audio=types.Blob(data=silent_chunk, mime_type="audio/pcm;rate=16000")
                    )
                    audio_sent += 1
                    if audio_sent <= 5 or audio_sent % 100 == 0:
                        logger.info(f"  [SEND] Audio #{audio_sent} ({len(silent_chunk)}B) @ {elapsed:.1f}s")
                except Exception as e:
                    logger.error(f"  SEND AUDIO ERROR @ {elapsed:.1f}s: {e}")
                    break

                # Send video frame every 1s (phase 2+)
                if phase >= 2 and jpeg_frame and now - last_video >= 1.0:
                    last_video = now
                    try:
                        await session.send_realtime_input(
                            video=types.Blob(data=jpeg_frame, mime_type="image/jpeg")
                        )
                        video_sent += 1
                        logger.info(f"  [SEND] Video #{video_sent} ({len(jpeg_frame)}B) @ {elapsed:.1f}s")
                    except Exception as e:
                        logger.error(f"  SEND VIDEO ERROR @ {elapsed:.1f}s: {e}")
                        break

                # Send context every 5s (phase 3) — use send_realtime_input(text=...)
                # NOT send_client_content which causes 1007 during active audio streaming
                if phase >= 3 and now - last_context >= 5.0:
                    last_context = now
                    try:
                        await session.send_realtime_input(
                            text="[CONTEXT]\n[GPS] No fix\n[MODE] PRODUCTION"
                        )
                        context_sent += 1
                        logger.info(f"  [SEND] Context #{context_sent} @ {elapsed:.1f}s")
                    except Exception as e:
                        logger.error(f"  SEND CONTEXT ERROR @ {elapsed:.1f}s: {e}")
                        break

                await asyncio.sleep(0.032)  # ~32ms interval

            elapsed = time.time() - connect_time
            logger.info(
                f"Test PASSED — survived {elapsed:.1f}s without 1007! "
                f"(audio={audio_sent}, video={video_sent}, context={context_sent})"
            )
            recv_task.cancel()

    except Exception as e:
        elapsed = time.time() - connect_time
        logger.error(
            f"Test FAILED @ {elapsed:.1f}s: {type(e).__name__}: {e} "
            f"(audio={audio_sent}, video={video_sent}, context={context_sent})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini 1007 reproduction test")
    parser.add_argument("--phase", type=int, default=1, help="1=audio, 2=+video, 3=+context")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds")
    args = parser.parse_args()
    asyncio.run(run_test(args.phase, args.duration))
