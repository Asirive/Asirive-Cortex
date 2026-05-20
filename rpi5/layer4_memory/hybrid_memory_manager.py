"""
Hybrid Memory Manager - Dual Storage System (SQLite + Supabase)

This module manages dual storage strategy:
- Local: SQLite (hot cache, last 1000 detections, <10ms writes)
- Cloud: Supabase PostgreSQL (all historical data, batch upload every 60s)

Key Features:
- Fast local writes (<10ms)
- Offline support (queue locally, sync when online)
- Bandwidth efficient (batch upload 100 rows at once)
- Auto-cleanup (keep last 1000 rows locally)
- Graceful degradation (works if Supabase down)

Author: Haziq (@IRSPlays) + AI Implementer (Claude)
Date: January 8, 2026
"""

import asyncio
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class HybridMemoryManager:
    """
    Manages dual storage: Local SQLite (hot cache) + Supabase (cold storage)

    Sync Strategy:
    1. Store all data locally first (<10ms, fast)
    2. Queue for batch upload every 60 seconds
    3. Keep local cache of last 1000 detections (delete older)
    4. Offline mode: queue locally, sync when online
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        device_id: str,
        local_db_path: str = "local_cortex.db",
        sync_interval: int = 60,
        batch_size: int = 100,
        local_cache_size: int = 1000
    ):
        """
        Initialize Hybrid Memory Manager

        Args:
            supabase_url: Supabase project URL
            supabase_key: Supabase anon key
            device_id: Unique device identifier (UUID)
            local_db_path: Path to local SQLite database
            sync_interval: Seconds between batch uploads (default: 60)
            batch_size: Max rows per batch upload (default: 100)
            local_cache_size: Max rows to keep locally (default: 1000)
        """
        logger.info("🧠 Initializing Hybrid Memory Manager...")

        # Configuration
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.device_id = device_id
        self.sync_interval = sync_interval
        self.batch_size = batch_size
        self.local_cache_size = local_cache_size

        # Local: SQLite (hot cache)
        self.local_db_path = local_db_path
        self.local_db = self._init_local_db()

        # Cloud: Supabase (lazy initialization)
        self.supabase_client = None
        self.supabase_available = True # Assume available until proven otherwise
        self._supabase_backoff = 1  # H23: Exponential backoff seconds
        self._supabase_disabled_at = None  # H26: Track when supabase was disabled
        self._supabase_retry_cooldown = 300  # H26: Retry after 5 minutes

        # Upload queue (for offline mode)
        self.upload_queue = []
        self._queue_lock = threading.Lock()
        self._heartbeat_inflight = threading.Lock()

        # Background sync worker
        self.sync_running = False
        self.sync_task = None
        self._sync_loop = None
        self._sync_thread = None

        # Local write buffer (batch inserts to avoid blocking detection threads)
        self._local_write_buffer: List[Dict[str, Any]] = []
        self._local_buffer_lock = threading.Lock()
        self._local_flush_interval = 5.0  # Flush every 5 seconds
        self._local_flush_thread = None
        self._cleanup_counter = 0

        logger.info("✅ Hybrid Memory Manager initialized")
        logger.info(f"   Local DB: {local_db_path}")
        logger.info(f"   Sync Interval: {sync_interval}s")
        logger.info(f"   Batch Size: {batch_size} rows")
        logger.info(f"   Local Cache: {local_cache_size} rows")

    def _init_local_db(self) -> sqlite3.Connection:
        """Initialize local SQLite database with schema"""
        conn = sqlite3.connect(self.local_db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL for better concurrency
        # NORMAL: faster commits (~1-2ms) vs FULL (~5-20ms). Power-loss risk is acceptable
        # for detection logs; critical data uses explicit fsync elsewhere.
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

        # Create tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS detections_local (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer TEXT NOT NULL,
                class_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                bbox_x1 REAL,
                bbox_y1 REAL,
                bbox_x2 REAL,
                bbox_y2 REAL,
                bbox_area REAL,
                detection_mode TEXT,
                source TEXT,
                timestamp REAL NOT NULL,
                synced INTEGER DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_detections_synced
            ON detections_local(synced, timestamp)
        """)

        # Conversations table (for ConversationManager)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations_local (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                query_type TEXT,
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_session
            ON conversations_local(session_id, timestamp)
        """)

        # User profile table (for personalization)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        conn.commit()
        logger.info("✅ Local SQLite database initialized")
        return conn

    def recall(self, object_name: str, latest: bool = True) -> Optional[Dict[str, Any]]:
        """Legacy object-recall adapter used by Gemini tool calls."""
        try:
            cursor = self.local_db.cursor()
            search_term = f"%{object_name}%"
            order_clause = "DESC" if latest else "ASC"

            columns = {
                row[1] for row in cursor.execute("PRAGMA table_info(conversations_local)").fetchall()
            }

            if "full_response" in columns:
                row = cursor.execute(
                    f"""
                    SELECT COALESCE(full_response, content), timestamp
                    FROM conversations_local
                    WHERE LOWER(content) LIKE LOWER(?)
                       OR LOWER(full_response) LIKE LOWER(?)
                    ORDER BY timestamp {order_clause}
                    LIMIT 1
                    """,
                    (search_term, search_term),
                ).fetchone()
            else:
                row = cursor.execute(
                    f"""
                    SELECT content, timestamp
                    FROM conversations_local
                    WHERE LOWER(content) LIKE LOWER(?)
                    ORDER BY timestamp {order_clause}
                    LIMIT 1
                    """,
                    (search_term,),
                ).fetchone()

            if row:
                description, timestamp = row
                return {
                    "object_name": object_name,
                    "description": description or "",
                    "location_estimate": "",
                    "timestamp": datetime.fromtimestamp(timestamp).isoformat() if timestamp else "",
                }

            detection_row = cursor.execute(
                f"""
                SELECT class_name, timestamp
                FROM detections_local
                WHERE LOWER(class_name) LIKE LOWER(?)
                ORDER BY timestamp {order_clause}
                LIMIT 1
                """,
                (search_term,),
            ).fetchone()
            if detection_row:
                class_name, timestamp = detection_row
                return {
                    "object_name": class_name,
                    "description": f"I last logged a detection for {class_name}.",
                    "location_estimate": "",
                    "timestamp": datetime.fromtimestamp(timestamp).isoformat() if timestamp else "",
                }
        except Exception as e:
            logger.debug(f"Recall adapter failed for '{object_name}': {e}")

        return None

    async def init_supabase(self):
        """Lazy initialization of Supabase client"""
        # H26: If disabled, check if cooldown has elapsed for retry
        if not self.supabase_available:
            if self._supabase_disabled_at is not None:
                elapsed = time.time() - self._supabase_disabled_at
                if elapsed >= self._supabase_retry_cooldown:
                    logger.info("🔄 Supabase cooldown elapsed, retrying connection...")
                    self.supabase_available = True
                    self._supabase_backoff = 1
                    self._supabase_disabled_at = None
                else:
                    return
            else:
                return

        if self.supabase_client is None:
            try:
                from supabase import create_async_client
                self.supabase_client = await create_async_client(
                    self.supabase_url,
                    self.supabase_key
                )
                logger.info("✅ Supabase client initialized")
                self._supabase_backoff = 1  # Reset backoff on success
            except ImportError:
                logger.warning("⚠️ supabase package not installed. Cloud sync disabled.")
                self.supabase_available = False
            except Exception as e:
                logger.error(f"❌ Failed to initialize Supabase: {e}")
                self._disable_supabase_with_cooldown()

    def store_detection(self, detection: Dict[str, Any]) -> None:
        """
        Store detection locally (fast, non-blocking)
        Will be uploaded to cloud in next batch

        Args:
            detection: Detection dictionary with keys:
                - layer: 'guardian' or 'learner'
                - class_name: str
                - confidence: float (0-1)
                - bbox_x1, bbox_y1, bbox_x2, bbox_y2: float (normalized 0-1)
                - bbox_area: float
                - detection_mode: str (optional)
                - source: str (optional)
        """
        # Buffer in memory — background thread flushes to SQLite.
        # This keeps the detection ThreadPoolExecutor worker unblocked.
        with self._local_buffer_lock:
            self._local_write_buffer.append(detection)
            buffer_size = len(self._local_write_buffer)

        if buffer_size >= 50:
            self._trigger_local_flush()

    def _trigger_local_flush(self):
        """Spawn a background thread to flush the local write buffer."""
        with self._local_buffer_lock:
            if not self._local_write_buffer:
                return
            batch = self._local_write_buffer[:]
            self._local_write_buffer = []
        threading.Thread(target=self._flush_local_buffer, args=(batch,), daemon=True).start()

    def _flush_local_buffer(self, batch: List[Dict[str, Any]]):
        """Batch write detections to SQLite and queue for cloud sync."""
        if not batch:
            return
        try:
            start_time = time.time()
            cursor = self.local_db.cursor()
            for d in batch:
                cursor.execute("""
                    INSERT INTO detections_local
                    (layer, class_name, confidence, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                     bbox_area, detection_mode, source, timestamp, synced)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    d.get('layer'), d.get('class_name'), d.get('confidence'),
                    d.get('bbox_x1'), d.get('bbox_y1'), d.get('bbox_x2'), d.get('bbox_y2'),
                    d.get('bbox_area'), d.get('detection_mode'), d.get('source'),
                    time.time()
                ))
                row_id = cursor.lastrowid
                queue_item = {
                    'table': 'detections',
                    'row_id': row_id,
                    'data': {**d, 'device_id': self.device_id}
                }
                with self._queue_lock:
                    if len(self.upload_queue) < self.local_cache_size * 2:
                        self.upload_queue.append(queue_item)
                    else:
                        self.upload_queue.pop(0)
                        self.upload_queue.append(queue_item)
            self.local_db.commit()
            write_time = (time.time() - start_time) * 1000
            logger.debug(f"💾 Local batch write: {len(batch)} rows in {write_time:.2f}ms")

            # Cleanup old rows periodically (~every 100 inserted rows)
            self._cleanup_counter += len(batch)
            if self._cleanup_counter >= 100:
                self._cleanup_counter = 0
                self._cleanup_old_rows()
        except Exception as e:
            logger.error(f"❌ Local batch flush failed: {e}")

    def _cleanup_old_rows(self):
        """Delete old synced rows to keep local cache size under limit.
        Only deletes rows that have been synced to cloud (synced=1)."""
        cursor = self.local_db.cursor()
        cursor.execute(f"""
            DELETE FROM detections_local
            WHERE synced = 1 AND id NOT IN (
                SELECT id FROM detections_local
                WHERE synced = 1
                ORDER BY id DESC
                LIMIT {self.local_cache_size}
            )
        """)
        deleted = cursor.rowcount
        self.local_db.commit()

        if deleted > 0:
            logger.debug(f"🧹 Cleaned up {deleted} old synced rows from local DB")

    async def _sync_worker(self):
        """
        Background worker: Upload queued data every sync_interval seconds
        """
        logger.info(f"🔄 Background sync worker started (interval: {self.sync_interval}s)")

        while self.sync_running:
            try:
                await asyncio.sleep(self.sync_interval)

                with self._queue_lock:
                    if not self.upload_queue:
                        batch = []
                    else:
                        batch = list(self.upload_queue[:self.batch_size])

                if not batch:
                    logger.debug("✓ Upload queue empty, skipping sync")
                    continue

                if not self._is_wifi_connected():
                    logger.info("⚠️ WiFi disconnected, queueing locally")
                    continue

                # Initialize Supabase if needed
                await self.init_supabase()

                try:
                    await self._upload_batch(batch)

                    # M19: Mark as synced — if this fails, rows will be re-uploaded (safe duplicate)
                    try:
                        self._mark_as_synced(batch)
                    except Exception as mark_err:
                        logger.error(f"Failed to mark batch as synced: {mark_err}. Rows may re-upload.")

                    # Remove synced rows from queue without disturbing newer appends.
                    synced_row_ids = {
                        item.get('row_id') for item in batch if item.get('row_id') is not None
                    }
                    with self._queue_lock:
                        self.upload_queue = [
                            item for item in self.upload_queue
                            if item.get('row_id') not in synced_row_ids
                        ]
                        queue_size = len(self.upload_queue)

                    logger.info(f"✅ Synced {len(batch)} detections to Supabase")
                    logger.info(f"⏳ Queue size: {queue_size} rows remaining")

                except Exception as e:
                    logger.error(f"❌ Batch upload failed: {e}, backoff {self._supabase_backoff}s")
                    self._handle_supabase_failure()
                    await asyncio.sleep(self._supabase_backoff)

            except Exception as e:
                logger.error(f"❌ Sync worker error: {e}")
                # Continue running even if one sync fails

        logger.info("⏹️ Background sync worker stopped")

    async def _upload_batch(self, batch: List[Dict[str, Any]]):
        """
        Upload batch of detections to Supabase with timeout and backoff.

        Args:
            batch: List of detection dicts
        """
        if not self.supabase_client:
            await self.init_supabase()
        if not self.supabase_client:
            return

        # Extract data from batch
        detections = [item['data'] for item in batch]

        # Add created_at timestamp
        for det in detections:
            det['created_at'] = datetime.utcnow().isoformat()

        # H25: Batch insert with timeout
        start_time = time.time()
        try:
            result = await asyncio.wait_for(
                self.supabase_client.table('detections').insert(detections).execute(),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            logger.error("❌ Supabase upload timed out (15s)")
            self._handle_supabase_failure()
            raise
        upload_time = (time.time() - start_time) * 1000
        self._supabase_backoff = 1  # Reset backoff on success

        logger.debug(f"⬆️ Upload: {len(detections)} rows in {upload_time:.2f}ms")

    def _mark_as_synced(self, batch: List[Dict[str, Any]]):
        """
        Mark detections as synced in local DB using row_id.

        Args:
            batch: List of detection dicts with row_id
        """
        row_ids = [item.get('row_id') for item in batch if item.get('row_id') is not None]
        if not row_ids:
            return

        with sqlite3.connect(self.local_db_path, check_same_thread=False, timeout=5.0) as conn:
            placeholders = ','.join('?' * len(row_ids))
            conn.execute(f"""
                UPDATE detections_local
                SET synced = 1
                WHERE id IN ({placeholders})
            """, row_ids)
            conn.commit()

    def _is_wifi_connected(self) -> bool:
        """
        Check if WiFi/network is actually connected.
        """
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(("8.8.8.8", 53))
            sock.close()
            return True
        except (socket.error, OSError):
            return False

    async def fetch_recent_detections(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch recent detections from Supabase

        Args:
            limit: Max number of detections to fetch

        Returns:
            List of detection dicts
        """
        if not self.supabase_client:
            await self.init_supabase()
        if not self.supabase_client:
            return []

        result = await self.supabase_client.table('detections')\
            .select('*')\
            .eq('device_id', self.device_id)\
            .order('created_at', desc=True)\
            .limit(limit)\
            .execute()

        return result.data

    async def fetch_adaptive_prompts(self) -> List[Dict[str, Any]]:
        """
        Fetch adaptive prompts from Supabase

        Returns:
            List of prompt dicts with class_name, source, use_count
        """
        if not self.supabase_client:
            await self.init_supabase()
        if not self.supabase_client:
            return []

        result = await self.supabase_client.table('adaptive_prompts')\
            .select('*')\
            .eq('device_id', self.device_id)\
            .order('use_count', desc=True)\
            .execute()

        return result.data

    async def store_query(
        self,
        user_query: str,
        transcribed_text: str,
        routed_layer: str,
        routing_confidence: float,
        detection_mode: Optional[str] = None,
        ai_response: Optional[str] = None,
        response_latency_ms: Optional[int] = None,
        tier_used: Optional[str] = None
    ):
        """
        Store user query and AI response

        Args:
            user_query: Original user query text
            transcribed_text: Whisper transcription output
            routed_layer: Which layer was routed to ('layer1', 'layer2', 'layer3')
            routing_confidence: Router confidence score (0-1)
            detection_mode: Detection mode if Layer 1
            ai_response: AI's response
            response_latency_ms: End-to-end latency in ms
            tier_used: Which tier was used ('local', 'gemini_live', etc.)
        """
        if not self.supabase_client:
            await self.init_supabase()
        if not self.supabase_client:
            logger.debug("Supabase unavailable, skipping query store")
            return

        await self.supabase_client.table('queries').insert({
            'device_id': self.device_id,
            'user_query': user_query,
            'transcribed_text': transcribed_text,
            'routed_layer': routed_layer,
            'routing_confidence': routing_confidence,
            'detection_mode': detection_mode,
            'ai_response': ai_response,
            'response_latency_ms': response_latency_ms,
            'tier_used': tier_used,
            'created_at': datetime.utcnow().isoformat()
        }).execute()

        logger.debug(f"💾 Query stored: {routed_layer} - {user_query[:50]}...")

    async def store_system_log(
        self,
        level: str,
        component: str,
        message: str,
        latency_ms: Optional[int] = None,
        cpu_percent: Optional[float] = None,
        memory_mb: Optional[int] = None,
        error_trace: Optional[str] = None
    ):
        """
        Store system log entry

        Args:
            level: 'DEBUG', 'INFO', 'WARNING', 'ERROR'
            component: 'layer0', 'layer1', 'layer2', 'layer3', 'layer4'
            message: Log message
            latency_ms: Operation latency in ms
            cpu_percent: CPU usage percentage
            memory_mb: Memory usage in MB
            error_trace: Error stack trace (if applicable)
        """
        if not self.supabase_client:
            await self.init_supabase()
        if not self.supabase_client:
            logger.debug("Supabase unavailable, skipping system log store")
            return

        await self.supabase_client.table('system_logs').insert({
            'device_id': self.device_id,
            'level': level,
            'component': component,
            'message': message,
            'latency_ms': latency_ms,
            'cpu_percent': cpu_percent,
            'memory_mb': memory_mb,
            'error_trace': error_trace,
            'created_at': datetime.utcnow().isoformat()
        }).execute()

        if level == 'ERROR':
            logger.error(f"📝 ERROR logged: {component} - {message}")

    async def update_device_heartbeat(
        self,
        device_name: str,
        battery_percent: Optional[int] = None,
        cpu_percent: Optional[float] = None,
        memory_mb: Optional[int] = None,
        temperature: Optional[float] = None,
        active_layers: Optional[List[str]] = None,
        current_mode: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None
    ):
        """
        Update device heartbeat in Supabase (graceful degradation)
        """
        # Guard clause: Skip if Supabase is disabled
        if not self.supabase_available:
            logger.debug("⏭️ Heartbeat skipped: Supabase disabled")
            return
        if not self._is_wifi_connected():
            logger.debug("⏭️ Heartbeat skipped: no network")
            return
        if not self._heartbeat_inflight.acquire(blocking=False):
            logger.debug("⏭️ Heartbeat skipped: previous heartbeat still running")
            return

        try:
            # Ensure client is initialized
            if not self.supabase_client:
                await asyncio.wait_for(self.init_supabase(), timeout=5.0)

            # Guard clause: If still not available (failed init), exit
            if not self.supabase_client:
                return

            # Call Supabase RPC function
            await asyncio.wait_for(
                self.supabase_client.rpc('update_device_heartbeat', {
                    'p_device_id': self.device_id,
                    'p_device_name': device_name,
                    'p_battery': battery_percent,
                    'p_cpu': cpu_percent,
                    'p_memory': memory_mb,
                    'p_temp': temperature,
                    'p_active_layers': active_layers,
                    'p_current_mode': current_mode,
                    'p_lat': latitude,
                    'p_lon': longitude
                }).execute(),
                timeout=5.0,
            )

            logger.debug(f"💓 Heartbeat updated: {device_name}")
        except asyncio.TimeoutError:
            logger.warning("⚠️ Heartbeat skipped: timed out")
            self._handle_supabase_failure()
        except Exception as e:
            error_msg = str(e)
            # Check for known non-critical errors (function overload ambiguity)
            if 'PGRST203' in error_msg or 'could not choose' in error_msg.lower():
                logger.warning("⚠️ Heartbeat skipped: Supabase function overload - fix database")
                # Disable future attempts to avoid log spam
                self.supabase_available = False
            elif 'Event loop is closed' in error_msg:
                # Suppress during shutdown
                pass
            else:
                logger.warning(f"⚠️ Heartbeat skipped: {e}")
                self._handle_supabase_failure()
        finally:
            self._heartbeat_inflight.release()

    def start_sync_worker(self):
        """Start background sync worker"""
        if not self.sync_running:
            self.sync_running = True
            self._sync_thread = threading.Thread(
                target=self._sync_worker_thread,
                name="memory-sync-worker",
                daemon=True,
            )
            self._sync_thread.start()
            self._start_local_flush_worker()
            logger.info("✅ Sync worker started")

    def stop_sync_worker(self):
        """Stop background sync worker"""
        if self.sync_running:
            self.sync_running = False
            self._stop_local_flush_worker()
            if self._sync_loop and self.sync_task:
                def _cancel_sync_task():
                    if self.sync_task and not self.sync_task.done():
                        self.sync_task.cancel()

                self._sync_loop.call_soon_threadsafe(_cancel_sync_task)
            if self._sync_thread and self._sync_thread.is_alive():
                self._sync_thread.join(timeout=2.0)
            self._sync_thread = None
            logger.info("⏹️ Sync worker stopped")

    def _start_local_flush_worker(self):
        """Start periodic background flush of local write buffer."""
        self._local_flush_running = True

        def _timer_loop():
            while self._local_flush_running:
                time.sleep(self._local_flush_interval)
                self._trigger_local_flush()

        self._local_flush_thread = threading.Thread(
            target=_timer_loop,
            name="memory-local-flush",
            daemon=True,
        )
        self._local_flush_thread.start()
        logger.info("✅ Local flush worker started")

    def _stop_local_flush_worker(self):
        """Stop the local flush worker."""
        self._local_flush_running = False
        if self._local_flush_thread and self._local_flush_thread.is_alive():
            self._local_flush_thread.join(timeout=2.0)
        self._local_flush_thread = None
        # Final flush of any remaining buffered detections
        self._trigger_local_flush()
        logger.info("⏹️ Local flush worker stopped")

    def _sync_worker_thread(self):
        """Own the background event loop that drives periodic Supabase sync."""
        loop = asyncio.new_event_loop()
        self._sync_loop = loop
        asyncio.set_event_loop(loop)
        self.sync_task = loop.create_task(self._sync_worker())
        try:
            loop.run_until_complete(self.sync_task)
        except asyncio.CancelledError:
            pass
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.sync_task = None
            self._sync_loop = None
            loop.close()

    # =================================================================
    # CONVERSATION MEMORY METHODS
    # =================================================================

    def store_conversation_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        query_type: Optional[str] = None
    ):
        """
        Store a single conversation turn to local SQLite.
        
        Args:
            session_id: UUID session identifier
            role: 'user' or 'model'
            content: Text content of the turn
            query_type: Optional query type (e.g., 'analysis_ocr')
        """
        try:
            cursor = self.local_db.cursor()
            cursor.execute("""
                INSERT INTO conversations_local
                (session_id, role, content, query_type, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, role, content, query_type, time.time()))
            self.local_db.commit()
            logger.debug(f"💬 Conversation turn stored: {role} ({len(content)} chars)")
        except Exception as e:
            logger.error(f"❌ Failed to store conversation turn: {e}")

    def get_session_turns(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get all turns for a given session.
        
        Args:
            session_id: UUID session identifier
            
        Returns:
            List of turn dicts with role, content, query_type, timestamp
        """
        try:
            cursor = self.local_db.cursor()
            cursor.execute("""
                SELECT role, content, query_type, timestamp
                FROM conversations_local
                WHERE session_id = ?
                ORDER BY timestamp ASC
            """, (session_id,))
            
            rows = cursor.fetchall()
            return [
                {
                    'role': row[0],
                    'content': row[1],
                    'query_type': row[2],
                    'timestamp': row[3],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"❌ Failed to get session turns: {e}")
            return []

    def get_latest_session_id(self) -> Optional[Dict[str, Any]]:
        """
        Get the most recent session_id and its last timestamp.
        
        Returns:
            Dict with 'session_id' and 'last_timestamp', or None
        """
        try:
            cursor = self.local_db.cursor()
            cursor.execute("""
                SELECT session_id, MAX(timestamp) as last_ts
                FROM conversations_local
                GROUP BY session_id
                ORDER BY last_ts DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row[0]:
                return {
                    'session_id': row[0],
                    'last_timestamp': row[1],
                }
            return None
        except Exception as e:
            logger.error(f"❌ Failed to get latest session: {e}")
            return None

    def store_user_profile(self, key: str, value: str):
        """
        Store a user profile fact (upsert).
        
        Args:
            key: Profile key (e.g., 'name', 'allergy')
            value: Profile value
        """
        try:
            cursor = self.local_db.cursor()
            cursor.execute("""
                INSERT INTO user_profile (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """, (key, value, time.time(), value, time.time()))
            self.local_db.commit()
            logger.info(f"👤 User profile updated: {key} = '{value}'")
        except Exception as e:
            logger.error(f"❌ Failed to store user profile: {e}")

    def get_user_profile(self) -> Dict[str, str]:
        """
        Get all user profile key-value pairs.
        
        Returns:
            Dict of profile facts
        """
        try:
            cursor = self.local_db.cursor()
            cursor.execute("SELECT key, value FROM user_profile")
            rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            logger.error(f"❌ Failed to get user profile: {e}")
            return {}

    def cleanup_old_conversations(self, days: int = 7):
        """
        Delete conversations older than N days from local SQLite.
        
        Args:
            days: Delete conversations older than this many days
        """
        cutoff = time.time() - (days * 86400)
        try:
            cursor = self.local_db.cursor()
            cursor.execute(
                "DELETE FROM conversations_local WHERE timestamp < ?",
                (cutoff,)
            )
            deleted = cursor.rowcount
            self.local_db.commit()
            if deleted > 0:
                logger.info(f"🧹 Cleaned up {deleted} conversation turns older than {days} days")
        except Exception as e:
            logger.error(f"❌ Failed to cleanup old conversations: {e}")

    def _disable_supabase_with_cooldown(self):
        """H26: Disable Supabase with auto-retry cooldown."""
        self.supabase_available = False
        self._supabase_disabled_at = time.time()
        logger.warning(f"⚠️ Supabase disabled, will retry in {self._supabase_retry_cooldown}s")

    def _handle_supabase_failure(self):
        """H23: Exponential backoff on Supabase failures."""
        self._supabase_backoff = min(self._supabase_backoff * 2, 300)  # Cap at 5 min
        logger.warning(f"⚠️ Supabase failure, backoff: {self._supabase_backoff}s")
        if self._supabase_backoff >= 60:
            self._disable_supabase_with_cooldown()

    def cleanup(self):
        """Cleanup resources"""
        logger.info("🧹 Cleaning up Hybrid Memory Manager...")

        # Stop sync worker (also triggers final local flush)
        self.stop_sync_worker()

        # H24: Close Supabase client if initialized
        if self.supabase_client:
            try:
                # Supabase async client doesn't have sync close, but we clear the reference
                self.supabase_client = None
                logger.info("✅ Supabase client released")
            except Exception as e:
                logger.warning(f"⚠️ Error releasing Supabase client: {e}")

        # Final flush of any remaining buffered detections before closing DB
        with self._local_buffer_lock:
            if self._local_write_buffer:
                batch = self._local_write_buffer[:]
                self._local_write_buffer = []
                self._flush_local_buffer(batch)

        # Close local DB
        if self.local_db:
            self.local_db.close()
            logger.info("✅ Local DB closed")

        logger.info("✅ Hybrid Memory Manager cleaned up")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the memory manager

        Returns:
            Dict with stats: local_rows, queue_size, etc.
        """
        cursor = self.local_db.cursor()

        # Local DB stats
        cursor.execute("SELECT COUNT(*) FROM detections_local")
        local_rows = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM detections_local WHERE synced = 0")
        unsynced_rows = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM detections_local WHERE synced = 1")
        synced_rows = cursor.fetchone()[0]

        return {
            'device_id': self.device_id,
            'local_db_rows': local_rows,
            'unsynced_rows': unsynced_rows,
            'synced_rows': synced_rows,
            'upload_queue_size': len(self.upload_queue),
            'sync_running': self.sync_running,
            'local_db_path': self.local_db_path
        }


# Example usage
if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)

    async def test():
        # Initialize
        manager = HybridMemoryManager(
            supabase_url="https://your-project.supabase.co",
            supabase_key="your-anon-key",
            device_id="test-device-001"
        )

        # Test storing detections
        for i in range(10):
            manager.store_detection({
                'layer': 'guardian',
                'class_name': 'person',
                'confidence': 0.9,
                'bbox_x1': 0.1, 'bbox_y1': 0.2,
                'bbox_x2': 0.3, 'bbox_y2': 0.4,
                'bbox_area': 0.04,
                'source': 'base'
            })

        # Get stats
        stats = manager.get_stats()
        print(f"\n📊 Stats: {stats}")

        # Cleanup
        manager.cleanup()

    asyncio.run(test())
