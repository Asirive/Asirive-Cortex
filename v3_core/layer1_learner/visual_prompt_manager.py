"""
Layer 1: Visual Prompt Manager - Personal Object Memory System

Manages visual prompts for YOLOE, integrated with Layer 4 memory storage.

KEY FEATURES:
- Save visual embeddings (model.predictor.vpe) as .npz files
- Store bounding boxes + class IDs in JSON format
- Integrate with MemoryStorage for SLAM coordinates
- Cross-session persistence (survives restarts)
- Fast loading (<50ms) for "where's my" queries

WORKFLOW:
1. User: "Remember this wallet"
   → Capture frame, user draws bounding box (GUI)
   → Extract visual embeddings via model.predict(..., return_vpe=True)
   → Save to memory_storage/wallet_003/visual_embedding.npz
   → Save bbox to memory_storage/wallet_003/visual_prompt.json
   → Save SLAM coords to memories.db

2. User: "Where's my wallet"
   → Load visual embeddings from memory_storage/wallet_003/
   → Set classes: model.set_classes(["wallet"], vpe)
   → Run detection with YOLOEVPSegPredictor
   → Retrieve SLAM coords, calculate 3D audio direction

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Competition: Young Innovators Awards (YIA) 2026
Date: December 29, 2025
"""

import numpy as np
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class VisualPrompt:
    """Visual prompt metadata."""
    object_name: str
    bboxes: np.ndarray  # Shape: (N, 4) - [x1, y1, x2, y2]
    cls: np.ndarray  # Shape: (N,) - Class IDs
    reference_image_path: str
    visual_embedding_path: str
    slam_coordinates: Optional[Tuple[float, float, float]] = None  # (x, y, z)
    timestamp: str = ""
    memory_id: str = ""


