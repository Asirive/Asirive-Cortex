"""
Project-Cortex v2.0 - Launcher Script
Ensures proper UTF-8 encoding before starting the GUI.

Author: Haziq (@IRSPlays)
Date: November 17, 2025
"""

import sys
import os

# Force UTF-8 encoding for Windows
if sys.platform == 'win32':
    # Set console code page to UTF-8
    os.system('chcp 65001 > nul')
    
    # Reconfigure standard streams
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

# Set environment variable for consistent encoding
os.environ['PYTHONIOENCODING'] = 'utf-8'

print("=" * 60)
print("🚀 Project-Cortex v2.0 - Starting...")
print("=" * 60)
print()

# Import and run main application
try:
    from src.cortex_gui import main
    main()
except ImportError:
    # Fallback if running from different directory
    import subprocess
    subprocess.run([sys.executable, 'src/cortex_gui.py'], check=True)
