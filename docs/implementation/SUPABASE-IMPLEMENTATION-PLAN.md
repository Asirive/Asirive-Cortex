# ProjectCortex v2.0 - Implementation Plan
**3-Tier Hybrid Architecture with Supabase Integration**

**Last Updated:** January 8, 2026
**Author:** Haziq (@IRSPlays) + AI Planner (Claude)
**Status:** Planning Phase Complete → Ready for Implementation
**Target:** Young Innovators Awards (YIA) 2026 Competition

---

## 📋 EXECUTIVE SUMMARY

This document outlines the **step-by-step implementation plan** to integrate Supabase into ProjectCortex v2.0, transforming it from a single-device system into a **cloud-powered, multi-device capable platform**.

### Current State
- ✅ All 4 AI layers implemented (Layer 0-3)
- ✅ Dual YOLO cascade (Guardian + Learner) working
- ✅ Gemini Live API integration complete
- ✅ Intent Router (97.7% accuracy) tested
- ⚠️ **Gap**: No cloud persistence, no real-time sync, no remote monitoring

### Target State (After Implementation)
- ✅ Hybrid memory: Local SQLite + Supabase PostgreSQL
- ✅ Real-time device monitoring via dashboard
- ✅ Remote configuration changes
- ✅ Offline mode with queue + sync
- ✅ Multi-device coordination ready
- ✅ Free tier optimized (within 500MB/5GB limits)

---

## 🎯 IMPLEMENTATION GOALS

### Primary Goals (Must Have)
1. **Persistent Cloud Storage**: All detections/queries/logs synced to Supabase
2. **Real-Time Dashboard**: Live device monitoring from anywhere
3. **Offline Support**: Queue locally, sync when online
4. **Remote Control**: Change detection modes/config from dashboard
5. **Free Tier Compliance**: Stay within 500MB DB, 5GB bandwidth

### Secondary Goals (Nice to Have)
1. Multi-device coordination (future expansion)
2. Push notifications (Telegram/Pushover)
3. Analytics dashboards (usage insights)
4. Automated data cleanup (cron jobs)

---

## 📅 IMPLEMENTATION ROADMAP (4-Week Sprint)

### **Week 1: Supabase Setup & Database Schema**
**Goal**: Get cloud infrastructure ready

**Deliverables**:
- ✅ Supabase project created (free tier)
- ✅ Database schema deployed (6 tables)
- ✅ Row Level Security (RLS) policies configured
- ✅ Edge Functions deployed (cleanup, stats)
- ✅ Python client configured and tested

**Tasks**:
1. **Day 1-2: Project Setup**
   - Create Supabase account/project
   - Get API keys (anon + service_role)
   - Enable PostgreSQL database
   - Enable Realtime for all tables
   - Enable Storage buckets

2. **Day 3-4: Database Schema**
   - Run SQL schema script (6 tables)
   - Create indexes for performance
   - Enable Realtime publications
   - Test with sample data

3. **Day 5-6: Security & Edge Functions**
   - Configure RLS policies
   - Deploy cleanup function (Deno)
   - Deploy daily stats function
   - Test cron jobs

4. **Day 7: Python Client Testing**
   - Install `supabase` package
   - Test async connection
   - Test batch insert (100 rows)
   - Test Realtime subscription

**Acceptance Criteria**:
- Can insert 100 detections to Supabase
- Can query last 100 detections via Python client
- Realtime subscription receives UPDATE events
- Database size <10MB (well under 500MB limit)

---

### **Week 2: Layer 4 Hybrid Memory Manager**
**Goal**: Implement dual storage (SQLite + Supabase)

**Deliverables**:
- ✅ `rpi5/layer4_memory/hybrid_memory_manager.py` complete
- ✅ Background sync worker (60s interval)
- ✅ Offline queue + resume logic
- ✅ Local cache management (last 1000 rows)
- ✅ Unit tests (80% coverage)

**Tasks**:
1. **Day 1-2: Core Implementation**
   ```python
   # File: rpi5/layer4_memory/hybrid_memory_manager.py
   class HybridMemoryManager:
       def __init__(self, supabase_url, supabase_key):
           self.local_db = sqlite3.connect("local_cortex.db")
           self.supabase_client = None  # Lazy init
           self.upload_queue = []

       def store_detection(self, detection):
           # Store locally (<10ms)
           # Queue for upload
           pass

       async def _sync_worker(self):
           # Every 60s, upload batch
           # Handle offline mode
           pass
   ```

