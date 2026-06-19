"""Test all panel renderers with the new state shape."""
import sys
import logging
sys.path.insert(0, r'C:\Users\Haziq\Documents\ProjectCortex')
logging.disable(logging.CRITICAL)

from rpi5.live_dashboard.state import DashboardState
from rpi5.live_dashboard.app_textual import CortexFullApp


class MockSystem:
    _memory_init_state = ''
    def __getattr__(self, name):
        return None


def main():
    s = DashboardState()
    s.update(events=[
        {'ts': 1.0, 'source': 'l2', 'kind': 'heard',
         'message': '"Can you guide me outside my room?"'},
        {'ts': 4.0, 'source': 'l2', 'kind': 'said',
         'message': '"Sure, I can help with that."'},
        {'ts': 5.0, 'source': 'ai', 'kind': 'tool',
         'message': 'guide_indoor(destination="outside")'},
        {'ts': 6.0, 'source': 'safety', 'kind': 'alert',
         'message': 'overhang @1.2m'},
        {'ts': 7.0, 'source': 'stt', 'kind': 'heard',
         'message': '"Do you see the door?" (0.92)'},
    ])

    app = CortexFullApp(s, MockSystem())
    snap = s.snapshot()
    hist = s.history()

    # Render all 7 panels
    for panel_id in ['detection', 'layer2', 'sensors', 'system', 'tts', 'memory', 'activity']:
        try:
            panel = app._render_panel(panel_id, snap, hist)
            print(f'OK: {panel_id}')
        except Exception as e:
            print(f'FAIL: {panel_id}: {type(e).__name__}: {e}')

    # BT variants
    for bt in [
        {'connected': True, 'device': 'F-16', 'earbuds': 'CMF Buds', 'battery_pct': 87},
        {'connected': False, 'device': 'F-16', 'earbuds': '', 'battery_pct': -1},
        {'connected': False, 'device': '', 'earbuds': '', 'battery_pct': -1},
    ]:
        s.update(bt=bt)
        try:
            panel = app._render_panel('sensors', snap, hist)
            print(f'OK: bt connected={bt.get("connected")}')
        except Exception as e:
            print(f'FAIL: bt={bt.get("connected")}: {e}')

    # l2 state variants
    for st in ['connected', 'reconnecting', 'disconnected']:
        s.update(l2={
            'connected': st != 'disconnected',
            'state': st,
            'uptime_s': 60,
            'model': 'gemini-3.1',
            'voice': 'Zephyr',
            'lang': 'en',
        })
        try:
            panel = app._render_panel('layer2', snap, hist)
            print(f'OK: l2 state={st}')
        except Exception as e:
            print(f'FAIL: l2 state={st}: {e}')

    # L4 availability variants
    for l4 in [
        {'available': False, 'local_rows': 0, 'detections_stored': 0, 'events_stored': 0},
        {'available': True, 'local_rows': 0, 'detections_stored': 0, 'events_stored': 0},
        {'available': True, 'local_rows': 42, 'detections_stored': 100, 'events_stored': 5},
    ]:
        s.update(l4=l4)
        try:
            panel = app._render_panel('memory', snap, hist)
            print(f'OK: l4 available={l4.get("available")}, rows={l4.get("local_rows")}')
        except Exception as e:
            print(f'FAIL: l4: {e}')

    # System stats all populated
    s.update(
        system={'cpu_percent': 22.0, 'cpu_temp_c': 51.0, 'ram_percent': 45.0,
                'ram_used_mb': 1800, 'ram_total_mb': 4096, 'load_avg_1m': 0.5},
        disk={'used_gb': 8.5, 'total_gb': 32.0, 'percent': 26.5},
    )
    for panel_id in ['sensors', 'memory']:
        try:
            panel = app._render_panel(panel_id, snap, hist)
            print(f'OK: {panel_id} (with system stats)')
        except Exception as e:
            print(f'FAIL: {panel_id} (with system stats): {e}')


if __name__ == '__main__':
    main()
