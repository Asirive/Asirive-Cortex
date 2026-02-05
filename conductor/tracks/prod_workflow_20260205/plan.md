# Implementation Plan: Stabilize Production Workflow

## Phase 1: Laptop Service Stabilization
- [ ] Task: Audit \laptop/layer1_service.py\ for NPF model loading and GPU utilization.
- [ ] Task: Implement robust error handling for ZMQ video stream interruptions.
- [ ] Task: Conductor - User Manual Verification 'Phase 1' (Protocol in workflow.md)

## Phase 2: Communication & Sync
- [ ] Task: Optimize WebSocket message payload for NPF detection metadata.
- [ ] Task: Verify detection latency from Laptop to RPi5 TUI.
- [ ] Task: Conductor - User Manual Verification 'Phase 2' (Protocol in workflow.md)

## Phase 3: Production Mode Verification
- [ ] Task: Test the 'SET_MODE' toggle from Dashboard to RPi5.
- [ ] Task: Final end-to-end latency and stability test.
- [ ] Task: Conductor - User Manual Verification 'Phase 3' (Protocol in workflow.md)
