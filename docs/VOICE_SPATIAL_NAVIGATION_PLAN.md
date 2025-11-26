# Project-Cortex v2.0 - Voice-Activated Spatial Navigation System

**Implementation Plan**  
**Date:** November 26, 2025  
**Author:** Haziq (@IRSPlays)  
**Status:** 📋 Planning Phase

---

## 🎯 Mission Objective

Implement a **voice-activated object finding system** that:
1. User says: **"Where is a seat?"** (or chair, door, person, etc.)
2. System searches using **YOLO** (Layer 1) for known objects
3. If not found by YOLO, uses **Gemini Vision** (Layer 2) for advanced analysis
4. Plays **3D spatial audio beacon** guiding user toward the target
5. Provides **spoken feedback** describing object location

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         USER VOICE COMMAND                                        │
│                    "Where is a seat?" / "Find the door"                          │
└─────────────────────────────────────────────────────────────────────────────────┬─┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                    WHISPER STT + INTENT ROUTER                                    │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  Input: Audio → Whisper → "where is a seat"                                 │ │
│  │  Router: Detects "where is" + object → SPATIAL_NAVIGATION intent           │ │
│  │  Extract: target_object = "seat" (synonyms: chair, couch, bench)           │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┬─┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
┌───────────────────────────────────┐ ┌───────────────────────────────────────────┐
│      LAYER 1: YOLO SEARCH         │ │      LAYER 2: GEMINI VISION FALLBACK      │
│  (Fast, Offline, 80 classes)      │ │  (Slow, Cloud, Unlimited objects)         │
├───────────────────────────────────┤ ├───────────────────────────────────────────┤
│  1. Check current detections      │ │  Only if YOLO fails to find target:       │
│  2. Search for "chair" class      │ │  1. Send frame to Gemini Vision           │
│  3. If found → get bbox           │ │  2. Prompt: "Find [object], describe      │
│  4. Calculate 3D position         │ │     its position (left/right/center,      │
│                                   │ │     near/far)"                            │
│  Classes: chair, couch, bench,    │ │  3. Parse spatial description             │
│  person, door, car, etc.          │ │  4. Convert to approximate 3D coords      │
└───────────────────────────┬───────┘ └───────────────────────────┬───────────────┘
                            │                                     │
                            └──────────────┬──────────────────────┘
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         SPATIAL AUDIO BEACON                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  If target found:                                                           │ │
│  │    1. Start audio beacon at target's 3D position                           │ │
│  │    2. Beacon intensity increases as user gets closer                       │ │
│  │    3. Beacon pitch/tempo changes based on distance                         │ │
│  │                                                                              │ │
│  │  If target NOT found:                                                       │ │
│  │    → Speak: "I cannot see a [object] right now. Try turning around."       │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┬─┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         TTS SPOKEN FEEDBACK                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  Examples:                                                                   │ │
│  │  • "Found a chair about 2 meters ahead and slightly to your left."         │ │
│  │  • "I see a door on your right, approximately 3 meters away."              │ │
│  │  • "There's a person directly in front of you, very close."                │ │
│  │  • "I cannot find any seats nearby. Try looking in another direction."     │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📋 Implementation Tasks

### Phase 1: Enhanced Intent Router (router.py)

**New Intent Type: SPATIAL_NAVIGATION**

```python
# New patterns for spatial navigation
self.spatial_nav_patterns = [
    "where is", "where's", "find", "locate", "guide me to",
    "take me to", "show me", "help me find", "point me to",
    "is there a", "can you see a", "do you see a"
]

# Object synonyms for better matching
self.object_synonyms = {
    "seat": ["chair", "couch", "bench", "sofa", "stool"],
    "exit": ["door", "entrance", "gate", "doorway"],
    "vehicle": ["car", "truck", "bus", "motorcycle", "bicycle"],
    "person": ["human", "someone", "people", "man", "woman"],
}
```

**Router Decision:**
- If query matches `spatial_nav_patterns` → Return `"layer3_spatial"`
- Extract `target_object` from query using NLP

---

### Phase 2: Object Search Pipeline (spatial_search.py)

**New Module: `src/layer3_guide/spatial_audio/spatial_search.py`**