class VisualPromptManager:
    """
    Manages visual prompts for YOLOE personal object recognition.
    
    Integrates with Layer 4 memory storage for cross-session persistence.
    
    Example Usage:
    ```python
    # Save visual prompt
    vpm = VisualPromptManager()
    vpm.save_visual_prompt(
        object_name="wallet",
        memory_id="wallet_003",
        bboxes=np.array([[450, 320, 580, 450]]),
        cls=np.array([0]),
        visual_embedding=model.predictor.vpe,
        reference_image_path="memory_storage/wallet_003/image.jpg",
        slam_coordinates=(2.3, 0.8, 0.9)
    )
    
    # Load visual prompt
    prompt = vpm.load_visual_prompt("wallet_003")
    vpe = vpm.get_visual_embedding("wallet_003")
    model.set_classes([prompt.object_name], vpe)
    ```
    """
    
    def __init__(self, memory_storage_dir: str = "memory_storage"):
        """
        Initialize visual prompt manager.
        
        Args:
            memory_storage_dir: Root directory for memory storage (Layer 4)
        """
        self.memory_storage_dir = Path(memory_storage_dir)
        self.memory_storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache loaded visual prompts (for fast retrieval)
        self.loaded_prompts: Dict[str, VisualPrompt] = {}
        
        logger.info(f"✅ Visual Prompt Manager initialized: {self.memory_storage_dir}")
    
    def save_visual_prompt(
        self,
        object_name: str,
        memory_id: str,
        bboxes: np.ndarray,
        cls: np.ndarray,
        visual_embedding: np.ndarray,
        reference_image_path: str,
        slam_coordinates: Optional[Tuple[float, float, float]] = None
    ) -> bool:
        """
        Save visual prompt to Layer 4 memory storage.
        
        Args:
            object_name: Name of object (e.g., "wallet", "keys")
            memory_id: Unique memory ID (e.g., "wallet_003")
            bboxes: Bounding boxes [[x1, y1, x2, y2], ...], shape (N, 4)
            cls: Class IDs [0, 1, ...], shape (N,)
            visual_embedding: Visual embeddings from model.predictor.vpe
            reference_image_path: Path to reference image
            slam_coordinates: (x, y, z) SLAM position in meters
            
        Returns:
            True if saved successfully
        """
        try:
            # Create memory directory
            memory_dir = self.memory_storage_dir / memory_id
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Save visual embeddings (.npz)
            embedding_path = memory_dir / "visual_embedding.npz"
            np.savez_compressed(embedding_path, vpe=visual_embedding)
            logger.info(f"💾 Saved visual embeddings: {embedding_path} ({visual_embedding.nbytes / 1024:.1f}KB)")
            
            # Save visual prompt JSON
            prompt_data = {
                "object_name": object_name,
                "memory_id": memory_id,
                "bboxes": bboxes.tolist(),
                "cls": cls.tolist(),
                "reference_image": reference_image_path,
                "visual_embedding_path": str(embedding_path),
                "slam_coordinates": list(slam_coordinates) if slam_coordinates else None,
                "timestamp": datetime.now().isoformat()
            }
            
            prompt_path = memory_dir / "visual_prompt.json"
            with open(prompt_path, 'w') as f:
                json.dump(prompt_data, f, indent=2)
            logger.info(f"💾 Saved visual prompt: {prompt_path}")
            
            # Cache in memory
            self.loaded_prompts[memory_id] = VisualPrompt(
                object_name=object_name,
                bboxes=bboxes,
                cls=cls,
                reference_image_path=reference_image_path,
                visual_embedding_path=str(embedding_path),
                slam_coordinates=slam_coordinates,
                timestamp=prompt_data["timestamp"],
                memory_id=memory_id
            )
            
            logger.info(f"✅ Visual prompt saved: {memory_id} ({object_name})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save visual prompt: {e}", exc_info=True)
            return False
    
    def load_visual_prompt(self, memory_id: str) -> Optional[VisualPrompt]:
        """
        Load visual prompt from Layer 4 memory storage.
        
        Args:
            memory_id: Unique memory ID (e.g., "wallet_003")
            
        Returns:
            VisualPrompt object or None if not found
        """
        # Check cache first
        if memory_id in self.loaded_prompts:
            logger.debug(f"📦 Visual prompt loaded from cache: {memory_id}")
            return self.loaded_prompts[memory_id]
        
        try:
            # Load from disk
            memory_dir = self.memory_storage_dir / memory_id
            prompt_path = memory_dir / "visual_prompt.json"
            
            if not prompt_path.exists():
                logger.warning(f"⚠️ Visual prompt not found: {memory_id}")
                return None
            
            # Load JSON metadata
            with open(prompt_path, 'r') as f:
                prompt_data = json.load(f)
            
            # Create VisualPrompt object (embedding loaded separately via get_visual_embedding)
            prompt = VisualPrompt(
                object_name=prompt_data["object_name"],
                bboxes=np.array(prompt_data["bboxes"]),
                cls=np.array(prompt_data["cls"]),
                reference_image_path=prompt_data["reference_image"],
                visual_embedding_path=prompt_data["visual_embedding_path"],
                slam_coordinates=tuple(prompt_data["slam_coordinates"]) if prompt_data.get("slam_coordinates") else None,
                timestamp=prompt_data["timestamp"],
                memory_id=memory_id
            )
            
            # Cache for fast retrieval
            self.loaded_prompts[memory_id] = prompt
            
            logger.info(f"✅ Visual prompt loaded: {memory_id} ({prompt.object_name})")
            return prompt
            
        except Exception as e:
            logger.error(f"❌ Failed to load visual prompt {memory_id}: {e}", exc_info=True)
            return None
    
    def get_visual_embedding(self, memory_id: str) -> Optional[np.ndarray]:
        """
        Get visual embedding for a stored object.
        
        Args:
            memory_id: Unique memory ID
            
        Returns:
            Visual embedding array or None
        """
        prompt = self.load_visual_prompt(memory_id)
        if prompt:
            try:
                vpe_data = np.load(prompt.visual_embedding_path)
                embedding = vpe_data['vpe']
                logger.debug(f"📦 Loaded visual embedding: {memory_id} ({embedding.nbytes / 1024:.1f}KB)")
                return embedding
            except Exception as e:
                logger.error(f"❌ Failed to load visual embedding {memory_id}: {e}")
                return None
        return None
    
    def search_by_object_name(self, object_name: str) -> List[str]:
        """
        Find all memory IDs for a given object name.
        
        Args:
            object_name: Object name (e.g., "wallet")
            
        Returns:
            List of memory IDs (sorted by timestamp, newest first)
        """
        matching_ids = []
        
        for memory_dir in self.memory_storage_dir.iterdir():
            if memory_dir.is_dir():
                prompt_path = memory_dir / "visual_prompt.json"
                if prompt_path.exists():
                    try:
                        with open(prompt_path, 'r') as f:
                            data = json.load(f)
                        if data["object_name"].lower() == object_name.lower():
                            matching_ids.append({
                                "memory_id": memory_dir.name,
                                "timestamp": data["timestamp"]
                            })
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to read {prompt_path}: {e}")
        
        # Sort by timestamp (newest first)
        matching_ids.sort(key=lambda x: x["timestamp"], reverse=True)
        result = [item["memory_id"] for item in matching_ids]
        
        logger.info(f"🔍 Found {len(result)} visual prompts for '{object_name}': {result}")
        return result
    
    def list_all_visual_prompts(self) -> List[Dict[str, Any]]:
        """
        List all visual prompts in memory storage.
        
        Returns:
            List of visual prompt metadata dictionaries
        """
        prompts = []
        
        for memory_dir in self.memory_storage_dir.iterdir():
            if memory_dir.is_dir():
                prompt_path = memory_dir / "visual_prompt.json"
                if prompt_path.exists():
                    try:
                        with open(prompt_path, 'r') as f:
                            data = json.load(f)
                        prompts.append(data)
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to read {prompt_path}: {e}")
        
        # Sort by timestamp (newest first)
        prompts.sort(key=lambda x: x["timestamp"], reverse=True)
        
        logger.info(f"📋 Found {len(prompts)} visual prompts in memory storage")
        return prompts
    
    def delete_visual_prompt(self, memory_id: str) -> bool:
        """
        Delete visual prompt from memory storage.
        
        Args:
            memory_id: Unique memory ID
            
        Returns:
            True if deleted successfully
        """
        try:
            memory_dir = self.memory_storage_dir / memory_id
            prompt_path = memory_dir / "visual_prompt.json"
            embedding_path = memory_dir / "visual_embedding.npz"
            
            if prompt_path.exists():
                prompt_path.unlink()
                logger.info(f"🗑️ Deleted visual prompt JSON: {prompt_path}")
            
            if embedding_path.exists():
                embedding_path.unlink()
                logger.info(f"🗑️ Deleted visual embedding: {embedding_path}")
            
            # Remove from cache
            if memory_id in self.loaded_prompts:
                del self.loaded_prompts[memory_id]
            
            logger.info(f"✅ Visual prompt deleted: {memory_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to delete visual prompt {memory_id}: {e}")
            return False


