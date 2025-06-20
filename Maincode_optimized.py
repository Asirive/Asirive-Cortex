import os
import cv2
import tkinter as tk
from tkinter import scrolledtext, messagebox
import tkinter.font as tkFont
import threading
import queue
import time
import traceback
import platform
import requests
import numpy as np
import torch
from PIL import Image, ImageTk
import google.generativeai as genai
import pygame
import sounddevice as sd
from scipy.io.wavfile import write as write_wav
from gradio_client import Client as GradioClient, file as gradio_file
import shutil
import sys
import base64
from ultralytics import YOLO
from murf import Murf


# --- Configuration ---
GOOGLE_API_KEY = "AIzaSyBpvmKgr280xIXN0XL1YwkeUbiWEzwWXBw"
MURF_API_KEY = "ap2_2bc1ff2a-0e45-4c92-b440-93ba18a3eb32" # IMPORTANT: Replace with your actual Murf AI API key
genai.configure(api_key=GOOGLE_API_KEY)
GEMINI_MODEL_ID = "gemini-1.5-flash-latest"

DEFAULT_ESP32_CAM_IP = "192.168.51.73"

WHISPER_API_URL = "hf-audio/whisper-large-v3"
AUDIO_FILE_FOR_WHISPER = "temp_mic_input.wav"
TEMP_TTS_OUTPUT_FILE = "temp_tts_output.mp3" # Murf produces MP3


