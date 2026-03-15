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

        # Background sync worker
        self.sync_running = False
        self.sync_task = None

        logger.info("✅ Hybrid Memory Manager initialized")
        logger.info(f"   Local DB: {local_db_path}")
        logger.info(f"   Sync Interval: {sync_interval}s")
        logger.info(f"   Batch Size: {batch_size} rows")
        logger.info(f"   Local Cache: {local_cache_size} rows")

    def _init_local_db(self) -> sqlite3.Connection:
        """Initialize local SQLite database with schema"""
        conn = sqlite3.connect(self.local_db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL for better concurrency
        conn.execute("PRAGMA synchronous=FULL")  # Safe for power-failure scenarios (wearable device)
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
        start_time = time.time()

        # 1. Store locally (<10ms)
        cursor = self.local_db.cursor()
        cursor.execute("""
            INSERT INTO detections_local
            (layer, class_name, confidence, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
             bbox_area, detection_mode, source, timestamp, synced)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            detection.get('layer'),
            detection.get('class_name'),
            detection.get('confidence'),
            detection.get('bbox_x1'),
            detection.get('bbox_y1'),
            detection.get('bbox_x2'),
            detection.get('bbox_y2'),
            detection.get('bbox_area'),
            detection.get('detection_mode'),
            detection.get('source'),
            time.time()
        ))
        self.local_db.commit()

        write_time = (time.time() - start_time) * 1000
        logger.debug(f"💾 Local write: {write_time:.2f}ms")

        # 2. Queue for cloud upload (non-blocking, capped to prevent OOM)
        row_id = cursor.lastrowid
        if len(self.upload_queue) < self.local_cache_size * 2:
            self.upload_queue.append({
                'table': 'detections',
                'row_id': row_id,
                'data': {**detection, 'device_id': self.device_id}
            })
        else:
            logger.warning(f"Upload queue full ({len(self.upload_queue)} items), dropping oldest")
            self.upload_queue.pop(0)
            self.upload_queue.append({
                'table': 'detections',
                'row_id': row_id,
                'data': {**detection, 'device_id': self.device_id}
            })

        # 3. Cleanup old local rows (keep last 1000)
        self._cleanup_old_rows()

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

                if not self.upload_queue:
                    logger.debug("✓ Upload queue empty, skipping sync")
                    continue

                if not self._is_wifi_connected():
                    logger.info("⚠️ WiFi disconnected, queueing locally")
                    continue

                # Initialize Supabase if needed
                await self.init_supabase()

                # Batch upload (max batch_size rows at once)
                batch = self.upload_queue[:self.batch_size]

                try:
                    await self._upload_batch(batch)

                    # M19: Mark as synced — if this fails, rows will be re-uploaded (safe duplicate)
                    try:
                        self._mark_as_synced(batch)
                    except Exception as mark_err:
                        logger.error(f"Failed to mark batch as synced: {mark_err}. Rows may re-upload.")

                    # Remove from queue
                    self.upload_queue = self.upload_queue[len(batch):]

                    logger.info(f"✅ Synced {len(batch)} detections to Supabase")
                    logger.info(f"⏳ Queue size: {len(self.upload_queue)} rows remaining")

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
        cursor = self.local_db.cursor()

        row_ids = [item.get('row_id') for item in batch if item.get('row_id') is not None]
        if row_ids:
            placeholders = ','.join('?' * len(row_ids))
            cursor.execute(f"""
                UPDATE detections_local
                SET synced = 1
                WHERE id IN ({placeholders})
            """, row_ids)

        self.local_db.commit()

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
            
        # Ensure client is initialized
        if not self.supabase_client:
             await self.init_supabase()
              
        # Guard clause: If still not available (failed init), exit
        if not self.supabase_client:
            return

        try:
            # Call Supabase RPC function
            await self.supabase_client.rpc('update_device_heartbeat', {
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
            }).execute()

            logger.debug(f"💓 Heartbeat updated: {device_name}")
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

    def start_sync_worker(self):
        """Start background sync worker"""
        if not self.sync_running:
            self.sync_running = True
            # Handle both async and sync contexts
            try:
                # We're in an async context with running loop
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # We're in a sync context, create a new loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            self.sync_task = loop.create_task(self._sync_worker())
            logger.info("✅ Sync worker started")

    def stop_sync_worker(self):
        """Stop background sync worker"""
        if self.sync_running:
            self.sync_running = False
            if self.sync_task:
                self.sync_task.cancel()
            logger.info("⏹️ Sync worker stopped")

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

        # Stop sync worker
        self.stop_sync_worker()

        # H24: Close Supabase client if initialized
        if self.supabase_client:
            try:
                # Supabase async client doesn't have sync close, but we clear the reference
                self.supabase_client = None
                logger.info("✅ Supabase client released")
            except Exception as e:
                logger.warning(f"⚠️ Error releasing Supabase client: {e}")

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
