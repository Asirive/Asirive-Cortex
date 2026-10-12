#!/usr/bin/env bash
#
# fix_rpi5_5ghz.sh — Unblock 5GHz on RPi5 by setting the regulatory domain.
#
# Why this is needed
# ------------------
# The RPi5's Wi-Fi chip (Infineon CYW43455) is 5GHz-capable, but if the
# regulatory domain is unset (country code "00" = world), the kernel
# disables most 5GHz channels for legal reasons. Phones broadcasting 5GHz
# hotspots use UNII-1 (ch 36-48) or UNII-3 (ch 149-165), all legal in SG,
# but RPi5 won't try them until told where it is.
#
# Symptoms
# --------
# - `iw reg get` reports "country 00"
# - `iw list` shows 5GHz band but only DFS channels (52-144)
# - Phone's 5GHz personal hotspot is invisible to RPi5
# - Home Wi-Fi 5GHz is also flaky
#
# Usage
# -----
#   ssh cortex@<rpi5-ip>
#   chmod +x fix_rpi5_5ghz.sh
#   sudo ./fix_rpi5_5ghz.sh
#
# After running, restart the phone's 5GHz hotspot — RPi5 should connect
# immediately (verify with `iw dev wlan0 link`).

set -euo pipefail

COUNTRY="${1:-SG}"

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
cyan()   { printf '\033[36m%s\033[0m\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    red "This script needs sudo. Re-run: sudo $0"
    exit 1
fi

cyan ""
cyan "=== RPi5 5GHz fix ==="
cyan "Setting regulatory domain to: ${COUNTRY}"
cyan ""

# ── 1. Current state ─────────────────────────────────────────────
echo "[1/5] Current state:"
if command -v iw >/dev/null 2>&1; then
    iw reg get | head -5
else
    yellow "  (iw not found — installing wireless-tools)"
    apt-get install -y wireless-tools
fi

# ── 2. Apply country code (volatile) ─────────────────────────────
echo ""
echo "[2/5] Applying country=${COUNTRY} (runtime)..."
iw reg set "${COUNTRY}"
sleep 1
echo "After:"
iw reg get | head -5

# ── 3. Make persistent in wpa_supplicant.conf ────────────────────
echo ""
echo "[3/5] Making persistent..."
WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
if [[ -f "${WPA_CONF}" ]]; then
    if grep -qE '^country=' "${WPA_CONF}"; then
        sed -i "s/^country=.*/country=${COUNTRY}/" "${WPA_CONF}"
        green "  Updated existing country= line in ${WPA_CONF}"
    else
        # Insert country= as the first non-comment line
        sed -i "1i country=${COUNTRY}" "${WPA_CONF}"
        green "  Added country=${COUNTRY} to ${WPA_CONF}"
    fi
else
    yellow "  ${WPA_CONF} not found — skipping persistence"
    yellow "  (NetworkManager usually manages this; check with: nmcli con show)"
fi

# ── 4. NetworkManager path (Bookworm default) ────────────────────
echo ""
echo "[4/5] NetworkManager country code (if applicable)..."
if systemctl is-active --quiet NetworkManager; then
    # Set the Wi-Fi country. Persists across reboots.
    if nmcli -t -f WIFI country >/dev/null 2>&1; then
        nmcli radio wifi off
        sleep 1
        nmcli radio wifi on
        green "  Wi-Fi radio bounced — reconnecting with ${COUNTRY}"
    fi
else
    echo "  NetworkManager not active — using wpa_supplicant"
fi

# ── 5. Reload wpa_supplicant if present ───────────────────────────
if systemctl is-active --quiet wpa_supplicant; then
    echo "  Reloading wpa_supplicant..."
    wpa_cli -i wlan0 reconfigure 2>/dev/null || true
fi

# ── Verify ────────────────────────────────────────────────────────
echo ""
echo "[5/5] Verifying 5GHz channels now visible:"
if iw list 2>/dev/null | grep -A 100 "Band 2" | grep -m 10 "MHz" | head -10; then
    green ""
    green "✅ Fix applied. Try connecting to a 5GHz network now."
    green "   (e.g. restart your phone's 5GHz personal hotspot)"
else
    red ""
    red "❌ Band 2 (5GHz) still not visible. Check:"
    red "   - antenna is connected (on RPi5 the antenna is internal)"
    red "   - 'iw list' shows 'Band 2' at all"
    red "   - regulatory domain is actually supported by your kernel"
fi
echo ""
echo "Quick checks:"
echo "  iw dev wlan0 link           # current connection"
echo "  iw dev wlan0 scan | grep SSID | grep -i 'your-hotspot'"
echo "  sudo iw reg get             # confirm country"