#!/usr/bin/env python3
"""Simple script to check what IP address is being used"""

# Direct check of the variables in the main file
with open('Maincode_optimized.py', 'r') as f:
    content = f.read()
    
print("=== IP Address Check ===")
print("Searching for IP addresses in Maincode_optimized.py:")

import re
ip_pattern = r'192\.168\.99\.\d+'
matches = re.findall(ip_pattern, content)

for match in matches:
    print(f"Found IP: {match}")

# Also check by importing
print("\n=== Import Check ===")
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("maincode", "Maincode_optimized.py") 
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    print(f"ESP32_CAM_IP: {module.ESP32_CAM_IP}")
    print(f"ESP32_CAM_STREAM_URL: {module.ESP32_CAM_STREAM_URL}")
    print(f"ESP32_CAM_TEST_URL: {module.ESP32_CAM_TEST_URL}")
    print(f"ESP32_CAM_ROOT_URL: {module.ESP32_CAM_ROOT_URL}")
    
except Exception as e:
    print(f"Import error: {e}")
