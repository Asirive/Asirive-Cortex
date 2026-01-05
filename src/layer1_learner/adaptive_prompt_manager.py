"""
Layer 1: Adaptive Prompt Manager - Dynamic Text Vocabulary System

This module manages the real-time updatable prompt list for YOLOE Layer 1.
It learns new objects from multiple sources without model retraining.

KEY FEATURES:
- Base vocabulary: 15 essential objects (always included)
- Dynamic learning from Gemini scene descriptions (NLP noun extraction)
- Dynamic learning from Google Maps POI (POI-to-object mapping)
- Dynamic learning from user memory (Layer 4 integration)
- Auto-pruning: Remove unused prompts after 24 hours
- JSON persistence: Survives restarts
- Deduplication: Prevent synonym duplicates

LEARNING SOURCES:
1. Gemini (Layer 2): Extract nouns from scene descriptions using spaCy
2. Maps (Layer 3): Convert POI to detection objects (e.g., "Starbucks" → "coffee shop sign")
3. Memory (Layer 4): User-stored objects (e.g., "brown leather wallet")

PROMPT LIFECYCLE:
- Add: When first learned from source
- Update: Increment use_count when detected
- Prune: Remove if age > 24h AND use_count < 3
- Persist: Save to JSON after every update

Author: Haziq (@IRSPlays)
Competition: Young Innovators Awards (YIA) 2026
"""

import logging
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

# spaCy for noun extraction (NLP)
try:
    import spacy
    SPACY_AVAILABLE = True
    # Try to load spaCy model
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        # Model not installed, will download on first use
        nlp = None
        logging.info("ℹ️ spaCy model not loaded. Run: python -m spacy download en_core_web_sm")
except ImportError:
    SPACY_AVAILABLE = False
    nlp = None
    logging.warning("⚠️ spaCy not installed. Run: pip install spacy")

logger = logging.getLogger(__name__)


