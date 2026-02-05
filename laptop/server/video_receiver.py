"""
ZMQ Video Receiver - Receives video frames from RPi5 on Laptop

Uses single-part messages to avoid CONFLATE + multipart crash bug.
See: https://github.com/zeromq/libzmq/issues/3663

Author: Haziq (@IRSPlays)
Date: January 25, 2026
"""
import zmq
import numpy as np
import cv2
import logging
import threading
import time
import struct
from typing import Optional, Callable

logger = logging.getLogger(__name__)

class VideoReceiver:
    """
    Receives video frames from RPi5 via ZeroMQ (PUB/SUB).
    Runs in a background thread to avoid blocking the main thread.
    
    Uses single-part messages with a simple header to avoid the
    CONFLATE + multipart assertion crash bug in libzmq.
    
    Message format: [4-byte topic length][topic bytes][jpeg data]
    """
    def __init__(self, port: int = 5555, on_frame: Optional[Callable] = None, timeout: float = 3.0):
        self.port = port
        self.on_frame = on_frame
        self.on_status_change: Optional[Callable[[str], None]] = None
        self.timeout = timeout
        self.running = False
        self.thread = None
        
        # ZMQ Context
        self.context = None
        self.socket = None
        
        # Stats
        self.fps = 0.0
        self.last_frame_time = 0.0
        self.frame_count = 0
        self.last_log_time = time.time()
        self.stream_active = False
        
        logger.info(f"[ZMQ-RX] VideoReceiver initialized (port={port}, timeout={timeout}s)")
        
    def start(self):
        """Start receiver thread"""
        if self.running:
            logger.warning("[ZMQ-RX] Already running, ignoring start()")
            return
        
        logger.info("[ZMQ-RX] Starting receiver...")
        
        try:
            self.context = zmq.Context()
            logger.info("[ZMQ-RX] ZMQ Context created")
            
            self.socket = self.context.socket(zmq.SUB)
            logger.info("[ZMQ-RX] SUB socket created")
            
            # CRITICAL: Do NOT use CONFLATE with multipart messages - it crashes!
            # Use RCVHWM instead to limit buffer size
            self.socket.setsockopt(zmq.RCVHWM, 1)
            logger.info("[ZMQ-RX] RCVHWM set to 1 (keep only latest frame)")
            
            # Set linger to 0 for clean shutdown
            self.socket.setsockopt(zmq.LINGER, 0)
            logger.info("[ZMQ-RX] LINGER set to 0")
            
            # Subscribe to all topics (empty string = all)
            self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
            logger.info("[ZMQ-RX] Subscribed to all topics")
            
            # Bind to receive connections from RPi5
            bind_addr = f"tcp://0.0.0.0:{self.port}"
            self.socket.bind(bind_addr)
            logger.info(f"[ZMQ-RX] ✅ Bound to {bind_addr}")
            
            self.running = True
            self.thread = threading.Thread(target=self._receive_loop, daemon=True, name="ZMQ-VideoReceiver")
            self.thread.start()
            logger.info("[ZMQ-RX] Receiver thread started")
            
        except zmq.ZMQError as e:
            logger.error(f"[ZMQ-RX] ❌ Failed to start: {e}")
            raise
        except Exception as e:
            logger.error(f"[ZMQ-RX] ❌ Unexpected error: {e}")
            raise
        
    def stop(self):
        """Stop receiver"""
        logger.info(f"[ZMQ-RX] Stopping... (received {self.frame_count} frames)")
        self.running = False
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            if self.thread.is_alive():
                logger.warning("[ZMQ-RX] Thread did not stop gracefully")
        
        if self.socket:
            try:
                self.socket.close()
                logger.info("[ZMQ-RX] Socket closed")
            except Exception as e:
                logger.error(f"[ZMQ-RX] Error closing socket: {e}")
                
        if self.context:
            try:
                self.context.term()
                logger.info("[ZMQ-RX] Context terminated")
            except Exception as e:
                logger.error(f"[ZMQ-RX] Error terminating context: {e}")
                
        logger.info("[ZMQ-RX] Stopped")
            
    def _receive_loop(self):
        """Main receive loop with robust error handling and timeout detection"""
        logger.info("[ZMQ-RX] 🧵 Receive loop started, waiting for frames...")
        
        # Reset stats
        self.last_frame_time = time.time()
        self.stream_active = False

        while self.running:
            try:
                # Poll with timeout to allow checking self.running and stream timeout
                if not self.socket.poll(100):  # 100ms timeout
                    # Check for stream timeout
                    if self.stream_active and (time.time() - self.last_frame_time > self.timeout):
                        self.stream_active = False
                        logger.warning(f"[ZMQ-RX] ⚠️ Stream lost (no frames for {self.timeout}s)")
                        if self.on_status_change:
                            try:
                                self.on_status_change("LOST")
                            except Exception as e:
                                logger.error(f"Error in on_status_change callback: {e}")
                    continue
                    
                # Receive single-part message (not multipart!)
                message = self.socket.recv(zmq.NOBLOCK)
                now = time.time()
                
                if len(message) < 4:
                    logger.warning(f"[ZMQ-RX] Message too short: {len(message)} bytes")
                    continue
                
                # Parse message: [4-byte topic length][topic bytes][jpeg data]
                topic_len = struct.unpack('>I', message[:4])[0]
                
                if len(message) < 4 + topic_len:
                    logger.warning(f"[ZMQ-RX] Malformed message: topic_len={topic_len}, msg_len={len(message)}")
                    continue
                
                # Update stream status if restored
                if not self.stream_active:
                    self.stream_active = True
                    logger.info("[ZMQ-RX] ✅ Stream restored/active")
                    if self.on_status_change:
                        try:
                            self.on_status_change("ACTIVE")
                        except Exception as e:
                            logger.error(f"Error in on_status_change callback: {e}")
                    
                topic = message[4:4+topic_len].decode('utf-8', errors='replace')
                image_data = message[4+topic_len:]
                
                self.frame_count += 1
                
                # Log first frame immediately
                if self.frame_count == 1:
                    logger.info(f"[ZMQ-RX] 🎉 First frame received! topic='{topic}', size={len(image_data)} bytes")
                
                # Log every 5 seconds
                if now - self.last_log_time > 5:
                    fps_str = f"{self.fps:.1f}" if self.fps > 0 else "calculating..."
                    logger.info(f"[ZMQ-RX] Frame #{self.frame_count}, size={len(image_data)} bytes, fps={fps_str}")
                    self.last_log_time = now
                
                # Decode JPEG to numpy array
                frame = cv2.imdecode(np.frombuffer(image_data, dtype='uint8'), cv2.IMREAD_COLOR)
                
                if frame is not None:
                    # Call the callback if provided
                    if self.on_frame:
                        try:
                            self.on_frame(frame)
                        except Exception as e:
                            logger.error(f"[ZMQ-RX] Error in on_frame callback: {e}")
                    
                    # Update FPS stats (exponential moving average)
                    dt = now - self.last_frame_time
                    if dt > 0 and dt < 10:  # Ignore unreasonable deltas
                        self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)
                    self.last_frame_time = now
                else:
                    logger.warning(f"[ZMQ-RX] Failed to decode JPEG ({len(image_data)} bytes)")
                    
            except zmq.Again:
                # No message available (expected with NOBLOCK)
                continue
            except zmq.ZMQError as e:
                if self.running:
                    logger.error(f"[ZMQ-RX] ZMQ error: {e}")
                    time.sleep(0.1)
            except Exception as e:
                if self.running:
                    logger.error(f"[ZMQ-RX] Unexpected error: {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
                    time.sleep(0.1)
                    
        logger.info("[ZMQ-RX] 🧵 Receive loop exiting")