```python
class SpatialObjectSearcher:
    """
    Search for objects using YOLO first, then Gemini Vision fallback.
    """
    
    def search(self, target_object: str, yolo_detections: List, frame: np.ndarray) -> SearchResult:
        """
        1. Check YOLO detections for target
        2. If not found, query Gemini Vision
        3. Return position and confidence
        """
        
        # Step 1: YOLO search (fast, offline)
        result = self._search_yolo(target_object, yolo_detections)
        if result.found:
            return result
        
        # Step 2: Gemini Vision fallback (slow, cloud)
        result = self._search_gemini(target_object, frame)
        return result
    
    def _search_yolo(self, target: str, detections: List) -> SearchResult:
        """Search YOLO detections for target class."""
        # Handle synonyms: "seat" → check for "chair", "couch", etc.
        target_classes = self._expand_synonyms(target)
        
        for detection in detections:
            if detection.class_name.lower() in target_classes:
                return SearchResult(
                    found=True,
                    source="yolo",
                    class_name=detection.class_name,
                    bbox=detection.bbox,
                    confidence=detection.confidence,
                    position_3d=self._bbox_to_3d(detection.bbox)
                )
        return SearchResult(found=False)
    
    def _search_gemini(self, target: str, frame: np.ndarray) -> SearchResult:
        """Use Gemini Vision to find objects YOLO can't detect."""
        prompt = f'''Look at this image and find: "{target}"

If you see it, respond in this EXACT format:
FOUND: [object name]
POSITION: [left/center/right]
DISTANCE: [close/medium/far]
DESCRIPTION: [one sentence about its location]

If you do NOT see it, respond:
NOT_FOUND: [object name]'''
        
        # Send to Gemini and parse response
        response = gemini_vision.analyze(frame, prompt)
        return self._parse_gemini_response(response, frame.shape)
```

---

### Phase 3: Spoken Feedback Generator

**Natural Language Descriptions**

```python
def generate_spoken_feedback(search_result: SearchResult) -> str:
    """Generate natural speech describing object location."""
    
    if not search_result.found:
        return f"I cannot see a {search_result.target} right now. Try turning around or moving to a different location."
    
    # Position descriptions
    horizontal = _describe_horizontal(search_result.position_3d.x)
    distance = _describe_distance(search_result.position_3d.distance_meters)
    
    # Build natural sentence
    return f"Found a {search_result.class_name} {distance} and {horizontal}."

def _describe_horizontal(x: float) -> str:
    """Convert x position (-1 to +1) to natural language."""
    if x < -0.6:
        return "on your far left"
    elif x < -0.2:
        return "slightly to your left"
    elif x > 0.6:
        return "on your far right"
    elif x > 0.2:
        return "slightly to your right"
    else:
        return "directly ahead"

def _describe_distance(meters: float) -> str:
    """Convert distance to natural language."""
    if meters < 1.0:
        return "very close, about 1 meter away"
    elif meters < 2.0:
        return f"about {meters:.0f} meters ahead"
    elif meters < 5.0:
        return f"approximately {meters:.0f} meters away"
    else:
        return "quite far, about 5 or more meters away"
```

---

### Phase 4: GUI Integration (cortex_gui.py)

**New Execution Path: `_execute_spatial_navigation()`**

```python
def _execute_spatial_navigation(self, text: str):
    """Voice-activated spatial object finding with 3D audio guidance."""
    
    # 1. Extract target object from query
    target = self._extract_target_object(text)
    self.debug_print(f"🔍 Searching for: {target}")
    
    # 2. Get current YOLO detections
    detections = self._get_current_detections()
    
    # 3. Search with YOLO, then Gemini fallback
    searcher = SpatialObjectSearcher()
    result = searcher.search(target, detections, self.latest_frame_for_gemini)
    
    # 4. Generate spoken feedback
    feedback = generate_spoken_feedback(result)
    
    # 5. Start spatial audio beacon if found
    if result.found and self.spatial_audio:
        self.spatial_audio.start_beacon(result.class_name)
        # Beacon will auto-update position from YOLO detections
    
    # 6. Speak the feedback
    self._speak_response(feedback)
```

---

## 🎯 Example User Flows

### Flow 1: YOLO Success (Fast Path)
```
User: "Where is a seat?"
System: 
  1. Whisper: "where is a seat" (150ms)
  2. Router: spatial_navigation, target="seat" (5ms)
  3. YOLO search: Found "chair" at bbox [100, 200, 300, 400] (0ms - already cached)
  4. Position calc: x=-0.3, distance=2.5m
  5. Beacon: Start at (-0.3, 0, -2.5)
  6. TTS: "Found a chair about 2 meters ahead and slightly to your left."
Total: ~500ms
```

