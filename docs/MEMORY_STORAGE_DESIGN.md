# Project-Cortex Memory Storage System

**Feature**: Voice-activated object memory  
**Command**: "Remember this [object name]"  
**Storage**: Server-side with image + metadata  

---

## System Architecture

```
User Voice → VAD → Whisper → Router → Memory System
                                            ↓
                                      Save Image
                                            ↓
                    Server Storage: memory_storage/
                                    ├── wallet_001/
                                    │   ├── image.jpg
                                    │   ├── metadata.json
                                    │   └── detections.json
                                    ├── keys_001/
                                    └── phone_001/
```

---

## Voice Commands

### Remember (Store)
- **"remember this wallet"** → Saves current frame + YOLO detections as "wallet_001"
- **"save this as my keys"** → Saves as "keys_001"
- **"memorize this phone"** → Saves as "phone_001"

### Recall (Retrieve)
- **"where is my wallet?"** → Searches memory database, shows last known image
- **"find my keys"** → Retrieves stored location/image
- **"show me my phone"** → Displays saved image with timestamp

### List (Browse)
- **"what do you remember?"** → Lists all saved objects
- **"show my saved items"** → Displays memory inventory

---

## Memory Database Structure

### metadata.json
```json
{
  "object_name": "wallet",
  "memory_id": "wallet_001",
  "timestamp": "2025-12-19T14:30:00Z",
  "location_estimate": "on desk",
  "user_tags": ["brown", "leather"],
  "confidence": 0.89
}
```

### detections.json (YOLO Output)
```json
{
  "yolo_classes": ["wallet", "laptop", "mouse"],
  "primary_object": "wallet",
  "bbox": [120, 340, 280, 450],
  "confidence": 0.89
}
```

---

## Implementation Files

### Server Side (New)
- `server/memory_storage.py` - Memory database manager
- `server/api_routes.py` - REST API for memory operations
- `memory_storage/` - Directory for stored objects

### Client Side (Update)
- `src/layer3_guide/router.py` - Add "remember" keywords
- `src/cortex_gui.py` - Add _execute_memory_command()

---

## API Endpoints

### POST /memory/store
```json
{
  "object_name": "wallet",
  "image_base64": "...",
  "detections": {...},
  "metadata": {...}
}
```

### GET /memory/recall/{object_name}
```json
{
  "found": true,
  "memory_id": "wallet_001",
  "image_url": "/memory/wallet_001/image.jpg",
  "timestamp": "...",
  "location": "..."
}
```

### GET /memory/list
```json
{
  "memories": [
    {"name": "wallet", "count": 3, "last_seen": "..."},
    {"name": "keys", "count": 1, "last_seen": "..."}
  ]
}
```

---

## Router Updates

Add to `layer3_guide/router.py`:

```python
self.layer3_patterns = [
    # Memory commands (NEW)
    "remember", "save this", "memorize", "store this",
    "where is my", "find my", "recall",
    "what do you remember", "show saved", "list memories",
    # ... existing patterns
]
```

---

## Usage Example

**User:** "Remember this wallet"

1. VAD detects speech → Whisper transcribes
2. Router identifies Layer 3 (memory command)
3. System captures current frame + YOLO detections
4. Server stores:
   - `memory_storage/wallet_001/image.jpg`
   - `memory_storage/wallet_001/metadata.json`
5. TTS responds: "I've remembered your wallet. I can see it on the desk."

**Later...**

**User:** "Where is my wallet?"

1. Router identifies Layer 3 (recall command)
2. Server searches memory database for "wallet"
3. Returns most recent "wallet_001"
4. TTS responds: "I last saw your wallet on the desk at 2:30 PM today."
5. Optionally displays saved image on screen

---

## Security & Privacy

- **Local Storage**: All data stored on user's laptop server (not cloud)
- **No Upload**: Images never leave local network
- **Auto-Cleanup**: Optional TTL for old memories (e.g., delete after 30 days)
- **Encryption**: Optional AES encryption for sensitive objects

---

## Next Steps

1. ✅ Create `server/memory_storage.py` (database manager)
2. ✅ Create `server/api_routes.py` (FastAPI endpoints)
3. ✅ Update `src/layer3_guide/router.py` (add memory keywords)
4. ✅ Update `src/cortex_gui.py` (add _execute_memory_command)
5. ⏳ Test voice workflow end-to-end
