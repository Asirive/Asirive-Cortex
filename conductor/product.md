# Initial Concept

**Project-Cortex v2.0** is an open-source, adaptive AI wearable designed to democratize assistive technology for the visually impaired. By leveraging commodity hardware (Raspberry Pi 5 with AI Hat+), a hybrid edge-cloud architecture, and a dedicated companion dashboard, it aims to provide a ~$300 alternative to premium market devices.

## Target Users
- **Completely Blind Individuals:** Users requiring full scene description, obstacle avoidance, and precise navigation assistance.
- **Visually Impaired Individuals:** Users needing assistance with specific tasks such as reading text (OCR), identifying objects, or facial recognition.
- **Developers & Researchers:** The open-source community building upon the adaptive AI platform for accessibility innovation.

## Core Value Propositions
1.  **Affordability:** A ~$300 solution disrupting the $4,000+ assistive device market.
2.  **Adaptive Intelligence:** A "4-Layer AI Brain" that learns from user interactions and context.
3.  **Real-Time Safety:** Low-latency (<100ms) obstacle detection and "Guardian" layer reflexes powered by the Hailo 8L processor.
4.  **Hybrid Architecture:** Seamless integration of local edge processing (privacy, speed) with cloud capabilities (depth, reasoning) and laptop-side GPU offloading.

## Strategic Priorities (Phase 2)
1.  **Spatial Audio Precision:**
    -   Enhance the "Layer 3 Guide" to provide high-fidelity, body-relative 3D audio cues.
    -   Improve proximity alerts for safe navigation in complex environments.
2.  **Cognitive Memory Expansion:**
    -   Upgrade "Layer 4 Memory" to effectively catalog and recall personal items (e.g., keys, wallet) and familiar faces.
    -   Implement hybrid memory storage using local databases and Supabase for persistent context.
3.  **Adaptive Scene Understanding:**
    -   Refine "Layer 1 Learner" and "Layer 2 Thinker" to move beyond simple object detection.
    -   Provide context-aware descriptions (e.g., distinguishing between "a car" and "an approaching taxi").

## Current Operational Context
-   **Hardware:** Raspberry Pi 5 with AI Hat+ Kit (Hailo 8L Processor) communicating with a Laptop Dashboard.
-   **Network:** Local WiFi network (Current Subnet: 10.17.233.x).
-   **Connectivity:**
    -   WebSocket (Port 8765) via FastAPI for bidirectional command/control.
    -   ZMQ (Port 5555) for high-bandwidth video streaming from RPi5 to Laptop.
-   **Software Stack:**
    -   **RPi5:** Python 3.11/3.13, Picamera2, NCNN/ONNX, Kokoro TTS, Silero VAD.
    -   **Laptop:** PyQt6 Dashboard, FastAPI Server, GPU-accelerated inference offloading.
    -   **Cloud:** Supabase for memory sync and persistent storage.
-   **Audio:** PipeWire-based audio management on RPi5, utilizing Bluetooth peripherals (e.g., CMF Buds 2 Plus).
