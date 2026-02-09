<div align="center">

# Gemini-Cortex

### Real-Time AI Vision Assistant for the Visually Impaired — Powered by Gemini

[![Google Gemini](https://img.shields.io/badge/Powered%20by-Gemini%203%20Flash-4285F4?logo=google&logoColor=white)](https://ai.google.dev/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Hardware: RPi 5](https://img.shields.io/badge/Edge-Raspberry%20Pi%205-red.svg)](https://www.raspberrypi.com/products/raspberry-pi-5/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**A <$150 wearable that gives visually impaired users real-time scene understanding, object memory, and natural conversation — all powered by Gemini's multimodal intelligence.**

</div>

---

## What It Does

Gemini-Cortex is a chest-mounted wearable camera connected to a Raspberry Pi 5 that continuously captures the world around a visually impaired user. When the user speaks a question — *"What's in front of me?"*, *"Read that sign"*, *"Where did I leave my keys?"* — the system sends the live camera frame + voice query to **Gemini 3 Flash Preview** and speaks the answer back through Bluetooth earbuds in under 1 second.

**Demo flow:**
1. User asks: *"What do you see?"*
2. Silero VAD detects speech, Whisper transcribes it
3. Intent Router classifies it as a vision query
4. Camera frame + prompt sent to **Gemini 3 Flash Preview** (multimodal)
5. Gemini analyzes the scene and returns a natural description
6. **Gemini 2.5 Flash TTS** converts the response to speech
7. Audio plays through Bluetooth earbuds — total latency ~800ms

---

## How Gemini Is Used

This project uses **three Gemini capabilities** via the `google-genai` SDK:

### 1. Gemini 3 Flash Preview — Multimodal Vision Brain

The core intelligence. Every vision query sends a PNG frame + text prompt to `gemini-3-flash-preview`:

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model='gemini-3-flash-preview',
    contents=[
        types.Part.from_bytes(data=image_bytes, mime_type='image/png'),
        types.Part.from_text(text=user_query)
    ],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        system_instruction="You are a visual assistant for a visually impaired user...",
        thinking_config=types.ThinkingConfig(thinking_budget=0),  # Speed optimization
    )
)
```

**Key features used:**
- **Multi-turn conversation** — rolling history of user/model turns for contextual follow-ups
- **System instructions** — dynamic persona with spatial guidance rules, object recall behavior, and personalization (user's name, preferences extracted from speech)
- **ThinkingConfig** — `thinking_budget=0` disables internal reasoning for ~200-500ms latency savings on simple queries
- **Reference image comparison** — for object recall ("Where's my wallet?"), historical frames tagged `[Historical observation]` are sent alongside the current view so Gemini can compare locations

### 2. Gemini 2.5 Flash Preview TTS — Natural Speech Output

Text responses are converted to speech using Gemini's native TTS:

```python
response = client.models.generate_content(
    model='gemini-2.5-flash-preview-tts',
    contents=text_description,
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Kore"
                )
            )
        )
    )
)

# Extract raw PCM audio (24kHz, 16-bit mono)
audio_data = response.candidates[0].content.parts[0].inline_data.data
```

### 3. Smart TTS Routing (Gemini + Local Fallback)

A TTS router intelligently selects the engine based on response length:

| Response Length | Engine | Why |
|:---|:---|:---|
| < 300 chars | **Gemini 2.5 Flash TTS** | Natural voice, low latency for short phrases |
| >= 300 chars | **Kokoro-82M** (local ONNX) | Faster for long text, no API quota cost |
| All keys exhausted | **Kokoro-82M** (automatic) | Graceful offline degradation |

---

## Architecture

```
                    User (Visually Impaired)
                           |
                    [Bluetooth Earbuds]
                           |
               +-----------+-----------+
               |   Raspberry Pi 5 (4GB)|
               |                       |
               |  Camera Module 3 Wide |
               |         |             |
               |    [Frame Capture]    |
               |         |             |
               |  +------+------+      |
               |  | Intent      |      |
               |  | Router      |      |
               |  +------+------+      |
               |         |             |
               |    Layer 0: YOLO      |  <-- Safety detection (offline, <100ms)
               |    Layer 2: Gemini--->|---> Gemini 3 Flash Preview (cloud)
               |    Layer 4: Memory    |  <-- SQLite + object recall
               |                       |
               +-----------------------+
```

### The 4-Layer Pipeline

| Layer | Name | Role | Technology |
|:---|:---|:---|:---|
| **L0** | Guardian | Safety-critical object detection (cars, stairs, obstacles) | YOLO v26n NCNN (local, <100ms) |
| **L2** | Thinker | Scene understanding, reading, Q&A | **Gemini 3 Flash Preview** |
| **L3** | Router | Classifies user intent to the right layer | Fuzzy keyword matching (97.7% accuracy) |
| **L4** | Memory | Conversation history, object location recall | SQLite + Gemini reference images |

### Voice Pipeline

```
Microphone --> Silero VAD --> Whisper STT --> Intent Router --> Gemini Vision
                                                                    |
