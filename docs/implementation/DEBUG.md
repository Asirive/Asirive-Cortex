---
COMPREHENSIVE IMPLEMENTATION PLAN
Document: docs/implementation/BUG-FIXES-AND-IMPROVEMENTS-PLAN.md
---
 ProjectCortex v2.0 - Bug Fixes and Improvements Plan
**Author:** AI Assistant (OpenCode)  
**Date:** February 1, 2026  
**Status:** Ready for Implementation  
**Competition:** Young Innovators Awards (YIA) 2026
---
 Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Critical Bugs (Priority 1)](#2-critical-bugs-priority-1)
3. [High Priority Bugs (Priority 2)](#3-high-priority-bugs-priority-2)
4. [Medium Priority Bugs (Priority 3)](#4-medium-priority-bugs-priority-3)
5. [Low Priority Bugs (Priority 4)](#5-low-priority-bugs-priority-4)
6. [Feature Implementations](#6-feature-implementations)
7. [Configuration Improvements](#7-configuration-improvements)
8. [Protocol Synchronization](#8-protocol-synchronization)
9. [Implementation Order](#9-implementation-order)
10. [Testing Strategy](#10-testing-strategy)
---
 1. Executive Summary
This document outlines all bugs and improvements identified in the ProjectCortex codebase. Total issues found: **27**
| Priority | Count | Examples |
|----------|-------|----------|
| Critical | 5 | Button commands failing, async bugs |
| High | 6 | Bluetooth not starting, hardcoded IPs |
| Medium | 8 | Missing handlers, race conditions |
| Low | 4 | Bare excepts, thread safety |
| Features | 4 | Auto-connect Bluetooth, IP centralization |
---
 2. Critical Bugs (Priority 1)
 2.1 Button Commands Not Reaching RPi5
**Location:** `laptop/cli/start_dashboard.py:632-646`
**Problem:** When sending commands via FastAPI mode, the code creates a NEW event loop in a NEW thread. The WebSocket object was created in Uvicorn's event loop. Calling `websocket.send_text()` from a different loop causes silent failure.
**Current Code (Broken):**
def send_sync():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(connection_manager.send_message(device_id, cmd_msg))
    finally:
        loop.close()
send_thread = threading.Thread(target=send_sync, daemon=True)
send_thread.start()
Fix: Store Uvicorn's event loop reference and use asyncio.run_coroutine_threadsafe():
# In start_dashboard.py, store loop when FastAPI starts:
class DashboardRunner:
    def __init__(self):
        self._uvicorn_loop = None
    
    def _start_fastapi_server(self):
        # Store loop reference before starting
        self._uvicorn_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._uvicorn_loop)
        # ... start uvicorn ...
# In _handle_ui_command, use the stored loop:
if self._uvicorn_loop and self._uvicorn_loop.is_running():
    future = asyncio.run_coroutine_threadsafe(
        connection_manager.send_message(device_id, cmd_msg),
        self._uvicorn_loop
    )
    try:
        future.result(timeout=5.0)  # Wait up to 5 seconds
        logger.info(f"✅ Command sent to {device_id}")
    except Exception as e:
        logger.error(f"❌ Failed to send to {device_id}: {e}")
Files to Modify:
- laptop/cli/start_dashboard.py (lines 587-660)
---
2.2 Missing load_config Import
Location: rpi5/main.py:716
Problem: If a custom config_path is passed to CortexSystem.__init__(), it calls load_config(config_path) which is never imported.
Fix: Add to imports at line 193:
from rpi5.config.config import get_config, load_config
Files to Modify:
- rpi5/main.py (line 193)
---
2.3 Async Method Called Without Await
Location: shared/api/base_client.py:177-180
Problem: self._disconnect_impl() is called without await in sync stop() method.
Fix: Use the existing run_async_safe() helper:
def stop(self):
    """Stop the client (sync wrapper)."""
    if hasattr(self, '_disconnect_impl'):
        from rpi5.main import run_async_safe
        run_async_safe(self._disconnect_impl())
    self._running = False
Or add a sync disconnect method:
def _disconnect_sync(self):
    """Synchronous disconnect implementation."""
    self._connected = False
    self._closing = True
    # Close websocket if open
    if self._websocket:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._websocket.close(), loop
                ).result(timeout=2.0)
        except:
            pass
Files to Modify:
- shared/api/base_client.py (lines 177-180)
---
2.4 Infinite Loop Condition
Location: shared/api/base_client.py:252
Problem: while self._lock: checks if the lock object is truthy, which is ALWAYS True.
Fix:
# Change from:
while self._lock:
# To:
while self._connected and not self._closing:
Files to Modify:
- shared/api/base_client.py (line 252)
---
2.5 Shadows Built-in TimeoutError
Location: shared/api/exceptions.py:157
Problem: TimeoutError = ConnectionTimeout shadows Python's built-in.
Fix: Rename to ConnectionTimeoutError:
# Change from:
TimeoutError = ConnectionTimeout
# To:
ConnectionTimeoutError = ConnectionTimeout
And update all imports that use TimeoutError from this module.
Files to Modify:
- shared/api/exceptions.py (line 157)
- All files importing TimeoutError from this module
---
3. High Priority Bugs (Priority 2)
3.1 Bluetooth Not Initialized at Startup
Location: rpi5/main.py
Problem: Bluetooth is only initialized in set_mode("PRODUCTION"), which is never called automatically.
Fix: Add Bluetooth initialization to CortexSystem.start():
def start(self):
    """Start the Cortex system."""
    # ... existing code ...
    
    # Initialize Bluetooth if configured
    bluetooth_config = self.config.get('bluetooth', {})
    if bluetooth_config.get('auto_connect', False):
        self._init_bluetooth(bluetooth_config)
    
    # Set default mode (ensures voice coordinator starts)
    self.set_mode("DEV")
    
    # ... rest of start() ...
def _init_bluetooth(self, config: Dict):
    """Initialize Bluetooth audio connection."""
    if not BluetoothAudioManager:
        logger.warning("BluetoothAudioManager not available")
        return
    
    device_name = config.get('device_name', 'CMF Buds')
    try:
        self.bt_manager = BluetoothAudioManager(
            device_name=device_name,
            max_retries=config.get('retry_count', 3)
        )
        if self.bt_manager.connect_and_setup():
            logger.info(f"✅ Bluetooth audio connected: {device_name}")
            # Start auto-reconnect monitoring
            if config.get('auto_reconnect', True):
                self.bt_manager.start_auto_reconnect()
        else:
            logger.warning(f"⚠️ Bluetooth setup failed for {device_name}")
    except Exception as e:
        logger.error(f"❌ Bluetooth init error: {e}")
Files to Modify:
- rpi5/main.py (add _init_bluetooth() method, modify start())
- rpi5/config/config.yaml (add bluetooth config section)
---
3.2 Hardcoded IPs Throughout Codebase
Locations: 18+ files with hardcoded IPs
Fix Strategy: All code should read from get_config()['laptop_server']['host'] instead of hardcoded defaults.
Files to Modify and Changes:
| File | Lines | Change |
|------|-------|--------|
| rpi5/fastapi_client.py | 70, 446 | Read from config if host=None |
| rpi5/websocket_client.py | 45, 375 | Read from config if host=None |
| rpi5/__main__.py | 69-70, 98, 134-135, 164, 178, 198 | Read default from config |
| rpi5/cli/commands.py | 23, 274 | Read default from config |
| shared/config/__init__.py | 227 | Mark as fallback only |
Example Fix for rpi5/fastapi_client.py:
def __init__(
    self,
    host: str = None,  # No hardcoded default
    port: int = 8765,
    ...
):
    # Read from config if not provided
    if host is None:
        from rpi5.config.config import get_config
        config = get_config()
        host = config.get('laptop_server', {}).get('host', '0.0.0.0')
    
    self.host = host
    # ... rest of init ...
Example Fix for rpi5/__main__.py:
def create_parser() -> argparse.ArgumentParser:
    # Load config to get default laptop IP
    try:
        from rpi5.config.config import get_config
        config = get_config()
        default_laptop = config.get('laptop_server', {}).get('host', '0.0.0.0')
    except:
        default_laptop = '0.0.0.0'
    
    # ... use default_laptop in argparse defaults ...
---
3.3 VoiceCoordinator Never Started
Location: rpi5/main.py:877-878
Problem: VoiceCoordinator.initialize() is called but start() is never called by default.
Fix: Call set_mode("DEV") at end of start() to establish default mode:
def start(self):
    # ... existing initialization ...
    
    # Set default mode (starts voice coordinator in appropriate state)
    self.set_mode("DEV")
    
    # Start main loop
    self._main_loop()
Files to Modify:
- rpi5/main.py (in start() method)
---
3.4 Video Streaming Flag Inconsistent
Location: rpi5/main.py:869
Problem: video_streaming_active=True even when video_streamer=None (if init failed).
Fix:
# Change from:
self.video_streaming_active = True
# To:
self.video_streaming_active = (self.video_streamer is not None)
Files to Modify:
- rpi5/main.py (line 869)
---
3.5 asyncio.run() in Running Loop
Locations:
- laptop/cli/start_dashboard.py:194
- laptop/cli/start_dashboard.py:549
- laptop/server/fastapi_integration.py:173
Fix: Check for running loop first:
def run_async_safe(coro):
    """Run coroutine safely, handling existing event loops."""
    try:
        loop = asyncio.get_running_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    except RuntimeError:
        return asyncio.run(coro)
Files to Modify:
- laptop/cli/start_dashboard.py (lines 194, 549)
- laptop/server/fastapi_integration.py (line 173)
---
3.6 Missing Protocol MessageTypes
Location: laptop/protocol.py
Problem: Missing LAYER_RESPONSE, CONNECT, DISCONNECT, ACK from MessageType enum.
Fix: Synchronize with shared/api/protocol.py (see Section 8).
---
4. Medium Priority Bugs (Priority 3)
4.1 Missing Server Message Handlers
Location: laptop/server/fastapi_server.py
Missing Handlers:
- _handle_status()
- _handle_audio_event()
- _handle_memory_event()
- _handle_gps_imu()
- _handle_layer_response()
Fix: Add handler methods:
async def _handle_status(self, client_id: str, message: BaseMessage):
    """Handle STATUS messages from RPi5."""
    logger.debug(f"Status from {client_id}: {message.data}")
    # Forward to GUI if callback registered
    if self._on_status_cb:
        await self._safe_callback(self._on_status_cb, client_id, message.data)
async def _handle_audio_event(self, client_id: str, message: BaseMessage):
    """Handle AUDIO_EVENT messages from RPi5."""
    logger.debug(f"Audio event from {client_id}: {message.data}")
async def _handle_memory_event(self, client_id: str, message: BaseMessage):
    """Handle MEMORY_EVENT messages from RPi5."""
    logger.debug(f"Memory event from {client_id}: {message.data}")
async def _handle_gps_imu(self, client_id: str, message: BaseMessage):
    """Handle GPS_IMU messages from RPi5."""
    logger.debug(f"GPS/IMU from {client_id}: {message.data}")
async def _handle_layer_response(self, client_id: str, message: BaseMessage):
    """Handle LAYER_RESPONSE messages from RPi5."""
    logger.info(f"Layer response from {client_id}: {message.data}")
Files to Modify:
- laptop/server/fastapi_server.py
---
4.2 Missing Client Message Handlers
Location: rpi5/fastapi_client.py
Missing Handlers:
- _handle_navigation()
- _handle_spatial_audio()
Fix:
async def _handle_navigation(self, message: BaseMessage):
    """Handle NAVIGATION messages from laptop."""
    data = message.data
    logger.info(f"📍 Navigation command received: {data}")
    # TODO: Forward to Layer 3 spatial audio system
async def _handle_spatial_audio(self, message: BaseMessage):
    """Handle SPATIAL_AUDIO messages from laptop."""
    data = message.data
    logger.info(f"🔊 Spatial audio config received: {data}")
    # TODO: Apply spatial audio settings
Files to Modify:
- rpi5/fastapi_client.py
---
4.3 LAYER1_QUERY/LAYER1_RESPONSE Not in Protocol
Location: shared/api/protocol.py
Fix: Add to MessageType enum:
class MessageType(str, Enum):
    # ... existing types ...
    LAYER1_QUERY = "LAYER1_QUERY"
    LAYER1_RESPONSE = "LAYER1_RESPONSE"
Files to Modify:
- shared/api/protocol.py
- laptop/protocol.py (sync)
---
4.4 Race Condition in Connection Manager
Location: laptop/server/fastapi_server.py:127-140
Problem: Lock released before async send.
Fix: Use asyncio.Lock and hold during entire operation:
class FastAPIConnectionManager:
    def __init__(self):
        self._lock = asyncio.Lock()  # Changed from threading.Lock
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def send_message(self, device_id: str, message: BaseMessage) -> bool:
        async with self._lock:
            websocket = self.active_connections.get(device_id)
            if websocket:
                try:
                    await websocket.send_text(message.to_json())
                    return True
                except Exception as e:
                    logger.error(f"Send failed to {device_id}: {e}")
                    return False
        return False
Files to Modify:
- laptop/server/fastapi_server.py (lines 105-140)
---
4.5-4.8 Additional Medium Priority
(Detailed in full implementation - includes MessageType comparison fixes, exception handling improvements)
---
5. Low Priority Bugs (Priority 4)
5.1 Bare Except Clauses (18+ locations)
Fix Strategy: Replace all bare except: with specific exceptions:
# Change from:
except:
    return 0.0
# To:
except (OSError, IOError, ValueError) as e:
    logger.debug(f"Failed to read CPU temp: {e}")
    return 0.0
Files to Modify:
- rpi5/main.py (lines 605, 1107)
- rpi5/layer3_guide/spatial_audio/*.py (multiple files)
- models/yolo26s_ncnn_model/model_pnnx.py
---
5.2 StatusDisplay Singleton Not Thread-Safe
Location: rpi5/main.py:270-276
Fix:
class StatusDisplay:
    _instance = None
    _init_lock = threading.Lock()
    
    def __new__(cls):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance
Files to Modify:
- rpi5/main.py (StatusDisplay class)
---
6. Feature Implementations
6.1 Bluetooth Auto-Connect with Pairing Support
Location: rpi5/bluetooth_handler.py
New Methods to Add:
class BluetoothAudioManager:
    # ... existing code ...
    
    def scan_devices(self, duration: int = 10) -> List[Dict]:
        """Scan for nearby Bluetooth devices."""
        logger.info(f"🔍 Scanning for Bluetooth devices ({duration}s)...")
        
        # Start scanning
        subprocess.run(
            ["bluetoothctl", "scan", "on"],
            capture_output=True, timeout=5
        )
        
        time.sleep(duration)
        
        # Stop scanning
        subprocess.run(
            ["bluetoothctl", "scan", "off"],
            capture_output=True, timeout=5
        )
        
        # Get all discovered devices
        result = subprocess.run(
            ["bluetoothctl", "devices"],
            capture_output=True, text=True, timeout=10
        )
        
        devices = []
        for line in result.stdout.strip().split('\n'):
            if line.startswith('Device '):
                parts = line.split(' ', 2)
                if len(parts) >= 3:
                    devices.append({
                        'mac': parts[1],
                        'name': parts[2]
                    })
        
        logger.info(f"Found {len(devices)} devices")
        return devices
    
    def pair_device(self, mac_address: str) -> bool:
        """Pair with a Bluetooth device."""
        logger.info(f"🔗 Pairing with {mac_address}...")
        
        result = subprocess.run(
            ["bluetoothctl", "pair", mac_address],
            capture_output=True, text=True, timeout=30
        )
        
        if "Pairing successful" in result.stdout or "already paired" in result.stdout.lower():
            logger.info(f"✅ Paired with {mac_address}")
            return True
        else:
            logger.error(f"❌ Pairing failed: {result.stdout} {result.stderr}")
            return False
    
    def start_auto_reconnect(self, check_interval: float = 10.0):
        """Start background thread to monitor and reconnect."""
        if hasattr(self, '_reconnect_thread') and self._reconnect_thread.is_alive():
            return  # Already running
        
        self._reconnect_running = True
        self._reconnect_thread = threading.Thread(
            target=self._monitor_connection,
            args=(check_interval,),
            daemon=True,
            name="BluetoothReconnect"
        )
        self._reconnect_thread.start()
        logger.info("🔄 Bluetooth auto-reconnect started")
    
    def stop_auto_reconnect(self):
        """Stop the auto-reconnect thread."""
        self._reconnect_running = False
    
    def _monitor_connection(self, interval: float):
        """Background thread to monitor and reconnect."""
        while self._reconnect_running:
            try:
                if self.current_mac and not self.is_connected(self.current_mac):
                    logger.warning("🔌 Bluetooth disconnected, attempting reconnect...")
                    if self.connect_and_setup():
                        logger.info("✅ Bluetooth reconnected")
                    else:
                        logger.warning("⚠️ Reconnect failed, will retry")
            except Exception as e:
                logger.error(f"Reconnect check error: {e}")
            
            time.sleep(interval)
    
    def auto_connect_or_pair(self, scan_duration: int = 15) -> bool:
        """
        Auto-connect to known device, or scan and pair if not found.
        
        Flow:
        1. Try to connect to already-paired device matching device_name
        2. If not found, scan for new devices
        3. If matching device found in scan, pair and connect
        """
        # Step 1: Try known paired devices
        mac = self.find_device_by_name()
        if mac:
            logger.info(f"Found paired device: {mac}")
            return self.connect_and_setup()
        
        # Step 2: Scan for new devices
        logger.info(f"Device '{self.device_name}' not paired. Scanning...")
        devices = self.scan_devices(scan_duration)
        
        # Step 3: Find matching device in scan results
        for device in devices:
            if self.device_name.lower() in device['name'].lower():
                logger.info(f"Found matching device: {device['name']} ({device['mac']})")
                
                # Step 4: Pair
                if self.pair_device(device['mac']):
                    # Step 5: Trust and connect
                    self.trust_device(device['mac'])
                    time.sleep(1)
                    return self.connect_and_setup()
        
        logger.error(f"No device matching '{self.device_name}' found")
        return False
Files to Modify:
- rpi5/bluetooth_handler.py (add new methods)
- rpi5/main.py (use auto_connect_or_pair())
---
6.2 Centralized IP Configuration
Config Addition to rpi5/config/config.yaml:
# =====================================================
# NETWORK CONFIGURATION
# =====================================================
# RPi5 Device (for sync tools - not used in runtime code)
rpi5_device:
  host: "10.225.12.31"
  user: "cortex"
  path: "/home/cortex/ProjectCortex"
# Laptop Server (RPi5 connects to this)
laptop_server:
  host: "10.225.12.101"
  port: 8765
  zmq_port: 5555
# =====================================================
# BLUETOOTH CONFIGURATION
# =====================================================
bluetooth:
  enabled: true
  auto_connect: true
  auto_reconnect: true
  device_name: "CMF Buds"
  retry_count: 3
  scan_duration: 15
New Helper Script get_config.py:
#!/usr/bin/env python3
"""
Helper script to read config values for batch files.
Usage:
    python get_config.py rpi5_device.host    # Returns: 10.225.12.31
    python get_config.py laptop_server.port  # Returns: 8765
"""
import sys
from pathlib import Path
import yaml
def get_nested(d: dict, key: str, default=''):
    """Get nested dictionary value using dot notation."""
    keys = key.split('.')
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d
def main():
    config_paths = [
        Path(__file__).parent / "rpi5" / "config" / "config.yaml",
        Path(__file__).parent.parent / "rpi5" / "config" / "config.yaml",
    ]
    
    config = {}
    for path in config_paths:
        if path.exists():
            with open(path) as f:
                config = yaml.safe_load(f) or {}
            break
    
    if len(sys.argv) > 1:
        print(get_nested(config, sys.argv[1]))
    else:
        print("Usage: python get_config.py <key.path>")
if __name__ == "__main__":
    main()
Modified sync_rpi5.py (lines 40-55):
def load_rpi_config() -> Dict[str, str]:
    """Load RPi5 configuration from config.yaml."""
    config_paths = [
        Path(__file__).parent / "rpi5" / "config" / "config.yaml",
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                rpi_config = config.get('rpi5_device', {})
                return {
                    'host': rpi_config.get('host', '10.225.12.31'),
                    'user': rpi_config.get('user', 'cortex'),
                    'path': rpi_config.get('path', '/home/cortex/ProjectCortex'),
                }
    
    # Fallback
    logger.warning("Config not found, using defaults")
    return {'host': '10.225.12.31', 'user': 'cortex', 'path': '/home/cortex/ProjectCortex'}
# Load configuration
_rpi_config = load_rpi_config()
RPI_HOST_IP = _rpi_config['host']
RPI_USER = _rpi_config['user']
RPI_PATH = _rpi_config['path']
RPI_HOST = f"{RPI_USER}@{RPI_HOST_IP}"
Files to Modify:
- rpi5/config/config.yaml (add sections)
- sync_rpi5.py (read from config)
- Create get_config.py (new helper)
- sync.bat, sync_sc.bat, sync_fullpath.bat (optional - use helper)
---
7. Configuration Improvements
7.1 Add Bluetooth Section to config.yaml
See Section 6.2 above.
7.2 Add Network Section to config.yaml
See Section 6.2 above.
---
8. Protocol Synchronization
Strategy: Keep Both Files in Sync
Since you want to keep both laptop/protocol.py and shared/api/protocol.py, we need to synchronize them.
Changes to laptop/protocol.py:
1. Change MessageType to string-based enum:
class MessageType(str, Enum):
    # ... values ...
2. Add missing values:
    LAYER_RESPONSE = "LAYER_RESPONSE"
    CONNECT = "CONNECT"
    DISCONNECT = "DISCONNECT"
    ACK = "ACK"
    LAYER1_QUERY = "LAYER1_QUERY"
    LAYER1_RESPONSE = "LAYER1_RESPONSE"
3. Ensure BaseMessage matches shared version structure.
Alternatively: Make laptop/protocol.py import from shared:
"""
Protocol definitions for laptop-RPi5 communication.
Re-exports from shared.api.protocol for compatibility.
"""
from shared.api.protocol import (
    MessageType,
    BaseMessage,
    BoundingBox,
    Detection,
    SystemMetrics,
    GPSData,
    IMUData,
    Command,
    create_ping,
    create_pong,
    create_error,
    parse_message,
)
# Add any laptop-specific additions here
Files to Modify:
- laptop/protocol.py (synchronize with shared)
- shared/api/protocol.py (add LAYER1_QUERY, LAYER1_RESPONSE)
---
9. Implementation Order
Phase 1: Critical Fixes (Do First)
1. Fix button commands not reaching RPi5 (laptop/cli/start_dashboard.py)
2. Add missing load_config import (rpi5/main.py)
3. Fix async method without await (shared/api/base_client.py)
4. Fix infinite loop condition (shared/api/base_client.py)
5. Fix TimeoutError shadow (shared/api/exceptions.py)
Phase 2: High Priority
6. Add Bluetooth config and auto-connect (rpi5/config/config.yaml, rpi5/main.py)
7. Centralize IP configuration (all client files)
8. Fix VoiceCoordinator not started (rpi5/main.py)
9. Fix video streaming flag (rpi5/main.py)
10. Fix asyncio.run() in running loop (3 files)
11. Synchronize protocols (laptop/protocol.py, shared/api/protocol.py)
Phase 3: Medium Priority
12. Add missing server handlers (laptop/server/fastapi_server.py)
13. Add missing client handlers (rpi5/fastapi_client.py)
14. Add LAYER1 message types to protocol
15. Fix race condition in connection manager
16. Fix MessageType comparison inconsistency
Phase 4: Low Priority & Polish
17. Replace bare except clauses (18+ locations)
18. Fix StatusDisplay thread safety
19. Add Bluetooth pairing support (rpi5/bluetooth_handler.py)
20. Update sync tools to read from config
---
10. Testing Strategy
Unit Tests
# Test config loading
pytest tests/test_config.py -v
# Test protocol parsing
pytest tests/test_protocol.py -v
# Test Bluetooth handler (mock)
pytest tests/test_bluetooth.py -v
Integration Tests
# Test WebSocket communication
pytest tests/test_websocket.py -v
# Test command flow
pytest tests/test_commands.py -v
Manual Testing Checklist
- [ ] Start laptop dashboard: python -m laptop all --fastapi
- [ ] Start RPi5: python -m rpi5 all
- [ ] Verify WebSocket connection in logs
- [ ] Click "Production Mode" button
- [ ] Verify RPi5 receives SET_MODE command
- [ ] Verify Bluetooth connects (if configured)
- [ ] Verify status display updates for both layers
- [ ] Test voice command (say "what do you see")
- [ ] Verify no hardcoded IPs in logs
---
Summary
This implementation plan covers:
- 5 critical bugs that must be fixed for basic functionality
- 6 high priority bugs affecting major features
- 8 medium priority bugs for robustness
- 4 low priority bugs for code quality
- 4 feature implementations for complete functionality
Total estimated changes across 25+ files.
---
End of Implementation Plan
---
## Questions Before Implementation
1. **For Bluetooth pairing:** The current implementation requires devices to be pre-paired via `bluetoothctl`. The plan adds `scan_devices()`, `pair_device()`, and `auto_connect_or_pair()` methods. Should I also add a GUI button on the laptop dashboard to trigger Bluetooth pairing?
2. **For Protocol sync:** Should I make `laptop/protocol.py` a thin wrapper that imports from `shared/api/protocol.py` (cleaner, single source of truth), or keep them as separate identical files (more redundancy but potentially easier for team members)?
3. **Testing:** Do you have existing tests in `tests/` that I should ensure pass after changes, or should I also create new test files for the bug fixes?
4. **Batch file updates:** The Windows batch files (`sync.bat`, `sync_sc.bat`, `sync_fullpath.bat`) have hardcoded IPs. Should I update them to use the Python config helper, or leave them as-is since `sync_rpi5.py` is the primary sync tool?