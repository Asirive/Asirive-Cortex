"""
Layer 4: Memory - Persistent object context and recall.

This layer provides memory services to all other layers.
"""

from .memory_manager import MemoryManager, get_memory_manager, MEMORY_AVAILABLE

__all__ = ['MemoryManager', 'get_memory_manager', 'MEMORY_AVAILABLE']
