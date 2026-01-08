"""
Unit Tests for HybridMemoryManager

Tests cover:
1. Local storage (SQLite)
2. Upload queue management
3. Background sync worker
4. Supabase integration (mocked)
5. Offline mode handling

Author: Haziq (@IRSPlays) + AI Implementer (Claude)
Date: January 8, 2026
"""

import asyncio
import pytest
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from layer4_memory.hybrid_memory_manager import HybridMemoryManager


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def memory_manager(temp_db):
    """Create HybridMemoryManager for testing"""
    manager = HybridMemoryManager(
        supabase_url="https://test.supabase.co",
        supabase_key="test-key",
        device_id="test-device-001",
        local_db_path=temp_db,
        sync_interval=1,  # 1 second for fast testing
        batch_size=5,  # Small batch for testing
        local_cache_size=10  # Keep last 10 rows
    )
    yield manager
    manager.cleanup()


class TestLocalStorage:
    """Test local SQLite storage functionality"""

    def test_init_creates_local_db(self, temp_db):
        """Test that initialization creates local database"""
        manager = HybridMemoryManager(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            device_id="test-device",
            local_db_path=temp_db
        )

        # Check that database exists
        assert Path(temp_db).exists()

        # Check that table exists
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='detections_local'
        """)
        result = cursor.fetchone()
        assert result is not None
        conn.close()

        manager.cleanup()

    def test_store_detection_saves_locally(self, memory_manager):
        """Test that store_detection saves to local SQLite"""
        detection = {
            'layer': 'guardian',
            'class_name': 'person',
            'confidence': 0.92,
            'bbox_x1': 0.1, 'bbox_y1': 0.2,
            'bbox_x2': 0.3, 'bbox_y2': 0.4,
            'bbox_area': 0.04,
            'source': 'base'
        }

        memory_manager.store_detection(detection)

        # Verify stored in local DB
        cursor = memory_manager.local_db.cursor()
        cursor.execute("SELECT * FROM detections_local")
        rows = cursor.fetchall()

        assert len(rows) == 1
        assert rows[0][2] == 'person'  # class_name
        assert rows[0][3] == 0.92  # confidence
        assert rows[0][12] == 0  # synced flag (0 = not synced)

    def test_store_detection_adds_to_queue(self, memory_manager):
        """Test that store_detection adds to upload queue"""
        detection = {
            'layer': 'guardian',
            'class_name': 'person',
            'confidence': 0.92,
            'bbox_area': 0.04
        }

        memory_manager.store_detection(detection)

        # Check queue
        assert len(memory_manager.upload_queue) == 1
        assert memory_manager.upload_queue[0]['table'] == 'detections'
        assert memory_manager.upload_queue[0]['data']['class_name'] == 'person'

    def test_cleanup_old_rows(self, memory_manager):
        """Test that old rows are deleted to maintain cache size"""
        # Store 15 detections (cache size is 10)
        for i in range(15):
            memory_manager.store_detection({
                'layer': 'guardian',
                'class_name': 'person',
                'confidence': 0.9,
                'bbox_area': 0.04
            })

        # Check that only 10 rows remain
        cursor = memory_manager.local_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM detections_local")
        count = cursor.fetchone()[0]

        assert count == 10, f"Expected 10 rows, got {count}"

    def test_get_stats(self, memory_manager):
        """Test get_stats returns correct information"""
        # Store some detections
        for i in range(5):
            memory_manager.store_detection({
                'layer': 'guardian',
                'class_name': 'person',
                'confidence': 0.9,
                'bbox_area': 0.04
            })

        stats = memory_manager.get_stats()

        assert stats['local_db_rows'] == 5
        assert stats['unsynced_rows'] == 5
        assert stats['upload_queue_size'] == 5
        assert stats['device_id'] == 'test-device-001'


class TestUploadQueue:
    """Test upload queue management"""

    def test_queue_grows_with_detections(self, memory_manager):
        """Test that queue grows with more detections"""
        for i in range(10):
            memory_manager.store_detection({
                'layer': 'guardian',
                'class_name': 'person',
                'confidence': 0.9,
                'bbox_area': 0.04
            })

        assert len(memory_manager.upload_queue) == 10

    def test_queue_device_id_added(self, memory_manager):
        """Test that device_id is added to queued detections"""
        memory_manager.store_detection({
            'layer': 'guardian',
            'class_name': 'person',
            'confidence': 0.9,
            'bbox_area': 0.04
        })

        queued = memory_manager.upload_queue[0]
        assert queued['data']['device_id'] == 'test-device-001'


class TestBackgroundSync:
    """Test background sync worker"""

    @pytest.mark.asyncio
    async def test_sync_worker_starts_and_stops(self, memory_manager):
        """Test that sync worker can be started and stopped"""
        assert not memory_manager.sync_running

        memory_manager.start_sync_worker()
        assert memory_manager.sync_running

        # Wait a bit
        await asyncio.sleep(0.5)

        memory_manager.stop_sync_worker()
        assert not memory_manager.sync_running

    @pytest.mark.asyncio
    async def test_sync_with_mock_supabase(self, memory_manager):
        """Test sync worker with mocked Supabase client"""
        # Store some detections
        for i in range(3):
            memory_manager.store_detection({
                'layer': 'guardian',
                'class_name': 'person',
                'confidence': 0.9,
                'bbox_area': 0.04
            })

        # Mock Supabase client
        mock_client = AsyncMock()
        mock_client.table.return_value.insert.return_value.execute = AsyncMock(return_value=MagicMock())
        memory_manager.supabase_client = mock_client

        # Start sync worker
        memory_manager.start_sync_worker()

        # Wait for sync (sync_interval = 1s)
        await asyncio.sleep(2)

        # Stop sync worker
        memory_manager.stop_sync_worker()

        # Verify Supabase insert was called
        assert mock_client.table.called
        assert mock_client.table.return_value.insert.called


class TestOfflineMode:
    """Test offline mode handling"""

    def test_wifi_check_returns_bool(self, memory_manager):
        """Test that _is_wifi_connected returns boolean"""
        # This is a placeholder, should always return True in tests
        result = memory_manager._is_wifi_connected()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_offline_mode_queue_grows(self, memory_manager):
        """Test that queue grows when WiFi is 'disconnected'"""
        # Mock WiFi check to return False
        memory_manager._is_wifi_connected = lambda: False

        # Store detections
        for i in range(10):
            memory_manager.store_detection({
                'layer': 'guardian',
                'class_name': 'person',
                'confidence': 0.9,
                'bbox_area': 0.04
            })

        # Queue should grow
        assert len(memory_manager.upload_queue) == 10


class TestSupabaseIntegration:
    """Test Supabase integration (with mocking)"""

    @pytest.mark.asyncio
    async def test_init_supabase_client(self):
        """Test Supabase client initialization"""
        manager = HybridMemoryManager(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            device_id="test-device",
            local_db_path=":memory:"  # In-memory database for testing
        )

        with patch('layer4_memory.hybrid_memory_manager.create_async_client') as mock_create:
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            await manager.init_supabase()

            assert manager.supabase_client is not None
            assert mock_create.called

        manager.cleanup()

    @pytest.mark.asyncio
    async def test_store_query(self):
        """Test storing query to Supabase"""
        manager = HybridMemoryManager(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            device_id="test-device",
            local_db_path=":memory:"
        )

        # Mock Supabase client
        mock_client = AsyncMock()
        manager.supabase_client = mock_client

        await manager.store_query(
            user_query="what do you see",
            transcribed_text="what do you see",
            routed_layer="layer1",
            routing_confidence=0.95,
            ai_response="I see a person"
        )

        # Verify insert was called
        assert mock_client.table.called
        assert mock_client.table.return_value.insert.called

        manager.cleanup()

    @pytest.mark.asyncio
    async def test_store_system_log(self):
        """Test storing system log to Supabase"""
        manager = HybridMemoryManager(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            device_id="test-device",
            local_db_path=":memory:"
        )

        # Mock Supabase client
        mock_client = AsyncMock()
        manager.supabase_client = mock_client

        await manager.store_system_log(
            level='ERROR',
            component='layer0',
            message='Test error',
            latency_ms=100
        )

        # Verify insert was called
        assert mock_client.table.called

        manager.cleanup()


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