2. **Day 3-4: Background Sync**
   - Implement batch upload (100 rows at once)
   - Add WiFi detection (skip if offline)
   - Add retry logic (exponential backoff)
   - Add progress logging

3. **Day 5-6: Local Cache Management**
   - Auto-delete old rows (>1000)
   - Add `synced` flag to track uploads
   - Add cleanup on startup
   - Test memory usage

4. **Day 7: Testing**
   - Unit tests for all methods
   - Integration test (insert → sync → query)
   - Offline mode test (disconnect WiFi)
   - Performance test (1000 detections/min)

**Acceptance Criteria**:
- Store 1000 detections locally in <10 seconds
- Sync 100 detections to Supabase in <5 seconds
- Offline mode: queue 100 rows, sync when WiFi back
- Local DB stays <100MB (SQLite cache)

---

### **Week 3: Integration with Layer 0-3**
**Goal**: Wire Supabase into all AI layers

**Deliverables**:
- ✅ Layer 0 → Supabase (safety detections)
- ✅ Layer 1 → Supabase (adaptive learning)
- ✅ Layer 2 → Supabase (Gemini transcripts)
- ✅ Layer 3 → Supabase (routing decisions)
- ✅ All layers use HybridMemoryManager

**Tasks**:
1. **Day 1: Layer 0 Integration**
   ```python
   # rpi5/layer0_guardian/__init__.py
   def detect(self, frame):
       detections = self.model(frame)

       # NEW: Store to Supabase via Layer 4
       for det in detections:
           self.memory_manager.store_detection({
               'layer': 'guardian',
               'class_name': det['class'],
               'confidence': det['confidence'],
               'bbox': det['bbox'],
               ...
           })

       # Trigger haptic
       self.trigger_haptic_feedback(detections)
   ```

2. **Day 2: Layer 1 Integration**
   ```python
   # rpi5/layer1_learner/__init__.py
   def detect(self, frame):
       detections = self.model(frame)

       # NEW: Store to Supabase
       for det in detections:
           self.memory_manager.store_detection({
               'layer': 'learner',
               'detection_mode': self.mode.value,
               'source': get_source(det['class_name']),
               ...
           })

       return detections

   # NEW: Sync prompts from Supabase
   async def sync_prompts_from_cloud(self):
       prompts = await self.memory_manager.fetch_prompts()
       self.set_classes(prompts)
   ```

3. **Day 3-4: Layer 2 Integration**
   ```python
   # rpi5/layer2_thinker/gemini_live_handler.py
   async def send_query(self, query, frame):
       response = await self.session.send_realtime_input(...)

       # NEW: Store transcript to Supabase
       await self.memory_manager.store_query({
           'user_query': query,
           'transcribed_text': transcribed,
           'ai_response': response,
           'routed_layer': 'layer2',
           'tier_used': 'gemini_live',
           ...
       })

       return response
   ```

4. **Day 5: Layer 3 Integration**
   ```python
   # rpi5/layer3_guide/router.py
   def route(self, text):
       layer = self._route_text(text)

       # NEW: Log routing decision to Supabase
       self.memory_manager.store_routing_event({
           'query': text,
           'routed_layer': layer,
           'routing_method': 'priority_keyword' or 'fuzzy_match',
           ...
       })

       return layer
   ```

5. **Day 6-7: End-to-End Testing**
   - Run full system (all 4 layers + Supabase)
   - Generate 1000 detections
   - Verify all synced to Supabase
   - Check dashboard shows real-time updates

**Acceptance Criteria**:
- All layers use HybridMemoryManager
- Detection → Supabase latency <60s (batch upload)
- Can query last 100 detections from dashboard
- No data loss if WiFi disconnects

---

### **Week 4: Laptop Dashboard Integration with Supabase**
**Goal**: Add Supabase historical analytics to existing PyQt6 dashboard

**Deliverables**:
- ✅ PyQt6 dashboard (`laptop/cortex_monitor_gui.py`) updated
- ✅ Supabase client integration (historical data fetch)
- ✅ Analytics tab (detection trends, class distribution)
- ✅ Remote configuration via WebSocket (existing)
- ✅ Historical logs viewer (from Supabase)

