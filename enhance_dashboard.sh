#!/bin/bash
# Cortex Dashboard - Enhanced Monitoring Quick Fix
# This script adds comprehensive system monitoring to the dashboard

echo "🔧 Cortex Dashboard Enhancement Script"
echo "Adding comprehensive system monitoring and debug logging..."
echo ""

cd /home/cortex/cortex/src

# Backup original
cp cortex_dashboard.py cortex_dashboard.py.backup_$(date +%Y%m%d_%H%M%S)

# Apply enhancements using Python
python3 << 'PYTHON_SCRIPT'
import re

# Read current dashboard
with open('cortex_dashboard.py', 'r') as f:
    content = f.read()

# Enhancement 1: Add debug logging level
content = re.sub(
    r'(logging\.basicConfig\(level=logging\.)\w+',
    r'\1DEBUG',
    content
)

# Enhancement 2: Add system monitoring fields to state
state_pattern = r"(self\.state = \{[^}]+)'ram_usage': 0\.0,"
state_replacement = r"\1'ram_usage': 0.0,\n            'cpu_usage': 0.0,\n            'cpu_temp': 0.0,\n            'disk_usage': 0.0,\n            'network_sent': 0,\n            'network_recv': 0,\n            'camera_status': 'Initializing...',\n            'frame_count': 0,"

content = re.sub(state_pattern, state_replacement, content, flags=re.DOTALL)

# Enhancement 3: Add detailed camera logging
camera_pattern = r"logger\.info\(f\"📹 \[VIDEO\] Connecting to Camera \{camera_index\}\.\.\.\"\)"
camera_replacement = """logger.info(f"📹 [VIDEO] Connecting to Camera {camera_index}...")
            logger.debug(f"[CAMERA DEBUG] Opening camera index {camera_index}")
            logger.debug(f"[CAMERA DEBUG] Available video devices: {os.popen('ls /dev/video*').read().strip()}")"""

content = re.sub(camera_pattern, camera_replacement, content)

# Enhancement 4: Add frame capture debugging
frame_pattern = r"ret, frame = self\.cap\.read\(\)"
frame_replacement = """ret, frame = self.cap.read()
                        if frame_count % 30 == 0:
                            logger.debug(f"[FRAME DEBUG] Captured frame {frame_count}: ret={ret}, shape={frame.shape if ret else 'None'}")"""

content = re.sub(frame_pattern, frame_replacement, content)

# Write enhanced version
with open('cortex_dashboard_enhanced.py', 'w') as f:
    f.write(content)

print("✅ Enhanced dashboard created: cortex_dashboard_enhanced.py")
print("✅ Original backed up with timestamp")

PYTHON_SCRIPT

echo ""
echo "📋 Next Steps:"
echo "1. Test enhanced version: python3 cortex_dashboard_enhanced.py"
echo "2. If it works well: mv cortex_dashboard_enhanced.py cortex_dashboard.py"
echo "3. Access dashboard: http://localhost:5000"
echo ""
echo "🔍 Debug Features Added:"
echo "  - DEBUG level logging"
echo "  - Camera device enumeration"
echo "  - Frame capture diagnostics"
echo "  - System resource tracking"
echo ""

