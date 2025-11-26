"""
Project-Cortex v2.0 - Procedural Sound Generator

Generates audio tones programmatically using numpy for use with spatial audio.
No external WAV files needed - creates beeps, pings, and alerts on-the-fly.

Sound Types:
- Beacon pings: Navigation guidance tones
- Proximity alerts: Escalating warning sounds
- Object indicators: Distinct tones for different object classes
- Feedback sounds: System status indicators

Author: Haziq (@IRSPlays)
"""

import numpy as np
from typing import Optional, Dict, Tuple
import io
import logging

logger = logging.getLogger("SoundGenerator")

# Try to import audio libraries
SCIPY_AVAILABLE = False
PYOPENAL_AVAILABLE = False

try:
    from scipy.io import wavfile
    SCIPY_AVAILABLE = True
except ImportError:
    pass

try:
    from openal import Buffer
    PYOPENAL_AVAILABLE = True
except ImportError:
    pass


class ProceduralSoundGenerator:
    """
    Generates audio tones programmatically.
    
    All sounds are created using mathematical waveforms (sine, square, saw)
    without requiring external audio files.
    
    Example:
        gen = ProceduralSoundGenerator()
        
        # Get a beacon ping sound
        wav_data = gen.generate_beacon_ping(frequency=880, duration_ms=150)
        
        # Get a proximity warning at danger level
        wav_data = gen.generate_proximity_alert("danger")
        
        # Get a unique tone for a specific object class
        wav_data = gen.generate_object_tone("person")
    """
    
    # Sample rate for all generated sounds
    SAMPLE_RATE = 44100
    
    # Frequency mappings for object classes (Hz)
    OBJECT_FREQUENCIES: Dict[str, int] = {
        # Vehicles - Low frequencies (urgent, attention-grabbing)
        "car": 200,
        "truck": 160,
        "bus": 140,
        "motorcycle": 220,
        "bicycle": 350,
        
        # People - Mid frequencies
        "person": 440,  # A4 note
        
        # Navigation - Higher frequencies
        "door": 523,    # C5
        "stairs": 587,  # D5
        "traffic light": 659,  # E5
        "stop sign": 698,     # F5
        
        # Furniture - Mid-low frequencies
        "chair": 330,   # E4
        "couch": 294,   # D4
        "bed": 262,     # C4
        "dining table": 311,  # D#4
        
        # Animals
        "dog": 500,
        "cat": 600,
        
        # Electronics
        "cell phone": 800,
        "laptop": 750,
        "tv": 700,
        
        # Default
        "default": 400,
    }
    
    # Proximity alert configurations
    PROXIMITY_CONFIGS = {
        "notice": {"freq": 400, "duration_ms": 200, "repeats": 1},
        "warning": {"freq": 600, "duration_ms": 150, "repeats": 2},
        "danger": {"freq": 800, "duration_ms": 100, "repeats": 3},
        "critical": {"freq": 1000, "duration_ms": 50, "repeats": 5},
    }
    
    def __init__(self, sample_rate: int = 44100):
        """
        Initialize the sound generator.
        
        Args:
            sample_rate: Audio sample rate in Hz (default: 44100)
        """
        self.sample_rate = sample_rate
        self._cache: Dict[str, bytes] = {}
    
    def _generate_sine_wave(
        self,
        frequency: float,
        duration_ms: int,
        amplitude: float = 0.5,
        fade_ms: int = 10
    ) -> np.ndarray:
        """
        Generate a pure sine wave tone.
        
        Args:
            frequency: Frequency in Hz
            duration_ms: Duration in milliseconds
            amplitude: Volume (0.0 to 1.0)
            fade_ms: Fade in/out duration in milliseconds
            
        Returns:
            numpy array of audio samples
        """
        num_samples = int(self.sample_rate * duration_ms / 1000)
        t = np.linspace(0, duration_ms / 1000, num_samples, False)
        
        # Generate sine wave
        wave = np.sin(2 * np.pi * frequency * t) * amplitude
        
        # Apply fade in/out to prevent clicks
        fade_samples = int(self.sample_rate * fade_ms / 1000)
        if fade_samples > 0 and fade_samples * 2 < num_samples:
            fade_in = np.linspace(0, 1, fade_samples)
            fade_out = np.linspace(1, 0, fade_samples)
            wave[:fade_samples] *= fade_in
            wave[-fade_samples:] *= fade_out
        
        return wave
    
    def _generate_square_wave(
        self,
        frequency: float,
        duration_ms: int,
        amplitude: float = 0.3,
        fade_ms: int = 10
    ) -> np.ndarray:
        """Generate a square wave (harsher, more attention-grabbing)."""
        num_samples = int(self.sample_rate * duration_ms / 1000)
        t = np.linspace(0, duration_ms / 1000, num_samples, False)
        
        # Generate square wave using sign of sine
        wave = np.sign(np.sin(2 * np.pi * frequency * t)) * amplitude
        
        # Apply fade
        fade_samples = int(self.sample_rate * fade_ms / 1000)
        if fade_samples > 0 and fade_samples * 2 < num_samples:
            fade_in = np.linspace(0, 1, fade_samples)
            fade_out = np.linspace(1, 0, fade_samples)
            wave[:fade_samples] *= fade_in
            wave[-fade_samples:] *= fade_out
        
        return wave
    
    def _generate_chirp(
        self,
        start_freq: float,
        end_freq: float,
        duration_ms: int,
        amplitude: float = 0.5
    ) -> np.ndarray:
        """Generate a frequency sweep (chirp) sound."""
        num_samples = int(self.sample_rate * duration_ms / 1000)
        t = np.linspace(0, duration_ms / 1000, num_samples, False)
        
        # Linear frequency sweep
        freq = np.linspace(start_freq, end_freq, num_samples)
        phase = 2 * np.pi * np.cumsum(freq) / self.sample_rate
        wave = np.sin(phase) * amplitude
        
        # Fade in/out
        fade_samples = int(self.sample_rate * 10 / 1000)
        if fade_samples > 0:
            fade_in = np.linspace(0, 1, fade_samples)
            fade_out = np.linspace(1, 0, fade_samples)
            wave[:fade_samples] *= fade_in
            wave[-fade_samples:] *= fade_out
        
        return wave
    
    def _to_wav_bytes(self, samples: np.ndarray) -> bytes:
        """Convert numpy samples to WAV bytes."""
        # Convert to 16-bit PCM
        audio_16bit = (samples * 32767).astype(np.int16)
        
        # Create WAV in memory
        buffer = io.BytesIO()
        
        if SCIPY_AVAILABLE:
            wavfile.write(buffer, self.sample_rate, audio_16bit)
        else:
            # Manual WAV header if scipy not available
            buffer.write(self._create_wav_header(len(audio_16bit)))
            buffer.write(audio_16bit.tobytes())
        
        return buffer.getvalue()
    
    def _create_wav_header(self, num_samples: int) -> bytes:
        """Create a minimal WAV file header."""
        import struct
        
        channels = 1
        bits_per_sample = 16
        byte_rate = self.sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        data_size = num_samples * channels * bits_per_sample // 8
        
        header = b'RIFF'
        header += struct.pack('<I', 36 + data_size)  # File size - 8
        header += b'WAVE'
        header += b'fmt '
        header += struct.pack('<I', 16)  # Subchunk1 size
        header += struct.pack('<H', 1)   # PCM format
        header += struct.pack('<H', channels)
        header += struct.pack('<I', self.sample_rate)
        header += struct.pack('<I', byte_rate)
        header += struct.pack('<H', block_align)
        header += struct.pack('<H', bits_per_sample)
        header += b'data'
        header += struct.pack('<I', data_size)
        
        return header
    
    # ========== PUBLIC API: Beacon Sounds ==========
    
    def generate_beacon_ping(
        self,
        frequency: int = 880,
        duration_ms: int = 150,
        amplitude: float = 0.5
    ) -> bytes:
        """
        Generate a navigation beacon ping sound.
        
        Args:
            frequency: Ping frequency in Hz (higher = closer feel)
            duration_ms: Duration of ping in milliseconds
            amplitude: Volume (0.0 to 1.0)
            
        Returns:
            WAV file bytes
        """
        cache_key = f"beacon_{frequency}_{duration_ms}_{amplitude}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        wave = self._generate_sine_wave(frequency, duration_ms, amplitude)
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    def generate_beacon_success(self) -> bytes:
        """Generate a success chime (target reached)."""
        cache_key = "beacon_success"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Rising two-tone chime
        tone1 = self._generate_sine_wave(523, 150, 0.4)  # C5
        silence = np.zeros(int(self.sample_rate * 0.05))
        tone2 = self._generate_sine_wave(659, 200, 0.5)  # E5
        
        wave = np.concatenate([tone1, silence, tone2])
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    def generate_beacon_searching(self) -> bytes:
        """Generate a searching indicator (slow pulse)."""
        cache_key = "beacon_searching"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Low, slow pulse
        wave = self._generate_sine_wave(330, 300, 0.3)
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    # ========== PUBLIC API: Proximity Alerts ==========
    
    def generate_proximity_alert(self, level: str) -> bytes:
        """
        Generate a proximity alert sound.
        
        Args:
            level: Alert level ("notice", "warning", "danger", "critical")
            
        Returns:
            WAV file bytes
        """
        cache_key = f"proximity_{level}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        config = self.PROXIMITY_CONFIGS.get(level, self.PROXIMITY_CONFIGS["warning"])
        
        # Generate repeated beeps
        beep = self._generate_square_wave(
            config["freq"],
            config["duration_ms"],
            amplitude=0.4
        )
        
        silence_duration = max(50, config["duration_ms"])
        silence = np.zeros(int(self.sample_rate * silence_duration / 1000))
        
        # Combine beeps with silences
        parts = []
        for i in range(config["repeats"]):
            parts.append(beep)
            if i < config["repeats"] - 1:
                parts.append(silence)
        
        wave = np.concatenate(parts)
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    # ========== PUBLIC API: Object Tones ==========
    
    def generate_object_tone(
        self,
        object_class: str,
        duration_ms: int = 500,
        amplitude: float = 0.4
    ) -> bytes:
        """
        Generate a unique tone for an object class.
        
        Args:
            object_class: YOLO class name (e.g., "person", "car")
            duration_ms: Duration in milliseconds
            amplitude: Volume (0.0 to 1.0)
            
        Returns:
            WAV file bytes
        """
        object_class = object_class.lower()
        cache_key = f"object_{object_class}_{duration_ms}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Get frequency for this class
        base_freq = self.OBJECT_FREQUENCIES.get(
            object_class,
            self.OBJECT_FREQUENCIES["default"]
        )
        
        # Create a more complex, identifiable tone
        # Main tone + slight harmonic
        main = self._generate_sine_wave(base_freq, duration_ms, amplitude)
        harmonic = self._generate_sine_wave(base_freq * 1.5, duration_ms, amplitude * 0.2)
        
        wave = main + harmonic
        # Normalize
        wave = wave / np.max(np.abs(wave)) * amplitude
        
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    def generate_object_tone_looping(
        self,
        object_class: str,
        loop_duration_ms: int = 1000
    ) -> bytes:
        """
        Generate a loopable tone for continuous object tracking.
        
        Args:
            object_class: YOLO class name
            loop_duration_ms: Total loop duration
            
        Returns:
            WAV file bytes (designed to loop seamlessly)
        """
        object_class = object_class.lower()
        cache_key = f"object_loop_{object_class}_{loop_duration_ms}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        base_freq = self.OBJECT_FREQUENCIES.get(
            object_class,
            self.OBJECT_FREQUENCIES["default"]
        )
        
        # Create a pulsing pattern (on-off-on-off)
        pulse_duration = loop_duration_ms // 4
        
        tone_on = self._generate_sine_wave(base_freq, pulse_duration, 0.4)
        tone_off = np.zeros(int(self.sample_rate * pulse_duration / 1000))
        
        wave = np.concatenate([tone_on, tone_off, tone_on, tone_off])
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    # ========== PUBLIC API: Feedback Sounds ==========
    
    def generate_startup_sound(self) -> bytes:
        """Generate system startup sound."""
        cache_key = "feedback_startup"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Rising chirp
        wave = self._generate_chirp(200, 800, 300, 0.4)
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    def generate_shutdown_sound(self) -> bytes:
        """Generate system shutdown sound."""
        cache_key = "feedback_shutdown"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Falling chirp
        wave = self._generate_chirp(800, 200, 300, 0.4)
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    def generate_error_sound(self) -> bytes:
        """Generate error indicator sound."""
        cache_key = "feedback_error"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Two low harsh tones
        tone = self._generate_square_wave(150, 150, 0.3)
        silence = np.zeros(int(self.sample_rate * 0.1))
        wave = np.concatenate([tone, silence, tone])
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    def generate_confirmation_sound(self) -> bytes:
        """Generate confirmation/acknowledgment sound."""
        cache_key = "feedback_confirm"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Quick high beep
        wave = self._generate_sine_wave(1000, 100, 0.4)
        wav_bytes = self._to_wav_bytes(wave)
        
        self._cache[cache_key] = wav_bytes
        return wav_bytes
    
    # ========== UTILITY ==========
    
    def clear_cache(self) -> int:
        """Clear the sound cache. Returns number of items cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        total_bytes = sum(len(v) for v in self._cache.values())
        return {
            "cached_sounds": len(self._cache),
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / 1024 / 1024, 2),
        }
    
    def save_to_file(self, wav_bytes: bytes, filepath: str) -> None:
        """Save generated WAV bytes to a file."""
        with open(filepath, 'wb') as f:
            f.write(wav_bytes)


# Global instance for easy access
_generator_instance: Optional[ProceduralSoundGenerator] = None

def get_sound_generator() -> ProceduralSoundGenerator:
    """Get the global sound generator instance."""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = ProceduralSoundGenerator()
    return _generator_instance


# ============================================================================
# Standalone Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Procedural Sound Generator Test")
    print("=" * 60)
    
    gen = ProceduralSoundGenerator()
    
    print("\nGenerating sounds...")
    
    # Test beacon sounds
    beacon_ping = gen.generate_beacon_ping(880, 150)
    print(f"✅ Beacon ping: {len(beacon_ping)} bytes")
    
    beacon_success = gen.generate_beacon_success()
    print(f"✅ Beacon success: {len(beacon_success)} bytes")
    
    # Test proximity alerts
    for level in ["notice", "warning", "danger", "critical"]:
        alert = gen.generate_proximity_alert(level)
        print(f"✅ Proximity {level}: {len(alert)} bytes")
    
    # Test object tones
    for obj_class in ["person", "car", "chair", "dog", "unknown"]:
        tone = gen.generate_object_tone(obj_class)
        print(f"✅ Object {obj_class}: {len(tone)} bytes")
    
    # Test feedback sounds
    startup = gen.generate_startup_sound()
    print(f"✅ Startup sound: {len(startup)} bytes")
    
    error = gen.generate_error_sound()
    print(f"✅ Error sound: {len(error)} bytes")
    
    print(f"\nCache stats: {gen.get_cache_stats()}")
    
    # Save a sample file
    print("\nSaving sample file...")
    gen.save_to_file(beacon_ping, "test_beacon_ping.wav")
    print("✅ Saved to test_beacon_ping.wav")
    
    print("\n✅ All tests passed!")