Bluetooth Speaker <-- Audio Playback <-- Gemini TTS / Kokoro <-- Response
```

---

## Gemini API Features Used

| Feature | How We Use It | File |
|:---|:---|:---|
| **Multimodal input** (image + text) | Send camera frame + voice query | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **Multi-turn conversation** | Rolling session history for context | `rpi5/conversation_manager.py` |
| **Dynamic system instructions** | Personalized persona with spatial guidance | `rpi5/conversation_manager.py` |
| **ThinkingConfig** | Disable thinking for latency optimization | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **Native TTS output** | `response_modalities=["AUDIO"]` with voice config | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **API key rotation** | Pool of up to 10 keys with automatic failover | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **Rate limit retry** | Exponential backoff + key rotation on 429/503 | `rpi5/layer2_thinker/gemini_tts_handler.py` |
| **Reference image comparison** | Historical frames for object recall queries | `rpi5/conversation_manager.py` |
| **Personal fact extraction** | "My name is..." extracted and stored | `rpi5/conversation_manager.py` |

---

## Quick Start

### Prerequisites

- **Hardware:** Raspberry Pi 5 (4GB) with Camera Module 3 Wide
- **Audio:** Bluetooth earbuds/headphones
- **API Key:** [Get a Gemini API key](https://aistudio.google.com/app/apikey)
- **Python:** 3.11+

### Installation

```bash
git clone https://github.com/IRSPlays/Gemini-Cortex.git
cd Gemini-Cortex

python -m venv venv
source venv/bin/activate   # Linux/RPi
pip install -r requirements.txt

# RPi5 only:
sudo apt install python3-picamera2 espeak-ng
```

### Configuration

```bash
# Create .env with your Gemini API key(s)
echo "GEMINI_API_KEY=your_key_here" > .env

# Optional: add backup keys for rate limit rotation
echo "GEMINI_API_KEY_2=second_key" >> .env
echo "GEMINI_API_KEY_3=third_key" >> .env
```

### Run

```bash
# Full system on RPi5
python -m rpi5 all

# With debug logging
python rpi5/main.py --debug
```

---

## Project Structure

```
Gemini-Cortex/
├── rpi5/                           # Wearable device code (Raspberry Pi 5)
│   ├── main.py                     # Main orchestrator
│   ├── conversation_manager.py     # Multi-turn Gemini history + object recall
│   ├── voice_coordinator.py        # VAD + Whisper STT coordination
│   ├── tts_router.py               # Smart Gemini/Kokoro TTS routing
│   ├── config/config.yaml          # Central configuration
│   ├── layer0_guardian/            # YOLO safety detection (offline)
│   ├── layer1_reflex/              # Kokoro TTS + Whisper STT + VAD
│   │   ├── kokoro_handler.py       # Local TTS fallback (82M ONNX)
│   │   ├── whisper_handler.py      # Speech-to-text
│   │   └── vad_handler.py          # Voice activity detection
│   ├── layer2_thinker/             # Gemini integration
│   │   └── gemini_tts_handler.py   # Gemini 3 Flash vision + TTS
│   ├── layer3_guide/               # Intent router
│   │   └── router.py               # Voice command classification
│   └── layer4_memory/              # SQLite persistence
├── shared/                         # Shared utilities
├── models/                         # YOLO model weights
├── requirements.txt
└── .env                            # API keys (not committed)
```

---

## Performance

Measured on Raspberry Pi 5 (4GB RAM), Bluetooth audio, production code:

| Metric | Result |
|:---|:---|
| **End-to-end latency** (ask question -> hear answer) | ~800ms - 1.2s |
| **Gemini vision response** | ~400-600ms |
| **Gemini TTS generation** | ~200-400ms |
| **Safety detection (YOLO, local)** | 60-80ms |
| **Intent routing** | <5ms |
| **RAM usage** | ~3.6GB / 4GB |
| **Total hardware cost** | <$150 |

---

## Key Technical Decisions

**Why Gemini 3 Flash Preview?**
- Multimodal (image + text) in a single API call — no separate vision pipeline needed
- Fast enough for real-time (<600ms typical response)
- High-quality scene descriptions with spatial awareness
- Native TTS output eliminates a separate speech synthesis step

**Why local YOLO alongside Gemini?**
- Safety-critical detection (cars, stairs) must work offline with <100ms latency
- Gemini adds ~500ms network latency — too slow for "a car is approaching" alerts
- YOLO handles the reflexes, Gemini handles the thinking

**Why Kokoro-82M as TTS fallback?**
- Gemini API has rate limits (especially free tier)
- Kokoro runs locally on RPi5 with zero API cost
- Automatic failover: if all API keys are exhausted, TTS degrades gracefully

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Built for accessibility. Powered by Gemini.**

*Gemini-Cortex by [@IRSPlays](https://github.com/IRSPlays)*

</div>
