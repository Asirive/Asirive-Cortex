"""
Layer 4: Memory - Legacy Module (Deprecated)

This module is kept for backwards compatibility but is no longer used.
Use core.layer4_memory.hybrid_memory_manager instead.
"""

import logging

logger = logging.getLogger(__name__)

# Legacy aliases to prevent import errors
MemoryManager = None
get_memory_manager = None
MEMORY_AVAILABLE = False

logger.warning("⚠️  Legacy core.layer4_memory.memory_manager is deprecated. Use HybridMemoryManager.")
