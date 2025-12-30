"""
Project-Cortex Memory Storage System

Handles server-side storage of objects with voice commands like:
- "Remember this wallet"
- "Where is my keys?"
- "What do you remember?"

Architecture:
- Local SQLite database for metadata
- Filesystem storage for images
- FastAPI REST endpoints for client access

Author: Haziq (@IRSPlays) + AI CTO
Date: December 19, 2025
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import logging
import base64
from PIL import Image
import io

logger = logging.getLogger(__name__)

# Storage configuration
MEMORY_STORAGE_DIR = Path("memory_storage")
MEMORY_DB_PATH = MEMORY_STORAGE_DIR / "memories.db"

class MemoryStorage:
    """
    Server-side memory storage manager.
    
    Stores objects with:
    - Image snapshot
    - YOLO detections
    - Timestamp
    - User metadata (tags, location)
    """
    
    def __init__(self, storage_dir: str = str(MEMORY_STORAGE_DIR)):
        """
        Initialize memory storage system.
        
        Args:
            storage_dir: Root directory for memory storage
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "memories.db"
        
        # Initialize database
        self._init_database()
        
        logger.info(f"✅ Memory Storage initialized: {self.storage_dir}")
    
    def _init_database(self):
        """Create SQLite database schema if not exists."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Memories table (enhanced with visual prompts support)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT UNIQUE NOT NULL,
                object_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                image_path TEXT NOT NULL,
                detections_json TEXT,
                metadata_json TEXT,
                location_estimate TEXT,
                confidence REAL,
                visual_prompt_bbox TEXT,
                visual_embedding_path TEXT,
                slam_coordinates TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Index for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_object_name 
            ON memories(object_name)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp 
            ON memories(timestamp DESC)
        """)
        
        conn.commit()
        conn.close()
        
        logger.info("✅ Memory database initialized")
    
    def store_memory(
        self,
        object_name: str,
        image_data: bytes,
        detections: Dict,
        metadata: Optional[Dict] = None,
        location_estimate: Optional[str] = None
    ) -> Tuple[bool, str, str]:
        """
        Store a new memory (object with image + metadata).
        
        Args:
            object_name: Name of object (e.g., "wallet", "keys")
            image_data: Image as bytes (JPEG/PNG)
            detections: YOLO detection results
            metadata: Additional user metadata
            location_estimate: Human-readable location
            
        Returns:
            (success, memory_id, message)
        """
        try:
            # Generate unique memory ID
            timestamp = datetime.now()
            count = self._count_memories(object_name) + 1
            memory_id = f"{object_name}_{count:03d}"
            
            # Create memory directory
            memory_dir = self.storage_dir / memory_id
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Save image
            image_path = memory_dir / "image.jpg"
            img = Image.open(io.BytesIO(image_data))
            img.save(image_path, "JPEG", quality=95)
            
            # Save detections JSON
            detections_path = memory_dir / "detections.json"
            with open(detections_path, 'w') as f:
                json.dump(detections, f, indent=2)
            
            # Save metadata JSON
            if metadata is None:
                metadata = {}
            
            metadata.update({
                "memory_id": memory_id,
                "object_name": object_name,
                "timestamp": timestamp.isoformat(),
                "location_estimate": location_estimate
            })
            
            metadata_path = memory_dir / "metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Store in database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO memories (
                    memory_id, object_name, timestamp, image_path,
                    detections_json, metadata_json, location_estimate, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                memory_id,
                object_name,
                timestamp.isoformat(),
                str(image_path),
                json.dumps(detections),
                json.dumps(metadata),
                location_estimate,
                detections.get('confidence', 0.0)
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Memory stored: {memory_id}")
            return True, memory_id, f"Remembered {object_name} as {memory_id}"
            
        except Exception as e:
            logger.error(f"❌ Failed to store memory: {e}")
            return False, "", str(e)
    
    def recall_memory(
        self,
        object_name: str,
        get_latest: bool = True
    ) -> Optional[Dict]:
        """
        Recall a memory by object name.
        
        Args:
            object_name: Name of object to recall
            get_latest: If True, returns most recent memory
            
        Returns:
            Memory dictionary or None if not found
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if get_latest:
                cursor.execute("""
                    SELECT memory_id, object_name, timestamp, image_path,
                           detections_json, metadata_json, location_estimate, confidence
                    FROM memories
                    WHERE object_name = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (object_name,))
            else:
                cursor.execute("""
                    SELECT memory_id, object_name, timestamp, image_path,
                           detections_json, metadata_json, location_estimate, confidence
                    FROM memories
                    WHERE object_name = ?
                    ORDER BY timestamp DESC
                """, (object_name,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "memory_id": row[0],
                    "object_name": row[1],
                    "timestamp": row[2],
                    "image_path": row[3],
                    "detections": json.loads(row[4]) if row[4] else {},
                    "metadata": json.loads(row[5]) if row[5] else {},
                    "location_estimate": row[6],
                    "confidence": row[7]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to recall memory: {e}")
            return None
    
    def list_memories(self) -> List[Dict]:
        """
        List all stored memories grouped by object name.
        
        Returns:
            List of memory summaries
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT object_name, COUNT(*) as count, MAX(timestamp) as last_seen
                FROM memories
                GROUP BY object_name
                ORDER BY last_seen DESC
            """)
            
            rows = cursor.fetchall()
            conn.close()
            
            return [
                {
                    "object_name": row[0],
                    "count": row[1],
                    "last_seen": row[2]
                }
                for row in rows
            ]
            
        except Exception as e:
            logger.error(f"❌ Failed to list memories: {e}")
            return []
    
    def delete_memory(self, memory_id: str) -> Tuple[bool, str]:
        """
        Delete a specific memory.
        
        Args:
            memory_id: Memory ID to delete
            
        Returns:
            (success, message)
        """
        try:
            # Delete from database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
            deleted_count = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            if deleted_count == 0:
                return False, f"Memory {memory_id} not found"
            
            # Delete filesystem directory
            memory_dir = self.storage_dir / memory_id
            if memory_dir.exists():
                import shutil
                shutil.rmtree(memory_dir)
            
            logger.info(f"✅ Memory deleted: {memory_id}")
            return True, f"Deleted memory {memory_id}"
            
        except Exception as e:
            logger.error(f"❌ Failed to delete memory: {e}")
            return False, str(e)
    
    def _count_memories(self, object_name: str) -> int:
        """Count existing memories for an object."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) FROM memories WHERE object_name = ?
            """, (object_name,))
            
            count = cursor.fetchone()[0]
            conn.close()
            
            return count
            
        except Exception as e:
            logger.error(f"❌ Failed to count memories: {e}")
            return 0
    
    def get_image_base64(self, memory_id: str) -> Optional[str]:
        """
        Get image as base64 string for transmission.
        
        Args:
            memory_id: Memory ID
            
        Returns:
            Base64 encoded image or None
        """
        try:
            image_path = self.storage_dir / memory_id / "image.jpg"
            
            if not image_path.exists():
                return None
            
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            return base64.b64encode(image_bytes).decode('utf-8')
            
        except Exception as e:
            logger.error(f"❌ Failed to get image: {e}")
            return None


# Singleton instance
_memory_storage = None

def get_memory_storage() -> MemoryStorage:
    """Get singleton memory storage instance."""
    global _memory_storage
    if _memory_storage is None:
        _memory_storage = MemoryStorage()
    return _memory_storage


if __name__ == "__main__":
    # Test memory storage
    logging.basicConfig(level=logging.INFO)
    
    storage = get_memory_storage()
    
    # List all memories
    memories = storage.list_memories()
    print(f"\nStored Memories ({len(memories)}):")
    for mem in memories:
        print(f"  - {mem['object_name']}: {mem['count']} items, last seen {mem['last_seen']}")