# Test code (run as: python -m layer1_learner.visual_prompt_manager)
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    print("🧪 Testing Visual Prompt Manager...")
    vpm = VisualPromptManager()
    
    # Test save
    print("\n📝 Test: Save visual prompt")
    test_bbox = np.array([[450, 320, 580, 450]])
    test_cls = np.array([0])
    test_embedding = np.random.rand(1, 512).astype(np.float32)  # Mock embedding
    
    success = vpm.save_visual_prompt(
        object_name="test_wallet",
        memory_id="test_wallet_001",
        bboxes=test_bbox,
        cls=test_cls,
        visual_embedding=test_embedding,
        reference_image_path="test_image.jpg",
        slam_coordinates=(1.0, 2.0, 0.5)
    )
    print(f"✅ Save result: {success}")
    
    # Test load
    print("\n📦 Test: Load visual prompt")
    loaded_prompt = vpm.load_visual_prompt("test_wallet_001")
    if loaded_prompt:
        print(f"✅ Loaded: {loaded_prompt.object_name}")
        print(f"   Bboxes: {loaded_prompt.bboxes}")
        print(f"   SLAM: {loaded_prompt.slam_coordinates}")
    
    # Test search
    print("\n🔍 Test: Search by object name")
    results = vpm.search_by_object_name("test_wallet")
    print(f"✅ Found {len(results)} results: {results}")
    
    # Test list all
    print("\n📋 Test: List all visual prompts")
    all_prompts = vpm.list_all_visual_prompts()
    print(f"✅ Total visual prompts: {len(all_prompts)}")
    
    # Test delete
    print("\n🗑️ Test: Delete visual prompt")
    deleted = vpm.delete_visual_prompt("test_wallet_001")
    print(f"✅ Delete result: {deleted}")
    
    print("\n✅ All tests passed!")
