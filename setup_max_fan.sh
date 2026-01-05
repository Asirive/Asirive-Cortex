#!/bin/bash

# ==================================================================================
# Project Cortex: Raspberry Pi 5 Active Cooler Max Speed Setup
# ==================================================================================
# This script configures the Raspberry Pi 5 Official Active Cooler to run at 
# MAXIMUM speed (100% RPM) at all times by modifying the kernel thermal trip points.
#
# Target Hardware: Raspberry Pi 5 + Official Active Cooler (Fan Header)
# Method: /boot/firmware/config.txt (Persistent)
# ==================================================================================

echo "🌪️  Configuring Raspberry Pi 5 Active Cooler for MAX RPM..."

# 1. Identify config file location (Bookworm uses /boot/firmware/config.txt)
if [ -f "/boot/firmware/config.txt" ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
elif [ -f "/boot/config.txt" ]; then
    CONFIG_FILE="/boot/config.txt"
else
    echo "❌ Error: Could not find config.txt in /boot/ or /boot/firmware/"
    exit 1
fi

echo "📂 Found config file: $CONFIG_FILE"

# 2. Create backup
echo "💾 Creating backup..."
sudo cp "$CONFIG_FILE" "${CONFIG_FILE}.bak_$(date +%Y%m%d_%H%M%S)"

# 3. Append configuration
# We set all temperature trip points to 0°C with max speed (255)
# This forces the kernel to drive the fan at 100% immediately
echo "⚙️  Applying thermal configuration..."

sudo tee -a "$CONFIG_FILE" > /dev/null <<EOT

# --- Project Cortex: Force Max Fan Speed (Active Cooler) ---
# Override thermal trip points to force max speed at all temps
dtparam=fan_temp0=0
dtparam=fan_temp0_speed=255
dtparam=fan_temp1=0
dtparam=fan_temp1_speed=255
dtparam=fan_temp2=0
dtparam=fan_temp2_speed=255
dtparam=fan_temp3=0
dtparam=fan_temp3_speed=255
# ---------------------------------------------------------
EOT

echo "✅ Configuration applied successfully!"
echo ""
echo "⚠️  NOTE: A reboot is required for these changes to take effect."
echo "   To reboot now, run: sudo reboot"
echo ""
echo "💡 To revert changes, restore the backup file created in the same directory."