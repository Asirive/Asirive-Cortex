"""Run the Textual FULL mode with mock data and take a screenshot.

Mocks all the new state fields added in round 3:
- system metrics (CPU/RAM/temp/load) on SENSORS panel
- camera state on SENSORS panel
- nav mode/state/destination/instruction/leg/transit on NAV panel
- recent STT on TTS panel
- recent safety alerts on DETECTION panel
"""
import sys
import asyncio
import time
from pathlib import Path

# Allow running from rpi5.live_dashboard.tests
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent.parent))  # rpi5/
sys.path.insert(0, str(HERE.parent.parent))  # rpi5/live_dashboard/

from rpi5.live_dashboard.state import DashboardState
from rpi5.live_dashboard.app_textual import CortexFullApp, TEXTUAL_AVAILABLE


class MockSystem:
    def __init__(self):
        self.tts = type("FakeTTS", (), {"muted": False})()
    def _toggle_session_recording(self):
        pass


def main():
    if not TEXTUAL_AVAILABLE:
        print("Textual not available, skipping")
        return 1
    state = DashboardState()
    now = time.time()
    # Seed with realistic data
    state.update(
        mode="PRODUCTION", fps=20.5,
        l0_count=3, l0_classes=["person", "car", "traffic sign"], l0_latency_ms=47.0,
        l1_count=2, l1_classes=["door", "box"], l1_latency_ms=89.0,
        l1_mode="TEXT_PROMPTS",
        gps={"fix": 3, "sats": 11, "lat": 1.3521, "lon": 103.8198, "source": "m8u"},
        imu={"heading": 45.0, "cal": [3, 3, 3, 3]},
        environment="outdoor",
        bt={"connected": True, "device": "F-16", "earbuds": "CMF Buds", "battery_pct": 87},
        ai={"active": True, "last_call": "local"},
        l2={
            "connected": True, "uptime_s": 312.0,
            "model": "gemini-3.1-flash-live-preview",
            "voice": "Zephyr", "lang": "en",
            "last_heard": "navigate to school", "last_said": "starting outdoor navigation",
            "transcript": [
                "YOU: where am I right now?",
                "CORTEX: you're at home in Singapore, Sembawang area",
                "YOU: navigate to school",
                "CORTEX: ok, walking route via Sembawang Way, 1.2 km total",
                "YOU: how long will it take?",
                "CORTEX: about 15 minutes, take bus 16 from the stop ahead",
                "YOU: what bus do I take after that?",
                "CORTEX: bus 16 to Admiralty, then transfer to MRT",
                "YOU: is there an elevator at the station?",
                "CORTEX: yes, the Admiralty MRT has lift access on platform B",
            ],
            "tool_calls": 2, "google_searches": 1,
            "audio_input_level": 0.42,
            "latency_ms": {"avg": 540, "p95": 920, "ttfb": 280},
            "tool_call_log": [
                {"name": "get_navigation", "args_preview": "dest=school", "result_preview": "1.2km via Sembawang Way", "ts": now - 15},
                {"name": "google_search", "args_preview": "bus 16 schedule", "result_preview": "every 8 min, peak: 5 min", "ts": now - 22},
                {"name": "get_elevation", "args_preview": "loc=1.35,103.82", "result_preview": "12m above sea level", "ts": now - 41},
            ],
        },
        nav={
            # Headline
            "mode": "outdoor",
            "state": "navigating",
            "destination": "school",
            # Instruction + progress
            "next_instruction": "Walk 200m to bus stop, board bus 16",
            "waypoint_index": 2,
            "total_waypoints": 5,
            "distance_to_waypoint_m": 180.0,
            "distance_to_destination_m": 1200.0,
            "bearing_to_waypoint": 90.0,
            # Active leg (walking leg)
            "current_leg_type": "bus",
            "current_leg_distance_m": 180.0,
            "current_leg_duration_s": 240.0,
            "current_leg_instruction": "board bus 16 towards Sembawang",
            # Transit info
            "transit_service_no": "16",
            "transit_line_name": "",
            "transit_line_color": "",
            "transit_departure_stop": "Blk 123",
            "transit_arrival_stop": "Admiralty Stn",
            "transit_num_stops": 4,
            "transit_headsign": "Sembawang",
            # Saved
            "saved_locations": [
                {"name": "home", "address": "9 Canberra Drive", "default": True},
                {"name": "school", "address": "(set)"},
                {"name": "relative's", "address": "311 Canberra Rd"},
            ],
            "last_nav_destination": "school",
            "bus_state": "active", "lta_ok": True,
        },
        connectivity={"online": True, "ping_ms": 12, "supabase_ok": True, "last_supabase_sync_s": 14.0},
        tts={"engine": "cartesia", "state": "speaking", "fallback_engine": "supertonic", "voice": "Zephyr", "speed": 1.0, "muted": False},
        voice={"listening": True, "vad_active": False},
        safety={"tier": 0, "alert_type": "", "distance_m": 0.0, "alerts_last_60s": 3, "t0": 0, "t1": 0, "t2": 1, "t3": 2},
        l4={"local_rows": 1247, "last_sync_age_s": 14.0, "next_sync_in_s": 46.0, "sync_status": "idle", "detections_stored": 1180, "events_stored": 312, "upload_queue": 0, "upload_failed": 0},
        recorder={"is_recording": False, "toggle_key": "b"},
        hailo={"depth_fps": 21.0, "ocr_state": "idle"},
        # NEW: system metrics
        system={
            "cpu_percent": 42.0,
            "cpu_temp_c": 64.5,
            "ram_used_mb": 2150,
            "ram_total_mb": 7680,
            "ram_percent": 28.0,
            "load_avg_1m": 0.42,
        },
        # NEW: disk usage
        disk={
            "used_gb": 18.0,
            "total_gb": 64.0,
            "percent": 28.0,
            "free_gb": 46.0,
        },
        # NEW: camera
        camera={
            "available": True,
            "backend": "Picamera2",
            "resolution": [1920, 1080],
            "fps_target": 30.0,
        },
        # NEW: recent STT (4 entries now)
        stt_recent=[
            {"text": "navigate to school", "ts": now - 12, "confidence": 0.94},
            {"text": "how long will it take", "ts": now - 45, "confidence": 0.91},
            {"text": "what bus do I take", "ts": now - 90, "confidence": 0.88},
            {"text": "is there an elevator at the station?", "ts": now - 120, "confidence": 0.85},
        ],
        # NEW: recent safety alerts (3 entries)
        safety_recent=[
            {"type": "incoming_fast", "distance_m": 3.2, "tier": 3, "ts": now - 8},
            {"type": "wall",         "distance_m": 1.2, "tier": 1, "ts": now - 31},
            {"type": "overhang",     "distance_m": 0.6, "tier": 0, "ts": now - 65},
        ],
        # NEW: per-service health
        services={
            "supabase":    {"ok": True, "last_check_s": now - 14},
            "gemini":      {"ok": True, "last_check_s": now - 3},
            "google_maps": {"ok": True, "last_check_s": now - 60},
            "phone_gps":   {"ok": False, "last_check_s": now - 45},
        },
        # NEW: scene change detector
        scene={
            "last_change_ts": now - 22,
            "last_change_type": "indoor→outdoor",
        },
        # NEW: button press
        button={
            "last_press_ts": now - 18,
            "last_press_type": "short",
        },
        # NEW: activity feed (last 8 events, oldest first → newest last)
        events=[
            {"ts": now - 95, "source": "l2",      "kind": "tool",     "message": "google_search(bus 16 schedule) → every 8 min, peak 5 min"},
            {"ts": now - 78, "source": "nav",     "kind": "route",    "message": "→ school · 1.2 km via Sembawang Way"},
            {"ts": now - 65, "source": "safety",  "kind": "critical", "message": "overhang @0.6m"},
            {"ts": now - 45, "source": "stt",     "kind": "heard",    "message": "\"how long will it take\" (0.91)"},
            {"ts": now - 42, "source": "l2",      "kind": "said",     "message": "ok, walking route via Sembawang Way, 1.2 km total"},
            {"ts": now - 31, "source": "safety",  "kind": "alert",    "message": "wall @1.2m"},
            {"ts": now - 22, "source": "scene",   "kind": "info",     "message": "scene: indoor→outdoor"},
            {"ts": now - 18, "source": "btn",     "kind": "info",     "message": "short press"},
            {"ts": now - 12, "source": "stt",     "kind": "heard",    "message": "\"navigate to school\" (0.94)"},
            {"ts": now -  8, "source": "safety",  "kind": "alert",    "message": "incoming_fast @3.2m"},
            {"ts": now -  3, "source": "l2",      "kind": "tool",     "message": "get_navigation(dest=school) → 1.2km via Sembawang Way"},
        ],
        # NEW: session stats
        uptime_s=3847.0,
        frames_processed=68340,
        loop_iterations=3842,
    )
    # Seed history
    for i in range(40):
        state.record_sample(fps=15.0 + (i % 12), l0_count=(i % 4), l0_latency_ms=40.0 + (i % 20))
    # Seed L2 latency history for the sparkline
    for i in range(40):
        state.record_sample(l2_latency_ms=400.0 + ((i * 13) % 600))

    app = CortexFullApp(state, MockSystem())

    async def run_with_screenshot():
        # Use a larger terminal so all panel content fits. 180×70 is a typical
        # production terminal and gives panels ~17 rows tall each.
        async with app.run_test(size=(180, 70)) as pilot:
            # Let it render a few times
            await pilot.pause(0.05)
            for _ in range(5):
                await pilot.pause(0.5)
            # Save screenshot
            svg_path = "/tmp/cortex_full_screenshot.svg"
            app.save_screenshot(svg_path)
            print(f"SCREENSHOT_SAVED={svg_path}")
            await pilot.pause(0.2)

    asyncio.run(run_with_screenshot())
    return 0


if __name__ == "__main__":
    sys.exit(main())