**Tasks**:
1. **Day 1-2: Add Supabase Client to PyQt6 Dashboard**
   ```python
   # laptop/cortex_monitor_gui.py (UPDATED)
   from supabase import create_async_client
   import asyncio
   from PyQt6.QtCore import QThread, pyqtSignal

   class SupabaseWorker(QThread):
       """Background thread for Supabase queries"""
       stats_updated = pyqtSignal(dict)

       def __init__(self, supabase_url, supabase_key):
           super().__init__()
           self.url = supabase_url
           self.key = supabase_key
           self.client = None
           self.running = True

       async def init_client(self):
           self.client = await create_async_client(self.url, self.key)

       async def fetch_hourly_stats(self):
           while self.running:
               await asyncio.sleep(3600)  # Every hour

               result = await self.client.table('detections')\
                   .select('*')\
                   .gte('created_at', datetime.now() - timedelta(hours=1))\
                   .execute()

               self.stats_updated.emit(self._process_stats(result.data))

       def _process_stats(self, detections):
           class_counts = {}
           for det in detections:
               class_counts[det['class_name']] = class_counts.get(det['class_name'], 0) + 1
           return class_counts
   ```

2. **Day 3-4: Add Analytics Tab to PyQt6 GUI**
   ```python
   # laptop/cortex_monitor_gui.py (UPDATED)
   from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QLabel

   class CortexMonitorGUI(QMainWindow):
       def __init__(self):
           # ... existing init ...

           # NEW: Analytics tab
           self.analytics_tab = QWidget()
           analytics_layout = QVBoxLayout()

           self.analytics_label = QLabel("Loading analytics...")
           analytics_layout.addWidget(self.analytics_label)

           self.analytics_tab.setLayout(analytics_layout)
           self.tabs.addTab(self.analytics_tab, "Analytics")

           # NEW: Supabase worker
           self.supabase_worker = SupabaseWorker(SUPABASE_URL, SUPABASE_KEY)
           self.supabase_worker.stats_updated.connect(self.update_analytics)
           self.supabase_worker.start()

       def update_analytics(self, stats):
           """Update analytics tab (called from worker thread)"""
           text = "<h2>Hourly Detection Statistics</h2>"
           for class_name, count in stats.items():
               text += f"<p>{class_name}: {count}</p>"
           self.analytics_label.setText(text)
   ```

3. **Day 5: Historical Logs Viewer**
   ```python
   # Add to analytics tab
   async def fetch_error_logs(self):
       """Fetch ERROR logs from Supabase"""
       result = await self.supabase_client.table('system_logs')\
           .select('*')\
           .eq('level', 'ERROR')\
           .order('created_at', desc=True)\
           .limit(100)\
           .execute()

       # Display in logs viewer
       self.update_logs_viewer(result.data)
   ```

4. **Day 6: Remote Configuration (Already Implemented)**
   - The existing WebSocket server (port 8765) already supports remote commands
   - No Flask needed - use existing `send_command()` method
   ```python
   # laptop/websocket_server.py (EXISTING)
   async def send_command_to_rpi(self, command, params):
       """Send command to RPi via WebSocket"""
       message = {
           'type': 'COMMAND',
           'command': command,
           'params': params
       }
       await self.broadcast(message)
   ```