class AdaptivePromptManager:
    """
    Manages dynamic text prompts for YOLOE Layer 1.
    
    This enables the system to learn new objects without retraining by
    updating the text prompt list from Gemini, Maps, and Memory sources.
    """
    
    # Base vocabulary (76 objects, always included)
    BASE_PROMPTS = [
        "person", "car", "phone", "wallet", "keys",
        "door", "stairs", "chair", "table", "bottle",
        "cup", "book", "laptop", "bag", "glasses",
        "stone chess table", "tiled game table", "concrete stool", "bird cage", "bird singing pole",
        "void deck kiosk", "vending machine", "community fridge", "blue recycling bin", "metal gate",
        "shoe rack", "riser", "bamboo pole", "pole holder", "retractable laundry rack",
        "rubbish chute hopper", "plastic stool", "melamine plate", "melamine bowl", "porcelain kopi cup",
        "saucer", "ceramic spoon", "tissue packet", "takeaway drink plastic bag", "plastic string",
        "straw", "tray return rack", "tray return robot", "bus stop pole", "bus service plate",
        "priority seat", "EZ-Link card", "SimplyGo card", "MRT gantry", "ERP gantry",
        "In-Vehicle Unit", "CashCard", "parking coupon", "sheltered walkway", "taxi stand sign",
        "umbrella", "portable fan", "Tiger Balm jar", "Axe Brand Universal Oil", "Good Morning towel",
        "red incense burner bin", "joss paper", "roadside altar", "smooth-coated otter", "community cat",
        "bird spikes", "Karung Guni horn", "trolley", "Belisha beacon", "Green Man + card reader",
        "ice cream motorcycle sidecar", "rainbow bread", "wafer", "Private Hire Car decal", "smart lamp post",
        "monsoon drain", "noise barrier", "cobbler stand"
    ]
    
    # POI-to-object mapping (Google Maps integration)
    POI_MAPPINGS = {
        # Food & Drink
        "starbucks": ["coffee shop sign", "menu board", "coffee cup"],
        "mcdonald's": ["fast food sign", "menu board"],
        "restaurant": ["restaurant sign", "menu board"],
        "cafe": ["cafe sign", "menu board"],
        "bar": ["bar sign", "beer bottle"],
        
        # Services
        "bank": ["ATM sign", "bank sign"],
        "atm": ["ATM sign", "ATM machine"],
        "hospital": ["hospital sign", "emergency sign"],
        "pharmacy": ["pharmacy sign", "prescription counter"],
        "gas station": ["gas pump", "gas station sign"],
        
        # Retail
        "supermarket": ["shopping cart", "store sign"],
        "mall": ["mall entrance", "store sign"],
        "store": ["store sign", "shopping bag"],
        
        # Transport
        "bus stop": ["bus stop sign", "bus"],
        "train station": ["train station sign", "train"],
        "subway": ["subway sign", "metro entrance"],
        "parking": ["parking sign", "parking meter"]
    }
    
    def __init__(
        self,
        max_prompts: int = 50,
        storage_path: str = "memory/adaptive_prompts.json",
        prune_age_hours: int = 24,
        min_use_count: int = 3
    ):
        """
        Initialize adaptive prompt manager.
        
        Args:
            max_prompts: Maximum number of dynamic prompts (keep list manageable)
            storage_path: Path to JSON persistence file
            prune_age_hours: Remove prompts older than this (hours)
            min_use_count: Minimum use count to keep old prompts
        """
        logger.info("📝 Initializing Adaptive Prompt Manager...")
        
        self.max_prompts = max_prompts
        self.storage_path = Path(storage_path)
        self.prune_age_hours = prune_age_hours
        self.min_use_count = min_use_count
        
        # Base prompts (static, never pruned)
        self.base_prompts = self.BASE_PROMPTS.copy()
        
        # Dynamic prompts (learned from Gemini/Maps/Memory)
        # Format: {prompt: {source, timestamp, use_count, metadata}}
        self.dynamic_prompts: Dict[str, Dict[str, Any]] = {}
        
        # Load persisted prompts
        self._load_prompts()
        
        logger.info(f"✅ Adaptive Prompt Manager initialized")
        logger.info(f"   Base Prompts: {len(self.base_prompts)}")
        logger.info(f"   Dynamic Prompts: {len(self.dynamic_prompts)}")
        logger.info(f"   Total: {len(self.get_current_prompts())}")
    
    def add_from_gemini(self, gemini_response: str) -> List[str]:
        """
        Extract nouns from Gemini scene description and add to prompt list.
        
        Uses spaCy NLP to extract object nouns (NOUN, PROPN tags).
        
        Example:
            Input: "I see a red fire extinguisher, water fountain, and exit signs"
            Output: ["fire extinguisher", "water fountain", "exit sign"]
        
        Args:
            gemini_response: Text response from Gemini API
            
        Returns:
            List of newly added objects
        """
        if not SPACY_AVAILABLE or nlp is None:
            logger.warning("⚠️ spaCy not available, cannot extract nouns")
            return []
        
        try:
            # Extract nouns using spaCy
            doc = nlp(gemini_response)
            nouns = []
            
            # Extract noun chunks (e.g., "fire extinguisher", "water fountain")
            for chunk in doc.noun_chunks:
                # Filter out common words
                if chunk.text.lower() not in ["i", "you", "it", "thing", "something"]:
                    nouns.append(chunk.text.lower())
            
            # Also extract single nouns
            for token in doc:
                if token.pos_ in ["NOUN", "PROPN"]:
                    if token.text.lower() not in nouns and len(token.text) > 2:
                        nouns.append(token.text.lower())
            
            # Add to dynamic prompts
            added = []
            for noun in nouns:
                if self._add_prompt(noun, source="gemini"):
                    added.append(noun)
            
            if added:
                logger.info(f"🧠 [LAYER 2] Learned new classes from Gemini: {added}")
                logger.debug(f"📝 [ADAPTIVE] Saved {len(added)} new classes to {self.storage_path}")
                self._save_prompts()
            else:
                logger.debug(f"🔄 [ADAPTIVE] No new classes extracted (all already known)")
            
            return added
        
        except Exception as e:
            logger.error(f"❌ Failed to extract nouns from Gemini: {e}")
            return []
    
    def add_from_maps(self, poi_list: List[str]) -> List[str]:
        """
        Convert Google Maps POI to detection objects.
        
        Uses POI_MAPPINGS dictionary to convert place names to detectable objects.
        
        Example:
            Input: ["Starbucks", "Bank of America", "CVS Pharmacy"]
            Output: ["coffee shop sign", "menu board", "ATM sign", "pharmacy sign"]
        
        Args:
            poi_list: List of nearby POI from Google Maps API
            
        Returns:
            List of newly added objects
        """
        added = []
        
        for poi in poi_list:
            poi_lower = poi.lower()
            
            # Check POI mappings
            for poi_key, objects in self.POI_MAPPINGS.items():
                if poi_key in poi_lower:
                    for obj in objects:
                        if self._add_prompt(obj, source="maps", metadata={"poi": poi}):
                            added.append(obj)
            
            # If no mapping found, try generic conversion
            if not any(key in poi_lower for key in self.POI_MAPPINGS.keys()):
                # Generic: "Place Name" → "place sign"
                generic_object = f"{poi_lower} sign"
                if self._add_prompt(generic_object, source="maps", metadata={"poi": poi}):
                    added.append(generic_object)
        
        if added:
            logger.info(f"🗺️ [MAPS] Learned new classes from Maps POI: {added}")
            logger.debug(f"📝 [ADAPTIVE] Saved {len(added)} new classes to {self.storage_path}")
            self._save_prompts()
        else:
            logger.debug(f"🔄 [ADAPTIVE] No new classes from Maps (all already known)")
        
        return added
    
    def add_from_memory(
        self,
        object_name: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Add user-stored object to prompt list (Layer 4 Memory integration).
        
        Example:
            Input: "brown leather wallet", {"color": "brown", "material": "leather"}
            Output: True (added to prompt list)
        
        Args:
            object_name: Name of object to remember
            metadata: Optional metadata (color, size, description)
            
        Returns:
            True if added, False if already exists
        """
        added = self._add_prompt(object_name, source="memory", metadata=metadata)
        
        if added:
            logger.info(f"🧠 [MEMORY] Learned new class from Layer 4: {object_name}")
            logger.debug(f"📝 [ADAPTIVE] Saved 1 new class to {self.storage_path}")
            self._save_prompts()
        else:
            logger.debug(f"🔄 [ADAPTIVE] Class '{object_name}' already in vocabulary")
        
        return added
    
    def _add_prompt(
        self,
        prompt: str,
        source: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Internal method to add prompt with deduplication.
        
        Args:
            prompt: Object name
            source: Source ('gemini', 'maps', 'memory')
            metadata: Optional metadata
            
        Returns:
            True if added, False if already exists
        """
        prompt = prompt.lower().strip()
        
        # Skip if already in base prompts
        if prompt in self.base_prompts:
            return False
        
        # Skip if already in dynamic prompts
        if prompt in self.dynamic_prompts:
            # Increment use count
            self.dynamic_prompts[prompt]['use_count'] += 1
            logger.debug(f"🔄 [ADAPTIVE] Duplicate skipped: '{prompt}' (use_count: {self.dynamic_prompts[prompt]['use_count']})")
            return False
        
        # Check if list is full
        if len(self.dynamic_prompts) >= self.max_prompts:
            logger.warning(f"⚠️ Max prompts reached ({self.max_prompts}), pruning old prompts...")
            self.prune_old_prompts()
        
        # Add new prompt
        self.dynamic_prompts[prompt] = {
            'source': source,
            'timestamp': datetime.now().isoformat(),
            'use_count': 1,
            'metadata': metadata or {}
        }
        
        return True
    
    def get_current_prompts(self) -> List[str]:
        """
        Get full prompt list (base + dynamic).
        
        Returns:
            List of all current prompts
        """
        return self.base_prompts + list(self.dynamic_prompts.keys())
    
    def get_class_count(self) -> int:
        """
        Get total number of classes in vocabulary.
        
        Returns:
            Integer count of all classes (base + dynamic)
        """
        return len(self.get_current_prompts())
    
    def get_source(self, prompt: str) -> str:
        """
        Get source of a prompt.
        
        Args:
            prompt: Object name
            
        Returns:
            Source ('base', 'gemini', 'maps', 'memory')
        """
        if prompt in self.base_prompts:
            return 'base'
        elif prompt in self.dynamic_prompts:
            return self.dynamic_prompts[prompt]['source']
        return 'unknown'
    
    def prune_old_prompts(self) -> int:
        """
        Remove prompts older than prune_age_hours with use_count < min_use_count.
        
        Returns:
            Number of prompts removed
        """
        now = datetime.now()
        cutoff_time = now - timedelta(hours=self.prune_age_hours)
        
        to_remove = []
        for prompt, info in self.dynamic_prompts.items():
            timestamp = datetime.fromisoformat(info['timestamp'])
            
            if timestamp < cutoff_time and info['use_count'] < self.min_use_count:
                to_remove.append(prompt)
        
        for prompt in to_remove:
            del self.dynamic_prompts[prompt]
        
        if to_remove:
            logger.info(f"🧹 Pruned {len(to_remove)} old prompts: {to_remove}")
            self._save_prompts()
        
        return len(to_remove)
    
    def _load_prompts(self) -> None:
        """Load dynamic prompts from JSON file."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.dynamic_prompts = data.get('dynamic_prompts', {})
                logger.info(f"📂 Loaded {len(self.dynamic_prompts)} dynamic prompts from {self.storage_path}")
            except Exception as e:
                logger.error(f"❌ Failed to load prompts from {self.storage_path}: {e}")
                self.dynamic_prompts = {}
        else:
            logger.info("ℹ️ No existing prompts file, starting fresh")
            # Create directory if it doesn't exist
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _save_prompts(self) -> None:
        """Save dynamic prompts to JSON file."""
        try:
            # Ensure directory exists
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'dynamic_prompts': self.dynamic_prompts,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"💾 Saved {len(self.dynamic_prompts)} dynamic prompts to {self.storage_path}")
        except Exception as e:
            logger.error(f"❌ Failed to save prompts to {self.storage_path}: {e}")


# Example usage (for testing):
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize prompt manager
    manager = AdaptivePromptManager()
    
    print(f"\n📝 Initial Prompts: {len(manager.get_current_prompts())}")
    print(f"   Base: {manager.base_prompts}")
    
    # Test Gemini learning
    print("\n📝 Testing Gemini Learning:")
    gemini_response = "I see a red fire extinguisher, a water fountain, and exit signs above the doors"
    new_objects = manager.add_from_gemini(gemini_response)
    print(f"   Learned: {new_objects}")
    
    # Test Maps learning
    print("\n🗺️ Testing Maps Learning:")
    poi_list = ["Starbucks", "Bank of America", "CVS Pharmacy"]
    new_objects = manager.add_from_maps(poi_list)
    print(f"   Learned: {new_objects}")
    
    # Test Memory learning
    print("\n🧠 Testing Memory Learning:")
    manager.add_from_memory("brown leather wallet", {"color": "brown", "material": "leather"})
    
    # Show final prompt list
    print(f"\n📝 Final Prompts: {len(manager.get_current_prompts())}")
    print(f"   Total: {manager.get_current_prompts()}")
    
    # Test pruning
    print("\n🧹 Testing Pruning:")
    removed = manager.prune_old_prompts()
    print(f"   Removed: {removed} prompts")