# --- Main Application Class ---
class App:
    def __init__(self, window, window_title):
        self.window = window
        self.window.title(window_title)

        # --- Model and State ---
        self.model = None
        self.last_detections = "nothing detected"
        self.esp32_ip = DEFAULT_ESP32_CAM_IP
        self.cap = None
        self.last_tts_file = None
        self.classes = {} # To be populated by the model
        self.use_webcam_fallback = False # Flag to control video source
        self.murf_client = None
        self.murf_voice_id = "en-US-ken" # A default voice from Murf documentation
        self.latest_frame_for_gemini = None # To hold the most recent frame for Gemini

        # --- Threading and Queues ---
        self.stop_event = threading.Event()
        self.frame_queue = queue.Queue(maxsize=2)          # For raw frames from ESP32
        self.processed_frame_queue = queue.Queue(maxsize=2) # For annotated frames for UI
        self.status_queue = queue.Queue()                   # For status updates for UI
        self.detection_queue = queue.Queue()                # For detection strings for logic

        # --- UI Elements ---
        self.canvas = None
        self.photo = None
        self.delay = 15  # ms between UI updates

        # --- Audio ---
        self.input_devices = {}
        self.output_devices = {}
        self.selected_input_device = tk.StringVar(self.window)
        self.selected_output_device = tk.StringVar(self.window)
        self.last_used_output_device = None
        self.recording_active = False
        self.audio_queue = queue.Queue()

        # --- Build UI ---
        self.init_ui()

        # --- Initialize Systems ---
        self.init_audio()
        self.init_yolo() # This will start the YOLO loading thread
        self.init_murf_tts()

        # --- Start Core Background Threads ---
        threading.Thread(target=self.video_capture_thread, daemon=True).start()
        threading.Thread(target=self.yolo_processing_thread, daemon=True).start()

        # --- Start UI Update Loops ---
        self.update_video()
        self.update_status()
        self.update_detections()

        # --- Graceful Shutdown ---
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)

    def init_ui(self):
        """Sets up the main UI layout."""
        # --- Main Frames ---
        top_frame = tk.Frame(self.window)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        video_frame = tk.Frame(self.window)
        video_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        controls_frame = tk.Frame(self.window)
        controls_frame.pack(fill=tk.X, padx=10, pady=5)

        # --- Top Frame: IP Config and Status ---
        ip_frame = tk.Frame(top_frame)
        ip_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(ip_frame, text="ESP32 IP:").pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(ip_frame, width=20)
        self.ip_entry.insert(0, self.esp32_ip)
        self.ip_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(ip_frame, text="Update IP", command=self.update_ip).pack(side=tk.LEFT)

        self.status_label = tk.Label(top_frame, text="Status: Initializing...", fg="blue")
        self.status_label.pack(side=tk.RIGHT)

        # --- Video Frame ---
        self.canvas = tk.Canvas(video_frame, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas_width = self.canvas.winfo_width()
        self.canvas_height = self.canvas.winfo_height()

        # --- Controls Frame ---
        # Query
        query_frame = tk.Frame(controls_frame)
        query_frame.pack(fill=tk.X, pady=5)
        tk.Label(query_frame, text="Query:").pack(side=tk.LEFT)
        self.input_entry = tk.Entry(query_frame)
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.send_query_btn = tk.Button(query_frame, text="Send", command=self.send_query)
        self.send_query_btn.pack(side=tk.RIGHT)

        # Response
        tk.Label(controls_frame, text="Gemini's Response:").pack(anchor=tk.W)
        self.response_text = scrolledtext.ScrolledText(controls_frame, height=6, wrap=tk.WORD)
        self.response_text.pack(fill=tk.X, expand=True)

        # Audio
        audio_frame = tk.Frame(controls_frame)
        audio_frame.pack(fill=tk.X, pady=5)

        self.record_btn = tk.Button(audio_frame, text="🎤 Record", command=self.toggle_recording)
        self.record_btn.pack(side=tk.LEFT, padx=5)
        self.play_tts_btn = tk.Button(audio_frame, text="🔊 Replay TTS", command=self.replay_last_tts)
        self.play_tts_btn.pack(side=tk.LEFT, padx=5)

        # Audio Devices
        device_frame = tk.Frame(controls_frame)
        device_frame.pack(fill=tk.X, pady=5)
        tk.Label(device_frame, text="Input:").pack(side=tk.LEFT)
        self.input_device_menu = tk.OptionMenu(device_frame, self.selected_input_device, "No devices")
        self.input_device_menu.pack(side=tk.LEFT, padx=5)
        tk.Label(device_frame, text="Output:").pack(side=tk.LEFT)
        self.output_device_menu = tk.OptionMenu(device_frame, self.selected_output_device, "No devices")
        self.output_device_menu.pack(side=tk.LEFT, padx=5)
        tk.Button(device_frame, text="🔄 Refresh", command=self.populate_audio_devices).pack(side=tk.LEFT, padx=5)

        # Debug
        self.debug_text = scrolledtext.ScrolledText(controls_frame, height=4, wrap=tk.WORD)
        self.debug_text.pack(fill=tk.X, expand=True, pady=(10,0))
        self.debug_print("UI Initialized.")

    def on_canvas_resize(self, event):
        """Handles canvas resize to update dimensions for video scaling."""
        self.canvas_width = event.width
        self.canvas_height = event.height

    def update_ip(self):
        """Updates the ESP32 IP address and triggers a reconnect."""
        new_ip = self.ip_entry.get().strip()
        if new_ip and new_ip != self.esp32_ip:
            self.esp32_ip = new_ip
            self.debug_print(f"IP address updated to: {self.esp32_ip}. Forcing reconnect attempt.")
            
            # Reset the fallback state to force a new attempt on the ESP32
            self.use_webcam_fallback = False
            
            # Force a quicker reconnect by releasing the current capture object, if any.
            if self.cap:
                self.cap.release()
                self.cap = None

    def init_yolo(self):
        """Starts the YOLO model loading process in a background thread."""
        self.status_queue.put("Status: Loading YOLO model...")
        threading.Thread(target=self._init_yolo_thread, daemon=True).start()

    def _init_yolo_thread(self):
        """Loads the YOLOv11 model, with fallback to CPU and error handling."""
        model_path = 'models/yolo11x.pt'
        self.status_queue.put(f"Status: Loading {os.path.basename(model_path)}...")
        
        try:
            if not os.path.exists(model_path):
                self.status_queue.put(f"Status: ERROR - Model not found.")
                self.debug_print(f"FATAL: Model file not found: {model_path}")
                return

            # --- Attempt to load on GPU first ---
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self.debug_print(f"Attempting to load YOLO model on device: {device}")
            
            self.model = YOLO(model_path)
            self.model.to(device)
            self.classes = self.model.names

            # --- Run a test inference to catch runtime errors (like NMS) early ---
            if device == 'cuda':
                self.debug_print("Running test inference on dummy frame to verify CUDA setup...")
                dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                self.model(dummy_frame, verbose=False) # verbose=False to avoid console spam

            self.status_queue.put("Status: YOLO model loaded.")
            self.debug_print(f"YOLO model '{os.path.basename(model_path)}' loaded successfully on device {device}.")

        except NotImplementedError:
            self.status_queue.put("Status: CUDA error! Falling back to CPU.")
            self.debug_print("CUDA NMS error detected! Falling back to CPU.")
            self.debug_print("See console for instructions to enable full GPU support.")
            
            # Print detailed instructions to the terminal for the user
            print("\n" + "="*40)
            print("--- GPU ACCELERATION WARNING ---")
            print("Your installation of PyTorch/torchvision lacks CUDA support for a key operation (NMS).")
            print("The application will now use the CPU, which may be significantly slower.")
            print("\nTo enable GPU acceleration, please reinstall PyTorch and torchvision with the")
            print("correct CUDA toolkit version. You can find the command on the PyTorch website:")
            print("https://pytorch.org/get-started/locally/")
            print("="*40 + "\n")

            try:
                # --- Retry loading on CPU ---
                self.debug_print("Attempting to load model on CPU...")
                self.model = YOLO(model_path)
                self.model.to('cpu')
                self.classes = self.model.names
                self.status_queue.put("Status: YOLO model loaded (CPU).")
                self.debug_print("YOLO model loaded successfully on CPU.")
            except Exception as cpu_e:
                self.status_queue.put("Status: FATAL - Model failed on CPU.")
                self.debug_print(f"FATAL: Failed to load model on CPU after CUDA fallback: {cpu_e}")
                traceback.print_exc()
                self.model = None

        except Exception as e:
            self.status_queue.put("Status: Critical Error! Model failed.")
            self.debug_print(f"FATAL: An unexpected error occurred while loading the YOLO model: {e}")
            traceback.print_exc()
            self.model = None

    def video_capture_thread(self):
        """
        Connects to the ESP32-CAM and continuously captures frames.
        If the ESP32 fails, it falls back to the system webcam.
        Puts raw frames into self.frame_queue.
        """
        while not self.stop_event.is_set():
            try:
                # --- Connection Logic: Only attempt if connection is lost ---
                if self.cap is None or not self.cap.isOpened():
                    
                    # 1. TRY ESP32 (if not in fallback mode)
                    if not self.use_webcam_fallback:
                        self.status_queue.put(f"Status: Connecting to {self.esp32_ip}...")
                        stream_url = f"http://{self.esp32_ip}/stream"
                        self.cap = cv2.VideoCapture(stream_url)
                        
                        if self.cap.isOpened():
                            self.status_queue.put("Status: Connected to ESP32-CAM.")
                            self.debug_print(f"Successfully connected to video stream at {stream_url}")
                        else:
                            # This handles cases where VideoCapture doesn't throw an error but fails to open.
                            self.debug_print(f"Failed to open ESP32-CAM stream at {stream_url}. Falling back to webcam.")
                            self.status_queue.put(f"Status: ESP32 failed. Using webcam.")
                            self.use_webcam_fallback = True
                            self.cap = None # Ensure cap is None before trying webcam

                    # 2. TRY WEBCAM (if ESP32 failed or we are in fallback mode)
                    if self.use_webcam_fallback:
                        self.status_queue.put("Status: Using system webcam.")
                        self.cap = cv2.VideoCapture(0) # 0 is usually the default webcam
                        if not self.cap.isOpened():
                            self.status_queue.put("Status: Webcam not found. Retrying...")
                            self.debug_print("FATAL: Could not open webcam.")
                            self.cap = None
                            time.sleep(5) # Wait before retrying the whole connection process
                            continue # Go to the start of the while loop
                        else:
                            self.debug_print("Successfully connected to system webcam.")

                # --- Frame Reading Logic ---
                if self.cap is None: # If all connection attempts failed in the block above
                    time.sleep(1)
                    continue

                ret, frame = self.cap.read()
                if not ret:
                    self.status_queue.put("Status: Stream lost. Reconnecting...")
                    self.debug_print("Frame read failed. Releasing capture.")
                    self.cap.release()
                    self.cap = None
                    time.sleep(1) # Wait a moment before trying to reconnect
                    continue

                # Store the latest frame for Gemini
                self.latest_frame_for_gemini = frame

                if not self.frame_queue.full():
                    self.frame_queue.put(frame)

            except Exception as e:
                self.debug_print(f"ERROR in video_capture_thread: {e}")
                self.status_queue.put(f"Status: Connection error. Retrying...")
                if self.cap:
                    self.cap.release()
                self.cap = None
                # If any error occurs, trigger the fallback for the next iteration
                self.use_webcam_fallback = True 
                time.sleep(5)

    def yolo_processing_thread(self):
        """
        Gets raw frames from self.frame_queue, performs YOLO detection,
        and puts annotated frames into self.processed_frame_queue.
        """
        while not self.stop_event.is_set():
            if self.model is None:
                time.sleep(0.5) # Wait for the model to load
                continue
            try:
                frame = self.frame_queue.get(timeout=1)

                # Perform inference
                results = self.model(frame, verbose=False)
                
                # The result object has a .plot() method to draw detections
                annotated_frame = results[0].plot()

                # Process detections
                detections = []
                for box in results[0].boxes:
                    if box.conf > 0.5: # Use a confidence threshold
                        class_id = int(box.cls)
                        class_name = self.classes[class_id]
                        detections.append(class_name)
                
                detections_str = ", ".join(sorted(list(set(detections)))) or "nothing"
                self.detection_queue.put(detections_str)

                # Put the annotated frame in the queue for the UI
                if not self.processed_frame_queue.full():
                    self.processed_frame_queue.put(annotated_frame)

            except queue.Empty:
                continue # This is normal if the video stream is slow
            except Exception as e:
                self.debug_print(f"ERROR in yolo_processing_thread: {e}")
                traceback.print_exc()
                time.sleep(1)

    def update_video(self):
        """Gets an annotated frame from the queue and displays it on the canvas."""
        try:
            frame = self.processed_frame_queue.get_nowait()

            # Resize frame to fit canvas while maintaining aspect ratio
            h, w, _ = frame.shape
            if self.canvas_width > 1 and self.canvas_height > 1: # ensure canvas is rendered
                aspect_ratio = w / h
                if self.canvas_width / self.canvas_height > aspect_ratio:
                    new_h = self.canvas_height
                    new_w = int(new_h * aspect_ratio)
                else:
                    new_w = self.canvas_width
                    new_h = int(new_w / aspect_ratio)
                
                resized_frame = cv2.resize(frame, (new_w, new_h))
                
                img = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(img)
                self.photo = ImageTk.PhotoImage(image=img)
                
                # Clear canvas and draw new image in the center
                self.canvas.delete("all")
                self.canvas.create_image(self.canvas_width // 2, self.canvas_height // 2, image=self.photo, anchor=tk.CENTER)

        except queue.Empty:
            pass # No new frame, do nothing
        finally:
            self.window.after(self.delay, self.update_video)

    def update_status(self):
        """Updates the status label from the status queue."""
        try:
            message = self.status_queue.get_nowait()
            self.status_label.config(text=message)
        except queue.Empty:
            pass
        finally:
            self.window.after(100, self.update_status)

    def update_detections(self):
        """Updates the last_detections variable from its queue."""
        try:
            self.last_detections = self.detection_queue.get_nowait()
        except queue.Empty:
            pass
        finally:
            self.window.after(100, self.update_detections)

    def init_audio(self):
        """Initializes pygame mixer and populates audio device lists."""
        try:
            pygame.mixer.init()
            self.debug_print("Pygame mixer initialized.")
        except Exception as e:
            self.debug_print(f"Error initializing pygame mixer: {e}")
            messagebox.showerror("Audio Error", "Could not initialize audio playback system (Pygame).")
        self.populate_audio_devices()

    def populate_audio_devices(self):
        """Queries sounddevice for available audio devices and updates the UI."""
        self.debug_print("Refreshing audio devices...")
        try:
            devices = sd.query_devices()
            self.input_devices = {f"{i}: {d['name']}": i for i, d in enumerate(devices) if d['max_input_channels'] > 0}
            self.output_devices = {f"{i}: {d['name']}": i for i, d in enumerate(devices) if d['max_output_channels'] > 0}

            # --- Input Devices ---
            input_menu = self.input_device_menu["menu"]
            input_menu.delete(0, "end")
            if self.input_devices:
                for name in self.input_devices.keys():
                    input_menu.add_command(label=name, command=lambda value=name: self.selected_input_device.set(value))
                # Try to set a reasonable default
                default_input = sd.default.device[0]
                default_input_name = f"{default_input}: {sd.query_devices(default_input)['name']}"
                if default_input_name in self.input_devices:
                    self.selected_input_device.set(default_input_name)
                else:
                    self.selected_input_device.set(list(self.input_devices.keys())[0])
            else:
                self.selected_input_device.set("No input devices found")

            # --- Output Devices ---
            output_menu = self.output_device_menu["menu"]
            output_menu.delete(0, "end")
            if self.output_devices:
                for name in self.output_devices.keys():
                    output_menu.add_command(label=name, command=lambda value=name: self.selected_output_device.set(value))
                # Try to set a reasonable default
                default_output = sd.default.device[1]
                default_output_name = f"{default_output}: {sd.query_devices(default_output)['name']}"
                if default_output_name in self.output_devices:
                    self.selected_output_device.set(default_output_name)
                else:
                    self.selected_output_device.set(list(self.output_devices.keys())[0])
            else:
                self.selected_output_device.set("No output devices found")
            self.debug_print("Audio devices populated.")

        except Exception as e:
            self.debug_print(f"Error populating audio devices: {e}")
            messagebox.showerror("Audio Error", f"Could not list audio devices.\n{e}")

    def toggle_recording(self):
        if self.recording_active:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        """Starts recording audio in a background thread."""
        try:
            device_name = self.selected_input_device.get()
            if not device_name or "No input devices" in device_name:
                messagebox.showerror("Audio Error", "Please select a valid input device.")
                return
            
            device_id = self.input_devices[device_name]
            self.debug_print(f"Starting recording on device: {device_name} (ID: {device_id})")
            
            self.recording_active = True
            self.record_btn.config(text="🛑 Stop Recording", relief=tk.SUNKEN)
            self.audio_queue = queue.Queue() # Clear previous audio data
            
            threading.Thread(target=self._record_audio_thread, args=(device_id,), daemon=True).start()
        except Exception as e:
            self.debug_print(f"Error starting recording: {e}")
            messagebox.showerror("Recording Error", f"Could not start recording.\n{e}")
            self.recording_active = False
            self.record_btn.config(text="🎤 Record", relief=tk.RAISED)

    def _record_audio_thread(self, device_id):
        """The actual audio recording loop running in a thread."""
        samplerate = 44100
        channels = 1
        
        def callback(indata, frames, time, status):
            if status:
                print(status, file=sys.stderr)
            self.audio_queue.put(indata.copy())

        with sd.InputStream(samplerate=samplerate, device=device_id, channels=channels, callback=callback):
            while self.recording_active:
                time.sleep(0.1)
        self.debug_print("Recording thread finished.")

    def stop_recording(self):
        """Stops the audio recording and processes the recorded audio."""
        if not self.recording_active:
            return
        
        self.recording_active = False
        self.record_btn.config(text="🎤 Record", relief=tk.RAISED)
        self.debug_print("Stopping recording...")

        # Give the recording thread a moment to stop and collect data
        time.sleep(0.2)

        audio_data = []
        while not self.audio_queue.empty():
            audio_data.append(self.audio_queue.get())
        
        if not audio_data:
            self.debug_print("No audio data recorded.")
            return

        self.debug_print(f"Collected {len(audio_data)} audio chunks.")
        audio_data = np.concatenate(audio_data, axis=0)
        samplerate = 44100
        
        # Save to file
        write_wav(AUDIO_FILE_FOR_WHISPER, samplerate, audio_data)
        self.debug_print(f"Audio saved to {AUDIO_FILE_FOR_WHISPER}")

        # Automatically send for transcription and processing
        self.process_recorded_audio()

    def process_recorded_audio(self):
        """Transcribes audio and sends it as a query."""
        self.status_queue.put("Status: Transcribing audio...")
        try:
            self.debug_print(f"Transcribing {AUDIO_FILE_FOR_WHISPER} using {WHISPER_API_URL}...")
            # Using Gradio Client for Whisper, with the updated API structure
            client = GradioClient(WHISPER_API_URL)
            
            # The API now expects 'inputs' and 'task' as keyword arguments.
            result = client.predict(
                inputs=gradio_file(AUDIO_FILE_FOR_WHISPER),
                task="transcribe",
                api_name="/predict"
            )
            
            if isinstance(result, str):
                transcribed_text = result
            else:
                 # If the API returns a tuple/list, assume the text is the first element
                transcribed_text = str(result[0]) if isinstance(result, (list, tuple)) and result else ""

            self.debug_print(f"Whisper transcription: '{transcribed_text}'")
            
            if transcribed_text:
                self.input_entry.delete(0, tk.END)
                self.input_entry.insert(0, transcribed_text)
                self.send_query() # Automatically send the transcribed text
            else:
                self.debug_print("Whisper returned empty transcription.")
                self.status_queue.put("Status: Transcription was empty.")

        except Exception as e:
            self.debug_print(f"Error during Whisper transcription: {e}")
            self.status_queue.put("Status: Error in transcription.")
            messagebox.showerror("Transcription Error", f"Could not transcribe audio.\n{e}")

    def send_query(self):
        """Sends the user's query, current context, and video frame to the Gemini model."""
        query = self.input_entry.get()
        if not query:
            messagebox.showwarning("Input Error", "Please enter a query.")
            return

        if self.latest_frame_for_gemini is None:
            self.debug_print("Gemini query sent without an image.")
            messagebox.showwarning("Video Error", "No video frame available to send yet.")
            return

        self.status_queue.put("Status: Thinking...")
        self.response_text.delete('1.0', tk.END)

        # Pass a copy of the frame to the thread to avoid race conditions
        frame_copy = self.latest_frame_for_gemini.copy()
        
        # Run Gemini call in a thread to avoid blocking UI
        threading.Thread(target=self._send_query_thread, args=(query, frame_copy), daemon=True).start()

    def _send_query_thread(self, query, frame):
        """Handles the Gemini API call with text and an image."""
        try:
            self.debug_print("Preparing image for Gemini...")
            # Convert OpenCV BGR frame to PIL RGB Image, which the API expects
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(rgb_frame)

            # The context now instructs the model to analyze the image
            context = f"You are a helpful assistant. The user is looking at a live video feed. The user's query is: '{query}'. Based on the image, provide a detailed response."
            
            self.debug_print(f"Sending query and video frame to Gemini...")
            
            model = genai.GenerativeModel(GEMINI_MODEL_ID)
            # Send both the text prompt and the image to the model
            response = model.generate_content([context, img_pil])
            
            self.response_text.insert(tk.END, response.text)
            self.status_queue.put("Status: Response received.")
            
            # Generate and play TTS
            self.generate_and_play_tts(response.text)

        except Exception as e:
            self.debug_print(f"Error with Gemini API: {e}")
            self.status_queue.put("Status: Error with Gemini API.")
            self.response_text.insert(tk.END, f"An error occurred: {e}")
            traceback.print_exc()

    def init_murf_tts(self):
        """Initializes the Murf TTS service."""
        if not MURF_API_KEY or "YOUR_MURF_API_KEY" in MURF_API_KEY:
            self.debug_print("Murf API key not set. TTS will be disabled.")
            self.status_queue.put("Status: Murf TTS disabled (no API key).")
            return

        self.status_queue.put("Status: Initializing Murf TTS...")
        threading.Thread(target=self._init_murf_thread, daemon=True).start()

    def _init_murf_thread(self):
        """Background thread to initialize Murf TTS to avoid blocking UI."""
        try:
            self.debug_print("Initializing Murf AI client...")
            self.murf_client = Murf(api_key=MURF_API_KEY)
            # Simple client doesn't support listing voices, so we use a known good one.
            self.debug_print(f"Murf TTS initialized. Using voice ID: {self.murf_voice_id}")
            self.status_queue.put("Status: Murf TTS ready.")

        except Exception as e:
            self.debug_print(f"Error initializing Murf TTS: {e}")
            self.status_queue.put("Status: Murf TTS initialization failed.")
            self.murf_client = None

    def generate_and_play_tts(self, text):
        """Generates TTS audio from text using Murf AI SDK and plays it."""
        if not self.murf_client:
            self.debug_print("Murf TTS client not available. Skipping TTS.")
            self.status_queue.put("Status: TTS skipped (service unavailable).")
            return

        self.status_queue.put("Status: Generating speech with Murf AI...")
        # Run in a thread to avoid blocking UI
        threading.Thread(target=self._generate_murf_tts_thread, args=(text,), daemon=True).start()

    def _generate_murf_tts_thread(self, text):
        """Handles the Murf TTS generation in a background thread."""
        try:
            self.debug_print(f"Sending text to Murf TTS: \"{text[:50]}...\"")

            response = self.murf_client.text_to_speech.generate(
                text=text,
                voice_id=self.murf_voice_id,
                style="Conversational",
                format="mp3",
                sample_rate=44100
            )

            audio_url = response.audio_file
            self.debug_print(f"Murf TTS audio URL received.")

            # Download the audio file
            audio_response = requests.get(audio_url, stream=True)
            audio_response.raise_for_status() # Raise an exception for bad status codes

            self.last_tts_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), TEMP_TTS_OUTPUT_FILE)
            with open(self.last_tts_file, 'wb') as f:
                shutil.copyfileobj(audio_response.raw, f)
            
            del audio_response # Free up connection

            self.debug_print(f"Murf TTS audio saved to {self.last_tts_file}")
            self.status_queue.put("Status: Playing speech...")
            self.play_audio_file(self.last_tts_file)

        except Exception as e:
            self.debug_print(f"Error during Murf TTS generation/playback: {e}")
            self.status_queue.put("Status: Error in Murf TTS.")
            traceback.print_exc()

    def play_audio_file(self, file_path):
        """Plays an audio file using pygame.mixer.Sound to avoid file locking issues."""
        if not file_path or not os.path.exists(file_path):
            self.debug_print("TTS file not found, cannot play.")
            return

        try:
            # Ensure the mixer is initialized and on the correct device.
            # This logic is crucial for allowing dynamic output device switching.
            selected_device_name = self.selected_output_device.get()
            if selected_device_name and "No output devices" not in selected_device_name:
                if selected_device_name != self.last_used_output_device:
                    self.debug_print(f"Changing output device to: {selected_device_name}")
                    pygame.mixer.quit()
                    # Pygame needs the device name string, not the full name from sounddevice.
                    # e.g., "Speakers (Realtek(R) Audio)" instead of "1: Speakers (Realtek(R) Audio)"
                    device_name_for_pygame = selected_device_name.split(': ', 1)[1]
                    pygame.mixer.init(devicename=device_name_for_pygame)
                    self.last_used_output_device = selected_device_name
            
            # Stop any sound that is currently playing to prevent overlap.
            pygame.mixer.stop()

            # Load the audio file into a Sound object.
            # This loads the data into memory and immediately releases the file lock.
            sound = pygame.mixer.Sound(file_path)
            sound.play()
            
            self.debug_print(f"Playing audio on {self.last_used_output_device or 'default'}")

        except Exception as e:
            self.debug_print(f"Error playing audio with pygame: {e}")
            traceback.print_exc() # Print full traceback for better debugging
            messagebox.showerror("Playback Error", f"Could not play audio.\n{e}")

    def replay_last_tts(self):
        """Replays the last generated TTS audio."""
        self.play_audio_file(self.last_tts_file)

    def debug_print(self, msg):
        """Prints a message to the debug text area in a thread-safe way."""
        def _update_debug_text():
            self.debug_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {msg}\n")
            self.debug_text.see(tk.END)
        # Schedule the UI update to run in the main thread
        if self.window.winfo_exists():
            self.window.after(0, _update_debug_text)

    def on_closing(self):
        """Handles window closing event."""
        self.debug_print("Closing application...")
        self.stop_event.set()
        if self.cap:
            self.cap.release()
        pygame.mixer.quit()
        self.window.destroy()

# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root, "ASG YOLOv11 Gemini Vision Assistant")
    root.mainloop()
