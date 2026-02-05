# Product Guidelines

## Design Principles
1.  **Utility over Aesthetic:** For the wearable, every audio cue must provide actionable information. Avoid "flavor text" that could mask environmental sounds.
2.  **Safety-First (Layer 0 Priority):** Safety-critical haptic and audio alerts from the Guardian layer must override all other system communications.
3.  **Low Cognitive Load:** Use standardized audio terminology (e.g., "Object at [Clock Position], [Distance]") to ensure the user can process information while navigating.

## Interaction Guidelines (Wearable)
-   **Voice Tone:** Professional, neutral, and informative.
-   **Verbosity:** High-utility, concise responses. Use "Quiet Mode" automatically in high-noise or high-density environments.
-   **Audio Feedback:** Use 3D spatial beacons for navigation and distinct haptic patterns for proximity alerts.

## Dashboard Guidelines (Developer/Support)
-   **Telemetry:** Real-time display of Hailo 8L utilization (for depth/Guardian), FPS for local (RPi CPU) and offloaded (Laptop GPU) layers, and network latency.
-   **Visual Overlays:** Bounding boxes must be color-coded by layer (e.g., Red for Layer 0 Guardian, Purple for Layer 1 Learner).
-   **Control:** Bidirectional toggle for "Production" vs "Dev" modes, with explicit logging of command acknowledgments from the RPi5.

## Technical Standards
-   **Hybrid Offloading:** Maintain Layer 1 (YOLOe) offloading to the laptop server via ZMQ/WebSocket until Hailo 8L testing for adaptive detection is finalized.
-   **Latency Target:** Maintain <100ms end-to-end latency for the local Guardian layer.
-   **Sync Integrity:** Ensure Supabase memory sync happens in the background without interrupting the real-time inference loop.
-   **Fail-Safe:** If the Laptop connection fails, the system must automatically fall back to the NCNN-optimized Layer 0 CPU inference.
