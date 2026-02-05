# Track Specification: Stabilize Production Workflow

## Goal
Ensure the YOLOe Non-Prompt-Free (NPF) model runs reliably on the laptop server and its detections are synchronized with the RPi5 wearable in real-time.

## Key Deliverables
- Validated Laptop NPF Service: Stable inference loop on laptop GPU.
- High-Speed Sync: Optimized WebSocket/ZMQ delivery of metadata to RPi.
- Production Mode Hardening: Verified TUI and audio updates on RPi when switching modes.