### Flow 2: Gemini Fallback (Slow Path)
```
User: "Find my coffee mug"  (not in YOLO's 80 classes)
System:
  1. Whisper: "find my coffee mug" (150ms)
  2. Router: spatial_navigation, target="coffee mug" (5ms)
  3. YOLO search: Not found (0ms)
  4. Gemini Vision: "FOUND: coffee mug, POSITION: right, DISTANCE: close" (2000ms)
  5. Position calc: x=0.7, distance=1.0m
  6. Beacon: Start at (0.7, 0, -1.0)
  7. TTS: "Found a coffee mug very close on your right."
Total: ~3000ms
```

### Flow 3: Not Found
```
User: "Where is a dog?"
System:
  1. Whisper: "where is a dog" (150ms)
  2. Router: spatial_navigation, target="dog" (5ms)
  3. YOLO search: Not found (0ms)
  4. Gemini Vision: "NOT_FOUND: dog" (2000ms)
  5. TTS: "I cannot see a dog right now. Try turning around."
Total: ~2500ms
```

---

## 📁 Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/layer3_guide/router.py` | **Modify** | Add `spatial_nav_patterns`, synonyms, extract target |
| `src/layer3_guide/spatial_audio/spatial_search.py` | **Create** | Object search with YOLO + Gemini fallback |
| `src/layer3_guide/spatial_audio/feedback_generator.py` | **Create** | Natural language position descriptions |
| `src/cortex_gui.py` | **Modify** | Add `_execute_spatial_navigation()` method |
| `config/object_synonyms.yaml` | **Create** | Synonym mappings for common objects |

---

## 🔧 Technical Considerations

### 1. YOLO Class Mapping
YOLO v11 has 80 classes. Key ones for navigation:
- **Seating:** chair (56), couch (57), bench (13)
- **Vehicles:** car (2), motorcycle (3), bus (5), bicycle (1)
- **People:** person (0)
- **Doors:** Not in YOLO → needs Gemini fallback

### 2. Gemini Vision Prompt Engineering
Critical for reliable spatial parsing:
```python
GEMINI_SEARCH_PROMPT = '''Analyze this image to find: "{target}"

Respond in EXACTLY this format (no other text):
FOUND: [exact object name]
HORIZONTAL: [far-left | left | center | right | far-right]  
VERTICAL: [top | middle | bottom]
DISTANCE: [very-close | close | medium | far | very-far]
CONFIDENCE: [low | medium | high]

OR if not visible:
NOT_FOUND: {target}
REASON: [why you can't see it]'''
```

### 3. Body-Relative Audio Reminder
Before starting beacon, remind user:
> "Turn your BODY to center the sound, not just your head."

### 4. Beacon Behavior
- **Continuous beacon** for found objects
- **Pulsing rate** based on distance (closer = faster pulses)
- **Auto-stop** after 30 seconds or when user says "stop"

---

## 🚀 Implementation Order

1. **Phase 1:** Update router with spatial nav patterns (30 min)
2. **Phase 2:** Create `spatial_search.py` with YOLO+Gemini (1 hour)
3. **Phase 3:** Create `feedback_generator.py` (30 min)
4. **Phase 4:** Integrate into `cortex_gui.py` (1 hour)
5. **Phase 5:** Testing with various queries (30 min)

---

## ✅ Success Criteria

- [ ] "Where is a chair?" triggers beacon on detected chair
- [ ] "Find my phone" uses Gemini Vision (phone not in YOLO)
- [ ] Spoken feedback describes position naturally
- [ ] Beacon intensity changes with distance
- [ ] "Stop" voice command stops beacon
- [ ] Works within 3 seconds for YOLO objects
- [ ] Works within 5 seconds for Gemini fallback

---

## 💡 Additional Suggestions

### Suggestion 1: Continuous Tracking Mode
When user says "Keep tracking the chair", the system continuously updates the beacon position as the object moves or user moves.

### Suggestion 2: Multiple Object Handling
If multiple chairs are found:
> "I found 3 chairs. The closest one is about 2 meters ahead. Should I guide you to it?"

### Suggestion 3: Safety Priority Override
If a car or dangerous object is detected while searching:
> "Warning: Car approaching from your left! [safety beacon plays first]"

### Suggestion 4: Memory/Learning
> "Remember this as 'my desk'" - saves location for future reference

### Suggestion 5: Voice Commands During Guidance
- "Louder" / "Quieter" - adjust beacon volume
- "Stop" - cancel beacon
- "How far?" - speak current distance
- "What else is nearby?" - list other detected objects

---

**Ready to implement? Say "Let's build it!" 🚀**
