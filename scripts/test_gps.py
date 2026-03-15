"""
Quick GPS hardware test for NEO-M8U module.

Tests:
1. Serial device exists
2. Can open serial port
3. Reads raw NMEA data
4. Parses fix (lat/lon/satellites)

Usage:
    python scripts/test_gps.py

Author: Haziq (@IRSPlays)
Date: March 2026
"""

import sys
import time
import os

# Try multiple possible serial ports
PORTS = ["/dev/ttyAMA0", "/dev/ttyS0", "/dev/serial0", "/dev/ttyACM0", "/dev/ttyUSB0"]
BAUDRATES = [9600, 38400, 115200]  # NEO-M8U may ship at 9600 or 38400


def find_serial_device():
    """Check which serial devices exist."""
    print("=" * 60)
    print("STEP 1: Checking serial devices")
    print("=" * 60)
    found = []
    for port in PORTS:
        exists = os.path.exists(port)
        status = "✅ EXISTS" if exists else "   not found"
        print(f"  {port:25s} {status}")
        if exists:
            found.append(port)
    if not found:
        print("\n❌ No serial devices found!")
        print("   Did you enable UART?")
        print("   Run: sudo raspi-config → Interface Options → Serial")
        print("   Login shell: No, Hardware port: Yes, then reboot")
    return found


def test_raw_read(port, baudrate, duration=5):
    """Read raw bytes from serial port for a few seconds."""
    import serial

    print(f"\n{'=' * 60}")
    print(f"STEP 2: Raw read from {port} @ {baudrate} baud ({duration}s)")
    print("=" * 60)

    try:
        ser = serial.Serial(port, baudrate=baudrate, timeout=1.0)
    except serial.SerialException as e:
        print(f"  ❌ Could not open {port}: {e}")
        return False, []

    lines = []
    nmea_found = False
    start = time.time()

    while time.time() - start < duration:
        raw = ser.readline()
        if raw:
            try:
                line = raw.decode("ascii", errors="replace").strip()
            except Exception:
                line = repr(raw)

            if line.startswith("$"):
                nmea_found = True
                lines.append(line)
                print(f"  📡 {line}")
            elif line:
                # Could be UBX binary or garbage
                print(f"  ?? {line[:80]}")

    ser.close()

    if not nmea_found:
        print(f"  ⚠️  No NMEA sentences received at {baudrate} baud")
    else:
        print(f"  ✅ Got {len(lines)} NMEA sentences")

    return nmea_found, lines


def parse_nmea_sentences(lines):
    """Parse captured NMEA sentences for GPS info."""
    print(f"\n{'=' * 60}")
    print("STEP 3: Parsing NMEA data")
    print("=" * 60)

    fix_quality = 0
    satellites = 0
    lat = lon = alt = 0.0
    has_rmc = has_gga = False
    sentence_types = set()

    for line in lines:
        parts = line.split(",")
        msg = parts[0].lstrip("$")
        sentence_types.add(msg)

        try:
            if msg in ("GPRMC", "GNRMC"):
                has_rmc = True
                if len(parts) > 6 and parts[2] == "A":
                    lat = nmea_to_decimal(parts[3], parts[4])
                    lon = nmea_to_decimal(parts[5], parts[6])
                    print(f"  RMC: lat={lat:.6f}, lon={lon:.6f}")

            elif msg in ("GPGGA", "GNGGA"):
                has_gga = True
                if len(parts) > 9:
                    fix_quality = int(parts[6]) if parts[6] else 0
                    satellites = int(parts[7]) if parts[7] else 0
                    alt = float(parts[9]) if parts[9] else -1.0
                    print(f"  GGA: fix={fix_quality}, sats={satellites}, alt={alt:.1f}m")

        except (IndexError, ValueError) as e:
            pass

    print(f"\n  Sentence types seen: {', '.join(sorted(sentence_types))}")
    print(f"  Has RMC: {'✅' if has_rmc else '❌'}")
    print(f"  Has GGA: {'✅' if has_gga else '❌'}")
    print(f"  Fix quality: {fix_quality} (0=none, 1=GPS, 2=DGPS, 6=DR)")
    print(f"  Satellites: {satellites}")

    if fix_quality > 0:
        print(f"\n  🎉 GPS FIX ACQUIRED!")
        print(f"     Latitude:   {lat:.6f}")
        print(f"     Longitude:  {lon:.6f}")
        print(f"     Altitude:   {alt:.1f}m")
        print(f"     Satellites: {satellites}")
    else:
        print(f"\n  ⚠️  No GPS fix yet (this is normal indoors)")
        print(f"     The module IS communicating — just needs sky view for a fix.")

    return fix_quality > 0


