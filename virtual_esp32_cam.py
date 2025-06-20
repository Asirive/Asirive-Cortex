#!/usr/bin/env python3
"""
Virtual ESP32 CAM Simulator
This simulates an ESP32 CAM stream for testing your Python application
"""

import cv2
import numpy as np
from flask import Flask, Response
import threading
import time

app = Flask(__name__)

class VirtualESP32CAM:
    def __init__(self):
        self.is_running = False
        
    def generate_test_frame(self):
        """Generate a test frame with timestamp"""
        # Create a 640x480 test image
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Add some colored rectangles
        cv2.rectangle(img, (50, 50), (200, 150), (0, 255, 0), -1)  # Green
        cv2.rectangle(img, (250, 100), (400, 200), (255, 0, 0), -1)  # Blue
        cv2.rectangle(img, (450, 150), (590, 250), (0, 0, 255), -1)  # Red
        
        # Add timestamp
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(img, f"Virtual ESP32 CAM", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.putText(img, timestamp, (10, 70), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # Add some moving elements
        t = time.time()
        x = int(320 + 100 * np.sin(t))
        y = int(240 + 50 * np.cos(t * 2))
        cv2.circle(img, (x, y), 20, (255, 255, 0), -1)
        
        return img
    
    def generate_frames(self):
        """Generate video frames"""
        while self.is_running:
            frame = self.generate_test_frame()
            
            # Encode frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            time.sleep(0.033)  # ~30 FPS

# Global camera instance
virtual_cam = VirtualESP32CAM()

@app.route('/')
def index():
    """Home page with embedded video"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Virtual ESP32-CAM</title>
    </head>
    <body>
        <h1>Virtual ESP32-CAM Stream</h1>
        <img src="/stream" style="width:640px;height:480px;">
        <p>This is a virtual ESP32 CAM simulation for testing.</p>
    </body>
    </html>
    '''

@app.route('/stream')
def video_feed():
    """Video streaming route"""
    virtual_cam.is_running = True
    return Response(virtual_cam.generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    print("Starting Virtual ESP32 CAM on http://192.168.1.100:80")
    print("Note: Change the IP in your Python code to http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
