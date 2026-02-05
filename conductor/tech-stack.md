# Technology Stack

## Core Infrastructure
- **Wearable (Edge):** Raspberry Pi 5 (4GB/8GB) with AI Hat+ Kit (Hailo 8L NPU, 13 TOPS).
- **Compute Server (Laptop):** High-performance GPU-enabled machine for VIO/SLAM post-processing and real-time dashboard monitoring.
- **Mobile Component:** Expo Go (React Native) app for remote user interaction.
- **Networking & Tunneling:**
    - **Local:** Dedicated WiFi subnet (10.17.233.x) for RPi5-to-Laptop communication.
    - **Remote Access:** Playit.gg port forwarding on the Laptop to expose system status and API endpoints to the Expo Go app.
    - **Protocols:** WebSocket (FastAPI) for commands, ZMQ for high-bandwidth video.

## AI & Computer Vision
- **Layer 0 (Guardian):** YOLOv26n optimized via NCNN running on the **RPi5 CPU** for ultra-reliable safety-critical detection.
- **Layer 1 (Learner):** YOLOe-11n-seg running on the **Hailo 8L NPU**, utilizing both Text Prompts (Open-Vocabulary) and Visual Prompts (Personal Object Memory).
- **Layer 2 (Thinker):** 
    - **Production:** Gemini 2.5 Flash Live API for <500ms audio-to-audio conversational AI.
    - **Development:** Gemini 3 Flash / Gemini 2.5 Flash HTTP with Kokoro TTS fallback.
- **Spatial AI:** 
    - **Navigation:** Google Maps API + GPS (NEO8MV2) + BNO055 IMU.
    - **Localization:** Real-time VIO/SLAM (run continuously) with server-side post-processing.
    - **Audio:** PyOpenAL for body-relative 3D spatial beacons and proximity alerts.

## Software Stack
- **Languages:** Python 3.11/3.13 (Core), React Native (Mobile).
- **Frameworks:** FastAPI, PyQt6 (Dashboard), NCNN, Hailo TAPPAS/DFM, ONNX Runtime.
- **Audio Processing:** PipeWire, Silero VAD, Whisper (base), Kokoro TTS, Misaki G2P.
- **Data & Memory:** 
    - **Local:** SQLite for high-speed local caching.
    - **Cloud:** Supabase (PostgreSQL + Storage) for cross-session persistent memory.

## Project Timeline
- **Feature Completion:** March 10, 2026.
- **User Feedback & Testing:** March 10 – March 30, 2026.
- **Final Submission (YIA 2026):** March 31, 2026.