5. **Day 7: Testing & Polish**
   - Load test (100 detections/minute)
   - Verify analytics update every hour
   - Test historical logs fetch
   - Error handling (Supabase down - show warning, don't crash)

**Acceptance Criteria**:
- PyQt6 dashboard displays hourly stats from Supabase
- Analytics tab shows detection trends
- Historical ERROR logs fetchable from Supabase
- Real-time monitoring still works via WebSocket (existing)
- No impact on real-time performance (analytics in background thread)

---

## 🔧 IMPLEMENTATION DETAILS

### **1. File Structure (After Implementation)**

```
rpi5/
├── layer0_guardian/
│   ├── __init__.py (UPDATED: use HybridMemoryManager)
│   └── haptic_controller.py
├── layer1_learner/
│   ├── __init__.py (UPDATED: sync prompts from cloud)
│   ├── adaptive_prompt_manager.py
│   └── visual_prompt_manager.py
├── layer2_thinker/
│   ├── __init__.py (UPDATED: store transcripts)
│   ├── gemini_live_handler.py
│   └── glm4v_handler.py
├── layer3_guide/
│   ├── router.py (UPDATED: log routing decisions)
│   └── detection_router.py
├── layer4_memory/
│   ├── __init__.py (UPDATED: export HybridMemoryManager)
│   ├── hybrid_memory_manager.py (NEW)
│   ├── local_manager.py (NEW: SQLite wrapper)
│   └── cloud_manager.py (NEW: Supabase wrapper)
├── main.py (UPDATED: init HybridMemoryManager)
└── config/
    └── config.yaml (NEW: Supabase credentials)

dashboard/
├── app.py (NEW: Flask server)
├── templates/
│   └── dashboard.html (NEW)
├── static/
│   ├── dashboard.js (NEW)
│   └── dashboard.css (NEW)
└── requirements.txt (NEW)

supabase/
├── migrations/
│   └── 001_initial_schema.sql (NEW)
└── functions/
    ├── cleanup/
    │   └── index.ts (NEW)
    └── daily-stats/
        └── index.ts (NEW)
```

---

### **2. Configuration Management**

**File: `rpi5/config/config.yaml`**
```yaml
# Supabase Configuration
supabase:
  url: "https://your-project.supabase.co"
  anon_key: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  device_id: "rpi5-cortex-001"  # Unique device ID

  # Sync Settings
  sync_interval_seconds: 60  # Batch upload every 60s
  batch_size: 100  # Max rows per batch
  enable_offline_queue: true  # Queue when WiFi disconnected

  # Local Cache Settings
  local_cache_size: 1000  # Keep last 1000 detections locally
  cleanup_old_rows: true  # Delete old rows from local DB

# Layer 0 (Guardian)
layer0:
  model_path: "models/yolo11n_ncnn_model"
  enable_haptic: true
  confidence: 0.5

# Layer 1 (Learner)
layer1:
  model_path: "models/yoloe-11m-seg.pt"
  mode: "TEXT_PROMPTS"  # PROMPT_FREE, TEXT_PROMPTS, VISUAL_PROMPTS
  confidence: 0.25

# Layer 2 (Thinker)
layer2:
  gemini_api_key: "AIzaSyD..."
  model: "gemini-2.0-flash-exp"
  enable_live_api: true

# Camera
camera:
  device_id: 0
  use_picamera: true  # True for RPi5, False for laptop
  resolution: [1920, 1080]
  fps: 30

# Logging
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR
  upload_logs: true  # Send ERROR logs to Supabase
```

---

### **3. Key Code Snippets**

#### **A. Initialize HybridMemoryManager in main.py**

```python
# rpi5/main.py
import yaml
from layer4_memory import HybridMemoryManager

def load_config(config_path):
    with open(config_path) as f:
        return yaml.safe_load(f)

def main():
    # Load configuration
    config = load_config("rpi5/config/config.yaml")

    # Initialize Hybrid Memory Manager
    memory_manager = HybridMemoryManager(
        supabase_url=config['supabase']['url'],
        supabase_key=config['supabase']['anon_key'],
        device_id=config['supabase']['device_id']
    )

    # Initialize Layer 0 (Guardian)
    layer0 = YOLOGuardian(
        model_path=config['layer0']['model_path'],
        enable_haptic=config['layer0']['enable_haptic']
    )
    layer0.set_memory_manager(memory_manager)  # NEW

    # Initialize Layer 1 (Learner)
    layer1 = YOLOELearner(
        model_path=config['layer1']['model_path'],
        mode=YOLOEMode[config['layer1']['mode']]
    )
    layer1.set_memory_manager(memory_manager)  # NEW

    # ... rest of initialization

    # Start main loop
    asyncio.run(main_loop(layer0, layer1, layer2, layer3, memory_manager))
```

#### **B. Store Detection from Layer 0**

```python
# rpi5/layer0_guardian/__init__.py
class YOLOGuardian:
    def __init__(self, ..., memory_manager=None):
        self.memory_manager = memory_manager

    def detect(self, frame):
        start_time = time.time()

        # Run YOLO detection
        results = self.model(frame, conf=self.confidence, verbose=False)

        detections = []
        if results and len(results) > 0:
            result = results[0]
            if result.boxes is not None:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = result.names[class_id]
                    conf_score = float(box.conf[0])
                    bbox = box.xyxy[0].cpu().numpy()

                    # Only safety-critical classes
                    if class_name in self.SAFETY_CLASSES:
                        detection = {
                            'class': class_name,
                            'confidence': conf_score,
                            'bbox': bbox.tolist(),
                            'bbox_normalized': [
                                bbox[0] / frame_width,
                                bbox[1] / frame_height,
                                bbox[2] / frame_width,
                                bbox[3] / frame_height
                            ],
                            'bbox_area': (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / (frame_width * frame_height),
                            'layer': 'guardian'
                        }
                        detections.append(detection)

                        # NEW: Store to Supabase via Layer 4
                        if self.memory_manager:
                            self.memory_manager.store_detection({
                                'layer': 'guardian',
                                'class_name': detection['class'],
                                'confidence': detection['confidence'],
                                'bbox_x1': detection['bbox_normalized'][0],
                                'bbox_y1': detection['bbox_normalized'][1],
                                'bbox_x2': detection['bbox_normalized'][2],
                                'bbox_y2': detection['bbox_normalized'][3],
                                'bbox_area': detection['bbox_area'],
                                'detection_mode': None,
                                'source': 'base'
                            })

        # Trigger haptic feedback
        self.trigger_haptic_feedback(detections)

        return detections
```

#### **C. Sync Prompts from Supabase (Layer 1)**

```python
# rpi5/layer1_learner/__init__.py
class YOLOELearner:
    def __init__(self, ..., memory_manager=None):
        self.memory_manager = memory_manager

    async def sync_prompts_from_cloud(self):
        """
        Download adaptive prompts from Supabase and update model
        Called every 5 minutes or on config change
        """
        if not self.memory_manager:
            return

        # Fetch prompts from Supabase
        prompts = await self.memory_manager.fetch_adaptive_prompts()

        if prompts:
            logger.info(f"🔄 Downloaded {len(prompts)} prompts from Supabase")

            # Convert to class names list
            class_names = [p['class_name'] for p in prompts]

            # Update model
            self.set_classes(class_names)

            # Update local prompt manager
            if self.prompt_manager:
                self.prompt_manager.update_from_supabase(prompts)
        else:
            logger.warning("⚠️ No prompts fetched from Supabase, using local cache")
```

#### **D. Listen for Remote Commands**

```python
# rpi5/main.py
async def listen_for_remote_commands(memory_manager, layer1):
    """
    Subscribe to Supabase Realtime for remote commands
    """
    from realtime import AsyncRealtimeClient

    socket = AsyncRealtimeClient(
        f"{memory_manager.supabase_url.replace('https://', 'wss://')}/realtime/v1",
        memory_manager.supabase_key
    )
    channel = socket.channel('device-commands')

    channel.on_postgres_changes(
        'INSERT',
        schema='public',
        table='device_commands',
        callback=lambda payload: handle_remote_command(payload, layer1)
    )

    await channel.subscribe()
    logger.info("✅ Listening for remote commands...")

def handle_remote_command(payload, layer1):
    """Execute remote command from dashboard"""
    command = payload['new']
    cmd_type = command['command']
    params = command.get('params', {})

    logger.info(f"🎯 Remote command: {cmd_type} {params}")

    if cmd_type == 'switch_mode':
        new_mode = YOLOEMode[params['mode']]
        layer1.switch_mode(new_mode)
        logger.info(f"✅ Switched to {new_mode.value} mode")

    elif cmd_type == 'reboot':
        logger.warning("⚠️ Remote reboot command received")
        # Graceful shutdown
        # system_reboot()

    elif cmd_type == 'sync_prompts':
        # Force prompt sync from Supabase
        asyncio.create_task(layer1.sync_prompts_from_cloud())
```

---

## 📊 TESTING STRATEGY

### **Unit Tests** (80% coverage target)

```python
# tests/test_hybrid_memory_manager.py
import pytest
from layer4_memory import HybridMemoryManager

@pytest.fixture
async def memory_manager():
    manager = HybridMemoryManager(
        supabase_url="test-url",
        supabase_key="test-key"
    )
    yield manager
    await manager.cleanup()

@pytest.mark.asyncio
async def test_store_detection(memory_manager):
    """Test storing detection locally"""
    detection = {
        'layer': 'guardian',
        'class_name': 'person',
        'confidence': 0.92,
        'bbox': [100, 200, 300, 400]
    }

    memory_manager.store_detection(detection)

    # Verify stored locally
    cursor = memory_manager.local_db.cursor()
    cursor.execute("SELECT * FROM detections_local WHERE class_name = 'person'")
    rows = cursor.fetchall()

    assert len(rows) == 1
    assert rows[0]['confidence'] == 0.92

@pytest.mark.asyncio
async def test_batch_upload(memory_manager):
    """Test batch upload to Supabase"""
    # Store 100 detections
    for i in range(100):
        memory_manager.store_detection({
            'layer': 'guardian',
            'class_name': 'person',
            'confidence': 0.9
        })

    # Wait for sync
    await asyncio.sleep(61)

    # Verify upload queue empty
    assert len(memory_manager.upload_queue) == 0

@pytest.mark.asyncio
async def test_offline_mode(memory_manager):
    """Test offline queue + resume"""
    # Disable WiFi
    memory_manager._is_wifi_connected = lambda: False

    # Store 10 detections
    for i in range(10):
        memory_manager.store_detection({...})

    # Verify queued locally
    assert len(memory_manager.upload_queue) == 10

    # Enable WiFi
    memory_manager._is_wifi_connected = lambda: True

    # Wait for sync
    await asyncio.sleep(61)

    # Verify uploaded
    assert len(memory_manager.upload_queue) == 0
```

### **Integration Tests** (End-to-end)

```python
# tests/test_integration_supabase.py
import pytest
from layer0_guardian import YOLOGuardian
from layer1_learner import YOLOELearner
from layer4_memory import HybridMemoryManager

@pytest.mark.asyncio
async def test_full_pipeline():
    """Test: Frame → Detection → Supabase → Dashboard"""

    # 1. Initialize system
    memory_manager = HybridMemoryManager(...)
    layer0 = YOLOGuardian(memory_manager=memory_manager)
    layer1 = YOLOELearner(memory_manager=memory_manager)

    # 2. Load test frame
    frame = load_test_frame("tests/test_frame.jpg")

    # 3. Run detection
    detections = layer0.detect(frame)
    adaptive_detections = layer1.detect(frame)

    # 4. Wait for sync (60s timeout)
    await asyncio.sleep(61)

    # 5. Verify in Supabase
    supabase = await create_async_client(URL, KEY)
    result = await supabase.table('detections').select('*').execute()

    assert len(result.data) > 0

    # 6. Verify dashboard can fetch
    response = requests.get('http://localhost:5000/api/detections?limit=100')
    assert response.status_code == 200
    assert len(response.json()) > 0
```

### **Performance Tests** (Load testing)

```python
# tests/test_performance_supabase.py
@pytest.mark.asyncio
async def test_detection_throughput():
    """Test: 1000 detections/minute sync"""

    memory_manager = HybridMemoryManager(...)

    # Generate 1000 detections rapidly
    start_time = time.time()
    for i in range(1000):
        memory_manager.store_detection({
            'layer': 'guardian',
            'class_name': 'person',
            'confidence': 0.9
        })

    duration = time.time() - start_time
    logger.info(f"Stored 1000 detections in {duration:.2f}s")

    # Should be <10s (local SQLite)
    assert duration < 10

    # Wait for batch upload
    await asyncio.sleep(61)

    # Verify uploaded
    assert len(memory_manager.upload_queue) == 0

@pytest.mark.asyncio
async def test_bandwidth_usage():
    """Test: Stay within 5GB/month limit"""

    # Simulate 1 hour of operation (60 batches)
    for batch in range(60):
        for i in range(100):
            memory_manager.store_detection({...})
        await asyncio.sleep(1)  # Simulate time

    # Calculate bandwidth
    bandwidth_used = calculate_bandwidth()

    # 5GB/month = 5GB/30days/24hours = ~7MB/hour
    assert bandwidth_used < 7 * 1024 * 1024  # 7MB
```

---

## ✅ ACCEPTANCE CRITERIA

### **Week 1: Supabase Setup**
- [ ] Supabase project created (free tier)
- [ ] All 6 tables created with indexes
- [ ] RLS policies configured
- [ ] Can insert/query via Python client
- [ ] Realtime subscription working

### **Week 2: Layer 4 Memory**
- [ ] HybridMemoryManager stores locally <10ms
- [ ] Background sync uploads every 60s
- [ ] Offline mode queues 100+ rows
- [ ] Local cache auto-cleans (>1000 rows)
- [ ] Unit tests pass (80% coverage)

### **Week 3: Layer Integration**
- [ ] Layer 0 stores detections to Supabase
- [ ] Layer 1 syncs prompts from Supabase
- [ ] Layer 2 stores transcripts to Supabase
- [ ] Layer 3 logs routing decisions
- [ ] All layers use HybridMemoryManager

### **Week 4: Dashboard**
- [ ] Flask dashboard displays device status
- [ ] Real-time updates <1 second
- [ ] Can switch detection mode remotely
- [ ] Detection chart shows last 100
- [ ] Works on mobile (responsive)

---

## 🚨 RISK MITIGATION

### **Risk 1: Supabase Downtime**
**Impact**: Cannot sync data, queue grows indefinitely
**Mitigation**:
- Local SQLite works 100% offline
- Queue size limit (1000 rows, auto-delete old)
- Alert if queue >500 rows (send notification)
- Graceful degradation (local-only mode)

### **Risk 2: Free Tier Limits Exceeded**
**Impact**: Uploads blocked, data loss
**Mitigation**:
- Monitor database size hourly (alert at 400MB)
- Auto-cleanup old data (>90 days)
- Compression for large objects (images)
- Bandwidth throttling (limit to 5GB/month)

### **Risk 3: WiFi Connectivity Issues**
**Impact**: Intermittent sync, duplicate uploads
**Mitigation**:
- Exponential backoff retry (1s, 2s, 4s, 8s, ...)
- Duplicate detection (use `synced` flag)
- Queue prioritization (ERROR logs first)
- Connection health check (ping every 30s)

### **Risk 4: Performance Degradation**
**Impact**: Sync slows down detection, >100ms latency
**Mitigation**:
- Async/non-blocking I/O (background thread)
- Batch uploads (1 request vs 100)
- Local cache (hit rate >95%)
- Performance monitoring (alert if >150ms)

---

## 📈 SUCCESS METRICS

### **Technical Metrics**
| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Detection → Supabase Latency** | <60s (batch) | Timestamp comparison |
| **Dashboard Update Latency** | <1s | Realtime WebSocket |
| **Local Storage Performance** | <10ms | SQLite insert timing |
| **Offline Queue Size** | <1000 rows | Periodic check |
| **Free Tier Compliance** | <500MB DB | Supabase dashboard |
| **Bandwidth Usage** | <5GB/month | Supabase dashboard |

### **Functional Metrics**
| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Data Loss** | 0 rows | Compare local vs cloud |
| **Offline Survival** | 24 hours | Disconnect WiFi test |
| **Remote Command Latency** | <5s | Command → execute time |
| **Dashboard Uptime** | 99% | Availability monitoring |
| **Multi-Device Ready** | Yes | Architecture supports |

---

## 🎁 BONUS FEATURES (Future Enhancement)

### **Phase 5: Advanced Analytics** (Post-Competition)
1. **Usage Dashboards**
   - Detections per hour/day/week
   - Class distribution (pie chart)
   - Confidence histogram
   - Routing decision breakdown

2. **Performance Monitoring**
   - Layer 0 latency percentiles (p50, p95, p99)
   - Layer 1 detection mode usage
   - Layer 2 Gemini quota tracking
   - Layer 4 sync success rate

3. **Alert System**
   - Email alerts (ERROR logs)
   - Pushover notifications (offline device)
   - Slack integration (daily summary)

### **Phase 6: Multi-Device Coordination** (Future)
1. **Device Registry**
   - Register multiple RPi5 units
   - Assign roles (primary, backup)
   - Handoff detection (failover)

2. **Federated Learning**
   - Share adaptive prompts between devices
   - Aggregate statistics (privacy-preserving)
   - Collaborative learning

---

## 📚 REFERENCES

- **Supabase Python Docs**: https://context7.com/supabase/supabase-py/llms.txt
- **Supabase Realtime**: https://supabase.com/docs/guides/realtime
- **Edge Functions**: https://supabase.com/docs/guides/functions
- **Free Tier Limits**: https://supabase.com/pricing
- **Context7 Research**: Supabase async client, WebSocket subscriptions, batch operations

---

## 🚀 NEXT STEPS

**Immediate Actions** (This Week):
1. Create Supabase account/project
2. Run database schema SQL script
3. Install `supabase` Python package: `pip install supabase`
4. Test basic connection: insert 1 row, query it back

**After Planning Approval**:
1. Start Week 1 implementation (Supabase setup)
2. Create GitHub project board for tracking
3. Set up daily standup meetings (15 min)
4. Deploy to RPi5 hardware for testing

---

**End of Implementation Plan**

**Ready to start implementation! 🎉**
