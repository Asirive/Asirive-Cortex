"""
RPi5 Simulator for Testing ProjectCortex Dashboard

This script simulates an RPi5 device for testing the dashboard:
- Webcam video feed (uses system webcam)
- Simulated system stats (RAM, CPU, Battery, Temperature)
- Random detection generation
- WebSocket server for communication with dashboard

Usage:
    python tests/test_rpi5_simulator.py [--port 8765] [--webcam 0]

Author: Haziq (@IRSPlays)
Date: January 8, 2026
"""

import asyncio
import argparse
import base64
import cv2
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import websockets
from websockets import serve

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('RPi5Simulator')
logger.info("RPi5 Simulator initialized")

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_PORT = 8765
DEFAULT_WEBCAM = 0

# Detection classes for simulation
DETECTION_CLASSES = [
    "person", "car", "dog", "cat", "chair", "bottle", "cup",
    "laptop", "phone", "book", "table", "door", "stairs",
    "traffic light", "stop sign", "bench", "tree", "sky"
]

# ============================================================================
# RPI5 SIMULATOR
# ============================================================================

class RPi5Simulator:
    """Simulates RPi5 device for dashboard testing"""

    def __init__(self, port: int = DEFAULT_PORT, webcam_index: int = DEFAULT_WEBCAM):
        self.port = port
        self.webcam_index = webcam_index
        self.running = False
        self.clients: set = set()

        # System stats (simulated)
        self.ram_percent = 35.0
        self.cpu_percent = 25.0
        self.battery_percent = 85.0
        self.temperature = 42.5
        self.fps = 0.0

        # Video
        self.cap = None

        # Detection config
        self.current_detections: List[Dict] = []

        logger.info(f"RPi5 Simulator configured on port {port}")

    def start(self):
        """Start the simulator"""
        logger.info("Starting RPi5 Simulator...")

        # Open webcam
        self.cap = cv2.VideoCapture(self.webcam_index)
        if not self.cap.isOpened():
            logger.error(f"Failed to open webcam {self.webcam_index}")
            return False

        logger.info(f"Webcam opened successfully (index {self.webcam_index})")
        self.running = True
        return True

    def stop(self):
        """Stop the simulator"""
        logger.info("Stopping RPi5 Simulator...")
        self.running = False

        if self.cap:
            self.cap.release()
            logger.info("Webcam released")

    def get_frame(self) -> Optional[bytes]:
        """Capture and return a frame as JPEG bytes"""
        if not self.cap:
            return None

        ret, frame = self.cap.read()
        if not ret:
            logger.warning("Failed to capture frame")
            return None

        # Resize for network transmission (smaller = faster)
        frame = cv2.resize(frame, (640, 480))

        # Encode as JPEG
        _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return jpeg.tobytes()

    def update_stats(self):
        """Update simulated system stats"""
        # Fluctuate values slightly
        self.ram_percent = max(20, min(80, self.ram_percent + random.uniform(-2, 2)))
        self.cpu_percent = max(10, min(90, self.cpu_percent + random.uniform(-3, 3)))
        self.battery_percent = max(10, min(100, self.battery_percent - random.uniform(0, 0.05)))
        self.temperature = max(35, min(65, self.temperature + random.uniform(-0.5, 0.5)))

        # Calculate FPS
        if not hasattr(self, '_last_frame_time'):
            self._last_frame_time = time.time()
        else:
            current_time = time.time()
            delta = current_time - self._last_frame_time
            if delta > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / delta) if self.fps > 0 else 1.0 / delta
            self._last_frame_time = current_time

    def generate_detections(self) -> List[Dict]:
        """Generate random detections"""
        # Randomly add/remove detections
        if random.random() < 0.3:  # 30% chance to add new detection
            num_new = random.randint(1, 3)
            for _ in range(num_new):
                if len(self.current_detections) < 8:
                    detection = {
                        "class_name": random.choice(DETECTION_CLASSES),
                        "confidence": random.uniform(0.4, 0.95),
                        "layer": random.choice(["guardian", "learner"]),
                        "source": random.choice(["NCNN", "ONNX"])
                    }
                    # Add random bbox (normalized 0-1)
                    w, h = 640, 480
                    detection["bbox"] = [
                        random.uniform(0.1, 0.7),  # x1
                        random.uniform(0.1, 0.7),  # y1
                        random.uniform(detection["bbox"][0] + 0.1, 0.9) if "bbox" in detection else random.uniform(0.3, 0.9),  # x2
                        random.uniform(detection["bbox"][1] + 0.1, 0.9) if "bbox" in detection else random.uniform(0.3, 0.9)  # y2
                    ] if "bbox" not in detection else detection["bbox"]

                    # Recalculate bbox properly
                    x1 = random.uniform(50, 400)
                    y1 = random.uniform(50, 300)
                    x2 = x1 + random.uniform(50, 200)
                    y2 = y1 + random.uniform(50, 150)
                    detection["bbox"] = [x1, y1, x2, y2]
                    detection["timestamp"] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

                    self.current_detections.append(detection)

        # Remove old detections
        if random.random() < 0.2 and self.current_detections:
            self.current_detections.pop(random.randint(0, len(self.current_detections) - 1))

        return self.current_detections.copy()

    def get_stats_dict(self) -> Dict:
        """Get current stats as dictionary"""
        return {
            "fps": self.fps,
            "ram_percent": round(self.ram_percent, 1),
            "cpu_percent": round(self.cpu_percent, 1),
            "battery_percent": round(self.battery_percent, 1),
            "temperature": round(self.temperature, 1),
            "current_mode": random.choice(["PROMPT_FREE", "TEXT_PROMPTS", "VISUAL_PROMPTS"]),
            "active_layers": ["layer_0", "layer_1"],
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }

    def create_message(self, msg_type: str, data: Dict) -> str:
        """Create a JSON message"""
        return json.dumps({
            "type": msg_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        })


