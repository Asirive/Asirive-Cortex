import cv2
import time

ESP32_CAM_STREAM_URL = "http://10.104.142.73/stream"

print(f"Attempting to connect to: {ESP32_CAM_STREAM_URL}")
print(f"OpenCV version: {cv2.__version__}")

# Try with default backend (CAP_ANY)
print("\nTrying with default backend (cv2.CAP_ANY)...")
cap_any = None
try:
    cap_any = cv2.VideoCapture(ESP32_CAM_STREAM_URL, cv2.CAP_ANY)
    if cap_any.isOpened():
        print("  SUCCESS: Connected with cv2.CAP_ANY.")
        # Try to grab a frame to be sure
        cap_any.set(cv2.CAP_PROP_POS_FRAMES, 0) # Rewind if it's a file-like stream
        time.sleep(0.5) # Give it a moment
        ret, frame = cap_any.read()
        if ret and frame is not None:
            print(f"  SUCCESS: Frame read successfully (shape: {frame.shape}).")
        else:
            print(f"  FAILURE: Could not read frame (ret={ret}, frame is None: {frame is None}).")
    else:
        print("  FAILURE: Could not connect with cv2.CAP_ANY (isOpened() is False).")
except Exception as e:
    print(f"  ERROR during cv2.CAP_ANY attempt: {e}")
finally:
    if cap_any is not None and cap_any.isOpened():
        cap_any.release()

# Try with FFMPEG backend
print("\nTrying with FFMPEG backend (cv2.CAP_FFMPEG)...")
cap_ffmpeg = None
try:
    cap_ffmpeg = cv2.VideoCapture(ESP32_CAM_STREAM_URL, cv2.CAP_FFMPEG)
    if cap_ffmpeg.isOpened():
        print("  SUCCESS: Connected with cv2.CAP_FFMPEG.")
        cap_ffmpeg.set(cv2.CAP_PROP_POS_FRAMES, 0)
        time.sleep(0.5)
        ret, frame = cap_ffmpeg.read()
        if ret and frame is not None:
            print(f"  SUCCESS: Frame read successfully (shape: {frame.shape}).")
        else:
            print(f"  FAILURE: Could not read frame (ret={ret}, frame is None: {frame is None}).")
    else:
        print("  FAILURE: Could not connect with cv2.CAP_FFMPEG (isOpened() is False).")
except Exception as e:
    print(f"  ERROR during cv2.CAP_FFMPEG attempt: {e}")
finally:
    if cap_ffmpeg is not None and cap_ffmpeg.isOpened():
        cap_ffmpeg.release()

# Try with GStreamer backend (if available, might error if not compiled in)
cap_gstreamer = None
try:
    print("\nTrying with GStreamer backend (cv2.CAP_GSTREAMER)...")
    cap_gstreamer = cv2.VideoCapture(ESP32_CAM_STREAM_URL, cv2.CAP_GSTREAMER)
    if cap_gstreamer.isOpened():
        print("  SUCCESS: Connected with cv2.CAP_GSTREAMER.")
        cap_gstreamer.set(cv2.CAP_PROP_POS_FRAMES, 0)
        time.sleep(0.5)
        ret, frame = cap_gstreamer.read()
        if ret and frame is not None:
            print(f"  SUCCESS: Frame read successfully (shape: {frame.shape}).")
        else:
            print(f"  FAILURE: Could not read frame (ret={ret}, frame is None: {frame is None}).")
    else:
        print("  FAILURE: Could not connect with cv2.CAP_GSTREAMER (isOpened() is False).")
except Exception as e:
    print(f"  ERROR trying GStreamer: {e}")
finally:
    if cap_gstreamer is not None and cap_gstreamer.isOpened():
        cap_gstreamer.release()

print("\nTest finished.")