def test_gps_handler():
    """Test using the project's GPSHandler class."""
    print(f"\n{'=' * 60}")
    print("STEP 4: Testing GPSHandler class (10s)")
    print("=" * 60)

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rpi5"))
    try:
        from hardware.gps_handler import GPSHandler
    except ImportError as e:
        print(f"  ❌ Could not import GPSHandler: {e}")
        return

    gps = GPSHandler(port="/dev/ttyAMA0", baudrate=9600)
    ok = gps.start()
    if not ok:
        print("  ❌ GPSHandler.start() failed")
        return

    print("  Waiting for data...")
    for i in range(10):
        time.sleep(1)
        fix = gps.get_fix()
        if fix:
            print(f"  [{i+1}s] Fix: lat={fix.latitude:.6f}, lon={fix.longitude:.6f}, "
                  f"sats={fix.satellites}, qual={fix.fix_quality}, "
                  f"spd={fix.speed_kmh:.1f}km/h, alt={fix.altitude:.1f}m")
        else:
            print(f"  [{i+1}s] No fix yet...")

    gps.stop()
    final = gps.get_fix()
    if final and final.fix_quality > 0:
        print(f"\n  🎉 GPSHandler is working! Fix: ({final.latitude:.6f}, {final.longitude:.6f})")
    elif gps.is_receiving:
        print(f"\n  ✅ GPSHandler is receiving NMEA data (no satellite fix — normal indoors)")
    elif final:
        print(f"\n  ✅ GPSHandler is receiving data (no satellite fix — normal indoors)")
    else:
        print(f"\n  ⚠️  GPSHandler got no data at all")


def nmea_to_decimal(raw, direction):
    if not raw:
        return 0.0
    dot = raw.index(".")
    degrees = float(raw[:dot - 2])
    minutes = float(raw[dot - 2:])
    decimal = degrees + minutes / 60.0
    if direction in ("S", "W"):
        decimal = -decimal
    return decimal


def main():
    print("🛰️  ProjectCortex GPS Hardware Test")
    print("    Module: NEO-M8U (Untethered Dead Reckoning)")
    print()

    # Step 1: Find devices
    devices = find_serial_device()
    if not devices:
        sys.exit(1)

    # Step 2: Try raw read at different baud rates
    import serial  # Will fail if pyserial not installed

    working_port = None
    working_baud = None

    for port in devices:
        for baud in BAUDRATES:
            found, lines = test_raw_read(port, baud, duration=4)
            if found:
                working_port = port
                working_baud = baud
                # Step 3: Parse what we got
                parse_nmea_sentences(lines)
                break
        if working_port:
            break

    if not working_port:
        print(f"\n❌ No NMEA data received on any port/baudrate combination")
        print("   Check wiring: GPS TX → RPi5 Pin 10 (GPIO15)")
        print("   Check power:  GPS VCC → 3.3V (Pin 1)")
        sys.exit(1)

    # Report working config
    print(f"\n{'=' * 60}")
    print(f"WORKING CONFIG: {working_port} @ {working_baud} baud")
    print("=" * 60)

    # Step 4: Test GPSHandler class
    test_gps_handler()

    print(f"\n{'=' * 60}")
    print("GPS TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
