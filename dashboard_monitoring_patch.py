"""
Monitoring Enhancement Patch for Cortex Dashboard
Adds comprehensive system monitoring and debug logging
"""

ENHANCED_LOGGING_SETUP = """
# Enhanced logging for debugging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
"""

ENHANCED_STATE_INIT = """
        self.state = {
            'last_frame': None,
            'latency': 0.0,
            'fps': 0.0,
            'ram_usage': 0.0,
            'cpu_usage': 0.0,
            'cpu_temp': 0.0,
            'disk_usage': 0.0,
            'network_sent': 0,
            'network_recv': 0,
            'camera_status': 'Initializing...',
            'frame_count': 0,
            'detections': 'No objects',
            'vision_mode': 'Text Prompts',
            'logs': deque(maxlen=10),
            'layers': {
                'reflex': {'active': False, 'msg': 'Loading...'},
                'thinker': {'active': False, 'msg': 'Loading...'},
                'guide': {'active': False, 'msg': 'Loading...'},
                'memory': {'active': False, 'msg': 'Loading...'}
            }
        }
        self.frame_times = deque(maxlen=30)
        self.last_network_io = psutil.net_io_counters()
"""

ENHANCED_CAMERA_INIT = """
        # Camera with comprehensive debug logging
        try:
            camera_index = int(os.getenv('CAMERA_INDEX', '0'))
            logger.debug(f"[CAMERA DEBUG] Attempting to open camera index: {camera_index}")
            self.add_log(f"📹 [VIDEO] Connecting to Camera {camera_index}...")
            
            self.cap = cv2.VideoCapture(camera_index)
            logger.debug(f"[CAMERA DEBUG] VideoCapture created, checking if opened...")
            
            if not self.cap.isOpened():
                logger.error(f"[CAMERA DEBUG] Camera {camera_index} failed to open")
                raise Exception(f"Camera {camera_index} not found")
                
            # Set and verify camera properties
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            
            actual_width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            actual_height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            backend = self.cap.getBackendName()
            
            logger.debug(f"[CAMERA DEBUG] Camera properties set:")
            logger.debug(f"  - Resolution: {actual_width}x{actual_height}")
            logger.debug(f"  - FPS: {actual_fps}")
            logger.debug(f"  - Backend: {backend}")
            
            # Test frame capture
            ret, test_frame = self.cap.read()
            if ret:
                logger.debug(f"[CAMERA DEBUG] Test frame captured successfully: shape={test_frame.shape}")
                self.state['camera_status'] = f'✅ Active ({int(actual_width)}x{int(actual_height)})'
            else:
                logger.error(f"[CAMERA DEBUG] Test frame capture failed")
                self.state['camera_status'] = '❌ Capture Failed'
                
            self.add_log(f"✅ [VIDEO] Camera {camera_index} connected ({int(actual_width)}x{int(actual_height)}@{int(actual_fps)}fps, {backend})")
        except Exception as e:
            self.add_log(f"❌ [VIDEO] Connection failed: {e}")
            logger.exception("Camera init failed")
            self.state['camera_status'] = f'❌ Error: {str(e)[:30]}'
"""

print(__doc__)
print("\n=== Patch Components ===\n")
print("1. Enhanced logging setup")
print("2. Comprehensive state tracking with system metrics")
print("3. Debug-enabled camera initialization")
print("4. System monitoring (CPU, Temp, Disk, Network)")
print("\nApply these changes to cortex_dashboard.py for full monitoring.")
