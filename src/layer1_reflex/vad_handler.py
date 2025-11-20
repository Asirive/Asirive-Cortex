"""
Layer 1: VAD Handler - Real-time Voice Activity Detection

This module handles real-time voice activity detection using Silero VAD.
Optimized for <100ms latency for speech detection on Raspberry Pi 5.

Key Features:
- Deep learning-based VAD (superior to WebRTC VAD)
- Streaming audio processing with VADIterator
- PyAudio callback integration for non-blocking capture
- Speech buffer management with start/end timestamps
- Thread-safe singleton pattern

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import logging
import time
import threading
from typing import Optional, Callable, List, Dict, Any
from queue import Queue
import numpy as np

try:
    import pyaudio
except ImportError:
    raise ImportError(
        "PyAudio not installed. Install with: pip install pyaudio\n"
        "On Windows, you may need: pip install pipwin; pipwin install pyaudio"
    )

try:
    from silero_vad import load_silero_vad, VADIterator
except ImportError:
    raise ImportError(
        "Silero VAD not installed. Install with: pip install silero-vad"
    )

logger = logging.getLogger(__name__)


class VADHandler:
    """
    Real-time voice activity detection handler using Silero VAD.
    
    This is part of Layer 1 (Reflex) - providing fast, offline voice detection
    for triggering speech recognition with <100ms latency target.
    """
    
    _instance = None  # Singleton pattern
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern to prevent multiple VAD instances."""
        if cls._instance is None:
            cls._instance = super(VADHandler, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 512,  # 32ms at 16kHz (Silero VAD window)
        threshold: float = 0.5,  # Speech probability threshold (0.0-1.0)
        min_speech_duration_ms: int = 250,  # Minimum speech duration to trigger
        min_silence_duration_ms: int = 300,  # Silence duration to end speech
        padding_duration_ms: int = 100,  # Add padding before/after speech
        on_speech_start: Optional[Callable] = None,
        on_speech_end: Optional[Callable[[np.ndarray], None]] = None
    ):
        """
        Initialize VAD handler.
        
        Args:
            sample_rate: Audio sample rate (16000 or 8000)
            chunk_size: Audio chunk size in samples (512 for 16kHz, 256 for 8kHz)
            threshold: Speech probability threshold (0.0-1.0)
                - 0.3 = Very sensitive (more false positives)
                - 0.5 = Balanced (recommended)
                - 0.7 = Less sensitive (fewer false positives)
            min_speech_duration_ms: Minimum speech duration to trigger callback
            min_silence_duration_ms: Silence duration to consider speech ended
            padding_duration_ms: Padding to add before/after detected speech
            on_speech_start: Callback when speech starts (no arguments)
            on_speech_end: Callback when speech ends (receives audio numpy array)
        """
        if self._initialized:
            logger.debug("VADHandler already initialized, skipping...")
            return
            
        logger.info("🎤 Initializing VAD Handler...")
        
        # Validate sample rate
        if sample_rate not in [8000, 16000]:
            raise ValueError("Sample rate must be 8000 or 16000 Hz")
        
        # Set chunk size based on sample rate
        if sample_rate == 16000 and chunk_size != 512:
            logger.warning(f"⚠️ Recommended chunk size for 16kHz is 512, got {chunk_size}")
        elif sample_rate == 8000 and chunk_size != 256:
            logger.warning(f"⚠️ Recommended chunk size for 8kHz is 256, got {chunk_size}")
        
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.padding_duration_ms = padding_duration_ms
        
        # Callbacks
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        
        # VAD model and iterator
        self.vad_model = None
        self.vad_iterator = None
        
        # PyAudio components
        self.pyaudio_instance = None
        self.audio_stream = None
        
        # State management
        self.is_listening = False
        self.is_speech_active = False
        self.speech_buffer = []
        self.padding_buffer = []  # Pre-speech padding
        
        # Threading
        self.audio_queue = Queue()
        self.processing_thread = None
        self.stop_event = threading.Event()
        
        # Performance tracking
        self.detection_times = []
        self.total_chunks_processed = 0
        self.total_speech_segments = 0
        
        logger.info(f"📋 VAD Config:")
        logger.info(f"   Sample Rate: {sample_rate} Hz")
        logger.info(f"   Chunk Size: {chunk_size} samples ({chunk_size/sample_rate*1000:.1f}ms)")
        logger.info(f"   Threshold: {threshold}")
        logger.info(f"   Min Speech Duration: {min_speech_duration_ms}ms")
        logger.info(f"   Min Silence Duration: {min_silence_duration_ms}ms")
        logger.info(f"   Padding Duration: {padding_duration_ms}ms")
        
        self._initialized = True
    
    def load_model(self) -> bool:
        """
        Load the Silero VAD model.
        
        Returns:
            True if model loaded successfully, False otherwise
        """
        if self.vad_model is not None:
            logger.info("✅ Silero VAD model already loaded")
            return True
            
        try:
            logger.info("⏳ Loading Silero VAD model...")
            start_time = time.time()
            
            # Load Silero VAD model (downloads on first use)
            self.vad_model = load_silero_vad(onnx=False)
            
            # Create VAD iterator for streaming
            self.vad_iterator = VADIterator(
                self.vad_model,
                sampling_rate=self.sample_rate,
                threshold=self.threshold,
                min_silence_duration_ms=self.min_silence_duration_ms
            )
            
            load_time = time.time() - start_time
            logger.info(f"✅ Silero VAD model loaded in {load_time:.2f}s")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to load Silero VAD model: {e}")
            return False
    
    def _audio_callback(self, in_data, frame_count, time_info, status_flags):
        """
        PyAudio callback for real-time audio capture.
        
        This runs in a separate thread managed by PyAudio.
        
        Args:
            in_data: Audio data as bytes
            frame_count: Number of frames
            time_info: Timing information
            status_flags: Status flags (overflow/underflow)
            
        Returns:
            Tuple (None, paContinue)
        """
        if status_flags:
            logger.debug(f"⚠️ Audio callback status flags: {status_flags}")
        
        # Convert bytes to numpy array
        audio_chunk = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Add to processing queue
        self.audio_queue.put(audio_chunk)
        
        return (None, pyaudio.paContinue)
    
    def _process_audio_chunks(self):
        """
        Process audio chunks from the queue in a separate thread.
        
        This performs VAD inference and manages speech buffers.
        """
        logger.info("🔄 Audio processing thread started")
        
        padding_chunks = int(self.padding_duration_ms / (self.chunk_size / self.sample_rate * 1000))
        min_speech_chunks = int(self.min_speech_duration_ms / (self.chunk_size / self.sample_rate * 1000))
        
        while not self.stop_event.is_set():
            try:
                # Get audio chunk from queue (with timeout)
                audio_chunk = self.audio_queue.get(timeout=0.1)
                
                start_time = time.time()
                
                # Run VAD inference
                speech_dict = self.vad_iterator(audio_chunk, return_seconds=True)
                
                detection_time = (time.time() - start_time) * 1000
                self.detection_times.append(detection_time)
                self.total_chunks_processed += 1
                
                # Manage padding buffer (for pre-speech audio)
                self.padding_buffer.append(audio_chunk)
                if len(self.padding_buffer) > padding_chunks:
                    self.padding_buffer.pop(0)
                
                # Check if speech detected
                if speech_dict:
                    if not self.is_speech_active:
                        # Speech started
                        self.is_speech_active = True
                        self.total_speech_segments += 1
                        
                        # Add padding from before speech started
                        self.speech_buffer.extend(self.padding_buffer)
                        
                        logger.info(f"🗣️ Speech started (chunk {self.total_chunks_processed})")
                        
                        # Trigger callback
                        if self.on_speech_start:
                            try:
                                self.on_speech_start()
                            except Exception as e:
                                logger.error(f"❌ Error in on_speech_start callback: {e}")
                    
                    # Add chunk to speech buffer
                    self.speech_buffer.append(audio_chunk)
                    
                    # Log speech segment info
                    logger.debug(f"🎤 Speech: {speech_dict}")
                
                elif self.is_speech_active:
                    # Speech ended (silence detected)
                    self.is_speech_active = False
                    
                    # Check if speech duration meets minimum
                    speech_duration_ms = len(self.speech_buffer) * (self.chunk_size / self.sample_rate * 1000)
                    
                    if speech_duration_ms >= self.min_speech_duration_ms:
                        # Valid speech segment
                        speech_audio = np.concatenate(self.speech_buffer)
                        
                        logger.info(
                            f"🎤 Speech ended: {speech_duration_ms:.0f}ms "
                            f"({len(speech_audio)} samples)"
                        )
                        
                        # Trigger callback
                        if self.on_speech_end:
                            try:
                                self.on_speech_end(speech_audio)
                            except Exception as e:
                                logger.error(f"❌ Error in on_speech_end callback: {e}")
                    else:
                        logger.debug(
                            f"⏭️ Ignoring short speech segment: {speech_duration_ms:.0f}ms < "
                            f"{self.min_speech_duration_ms}ms"
                        )
                    
                    # Clear speech buffer
                    self.speech_buffer = []
                
                self.audio_queue.task_done()
                
            except Exception as e:
                if not self.stop_event.is_set():
                    logger.error(f"❌ Error processing audio chunk: {e}")
        
        logger.info("🛑 Audio processing thread stopped")
    
    def start_listening(self, device_index: Optional[int] = None) -> bool:
        """
        Start listening for voice activity.
        
        Args:
            device_index: Input device index (None = default device)
            
        Returns:
            True if started successfully, False otherwise
        """
        if self.is_listening:
            logger.warning("⚠️ Already listening")
            return True
        
        if self.vad_model is None:
            logger.error("❌ VAD model not loaded. Call load_model() first.")
            return False
        
        try:
            logger.info("🎤 Starting VAD listening...")
            
            # Initialize PyAudio
            self.pyaudio_instance = pyaudio.PyAudio()
            
            # Open audio stream with callback
            self.audio_stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=1,  # Mono
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback
            )
            
            # Start processing thread
            self.stop_event.clear()
            self.processing_thread = threading.Thread(
                target=self._process_audio_chunks,
                daemon=True
            )
            self.processing_thread.start()
            
            # Start audio stream
            self.audio_stream.start_stream()
            self.is_listening = True
            
            logger.info("✅ VAD listening started")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start listening: {e}")
            self.stop_listening()
            return False
    
    def stop_listening(self):
        """Stop listening for voice activity."""
        if not self.is_listening:
            return
        
        logger.info("🛑 Stopping VAD listening...")
        
        try:
            # Stop processing thread
            self.stop_event.set()
            if self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=2.0)
            
            # Stop and close audio stream
            if self.audio_stream:
                if self.audio_stream.is_active():
                    self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None
            
            # Terminate PyAudio
            if self.pyaudio_instance:
                self.pyaudio_instance.terminate()
                self.pyaudio_instance = None
            
            # Reset VAD iterator
            if self.vad_iterator:
                self.vad_iterator.reset_states()
            
            # Clear buffers
            self.speech_buffer = []
            self.padding_buffer = []
            while not self.audio_queue.empty():
                self.audio_queue.get_nowait()
            
            self.is_listening = False
            self.is_speech_active = False
            
            logger.info("✅ VAD listening stopped")
            
        except Exception as e:
            logger.error(f"❌ Error stopping listening: {e}")
    
    def is_speech_detected(self) -> bool:
        """
        Check if speech is currently being detected.
        
        Returns:
            True if speech is active, False otherwise
        """
        return self.is_speech_active
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics.
        
        Returns:
            Dictionary with detection latency, chunk count, and segment count
        """
        if not self.detection_times:
            return {
                "total_chunks": self.total_chunks_processed,
                "total_segments": self.total_speech_segments,
                "avg_detection_ms": 0,
                "min_detection_ms": 0,
                "max_detection_ms": 0
            }
        
        return {
            "total_chunks": self.total_chunks_processed,
            "total_segments": self.total_speech_segments,
            "avg_detection_ms": np.mean(self.detection_times),
            "min_detection_ms": np.min(self.detection_times),
            "max_detection_ms": np.max(self.detection_times),
            "sample_rate": self.sample_rate,
            "chunk_size": self.chunk_size,
            "threshold": self.threshold
        }


# Convenience function for quick usage
def create_vad_handler(
    threshold: float = 0.5,
    on_speech_start: Optional[Callable] = None,
    on_speech_end: Optional[Callable[[np.ndarray], None]] = None
) -> VADHandler:
    """
    Factory function to create and load VADHandler instance.
    
    Args:
        threshold: Speech probability threshold (0.0-1.0)
        on_speech_start: Callback when speech starts
        on_speech_end: Callback when speech ends (receives audio array)
        
    Returns:
        Initialized VADHandler instance
    """
    vad = VADHandler(
        threshold=threshold,
        on_speech_start=on_speech_start,
        on_speech_end=on_speech_end
    )
    vad.load_model()
    return vad


if __name__ == "__main__":
    # Test the VADHandler
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("="*60)
    print("🧪 Testing VADHandler")
    print("="*60)
    
    # Track speech segments
    speech_count = 0
    
    def on_start():
        global speech_count
        speech_count += 1
        print(f"\n🗣️ Speech segment #{speech_count} started!")
    
    def on_end(audio: np.ndarray):
        duration_ms = len(audio) / 16000 * 1000
        print(f"🎤 Speech segment ended: {duration_ms:.0f}ms, {len(audio)} samples")
    
    # Test 1: Create and load VAD
    vad = create_vad_handler(
        threshold=0.5,
        on_speech_start=on_start,
        on_speech_end=on_end
    )
    
    # Test 2: Start listening
    print("\n📝 Test: Start listening (speak into microphone)")
    print("Press Ctrl+C to stop...")
    
    if vad.start_listening():
        try:
            # Listen for 30 seconds or until Ctrl+C
            for i in range(30):
                time.sleep(1)
                if vad.is_speech_detected():
                    print("🎤", end="", flush=True)
                else:
                    print(".", end="", flush=True)
        except KeyboardInterrupt:
            print("\n\n⏹️ Stopping...")
        finally:
            vad.stop_listening()
    
    # Test 3: Show stats
    print("\n\n📊 Performance Stats:")
    stats = vad.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    print(f"\n✅ VADHandler test complete!")
    print(f"Total speech segments detected: {speech_count}")
