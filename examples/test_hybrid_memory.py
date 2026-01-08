"""
Example script demonstrating HybridMemoryManager usage

This script shows how to:
1. Initialize HybridMemoryManager with Supabase
2. Store detections locally (fast, non-blocking)
3. Sync to Supabase in the background
4. Fetch historical data

Author: Haziq (@IRSPlays) + AI Implementer (Claude)
Date: January 8, 2026
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add rpi5 to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from layer4_memory.hybrid_memory_manager import HybridMemoryManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Example usage of HybridMemoryManager"""

    # =====================================================
    # STEP 1: Initialize with YOUR Supabase credentials
    # =====================================================
    manager = HybridMemoryManager(
        supabase_url="https://ziarxgoansbhesdypfic.supabase.co",
        supabase_key="sb_publishable_ErFxooa2JFiE8eXtd4hx3Q_Yll74lv_",
        device_id="rpi5-cortex-001",
        local_db_path="example_cortex.db",
        sync_interval=30,  # Sync every 30 seconds for demo (use 60s in production)
        batch_size=10  # Smaller batch for demo (use 100 in production)
        local_cache_size=100  # Keep last 100 locally (use 1000 in production)
    )

    # Start background sync worker
    manager.start_sync_worker()

    print("\n" + "="*70)
    print("HYBRID MEMORY MANAGER - EXAMPLE DEMO")
    print("="*70)

    # =====================================================
    # STEP 2: Store detections (simulating Layer 0 output)
    # =====================================================
    print("\n📸 STEP 1: Storing detections (simulating camera frames)...")

    # Simulate 20 camera frames
    for i in range(20):
        # Simulate detection from Layer 0 (Guardian)
        manager.store_detection({
            'layer': 'guardian',
            'class_name': 'person',
            'confidence': 0.92,
            'bbox_x1': 0.1, 'bbox_y1': 0.2,
            'bbox_x2': 0.3, 'bbox_y2': 0.4,
            'bbox_area': 0.04,
            'source': 'base'
        })

        # Simulate detection from Layer 1 (Learner)
        manager.store_detection({
            'layer': 'learner',
            'class_name': 'fire extinguisher',
            'confidence': 0.87,
            'bbox_x1': 0.5, 'bbox_y1': 0.3,
            'bbox_x2': 0.7, 'bbox_y2': 0.8,
            'bbox_area': 0.16,
            'detection_mode': 'text_prompts',
            'source': 'gemini'
        })

        if i % 5 == 0:
            print(f"   ✓ Stored {2 * (i + 1)} detections...")

    # =====================================================
    # STEP 3: Check local cache stats
    # =====================================================
    print("\n📊 STEP 2: Checking local cache stats...")
    stats = manager.get_stats()

    print(f"   Local DB rows: {stats['local_db_rows']}")
    print(f"   Unsynced rows: {stats['unsynced_rows']}")
    print(f"   Upload queue: {stats['upload_queue_size']} rows")

    # =====================================================
    # STEP 4: Wait for background sync
    # =====================================================
    print("\n🔄 STEP 3: Waiting for background sync (30 seconds)...")
    print("   (In production, this runs every 60 seconds in background)")

    # Wait for at least one sync cycle
    await asyncio.sleep(35)

    # =====================================================
    # STEP 5: Fetch data from Supabase
    # =====================================================
    print("\n⬇️  STEP 4: Fetching historical data from Supabase...")

    try:
        # Fetch recent detections from Supabase
        recent_detections = await manager.fetch_recent_detections(limit=10)
        print(f"   ✓ Fetched {len(recent_detections)} recent detections from Supabase")

        if recent_detections:
            print("\n   Sample detections:")
            for det in recent_detections[:3]:
                print(f"   - {det['class_name']}: {det['confidence']:.2f} ({det['layer']})")

    except Exception as e:
        print(f"   ⚠️  Failed to fetch from Supabase: {e}")
        print("   (This is normal if Supabase credentials are not configured)")

    # =====================================================
    # STEP 6: Store system log
    # =====================================================
    print("\n📝 STEP 5: Storing system log...")

    await manager.store_system_log(
        level='INFO',
        component='layer0',
        message='Example: Layer 0 detection completed',
        latency_ms=75,
        cpu_percent=45.2,
        memory_mb=2048
    )

    print("   ✓ System log stored")

    # =====================================================
    # STEP 7: Update device heartbeat
    # =====================================================
    print("\n💓 STEP 6: Updating device heartbeat...")

    await manager.update_device_heartbeat(
        device_name='RPi5-Cortex-001',
        battery_percent=85,
        cpu_percent=45.2,
        memory_mb=2048,
        temperature=42.5,
        active_layers=['layer0', 'layer1', 'layer2'],
        current_mode='TEXT_PROMPTS'
    )

    print("   ✓ Device heartbeat updated")

    # =====================================================
    # STEP 8: Final stats
    # =====================================================
    print("\n📊 STEP 7: Final stats...")
    stats = manager.get_stats()

    print(f"   Local DB rows: {stats['local_db_rows']}")
    print(f"   Synced rows: {stats['synced_rows']}")
    print(f"   Upload queue: {stats['upload_queue_size']} rows")
    print(f"   Sync worker running: {stats['sync_running']}")

    # =====================================================
    # CLEANUP
    # =====================================================
    print("\n🧹 Cleaning up...")
    manager.stop_sync_worker()
    manager.cleanup()

    print("\n" + "="*70)
    print("✅ EXAMPLE COMPLETE!")
    print("="*70)
    print("\nNext steps:")
    print("1. Check your local DB: ls -la example_cortex.db")
    print("2. Check Supabase dashboard: https://supabase.com/dashboard/project/ziarxgoansbhesdypfic")
    print("3. View detections in Table Editor")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(0)
