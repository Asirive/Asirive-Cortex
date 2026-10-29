"""
Layer 4: Memory Manager - Persistent Object Context

This module handles memory storage and recall across all layers:
- Layer 1 (Reflex): Quick object recall ("where is my wallet?")
- Layer 3 (Guide): Spatial navigation to remembered objects
- Cross-session persistence via SQLite database

Architecture:
- Singleton pattern for memory manager
- Shared access from any layer
- Thread-safe operations

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
"""

import sys
from pathlib import Path
import logging

# Add server directory to path for memory storage
sys.path.append(str(Path(__file__).parent.parent.parent / "server"))

logger = logging.getLogger(__name__)

# Import memory storage backend
# NOTE: This MemoryManager class is legacy. Use HybridMemoryManager from hybrid_memory_manager.py instead.
# The import below is kept for backwards compatibility but may fail if memory_storage module doesn't exist.
try:
    from .memory_manager import get_memory_storage, MemoryStorage
    MEMORY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"⚠️ Legacy memory storage not available: {e}")
    MEMORY_AVAILABLE = False
    MemoryStorage = None


class MemoryManager:
    """
    High-level memory manager for Project-Cortex.
    
    Coordinates memory operations across all layers:
    - Layer 1: Quick recall ("I see your wallet here")
    - Layer 3: Spatial guidance ("Your wallet is on the desk, 2 meters ahead")
    """
    
    def __init__(self):
        """Initialize memory manager."""
        self.storage = None
        self._initialized = False
        
    def initialize(self) -> bool:
        """
        Initialize memory storage backend.
        
        Returns:
            True if initialization succeeded, False otherwise
        """
        if self._initialized:
            return True
            
        if not MEMORY_AVAILABLE:
            logger.error("❌ Memory storage backend not available")
            return False
            
        try:
            self.storage = get_memory_storage()
            self._initialized = True
            logger.info("✅ Memory Manager initialized")
            return True
        except Exception as e:
            logger.error(f"❌ Memory initialization failed: {e}")
            return False
    
    def store(self, object_name: str, image_data: bytes, detections: dict, 
              metadata: dict = None, location: str = None) -> tuple:
        """
        Store a memory.
        
        Args:
            object_name: Name of object to remember
            image_data: Image bytes (JPEG)
            detections: YOLO detection results
            metadata: Additional metadata
            location: Human-readable location
            
        Returns:
            (success, memory_id, message)
        """
        if not self._initialized:
            if not self.initialize():
                return False, "", "Memory system not initialized"
        
        return self.storage.store_memory(
            object_name=object_name,
            image_data=image_data,
            detections=detections,
            metadata=metadata,
            location_estimate=location
        )
    
    def recall(self, object_name: str, latest: bool = True) -> dict:
        """
        Recall a memory by object name.
        
        Args:
            object_name: Object to recall
            latest: If True, returns most recent memory
            
        Returns:
            Memory dict or None if not found
        """
        if not self._initialized:
            if not self.initialize():
                return None
        
        return self.storage.recall_memory(object_name, get_latest=latest)
    
    def list_all(self) -> list:
        """
        List all stored memories.
        
        Returns:
            List of memory summaries
        """
        if not self._initialized:
            if not self.initialize():
                return []
        
        return self.storage.list_memories()
    
    def delete(self, memory_id: str) -> tuple:
        """
        Delete a specific memory.
        
        Args:
            memory_id: Memory ID to delete
            
        Returns:
            (success, message)
        """
        if not self._initialized:
            if not self.initialize():
                return False, "Memory system not initialized"
        
        return self.storage.delete_memory(memory_id)
    
    def check_if_in_view(self, object_name: str, current_detections: str) -> bool:
        """
        Check if a remembered object is currently visible.
        
        Args:
            object_name: Object to check
            current_detections: Current YOLO detections string
            
        Returns:
            True if object is visible, False otherwise
        """
        if not current_detections or current_detections == "nothing":
            return False
        
        # Parse detections
        detections_list = current_detections.lower().split(", ")
        for detection in detections_list:
            obj_name = detection.split(" (")[0]
            if object_name.lower() in obj_name or obj_name in object_name.lower():
                return True
        
        return False


# Singleton instance
_memory_manager = None

def get_memory_manager() -> MemoryManager:
    """Get singleton memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


if __name__ == "__main__":
    # Test memory manager
    logging.basicConfig(level=logging.INFO)
    
    manager = get_memory_manager()
    manager.initialize()
    
    print("\n📋 Stored Memories:")
    for mem in manager.list_all():
        print(f"  - {mem['object_name']}: {mem['count']} items")
