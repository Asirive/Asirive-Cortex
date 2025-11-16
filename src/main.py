"""
Project-Cortex v2.0 - Main Application Entry Point

This is the orchestration layer that coordinates all 3 AI layers.

Architecture:
- Layer 1 (Reflex): Local YOLO object detection
- Layer 2 (Thinker): Cloud-based scene analysis via Gemini
- Layer 3 (Guide): Navigation, audio feedback, and dashboard

Author: Haziq (@IRSPlays)
Date: November 16, 2025
"""

import logging
import sys
import signal
from typing import NoReturn

# Layer imports (to be implemented)
# from layer1_reflex.detector import ObjectDetector
# from layer2_thinker.scene_analyzer import SceneAnalyzer
# from layer3_guide.navigator import Navigator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('cortex.log')
    ]
)
logger = logging.getLogger(__name__)


class ProjectCortex:
    """Main application class orchestrating all AI layers."""
    
    def __init__(self):
        """Initialize all subsystems."""
        logger.info("🧠 Project-Cortex v2.0 Initializing...")
        
        # TODO: Initialize layers
        # self.layer1 = ObjectDetector()
        # self.layer2 = SceneAnalyzer()
        # self.layer3 = Navigator()
        
        self.running = False
        
    def start(self) -> None:
        """Start the main application loop."""
        logger.info("🚀 Starting Project-Cortex...")
        self.running = True
        
        try:
            while self.running:
                # TODO: Main processing loop
                # 1. Capture frame from camera
                # 2. Run Layer 1 detection
                # 3. Trigger Layer 2 if needed
                # 4. Update Layer 3 UI/audio
                pass
                
        except KeyboardInterrupt:
            logger.info("⚠️ Received shutdown signal")
            self.stop()
            
    def stop(self) -> None:
        """Gracefully shutdown all subsystems."""
        logger.info("🛑 Shutting down Project-Cortex...")
        self.running = False
        
        # TODO: Cleanup resources
        # self.layer1.cleanup()
        # self.layer2.cleanup()
        # self.layer3.cleanup()
        
        logger.info("✅ Shutdown complete")
        

def signal_handler(signum, frame) -> NoReturn:
    """Handle system signals for graceful shutdown."""
    logger.warning(f"Received signal {signum}")
    sys.exit(0)


def main() -> None:
    """Application entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run application
    app = ProjectCortex()
    
    try:
        app.start()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
