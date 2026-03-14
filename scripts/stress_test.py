"""
Stress Test — 5-minute system resource monitor

Runs for 5 minutes, sampling CPU, RAM, and temperature every second.
Reports pass/fail against thresholds: CPU <80%, RAM <3GB, temp <75°C.

Usage:
    python scripts/stress_test.py              # Run during full pipeline
    python scripts/stress_test.py --duration 120  # Custom duration (seconds)

Author: Haziq (@IRSPlays)
Date: June 2025
"""

import argparse
import sys
import time

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run: pip install psutil")
    sys.exit(1)


# Thresholds
CPU_MAX = 80.0       # percent
RAM_MAX_MB = 3072    # 3 GB
TEMP_MAX = 75.0      # Celsius


def get_cpu_temp() -> float:
    """Read CPU temperature (RPi5 specific)."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read().strip()) / 1000.0
    except Exception:
        # Try psutil fallback
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for entries in temps.values():
                    for entry in entries:
                        if entry.current > 0:
                            return entry.current
        except Exception:
            pass
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="5-minute stress test monitor")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds (default: 300)")
    args = parser.parse_args()

    duration = args.duration
    print(f"Starting {duration}s stress test...")
    print(f"Thresholds: CPU <{CPU_MAX}%, RAM <{RAM_MAX_MB}MB, Temp <{TEMP_MAX}°C")
    print("-" * 60)

    samples = []
    peaks = {"cpu": 0.0, "ram_mb": 0.0, "temp": 0.0}
    violations = {"cpu": 0, "ram": 0, "temp": 0}

    start = time.time()
    try:
        while time.time() - start < duration:
            cpu = psutil.cpu_percent(interval=1)
            ram_mb = psutil.virtual_memory().used / (1024 * 1024)
            temp = get_cpu_temp()

            # Track peaks
            if cpu > peaks["cpu"]:
                peaks["cpu"] = cpu
            if ram_mb > peaks["ram_mb"]:
                peaks["ram_mb"] = ram_mb
            if temp > peaks["temp"]:
                peaks["temp"] = temp

            # Track violations
            if cpu > CPU_MAX:
                violations["cpu"] += 1
            if ram_mb > RAM_MAX_MB:
                violations["ram"] += 1
            if temp > TEMP_MAX:
                violations["temp"] += 1

            samples.append({"cpu": cpu, "ram_mb": ram_mb, "temp": temp})

            elapsed = int(time.time() - start)
            status = "OK" if (cpu <= CPU_MAX and ram_mb <= RAM_MAX_MB and temp <= TEMP_MAX) else "⚠️"
            print(
                f"[{elapsed:3d}s] CPU: {cpu:5.1f}% | RAM: {ram_mb:7.1f}MB | "
                f"Temp: {temp:5.1f}°C | {status}"
            )
    except KeyboardInterrupt:
        print("\nInterrupted.")

    total = len(samples)
    if total == 0:
        print("No samples collected.")
        return

    # Summary
    avg_cpu = sum(s["cpu"] for s in samples) / total
    avg_ram = sum(s["ram_mb"] for s in samples) / total
    avg_temp = sum(s["temp"] for s in samples) / total

    print("\n" + "=" * 60)
    print("STRESS TEST RESULTS")
    print("=" * 60)
    print(f"Duration:   {total} seconds")
    print(f"")
    print(f"{'Metric':<12} {'Average':>10} {'Peak':>10} {'Threshold':>10} {'Violations':>12} {'Result':>8}")
    print("-" * 64)

    cpu_pass = violations["cpu"] == 0
    ram_pass = violations["ram"] == 0
    temp_pass = violations["temp"] == 0

    print(f"{'CPU %':<12} {avg_cpu:>9.1f}% {peaks['cpu']:>9.1f}% {CPU_MAX:>9.1f}% {violations['cpu']:>10}s {'PASS' if cpu_pass else 'FAIL':>8}")
    print(f"{'RAM MB':<12} {avg_ram:>9.0f}  {peaks['ram_mb']:>9.0f}  {RAM_MAX_MB:>9}  {violations['ram']:>10}s {'PASS' if ram_pass else 'FAIL':>8}")
    print(f"{'Temp °C':<12} {avg_temp:>9.1f}  {peaks['temp']:>9.1f}  {TEMP_MAX:>9.1f}  {violations['temp']:>10}s {'PASS' if temp_pass else 'FAIL':>8}")

    print("\n" + "=" * 60)
    overall = cpu_pass and ram_pass and temp_pass
    print(f"OVERALL: {'✅ PASS' if overall else '❌ FAIL'}")
    print("=" * 60)

    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
