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
        conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes
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

        conn.commit()
        logger.info("✅ Local SQLite database initialized")
        return conn

    async def init_supabase(self):
        """Lazy initialization of Supabase client"""
        if not self.supabase_available:
            return

        if self.supabase_client is None:
            try:
                from supabase import create_async_client
                self.supabase_client = await create_async_client(
                    self.supabase_url,
                    self.supabase_key
                )
                logger.info("✅ Supabase client initialized")
            except ImportError:
                logger.warning("⚠️ supabase package not installed. Cloud sync disabled.")
                self.supabase_available = False
            except Exception as e:
                logger.error(f"❌ Failed to initialize Supabase: {e}")
                self.supabase_available = False

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

        # 2. Queue for cloud upload (non-blocking)
        self.upload_queue.append({
            'table': 'detections',
            'data': {**detection, 'device_id': self.device_id}
        })

        # 3. Cleanup old local rows (keep last 1000)
        self._cleanup_old_rows()

    def _cleanup_old_rows(self):
        """Delete old rows to keep local cache size under limit"""
        cursor = self.local_db.cursor()
        cursor.execute(f"""
            DELETE FROM detections_local
            WHERE id NOT IN (
                SELECT id FROM detections_local
                ORDER BY id DESC
                LIMIT {self.local_cache_size}
            )
        """)
        deleted = cursor.rowcount
        self.local_db.commit()

        if deleted > 0:
            logger.debug(f"🧹 Cleaned up {deleted} old rows from local DB")

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

                    # Mark as synced locally
                    self._mark_as_synced(batch)

                    # Remove from queue
                    self.upload_queue = self.upload_queue[len(batch):]

                    logger.info(f"✅ Synced {len(batch)} detections to Supabase")
                    logger.info(f"⏳ Queue size: {len(self.upload_queue)} rows remaining")

                except Exception as e:
                    logger.error(f"❌ Batch upload failed: {e}, will retry in {self.sync_interval}s")

            except Exception as e:
                logger.error(f"❌ Sync worker error: {e}")
                # Continue running even if one sync fails

        logger.info("⏹️ Background sync worker stopped")

    async def _upload_batch(self, batch: List[Dict[str, Any]]):
        """
        Upload batch of detections to Supabase

        Args:
            batch: List of detection dicts
        """
        if not self.supabase_client:
            await self.init_supabase()

        # Extract data from batch
        detections = [item['data'] for item in batch]

        # Add created_at timestamp
        for det in detections:
            det['created_at'] = datetime.utcnow().isoformat()

        # Batch insert
        start_time = time.time()
        result = await self.supabase_client.table('detections').insert(detections).execute()
        upload_time = (time.time() - start_time) * 1000

        logger.debug(f"⬆️ Upload: {len(detections)} rows in {upload_time:.2f}ms")

    def _mark_as_synced(self, batch: List[Dict[str, Any]]):
        """
        Mark detections as synced in local DB

        Args:
            batch: List of detection dicts with timestamp
        """
        cursor = self.local_db.cursor()

        for item in batch:
            timestamp = item['data'].get('timestamp')
            if timestamp:
                cursor.execute("""
                    UPDATE detections_local
                    SET synced = 1
                    WHERE timestamp = ?
                """, (timestamp,))

        self.local_db.commit()

    def _is_wifi_connected(self) -> bool:
        """
        Check if WiFi is connected (placeholder implementation)

        TODO: Implement actual WiFi detection
        - For RPi: Check /sys/class/net/wlan0/operstate
        - For laptop: Check network interfaces

        For now, returns True (assume connected)
        """
        # TODO: Implement actual WiFi detection
        # import os
        # if os.path.exists('/sys/class/net/wlan0/operstate'):
        #     with open('/sys/class/net/wlan0/operstate') as f:
        #         return f.read().strip() == 'up'
        return True

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
        Update device heartbeat in Supabase
        """
        # Ensure client is initialized
        if not self.supabase_client and self.supabase_available:
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
            logger.warning(f"⚠️ Heartbeat skipped: {e}")

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

    def cleanup(self):
        """Cleanup resources"""
        logger.info("🧹 Cleaning up Hybrid Memory Manager...")

        # Stop sync worker
        self.stop_sync_worker()

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
