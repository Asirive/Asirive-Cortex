#!/usr/bin/env python3
"""
Test script for RPi WebSocket Client - Standalone Test

This simulates the RPi sending data to the laptop server.
Run the laptop server first: python laptop/start_laptop_server.py

Then run this script to test the connection.

Author: Haziq (@IRSPlays)
Date: January 3, 2026
"""

import logging
import time
import random
from rpi_websocket_client import RPiWebSocketClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def simulate_metrics(client: RPiWebSocketClient):
    """Simulate sending metrics data."""
    fps = random.uniform(25, 35)
    latency = random.uniform(40, 80)
    ram_usage = random.uniform(2.0, 3.5)
    cpu = random.uniform(40, 80)
    battery = random.uniform(50, 100)
    
    layers = ["Layer 0 Guardian", "Layer 1 Learner", "Layer 2 Thinker", "Layer 3 Guide"]
    active_layer = random.choice(layers)
    
    client.send_metrics(
        fps=fps,
        latency_ms=latency,
        ram_usage_gb=ram_usage,
        ram_total_gb=4.0,
        cpu_usage_percent=cpu,
        battery_percent=battery,
        active_layer=active_layer
    )
    
    logger.info(f"📊 Sent metrics: FPS={fps:.1f}, Latency={latency:.1f}ms, RAM={ram_usage:.1f}GB")


def simulate_detections(client: RPiWebSocketClient):
    """Simulate sending detection data."""
    objects = [
        ["person", "car", "bicycle"],
        ["person", "chair", "laptop"],
        ["cup", "keyboard", "mouse"],
        ["phone", "book", "pen"],
        ["person", "backpack", "bottle"]
    ]
    
    detected = random.choice(objects)
    count = len(detected)
    merged = ", ".join(detected)
    modes = ["Prompt-Free", "Text Prompts", "Visual Prompts"]
    mode = random.choice(modes)
    
    client.send_detections(
        merged_detections=merged,
        detection_count=count,
        yoloe_mode=mode
    )
    
    logger.info(f"🎯 Sent detections: {merged} (Mode: {mode})")


def simulate_status(client: RPiWebSocketClient, message: str):
    """Simulate sending status update."""
    client.send_status("info", message)
    logger.info(f"📝 Sent status: {message}")


def main():
    """Main test function."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║          RPi WebSocket Client - Standalone Test              ║
║                                                              ║
║  This simulates the RPi sending data to laptop server.       ║
║                                                              ║
║  Make sure laptop server is running first:                   ║
║  python laptop/start_laptop_server.py                        ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Get server URL
    server_url = input("Enter laptop server URL [ws://192.168.0.171:8765]: ").strip()
    if not server_url:
        server_url = "ws://192.168.0.171:8765"
    
    print(f"\n🔌 Connecting to {server_url}...")
    
    # Create client
    client = RPiWebSocketClient(
        server_url=server_url,
        device_id="test_rpi_001",
        reconnect_interval=5,
        enable_metrics=True,
        enable_detections=True,
        enable_video=False,  # Disable video for this test
        enable_audio=True,
        enable_memory=True
    )
    
    # Set callbacks
    def on_connected():
        print("✅ Connected to laptop server!")
        simulate_status(client, "Test RPi client connected and ready")
    
    def on_disconnected():
        print("🔌 Disconnected from laptop server")
    
    def on_error(error):
        print(f"❌ Error: {error}")
    
    client.on_connected = on_connected
    client.on_disconnected = on_disconnected
    client.on_error = on_error
    
    # Start client
    client.start()
    
    print("\n⏳ Waiting for connection...")
    time.sleep(3)
    
    if not client.connected:
        print("\n⚠️  Not connected. Is laptop server running?")
        print("   Start it with: python laptop/start_laptop_server.py")
        response = input("\nPress Enter to retry or Ctrl+C to exit... ")
        time.sleep(2)
    
    print("\n🚀 Starting simulation loop...")
    print("   - Sending metrics every 2 seconds")
    print("   - Sending detections every 5 seconds")
    print("   - Press Ctrl+C to stop\n")
    
    try:
        iteration = 0
        while True:
            iteration += 1
            
            # Send metrics every iteration (2s)
            simulate_metrics(client)
            
            # Send detections every 5 seconds (every 2-3 iterations)
            if iteration % 3 == 0:
                simulate_detections(client)
            
            # Send audio event occasionally
            if iteration % 10 == 0:
                client.send_audio_event(
                    event="tts_started",
                    layer="Layer 2 Thinker",
                    text="Detected person ahead",
                    duration_ms=1500
                )
                logger.info("🎙️ Sent audio event")
            
            # Print statistics every 10 iterations
            if iteration % 10 == 0:
                stats = client.get_statistics()
                print(f"\n📊 Statistics:")
                print(f"   Connected: {stats['connected']}")
                print(f"   Messages Sent: {stats['messages_sent']}")
                print(f"   Messages Failed: {stats['messages_failed']}")
                print(f"   Messages Queued: {stats['messages_queued']}")
                print(f"   Connection Attempts: {stats['connection_attempts']}\n")
            
            time.sleep(2)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping test client...")
        client.stop()
        print("✅ Test completed!")
        
        # Final statistics
        stats = client.get_statistics()
        print(f"\n📊 Final Statistics:")
        print(f"   Messages Sent: {stats['messages_sent']}")
        print(f"   Messages Failed: {stats['messages_failed']}")
        print(f"   Connection Attempts: {stats['connection_attempts']}")


if __name__ == "__main__":
    main()