# ============================================================================
# WEBSOCKET HANDLER
# ============================================================================

class WebSocketHandler:
    """Handles WebSocket connections"""

    def __init__(self, simulator: RPi5Simulator):
        self.simulator = simulator
        self.clients: set = set()

    async def handle_client(self, websocket):
        """Handle a client connection"""
        client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        self.clients.add(websocket)
        logger.info(f"Client connected: {client_id}")

        try:
            async for message in websocket:
                logger.debug(f"Received from {client_id}: {message}")
                await self.process_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client disconnected: {client_id}")
        finally:
            self.clients.discard(websocket)

    async def process_message(self, websocket, message: str):
        """Process incoming message"""
        try:
            msg = json.loads(message)
            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            if msg_type == "PING":
                response = self.simulator.create_message("PONG", {"timestamp": datetime.utcnow().isoformat() + "Z"})
                await websocket.send(response)

            elif msg_type == "COMMAND":
                command = data.get("command", "")
                logger.info(f"Command received: {command}")
                response = self.simulator.create_message("COMMAND_ACK", {
                    "command": command,
                    "status": "executed",
                    "result": "OK"
                })
                await websocket.send(response)

            elif msg_type == "CONFIG":
                logger.info(f"Config received: {data}")
                response = self.simulator.create_message("CONFIG_ACK", {
                    "section": data.get("section"),
                    "status": "applied"
                })
                await websocket.send(response)

            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received: {message}")
            error_response = self.simulator.create_message("ERROR", {
                "message": "Invalid JSON format"
            })
            await websocket.send(error_response)

    async def broadcast(self, message: str):
        """Broadcast message to all clients"""
        if self.clients:
            await asyncio.gather(
                *[client.send(message) for client in self.clients],
                return_exceptions=True
            )
            logger.debug(f"Broadcast to {len(self.clients)} clients")


# ============================================================================
# MAIN LOOP
# ============================================================================

async def run_simulator(simulator: RPi5Simulator, handler: WebSocketHandler):
    """Run the main simulation loop"""
    logger.info("Starting simulation loop...")

    frame_interval = 1.0 / 30  # 30 FPS target
    stats_interval = 1.0       # Update stats every second
    detection_interval = 0.5   # Update detections every 0.5 seconds

    last_frame_time = 0
    last_stats_time = 0
    last_detection_time = 0

    while simulator.running:
        current_time = time.time()

        # Send video frames
        if current_time - last_frame_time >= frame_interval:
            frame = simulator.get_frame()
            if frame:
                msg = simulator.create_message("VIDEO_FRAME", {
                    "frame": base64.b64encode(frame).decode('utf-8'),
                    "width": 640,
                    "height": 480
                })
                await handler.broadcast(msg)
            last_frame_time = current_time

        # Update and send stats
        if current_time - last_stats_time >= stats_interval:
            simulator.update_stats()
            stats = simulator.get_stats_dict()
            msg = simulator.create_message("METRICS_UPDATE", stats)
            await handler.broadcast(msg)
            last_stats_time = current_time

        # Generate and send detections
        if current_time - last_detection_time >= detection_interval:
            detections = simulator.generate_detections()
            for det in detections:
                msg = simulator.create_message("DETECTION", det)
                await handler.broadcast(msg)
            last_detection_time = current_time

        # Small sleep to prevent CPU spinning
        await asyncio.sleep(0.01)

    logger.info("Simulation loop ended")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="RPi5 Simulator for ProjectCortex")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="WebSocket port")
    parser.add_argument("--webcam", type=int, default=DEFAULT_WEBCAM, help="Webcam index")
    args = parser.parse_args()

    # Create simulator
    simulator = RPi5Simulator(port=args.port, webcam_index=args.webcam)

    # Start simulator
    if not simulator.start():
        logger.error("Failed to start simulator")
        return 1

    # Create handler
    handler = WebSocketHandler(simulator)

    # Start WebSocket server
    logger.info(f"Starting WebSocket server on port {args.port}...")
    async with serve(handler.handle_client, "0.0.0.0", args.port):
        logger.info(f"WebSocket server running on ws://localhost:{args.port}")

        # Run simulation
        await run_simulator(simulator, handler)

    # Cleanup
    simulator.stop()
    logger.info("RPi5 Simulator shutdown complete")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
