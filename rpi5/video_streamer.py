"""
ZMQ Video Streamer - Sends video frames from RPi5 to Laptop

Uses single-part messages to avoid CONFLATE + multipart crash bug.
See: https://github.com/zeromq/libzmq/issues/3663

Author: Haziq (@IRSPlays)
Date: January 25, 2026
"""
import cv2
import zmq
import logging
import time
import socket
import struct

logger = logging.getLogger(__name__)

class VideoStreamer:
    """
    Streams video frames via ZeroMQ (PUB).
    
    Uses single-part messages with a simple header to avoid the
    CONFLATE + multipart assertion crash bug in libzmq.
    
    Message format: [4-byte topic length][topic bytes][jpeg data]
    """
    def __init__(self, host: str, port: int = 5555):
        self.host = host
        self.port = port
        self.frame_count = 0
        self.last_log_time = time.time()
        self.connected = False
        
        logger.info(f"[ZMQ-TX] Initializing VideoStreamer...")
        logger.info(f"[ZMQ-TX] Target: {host}:{port}")
        
        try:
            self.context = zmq.Context()
            logger.info(f"[ZMQ-TX] ZMQ Context created")
            
            self.socket = self.context.socket(zmq.PUB)
            logger.info(f"[ZMQ-TX] PUB socket created")
            
            # Optimization: Only keep 1 outgoing message in buffer (drop old frames)
            self.socket.setsockopt(zmq.SNDHWM, 1)
            logger.info(f"[ZMQ-TX] SNDHWM set to 1 (drop old frames)")
            
            # Set linger to 0 for clean shutdown
            self.socket.setsockopt(zmq.LINGER, 0)
            logger.info(f"[ZMQ-TX] LINGER set to 0")
            
            # NOTE: DO NOT use CONFLATE on PUB socket - it's only for SUB sockets
            # and even on SUB it crashes with multipart messages
            
            connect_str = f"tcp://{host}:{port}"
            logger.info(f"[ZMQ-TX] Connecting to {connect_str}...")
            self.socket.connect(connect_str)
            
            # ZMQ "slow joiner" problem: connection takes time to establish
            # Wait briefly to ensure connection is ready before sending
            time.sleep(0.5)
            
            self.hostname = socket.gethostname()
            self.connected = True
            logger.info(f"[ZMQ-TX] ✅ Connected! hostname={self.hostname}")
            logger.info(f"[ZMQ-TX] Ready to stream frames")
            
        except Exception as e:
            logger.error(f"[ZMQ-TX] ❌ Failed to initialize: {e}")
            self.connected = False
            raise

    def send_frame(self, frame, quality=80):
        """
        Compress and send frame as a single-part message.
        
        Message format: [4-byte topic length][topic bytes][jpeg data]
        This avoids the CONFLATE + multipart crash bug.
        """
        if not self.connected:
            return False
            
        try:
            # Compress to JPEG
            ret, jpg_buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            
            if not ret:
                logger.warning("[ZMQ-TX] Failed to encode frame to JPEG")
                return False
                
            frame_bytes = jpg_buffer.tobytes()
            topic_bytes = self.hostname.encode('utf-8')
            
            # Build single-part message: [topic_len (4 bytes)][topic][jpeg_data]
            # This avoids multipart which crashes with CONFLATE
            message = struct.pack('>I', len(topic_bytes)) + topic_bytes + frame_bytes
            
            # Send as single message (not multipart!)
            self.socket.send(message, zmq.NOBLOCK)
            
            self.frame_count += 1
            now = time.time()
            
            # Log first frame
            if self.frame_count == 1:
                logger.info(f"[ZMQ-TX] 🎉 First frame sent! size={len(frame_bytes)} bytes, topic={self.hostname}")
            
            # Log every 5 seconds
            if now - self.last_log_time > 5:
                logger.info(f"[ZMQ-TX] Frame #{self.frame_count} sent, size={len(frame_bytes)} bytes")
                self.last_log_time = now
                
            return True
            
        except zmq.Again:
            # Socket not ready, drop frame (this is expected with SNDHWM=1)
            logger.debug("[ZMQ-TX] Frame dropped (socket busy)")
            return False
        except Exception as e:
            logger.error(f"[ZMQ-TX] ❌ Send error: {e}")
            return False

    def close(self):
        """Clean shutdown"""
        logger.info(f"[ZMQ-TX] Closing... (sent {self.frame_count} frames)")
        try:
            if self.socket:
                self.socket.close()
            if self.context:
                self.context.term()
            logger.info("[ZMQ-TX] Closed successfully")
        except Exception as e:
            logger.error(f"[ZMQ-TX] Error during close: {e}")
