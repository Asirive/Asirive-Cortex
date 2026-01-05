"""
Camera Handler - Unified interface for OpenCV and Picamera2
Automatically detects RPi Camera Module and uses appropriate backend
"""
import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

class CameraHandler:
    """Unified camera interface supporting OpenCV VideoCapture and Picamera2."""
    
    def __init__(self, camera_index=0, width=640, height=480, fps=30):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.backend = None
        self.cap = None
        self.picam2 = None
        
        logger.info(f"🎥 Initializing CameraHandler (index={camera_index}, {width}x{height}@{fps}fps)")
        
        # Try Picamera2 first (RPi Camera Module support)
        if self._try_picamera2():
            logger.info("✅ Using Picamera2 backend (RPi Camera Module)")
            return
            
        # Fallback to OpenCV VideoCapture (USB cameras)
        if self._try_opencv():
            logger.info("✅ Using OpenCV VideoCapture backend (USB camera)")
            return
            
        raise Exception("No camera backend available")
    
    def _try_picamera2(self):
        """Try to initialize Picamera2 (for RPi Camera Module 3)."""
        try:
            from picamera2 import Picamera2
            
            logger.debug("[Picamera2] Attempting initialization...")
            self.picam2 = Picamera2()
            
            # Configure video mode
            config = self.picam2.create_video_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"},
                controls={"FrameRate": self.fps}
            )
            self.picam2.configure(config)
            
            # Start camera
            self.picam2.start()
            logger.debug("[Picamera2] Camera started successfully")
            
            # Test frame capture
            frame = self.picam2.capture_array()
            logger.debug(f"[Picamera2] Test frame captured: shape={frame.shape}")
            
            self.backend = "picamera2"
            return True
            
        except ImportError:
            logger.debug("[Picamera2] Library not available")
            return False
        except Exception as e:
            logger.debug(f"[Picamera2] Initialization failed: {e}")
            if self.picam2:
                try:
                    self.picam2.stop()
                except:
                    pass
                self.picam2 = None
            return False
    
    def _try_opencv(self):
        """Try to initialize OpenCV VideoCapture (for USB cameras)."""
        try:
            logger.debug(f"[OpenCV] Attempting VideoCapture({self.camera_index})...")
            self.cap = cv2.VideoCapture(self.camera_index)
            
            if not self.cap.isOpened():
                logger.debug(f"[OpenCV] Camera {self.camera_index} failed to open")
                return False
            
            # Set properties
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            
            # Test frame capture
            ret, frame = self.cap.read()
            if not ret:
                logger.debug("[OpenCV] Test frame capture failed")
                self.cap.release()
                self.cap = None
                return False
            
            logger.debug(f"[OpenCV] Test frame captured: shape={frame.shape}")
            self.backend = "opencv"
            return True
            
        except Exception as e:
            logger.debug(f"[OpenCV] Initialization failed: {e}")
            if self.cap:
                self.cap.release()
                self.cap = None
            return False
    
    def read(self):
        """
        Read a frame from the camera.
        
        Returns:
            tuple: (success: bool, frame: np.ndarray in BGR format)
        """
        if self.backend == "picamera2":
            try:
                # Capture frame in RGB888
                frame_rgb = self.picam2.capture_array()
                # Convert to BGR for OpenCV compatibility
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                return True, frame_bgr
            except Exception as e:
                logger.error(f"[Picamera2] Frame capture error: {e}")
                return False, None
                
        elif self.backend == "opencv":
            return self.cap.read()
            
        else:
            return False, None
    
    def isOpened(self):
        """Check if camera is opened."""
        if self.backend == "picamera2":
            return self.picam2 is not None
        elif self.backend == "opencv":
            return self.cap is not None and self.cap.isOpened()
        return False
    
    def release(self):
        """Release camera resources."""
        if self.backend == "picamera2" and self.picam2:
            logger.info("[Picamera2] Stopping camera...")
            self.picam2.stop()
            self.picam2 = None
        elif self.backend == "opencv" and self.cap:
            logger.info("[OpenCV] Releasing camera...")
            self.cap.release()
            self.cap = None
        self.backend = None
    
    def get(self, prop_id):
        """Get camera property (OpenCV compatible)."""
        if self.backend == "picamera2":
            # Map common properties
            if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
                return self.width
            elif prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
                return self.height
            elif prop_id == cv2.CAP_PROP_FPS:
                return self.fps
            return 0
        elif self.backend == "opencv":
            return self.cap.get(prop_id)
        return 0
    
    def getBackendName(self):
        """Get backend name."""
        return self.backend or "None"


# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    print("🧪 Testing CameraHandler...")
    try:
        cam = CameraHandler(camera_index=0, width=640, height=480)
        print(f"✅ Camera initialized: {cam.getBackendName()}")
        print(f"   Resolution: {cam.get(cv2.CAP_PROP_FRAME_WIDTH)}x{cam.get(cv2.CAP_PROP_FRAME_HEIGHT)}")
        
        # Capture 10 frames
        for i in range(10):
            ret, frame = cam.read()
            if ret:
                print(f"   Frame {i+1}: {frame.shape}")
            else:
                print(f"   Frame {i+1}: FAILED")
                break
        
        cam.release()
        print("✅ Test completed successfully")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
