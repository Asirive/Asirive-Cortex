"""
Base Worker Class for Project Cortex
=====================================

Provides common functionality for all worker processes:
- CPU pinning
- Signal handling
- Logging
- Health monitoring
- Graceful shutdown

Author: Project Cortex Team
Date: 2025
"""

import os
import sys
import signal
import logging
import time
from abc import ABC, abstractmethod
from multiprocessing import Process, Event, Value
from typing import Optional
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from frame_queue import SharedFrameBuffer


# Configure logging
def setup_worker_logging(worker_name: str, level: int = logging.INFO) -> logging.Logger:
    """Set up logging for a worker process."""
    logger = logging.getLogger(worker_name)
    logger.setLevel(level)
    
    # Console handler with custom format
    handler = logging.StreamHandler()
    handler.setLevel(level)
    formatter = logging.Formatter(
        f'[%(asctime)s] [{worker_name}] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


class BaseWorker(ABC):
    """
    Abstract base class for all worker processes.
    
    Provides:
    - CPU pinning for optimal performance
    - Signal handling for graceful shutdown
    - Health monitoring with heartbeat
    - Configurable logging
    
    Usage:
        class MyWorker(BaseWorker):
            def setup(self):
                self.model = load_model()
            
            def process_frame(self, frame, metadata):
                return self.model.predict(frame)
            
            def cleanup(self):
                del self.model
        
        worker = MyWorker(name="my_worker", cpu_core=1)
        worker.start()
    """
    
    def __init__(
        self,
        name: str,
        cpu_core: int,
        frame_buffer_name: str = "cortex_frames",
        worker_id: int = 0,
        log_level: int = logging.INFO
    ):
        """
        Initialize the worker.
        
        Args:
            name: Human-readable worker name
            cpu_core: CPU core to pin this worker to (0-3 on RPi 5)
            frame_buffer_name: Name of the SharedFrameBuffer to attach to
            worker_id: Unique ID for this worker (1=Guardian, 2=Learner, 3=Camera)
            log_level: Logging level
        """
        self.name = name
        self.cpu_core = cpu_core
        self.frame_buffer_name = frame_buffer_name
        self.worker_id = worker_id
        self.log_level = log_level
        
        # Process control
        self._stop_event = Event()
        self._ready_event = Event()
        self._process: Optional[Process] = None
        
        # Health monitoring
        self._last_heartbeat = Value('d', 0.0)  # Unix timestamp
        self._frames_processed = Value('i', 0)
        self._total_latency_ms = Value('d', 0.0)
        
        # Will be set in worker process
        self.logger: Optional[logging.Logger] = None
        self.frame_buffer: Optional[SharedFrameBuffer] = None
    
    def start(self, write_index=None, slot_locks=None) -> None:
        """
        Start the worker process.
        
        Args:
            write_index: SharedFrameBuffer write index (from parent)
            slot_locks: SharedFrameBuffer slot locks (from parent)
        """
        self._process = Process(
            target=self._run,
            args=(write_index, slot_locks),
            name=self.name
        )
        self._process.start()
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the worker process gracefully.
        
        Args:
            timeout: Maximum time to wait for graceful shutdown
        """
        self._stop_event.set()
        
        if self._process and self._process.is_alive():
            self._process.join(timeout=timeout)
            
            if self._process.is_alive():
                # Force kill if still running
                self._process.terminate()
                self._process.join(timeout=1.0)
    
    def is_alive(self) -> bool:
        """Check if the worker process is running."""
        return self._process is not None and self._process.is_alive()
    
    def is_ready(self) -> bool:
        """Check if the worker has completed setup and is ready."""
        return self._ready_event.is_set()
    
    def wait_ready(self, timeout: float = 30.0) -> bool:
        """
        Wait for the worker to be ready.
        
        Args:
            timeout: Maximum time to wait
            
        Returns:
            True if ready, False if timeout
        """
        return self._ready_event.wait(timeout=timeout)
    
    def get_stats(self) -> dict:
        """Get worker statistics."""
        frames = self._frames_processed.value
        total_latency = self._total_latency_ms.value
        
        return {
            "name": self.name,
            "worker_id": self.worker_id,
            "cpu_core": self.cpu_core,
            "is_alive": self.is_alive(),
            "is_ready": self.is_ready(),
            "frames_processed": frames,
            "avg_latency_ms": total_latency / frames if frames > 0 else 0,
            "last_heartbeat": self._last_heartbeat.value,
            "heartbeat_age_s": time.time() - self._last_heartbeat.value
        }
    
    def _run(self, write_index, slot_locks) -> None:
        """
        Main worker process entry point.
        
        This runs in a separate process. Do not call directly.
        """
        # Set up logging first
        self.logger = setup_worker_logging(self.name, self.log_level)
        self.logger.info(f"Worker starting on PID {os.getpid()}")
        
        # Pin to CPU core
        self._pin_cpu()
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        try:
            # Attach to shared frame buffer
            self.frame_buffer = SharedFrameBuffer.attach(
                name=self.frame_buffer_name,
                write_index=write_index,
                slot_locks=slot_locks
            )
            self.logger.info(f"Attached to frame buffer: {self.frame_buffer_name}")
            
            # Run user setup
            self.logger.info("Running setup...")
            self.setup()
            
            # Signal ready
            self._ready_event.set()
            self.logger.info("Worker ready, entering main loop")
            
            # Main processing loop
            self._main_loop()
            
        except Exception as e:
            self.logger.error(f"Worker error: {e}", exc_info=True)
        finally:
            # Cleanup
            self.logger.info("Running cleanup...")
            self.cleanup()
            
            if self.frame_buffer:
                self.frame_buffer.close()
            
            self.logger.info("Worker stopped")
    
    def _pin_cpu(self) -> None:
        """Pin this process to the specified CPU core."""
        try:
            os.sched_setaffinity(0, {self.cpu_core})
            self.logger.info(f"Pinned to CPU core {self.cpu_core}")
        except (OSError, AttributeError) as e:
            self.logger.warning(f"Could not pin to CPU {self.cpu_core}: {e}")
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, stopping...")
        self._stop_event.set()
    
    def _main_loop(self) -> None:
        """Main processing loop."""
        last_sequence = 0
        
        while not self._stop_event.is_set():
            # Update heartbeat
            self._last_heartbeat.value = time.time()
            
            # Get latest frame
            slot = self.frame_buffer.get_latest_frame()
            
            if slot is None:
                # No frame available, wait a bit
                time.sleep(0.001)
                continue
            
            # Skip if already processed by this worker
            if self.frame_buffer.is_processed(slot.slot_index, self.worker_id):
                time.sleep(0.001)
                continue
            
            # Skip if we've already processed a newer frame
            if slot.metadata.sequence <= last_sequence:
                time.sleep(0.001)
                continue
            
            # Process frame
            start_time = time.perf_counter()
            
            try:
                result = self.process_frame(slot.frame, slot.metadata)
                
                # Mark as processed
                self.frame_buffer.mark_processed(slot.slot_index, self.worker_id)
                last_sequence = slot.metadata.sequence
                
                # Update stats
                latency_ms = (time.perf_counter() - start_time) * 1000
                self._frames_processed.value += 1
                self._total_latency_ms.value += latency_ms
                
                # Handle result
                if result is not None:
                    self.on_result(result, slot.metadata, latency_ms)
                    
            except Exception as e:
                self.logger.error(f"Error processing frame: {e}", exc_info=True)
    
    @abstractmethod
    def setup(self) -> None:
        """
        Set up the worker (load models, etc).
        
        Called once when the worker starts, before the main loop.
        Override this in subclasses.
        """
        pass
    
    @abstractmethod
    def process_frame(self, frame, metadata) -> any:
        """
        Process a single frame.
        
        Called for each new frame in the main loop.
        Override this in subclasses.
        
        Args:
            frame: NumPy array (H, W, 3) dtype=uint8
            metadata: FrameMetadata with timestamp, sequence, flags
            
        Returns:
            Processing result (passed to on_result)
        """
        pass
    
    def on_result(self, result, metadata, latency_ms: float) -> None:
        """
        Handle a processing result.
        
        Called after process_frame returns a non-None result.
        Override this in subclasses to send results to main process.
        
        Args:
            result: Result from process_frame
            metadata: Frame metadata
            latency_ms: Processing time in milliseconds
        """
        pass
    
    def cleanup(self) -> None:
        """
        Clean up the worker (release models, etc).
        
        Called when the worker stops.
        Override this in subclasses if needed.
        """
        pass
