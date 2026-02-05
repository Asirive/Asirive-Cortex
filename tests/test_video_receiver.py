import pytest
import zmq
import time
import struct
import numpy as np
import cv2
import threading
from laptop.server.video_receiver import VideoReceiver

def test_video_receiver_initialization():
    """Test that VideoReceiver initializes correctly."""
    receiver = VideoReceiver(port=5556)
    assert receiver.port == 5556
    assert receiver.running is False

def test_video_receiver_stream_lifecycle():
    """Test that VideoReceiver detects ACTIVE and LOST states."""
    status_updates = []
    def on_status(status):
        status_updates.append(status)
        
    # Use short timeout for faster test
    receiver = VideoReceiver(port=5557, timeout=1.0)
    receiver.on_status_change = on_status
    receiver.start()
    
    # Initially inactive
    assert not receiver.stream_active
    
    # 1. Simulate ACTIVE
    # Setup a sender
    context = zmq.Context()
    sender = context.socket(zmq.PUB)
    sender.connect("tcp://127.0.0.1:5557") # Connect to bound receiver
    
    time.sleep(0.5) # Wait for connection
    
    # Send a dummy JPEG frame
    topic = "cortex-video".encode('utf-8')
    # Dummy JPEG data (minimum valid JPEG-ish)
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    _, img_encoded = cv2.imencode('.jpg', img)
    image_data = img_encoded.tobytes()
    
    # Format: [4-byte topic length][topic bytes][jpeg data]
    msg = struct.pack('>I', len(topic)) + topic + image_data
    sender.send(msg)
    
    time.sleep(0.5) # Wait for processing
    
    assert receiver.stream_active
    assert "ACTIVE" in status_updates
    
    # 2. Simulate LOST
    time.sleep(1.5) # Wait for timeout (1.0s)
    
    assert not receiver.stream_active
    assert "LOST" in status_updates
    
    receiver.stop()
    sender.close()
    context.term()
