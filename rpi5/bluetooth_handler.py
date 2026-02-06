"""
Bluetooth Audio Handler for Raspberry Pi 5
==========================================

Auto-connects to Bluetooth headphones (CMF Buds 2 Plus) and sets them
as the default audio input/output device.

Uses subprocess + bluetoothctl + wpctl (PipeWire) for maximum compatibility
with Raspberry Pi OS Bookworm.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
Date: January 27, 2026
"""

import subprocess
import re
import time
import logging
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)


class BluetoothAudioManager:
    """
    Manage Bluetooth audio devices on Raspberry Pi 5.
    
    Features:
    - Auto-detect paired devices by name
    - Connect with retry logic
    - Set as default PipeWire sink/source
    - Monitor connection status
    """
    
    _instance = None  # Singleton
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern - only one Bluetooth manager."""
        if cls._instance is None:
            cls._instance = super(BluetoothAudioManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        device_name: str = "CMF Buds",
        retry_delay: float = 2.0,
        max_retries: int = 3
    ):
        """
        Initialize Bluetooth Audio Manager.
        
        Args:
            device_name: Partial name to match (e.g., "CMF Buds" matches "CMF Buds 2 Plus")
            retry_delay: Seconds between retry attempts
            max_retries: Maximum connection attempts
        """
        if self._initialized:
            # Allow updating device_name if a different one is passed
            if device_name != self.device_name:
                logger.info(f"BluetoothAudioManager: updating device_name from '{self.device_name}' to '{device_name}'")
                self.device_name = device_name
            if max_retries != self.max_retries:
                self.max_retries = max_retries
            return
            
        self.device_name = device_name
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.connected_mac: Optional[str] = None
        self._initialized = True
        
        logger.info(f"BluetoothAudioManager initialized (looking for '{device_name}')")
    
    # =========================================================================
    # Device Discovery
    # =========================================================================
    
    def get_paired_devices(self) -> List[Dict[str, str]]:
        """
        Get list of paired Bluetooth devices.
        
        Returns:
            List of dicts with 'mac' and 'name' keys
        """
        try:
            result = subprocess.run(
                ["bluetoothctl", "devices", "Paired"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            devices = []
            # Output format: "Device XX:XX:XX:XX:XX:XX Device Name"
            pattern = r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)"
            
            for line in result.stdout.strip().split('\n'):
                match = re.match(pattern, line)
                if match:
                    devices.append({
                        "mac": match.group(1),
                        "name": match.group(2).strip()
                    })
            
            logger.debug(f"Found {len(devices)} paired devices")
            return devices
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout getting paired devices")
            return []
        except Exception as e:
            logger.error(f"Error getting paired devices: {e}")
            return []
    
    def find_device_by_name(self, name: Optional[str] = None) -> Optional[str]:
        """
        Find a paired device by partial name match.
        
        Args:
            name: Partial name to match (uses self.device_name if None)
            
        Returns:
            MAC address if found, None otherwise
        """
        search_name = name or self.device_name
        devices = self.get_paired_devices()
        
        for device in devices:
            if search_name.lower() in device["name"].lower():
                logger.info(f"Found device: {device['name']} ({device['mac']})")
                return device["mac"]
        
        logger.warning(f"Device '{search_name}' not found in paired devices")
        return None
    
    # =========================================================================
    # Connection Management
    # =========================================================================
    
    def is_connected(self, mac_address: Optional[str] = None) -> bool:
        """
        Check if a device is currently connected.
        
        Args:
            mac_address: MAC to check (uses last connected if None)
            
        Returns:
            True if connected
        """
        mac = mac_address or self.connected_mac
        if not mac:
            return False
            
        try:
            result = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True,
                text=True,
                timeout=5
            )
            connected = "Connected: yes" in result.stdout
            return connected
            
        except Exception as e:
            logger.error(f"Error checking connection status: {e}")
            return False
    
    def power_on(self) -> bool:
        """Power on the Bluetooth adapter."""
        try:
            result = subprocess.run(
                ["bluetoothctl", "power", "on"],
                capture_output=True,
                text=True,
                timeout=5
            )
            success = "succeeded" in result.stdout.lower() or "yes" in result.stdout.lower()
            if success:
                logger.debug("Bluetooth adapter powered on")
            return success
        except Exception as e:
            logger.error(f"Error powering on Bluetooth: {e}")
            return False
    
    def trust_device(self, mac_address: str) -> bool:
        """Trust a device for auto-reconnect."""
        try:
            result = subprocess.run(
                ["bluetoothctl", "trust", mac_address],
                capture_output=True,
                text=True,
                timeout=5
            )
            success = "trust succeeded" in result.stdout.lower() or "trusted: yes" in result.stdout.lower()
            if success:
                logger.debug(f"Device {mac_address} trusted")
            return success
        except Exception as e:
            logger.error(f"Error trusting device: {e}")
            return False
    
    def connect(self, mac_address: str, timeout: int = 30) -> bool:
        """
        Connect to a Bluetooth device.
        
        Args:
            mac_address: Device MAC address
            timeout: Connection timeout in seconds
            
        Returns:
            True if connection successful
        """
        logger.info(f"Connecting to {mac_address}...")
        
        try:
            result = subprocess.run(
                ["bluetoothctl", "connect", mac_address],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            success = "connection successful" in result.stdout.lower()
            
            if success:
                self.connected_mac = mac_address
                logger.info(f"Connected to {mac_address}")
            else:
                # Check common errors
                if "not available" in result.stdout.lower():
                    logger.error("Device not available (out of range or powered off)")
                elif "failed" in result.stdout.lower():
                    logger.error(f"Connection failed: {result.stdout.strip()}")
                else:
                    logger.error(f"Connection failed: {result.stdout} {result.stderr}")
            
            return success
            
        except subprocess.TimeoutExpired:
            logger.error(f"Connection timeout after {timeout}s")
            return False
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False
    
    def disconnect(self, mac_address: Optional[str] = None) -> bool:
        """
        Disconnect from a Bluetooth device.
        
        Args:
            mac_address: MAC to disconnect (uses last connected if None)
            
        Returns:
            True if disconnection successful
        """
        mac = mac_address or self.connected_mac
        if not mac:
            logger.warning("No device to disconnect")
            return False
            
        try:
            result = subprocess.run(
                ["bluetoothctl", "disconnect", mac],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            success = "successful" in result.stdout.lower()
            if success:
                self.connected_mac = None
                logger.info(f"Disconnected from {mac}")
            
            return success
            
        except Exception as e:
            logger.error(f"Disconnect error: {e}")
            return False
    
    # =========================================================================
    # Audio Device Management (PipeWire/WirePlumber)
    # =========================================================================
    
    def get_audio_devices(self) -> Tuple[List[Dict], List[Dict]]:
        """
        Get list of audio sinks (output) and sources (input).
        
        Returns:
            Tuple of (sinks, sources) lists
        """
        try:
            result = subprocess.run(
                ["wpctl", "status"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            logger.debug(f"wpctl status output:\n{result.stdout}")
            
            sinks = []
            sources = []
            current_section = None
            in_audio_section = False
            
            for line in result.stdout.split('\n'):
                # Track when we're in the Audio section
                if line.startswith("Audio"):
                    in_audio_section = True
                    continue
                elif line.startswith("Video") or line.startswith("Settings"):
                    in_audio_section = False
                    current_section = None
                    continue
                
                if not in_audio_section:
                    continue
                
                # Detect subsections within Audio
                if "Sinks:" in line:
                    current_section = "sinks"
                    continue
                elif "Sources:" in line:
                    current_section = "sources"
                    continue
                elif "Devices:" in line or "endpoints:" in line or "Streams:" in line:
                    current_section = None
                    continue
                
                # Parse device lines - handle tree characters (├─, │, └─)
                if current_section:
                    # Remove tree characters and clean the line
                    clean_line = re.sub(r'[├│└─]', '', line)
                    
                    # Format: "  * 47. Device Name [vol: 1.00]" or "    47. Device Name"
                    match = re.match(r'\s*(\*?)\s*(\d+)\.\s+(.+?)(?:\s+\[vol:.*\])?$', clean_line)
                    if match:
                        device = {
                            "default": match.group(1) == "*",
                            "id": int(match.group(2)),
                            "name": match.group(3).strip()
                        }
                        if current_section == "sinks":
                            sinks.append(device)
                            logger.debug(f"Found sink: {device}")
                        else:
                            sources.append(device)
                            logger.debug(f"Found source: {device}")
            
            logger.info(f"Audio devices found - Sinks: {len(sinks)}, Sources: {len(sources)}")
            return sinks, sources
            
        except Exception as e:
            logger.error(f"Error getting audio devices: {e}")
            return [], []
    
    def find_bluetooth_audio(self, mac_address: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Find Bluetooth sink and source IDs for a connected device.
        
        Args:
            mac_address: Connected device MAC
            
        Returns:
            Tuple of (sink_id, source_id), either may be None
        """
        mac_formatted = mac_address.replace(":", "_")
        sinks, sources = self.get_audio_devices()
        
        logger.info(f"Looking for Bluetooth audio: MAC={mac_formatted}, device_name='{self.device_name}'")
        logger.info(f"Available sinks ({len(sinks)}): {sinks}")
        logger.info(f"Available sources ({len(sources)}): {sources}")
        
        sink_id = None
        source_id = None
        
        # Find sink (speaker/headphone output)
        # Priority: 1) MAC address match, 2) device name match, 3) "bluez" fallback
        for sink in sinks:
            sink_name_lower = sink["name"].lower()
            logger.debug(f"Checking sink: '{sink['name']}' against '{self.device_name.lower()}'")
            if mac_formatted.lower() in sink_name_lower:
                sink_id = sink["id"]
                logger.info(f"✅ Found Bluetooth sink (MAC match): {sink['name']} (ID: {sink_id})")
                break
            elif self.device_name.lower() in sink_name_lower:
                sink_id = sink["id"]
                logger.info(f"✅ Found Bluetooth sink (name match): {sink['name']} (ID: {sink_id})")
                break
        
        # Fallback: if no MAC or name match, try "bluez" keyword (only one BT device expected)
        if sink_id is None:
            for sink in sinks:
                if "bluez" in sink["name"].lower():
                    sink_id = sink["id"]
                    logger.info(f"✅ Found Bluetooth sink (bluez fallback): {sink['name']} (ID: {sink_id})")
                    break
        
        # Find source (microphone input) - same priority
        for source in sources:
            source_name_lower = source["name"].lower()
            if mac_formatted.lower() in source_name_lower:
                source_id = source["id"]
                logger.info(f"✅ Found Bluetooth source (MAC match): {source['name']} (ID: {source_id})")
                break
            elif self.device_name.lower() in source_name_lower:
                source_id = source["id"]
                logger.info(f"✅ Found Bluetooth source (name match): {source['name']} (ID: {source_id})")
                break
        
        if source_id is None:
            for source in sources:
                if "bluez" in source["name"].lower():
                    source_id = source["id"]
                    logger.info(f"✅ Found Bluetooth source (bluez fallback): {source['name']} (ID: {source_id})")
                    break
        
        return sink_id, source_id
    
    def set_default_sink(self, sink_id: int) -> bool:
        """Set default audio output (speaker/headphone)."""
        try:
            result = subprocess.run(
                ["wpctl", "set-default", str(sink_id)],
                capture_output=True,
                timeout=5
            )
            success = result.returncode == 0
            if success:
                logger.info(f"Set default audio output to ID {sink_id}")
            return success
        except Exception as e:
            logger.error(f"Error setting default sink: {e}")
            return False
    
    def set_default_source(self, source_id: int) -> bool:
        """Set default audio input (microphone)."""
        try:
            result = subprocess.run(
                ["wpctl", "set-default", str(source_id)],
                capture_output=True,
                timeout=5
            )
            success = result.returncode == 0
            if success:
                logger.info(f"Set default audio input to ID {source_id}")
            return success
        except Exception as e:
            logger.error(f"Error setting default source: {e}")
            return False

    def ensure_hfp_profile(self, mac_address: str) -> bool:
        """
        Ensure the device is using HFP/HSP profile to enable the microphone.
        
        Uses pactl (PulseAudio compat layer) with named profiles, which is
        reliable on PipeWire. wpctl set-profile with numeric indices does not
        map correctly to Bluetooth profiles.
        
        Tries mSBC first (better audio quality), then falls back to CVSD.
        
        Args:
            mac_address: Device MAC
            
        Returns:
            True if profile set and source appeared
        """
        # Build the pactl card name from MAC: bluez_card.XX_XX_XX_XX_XX_XX
        card_name = f"bluez_card.{mac_address.replace(':', '_')}"
        
        # Profiles to try, in priority order:
        # - headset-head-unit: mSBC codec (wideband, better quality)
        # - headset-head-unit-cvsd: CVSD codec (narrowband, fallback)
        candidate_profiles = ["headset-head-unit", "headset-head-unit-cvsd"]
        
        logger.info(f"Switching to HFP/HSP profile on card {card_name}")
        
        for profile_name in candidate_profiles:
            try:
                logger.info(f"Trying profile: {profile_name}...")
                result = subprocess.run(
                    ["pactl", "set-card-profile", card_name, profile_name],
                    capture_output=True, text=True, timeout=5
                )
                
                if result.returncode != 0:
                    logger.warning(f"pactl set-card-profile failed: {result.stderr.strip()}")
                    continue
                
                # Wait for PipeWire to reconfigure audio nodes
                time.sleep(2)
                
                # Check if a source (mic) appeared
                _, sources = self.get_audio_devices()
                mac_formatted = mac_address.replace(":", "_").lower()
                for source in sources:
                    source_lower = source["name"].lower()
                    if (mac_formatted in source_lower or 
                        self.device_name.lower() in source_lower or
                        "bluez" in source_lower):
                        logger.info(f"Profile '{profile_name}' enabled mic: {source['name']}")
                        return True
                
                logger.info(f"Profile '{profile_name}' did not produce a mic source")
                
            except FileNotFoundError:
                logger.error("pactl not found. Install pulseaudio-utils: sudo apt install pulseaudio-utils")
                return False
            except Exception as e:
                logger.warning(f"Error trying profile '{profile_name}': {e}")
                continue
        
        logger.warning("No HFP/HSP profile produced a mic source")
        return False
    
    # =========================================================================
    # High-Level API
    # =========================================================================
    
    def connect_and_setup(self, device_name: Optional[str] = None) -> bool:
        """
        Connect to Bluetooth headphones and set as default audio device.
        
        This is the main method to call for Production Mode.
        
        Args:
            device_name: Partial name match (uses self.device_name if None)
            
        Returns:
            True if fully successful (connected + audio configured)
        """
        search_name = device_name or self.device_name
        logger.info(f"Setting up Bluetooth audio for '{search_name}'...")
        
        # Step 1: Power on adapter
        self.power_on()
        
        # Step 2: Find device
        mac = self.find_device_by_name(search_name)
        if not mac:
            logger.error(f"Device '{search_name}' not found. Please pair it first using bluetoothctl.")
            return False
        
        # Step 3: Trust device (for auto-reconnect)
        self.trust_device(mac)
        
        # Step 4: Connect with retries
        connected = False
        was_already_connected = False
        for attempt in range(1, self.max_retries + 1):
            if self.is_connected(mac):
                logger.info("Device already connected")
                connected = True
                was_already_connected = True
                break
            
            logger.info(f"Connection attempt {attempt}/{self.max_retries}...")
            if self.connect(mac):
                connected = True
                break
            
            if attempt < self.max_retries:
                logger.warning(f"Retrying in {self.retry_delay}s...")
                time.sleep(self.retry_delay)
        
        if not connected:
            logger.error("Failed to connect after all retries")
            return False
        
        self.connected_mac = mac
        
        # Step 5: Wait for audio profile to initialize
        if was_already_connected:
            logger.info("Device was already connected, checking audio immediately...")
            time.sleep(1)
        else:
            logger.info("Fresh connection - waiting for audio profile to initialize...")
            time.sleep(5)
        
        # Step 6: Find and set default audio devices
        # First, wait for PipeWire to register the sink (up to 3 attempts)
        sink_id = None
        source_id = None
        
        for attempt in range(1, 4):
            sink_id, source_id = self.find_bluetooth_audio(mac)
            if sink_id is not None:
                break
            logger.warning(f"Bluetooth audio not ready - attempt {attempt}/3, retrying in 3s...")
            time.sleep(3)
        
        # If we have sink but no source, try HFP/HSP profile switch
        # ensure_hfp_profile already iterates through candidate profiles
        # and verifies source appearance, so we only need to call it once
        if sink_id is not None and source_id is None:
            logger.info("Sink found but NO source (mic). Attempting HFP/HSP profile switch...")
            profile_ok = self.ensure_hfp_profile(mac)
            
            if profile_ok:
                # Re-scan to pick up the newly appeared source
                sink_id, source_id = self.find_bluetooth_audio(mac)
            else:
                logger.warning("HFP/HSP profile switch failed - continuing with A2DP (output only)")
        
        success = True
        
        if sink_id:
            if not self.set_default_sink(sink_id):
                logger.error("Failed to set Bluetooth as default output")
                success = False
        else:
            logger.error("Bluetooth audio sink not found")
            success = False
        
        if source_id:
            if not self.set_default_source(source_id):
                logger.error("Failed to set Bluetooth as default input")
                success = False
        else:
            logger.warning("Bluetooth audio source (mic) not found - device may not support mic")
        
        if success:
            logger.info(f"Bluetooth audio setup complete for '{search_name}'")
        
        return success
    
    def get_status(self) -> Dict:
        """
        Get current Bluetooth audio status.
        
        Returns:
            Dict with connection and audio status
        """
        mac = self.connected_mac
        connected = self.is_connected(mac) if mac else False
        
        status = {
            "connected": connected,
            "mac": mac,
            "device_name": self.device_name,
            "sink_id": None,
            "source_id": None
        }
        
        if connected and mac:
            sink_id, source_id = self.find_bluetooth_audio(mac)
            status["sink_id"] = sink_id
            status["source_id"] = source_id
        
        return status
    
    # =========================================================================
    # Auto-Connect and Pairing (NEW METHODS FOR V2.0)
    # =========================================================================
    
    def scan_devices(self, duration: int = 10) -> List[Dict]:
        """
        Scan for nearby Bluetooth devices.
        
        Args:
            duration: Seconds to scan
            
        Returns:
            List of dicts with 'mac' and 'name' keys
        """
        logger.info(f"🔍 Scanning for Bluetooth devices ({duration}s)...")
        
        try:
            # Start scanning
            subprocess.run(
                ["bluetoothctl", "scan", "on"],
                capture_output=True,
                timeout=5
            )
            
            time.sleep(duration)
            
            # Stop scanning
            subprocess.run(
                ["bluetoothctl", "scan", "off"],
                capture_output=True,
                timeout=5
            )
            
            # Get all discovered devices
            result = subprocess.run(
                ["bluetoothctl", "devices"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            devices = []
            pattern = r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)"
            
            for line in result.stdout.strip().split('\n'):
                match = re.match(pattern, line)
                if match:
                    devices.append({
                        'mac': match.group(1),
                        'name': match.group(2).strip()
                    })
            
            logger.info(f"Found {len(devices)} devices")
            for device in devices:
                logger.debug(f"  - {device['name']} ({device['mac']})")
            
            return devices
            
        except Exception as e:
            logger.error(f"Error scanning devices: {e}")
            return []
    
    def pair_device(self, mac_address: str) -> bool:
        """
        Pair with a Bluetooth device.
        
        Args:
            mac_address: Device MAC address
            
        Returns:
            True if pairing successful
        """
        logger.info(f"🔗 Pairing with {mac_address}...")
        
        try:
            result = subprocess.run(
                ["bluetoothctl", "pair", mac_address],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if "Pairing successful" in result.stdout:
                logger.info(f"✅ Paired with {mac_address}")
                return True
            elif "already paired" in result.stdout.lower():
                logger.info(f"✅ Already paired with {mac_address}")
                return True
            else:
                logger.error(f"❌ Pairing failed: {result.stdout} {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Pairing timeout")
            return False
        except Exception as e:
            logger.error(f"Pairing error: {e}")
            return False
    
    def start_auto_reconnect(self, check_interval: float = 10.0):
        """
        Start background thread to monitor and reconnect Bluetooth.
        
        Args:
            check_interval: Seconds between connection checks
        """
        import threading
        
        if hasattr(self, '_reconnect_thread') and self._reconnect_thread.is_alive():
            logger.debug("Auto-reconnect already running")
            return
        
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
        """Stop the auto-reconnect monitoring thread."""
        self._reconnect_running = False
        logger.info("🛑 Bluetooth auto-reconnect stopped")
    
    def _monitor_connection(self, interval: float):
        """
        Background thread to monitor Bluetooth connection.
        
        Args:
            interval: Seconds between checks
        """
        while self._reconnect_running:
            try:
                if self.connected_mac and not self.is_connected(self.connected_mac):
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
        
        Args:
            scan_duration: Seconds to scan for new devices
            
        Returns:
            True if connected successfully
        """
        # Step 1: Try known paired devices
        logger.info(f"Looking for paired device matching '{self.device_name}'...")
        mac = self.find_device_by_name()
        
        if mac:
            logger.info(f"Found paired device: {mac}")
            return self.connect_and_setup()
        
        # Step 2: Scan for new devices
        logger.info(f"Device '{self.device_name}' not paired. Scanning for {scan_duration}s...")
        devices = self.scan_devices(scan_duration)
        
        if not devices:
            logger.error("No Bluetooth devices found during scan")
            return False
        
        # Step 3: Find matching device in scan results
        for device in devices:
            if self.device_name.lower() in device['name'].lower():
                logger.info(f"Found matching device: {device['name']} ({device['mac']})")
                
                # Step 4: Pair with device
                if self.pair_device(device['mac']):
                    # Step 5: Trust and connect
                    self.trust_device(device['mac'])
                    time.sleep(1)  # Brief pause after pairing
                    return self.connect_and_setup()
                else:
                    logger.error(f"Failed to pair with {device['mac']}")
        
        logger.error(f"No device matching '{self.device_name}' found")
        return False


# =============================================================================
# Convenience functions
# =============================================================================

def setup_bluetooth_audio(device_name: str = "CMF Buds") -> bool:
    """
    Quick setup function for Production Mode.
    
    Args:
        device_name: Partial name of Bluetooth device
        
    Returns:
        True if successful
    """
    manager = BluetoothAudioManager(device_name=device_name)
    return manager.connect_and_setup()


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    manager = BluetoothAudioManager(device_name="CMF Buds")
    
    # List paired devices
    print("\n=== Paired Bluetooth Devices ===")
    for device in manager.get_paired_devices():
        print(f"  {device['mac']} - {device['name']}")
    
    # List audio devices
    print("\n=== Audio Devices ===")
    sinks, sources = manager.get_audio_devices()
    print("Sinks (Output):")
    for sink in sinks:
        default = "*" if sink["default"] else " "
        print(f"  {default} [{sink['id']}] {sink['name']}")
    print("Sources (Input):")
    for source in sources:
        default = "*" if source["default"] else " "
        print(f"  {default} [{source['id']}] {source['name']}")
    
    # Connect if requested
    if len(sys.argv) > 1 and sys.argv[1] == "connect":
        print("\n=== Connecting... ===")
        success = manager.connect_and_setup()
        print(f"Result: {'SUCCESS' if success else 'FAILED'}")
        
        print("\n=== Status ===")
        status = manager.get_status()
        for key, value in status.items():
            print(f"  {key}: {value}")
