#!/bin/bash
################################################################################
# Project Cortex v2.0 - Hardware Validation Script
# 
# This script validates all hardware components before running Project Cortex:
#   - Raspberry Pi 5 detection
#   - Camera Module 3 connectivity
#   - Active cooler / temperature monitoring
#   - GPIO access
#   - Audio output (Bluetooth headphones)
#   - Available RAM and disk space
#
# Usage:
#   chmod +x validate_hardware.sh
#   ./validate_hardware.sh
#
# Author: GitHub Copilot (CTO)
# Date: December 31, 2025
################################################################################

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Test counters
PASSED=0
FAILED=0
WARNINGS=0

log_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((FAILED++))
}

log_warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
    ((WARNINGS++))
}

log_info() {
    echo -e "${BLUE}ℹ️  INFO${NC}: $1"
}

section() {
    echo ""
    echo "========================================"
    echo "$1"
    echo "========================================"
}

# Test 1: Raspberry Pi 5 Detection
test_rpi5() {
    section "TEST 1: Raspberry Pi 5 Detection"
    
    if grep -q "Raspberry Pi 5" /proc/cpuinfo; then
        model=$(grep "Model" /proc/cpuinfo | cut -d: -f2 | xargs)
        log_pass "Detected: $model"
        
        # Check CPU cores
        cores=$(nproc)
        if [ "$cores" -eq 4 ]; then
            log_pass "CPU cores: $cores (4 cores detected)"
        else
            log_warn "CPU cores: $cores (expected 4)"
        fi
        
        # Check CPU frequency
        cpu_freq=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)
        cpu_freq_mhz=$((cpu_freq / 1000))
        log_info "Current CPU frequency: ${cpu_freq_mhz}MHz"
        
    else
        log_fail "Not running on Raspberry Pi 5"
        log_info "Detected: $(grep "Model" /proc/cpuinfo | cut -d: -f2 | xargs)"
    fi
}

# Test 2: Memory Check
test_memory() {
    section "TEST 2: Memory (RAM) Check"
    
    # Get total RAM in MB
    total_ram_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    total_ram_mb=$((total_ram_kb / 1024))
    total_ram_gb=$(echo "scale=1; $total_ram_mb / 1024" | bc)
    
    log_info "Total RAM: ${total_ram_gb}GB (${total_ram_mb}MB)"
    
    if [ "$total_ram_mb" -gt 3500 ]; then
        log_pass "RAM capacity sufficient for Project Cortex (need ~3.8GB)"
    elif [ "$total_ram_mb" -gt 3000 ]; then
        log_warn "RAM is at minimum threshold (${total_ram_gb}GB)"
    else
        log_fail "Insufficient RAM (need 4GB, have ${total_ram_gb}GB)"
    fi
    
    # Check available RAM
    available_ram_kb=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
    available_ram_mb=$((available_ram_kb / 1024))
    log_info "Available RAM: ${available_ram_mb}MB"
    
    if [ "$available_ram_mb" -lt 1000 ]; then
        log_warn "Low available RAM (${available_ram_mb}MB) - close other applications"
    fi
}

# Test 3: Disk Space Check
test_disk_space() {
    section "TEST 3: Disk Space Check"
    
    # Get available space on root partition
    available_gb=$(df -BG / | tail -1 | awk '{print $4}' | sed 's/G//')
    used_percent=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
    
    log_info "Disk space available: ${available_gb}GB"
    log_info "Disk usage: ${used_percent}%"
    
    if [ "$available_gb" -gt 15 ]; then
        log_pass "Sufficient disk space (need ~10GB for models)"
    elif [ "$available_gb" -gt 10 ]; then
        log_warn "Low disk space (${available_gb}GB available)"
    else
        log_fail "Insufficient disk space (need 10GB+, have ${available_gb}GB)"
    fi
}

# Test 4: Temperature Check
test_temperature() {
    section "TEST 4: Temperature & Cooling"
    
    if command -v vcgencmd &> /dev/null; then
        temp=$(vcgencmd measure_temp | cut -d= -f2)
        temp_num=$(echo $temp | cut -d. -f1 | sed 's/°C//')
        
        log_info "Current temperature: $temp"
        
        if [ "$temp_num" -lt 60 ]; then
            log_pass "Temperature normal ($temp)"
        elif [ "$temp_num" -lt 70 ]; then
            log_warn "Temperature elevated ($temp) - ensure active cooler is working"
        else
            log_fail "Temperature too high ($temp) - CRITICAL: Install active cooler!"
        fi
        
        # Check throttling
        throttled=$(vcgencmd get_throttled | cut -d= -f2)
        if [ "$throttled" = "0x0" ]; then
            log_pass "No throttling detected"
        else
            log_warn "Throttling detected (code: $throttled) - check cooling and power"
        fi
    else
        log_warn "vcgencmd not available - cannot check temperature"
    fi
}

# Test 5: Camera Detection
test_camera() {
    section "TEST 5: Camera Module Detection"
    
    if command -v libcamera-hello &> /dev/null; then
        # List cameras
        camera_output=$(libcamera-hello --list-cameras 2>&1)
        
        if echo "$camera_output" | grep -q "Available cameras"; then
            log_pass "Camera system operational"
            
            # Check for IMX708 (Camera Module 3)
            if echo "$camera_output" | grep -q "imx708"; then
                log_pass "Detected: Raspberry Pi Camera Module 3 (IMX708)"
                
                # Extract resolution
                if echo "$camera_output" | grep -q "4608x2592"; then
                    log_info "Maximum resolution: 4608x2592 (12MP)"
                fi
            else
                log_warn "Camera detected but not IMX708 - may not be Camera Module 3"
                log_info "Detected camera: $(echo "$camera_output" | grep -o 'imx[0-9]*')"
            fi
        else
            log_fail "No cameras detected"
            log_info "Check camera cable connection (blue side faces USB ports)"
        fi
    else
        log_fail "libcamera-hello not found - install with: sudo apt install libcamera-apps"
    fi
    
    # Check camera interface enabled
    if grep -q "start_x=1" /boot/config.txt 2>/dev/null || \
       grep -q "camera_auto_detect=1" /boot/firmware/config.txt 2>/dev/null; then
        log_pass "Camera interface enabled in config"
    else
        log_warn "Camera interface may not be enabled - run: sudo raspi-config"
    fi
}

# Test 6: GPIO Access
test_gpio() {
    section "TEST 6: GPIO Access"
    
    # Check if gpiochip exists
    if [ -c /dev/gpiochip0 ]; then
        log_pass "GPIO device found (/dev/gpiochip0)"
    else
        log_fail "GPIO device not found"
    fi
    
    # Check GPIO group membership
    if groups | grep -q "gpio"; then
        log_pass "User in 'gpio' group"
    else
        log_warn "User not in 'gpio' group - some operations may require sudo"
        log_info "Add to group with: sudo usermod -aG gpio $USER"
    fi
    
    # Test GPIO sysfs (legacy)
    if [ -d /sys/class/gpio ]; then
        log_info "Legacy GPIO sysfs available"
    fi
}

# Test 7: Audio System
test_audio() {
    section "TEST 7: Audio Output"
    
    # Check ALSA
    if command -v aplay &> /dev/null; then
        log_pass "ALSA audio system available"
        
        # List audio devices
        devices=$(aplay -l 2>/dev/null | grep "card")
        if [ -n "$devices" ]; then
            log_info "Audio devices found:"
            echo "$devices" | while read line; do
                log_info "  - $line"
            done
        fi
    else
        log_warn "ALSA (aplay) not found"
    fi
    
    # Check PulseAudio
    if command -v pactl &> /dev/null; then
        log_pass "PulseAudio available"
        
        # Check if PulseAudio server is running
        if pactl info &>/dev/null; then
            log_info "PulseAudio server running"
            
            # List sinks (output devices)
            default_sink=$(pactl get-default-sink 2>/dev/null)
            if [ -n "$default_sink" ]; then
                log_info "Default audio output: $default_sink"
            fi
        else
            log_warn "PulseAudio server not running"
        fi
    else
        log_warn "PulseAudio (pactl) not found"
    fi
    
    # Check OpenAL
    if [ -f /usr/lib/aarch64-linux-gnu/libopenal.so.1 ] || \
       [ -f /usr/lib/arm-linux-gnueabihf/libopenal.so.1 ]; then
        log_pass "OpenAL library installed (required for 3D audio)"
    else
        log_fail "OpenAL library not found"
        log_info "Install with: sudo apt install libopenal1"
    fi
}

# Test 8: Bluetooth
test_bluetooth() {
    section "TEST 8: Bluetooth (for headphones)"
    
    if command -v bluetoothctl &> /dev/null; then
        log_pass "Bluetooth tools available"
        
        # Check if Bluetooth is powered on
        if bluetoothctl show 2>/dev/null | grep -q "Powered: yes"; then
            log_pass "Bluetooth powered on"
            
            # Check paired devices
            paired_count=$(bluetoothctl paired-devices 2>/dev/null | wc -l)
            if [ "$paired_count" -gt 0 ]; then
                log_info "Paired devices: $paired_count"
            else
                log_info "No paired devices - pair Bluetooth headphones with: bluetoothctl"
            fi
        else
            log_warn "Bluetooth powered off"
            log_info "Enable with: bluetoothctl power on"
        fi
    else
        log_warn "Bluetooth tools not available"
        log_info "Install with: sudo apt install bluez bluez-tools"
    fi
}

# Test 9: USB Power
test_usb_power() {
    section "TEST 9: USB Power Configuration"
    
    # Check USB power boost setting
    if grep -q "usb_max_current_enable=1" /boot/firmware/config.txt 2>/dev/null; then
        log_pass "USB power boost enabled (recommended for camera)"
    else
        log_warn "USB power boost not enabled"
        log_info "Enable with: echo 'usb_max_current_enable=1' | sudo tee -a /boot/firmware/config.txt"
    fi
}

# Test 10: Python Environment
test_python() {
    section "TEST 10: Python Environment"
    
    # Check Python version
    if command -v python3 &> /dev/null; then
        python_version=$(python3 --version | cut -d' ' -f2)
        python_major=$(echo $python_version | cut -d. -f1)
        python_minor=$(echo $python_version | cut -d. -f2)
        
        log_info "Python version: $python_version"
        
        if [ "$python_major" -eq 3 ] && [ "$python_minor" -ge 11 ]; then
            log_pass "Python 3.11+ detected"
        else
            log_warn "Python version is older than 3.11"
        fi
    else
        log_fail "Python 3 not found"
    fi
    
    # Check pip
    if command -v pip3 &> /dev/null; then
        log_pass "pip3 available"
    else
        log_warn "pip3 not found"
    fi
    
    # Check venv module
    if python3 -m venv --help &>/dev/null; then
        log_pass "venv module available"
    else
        log_fail "venv module not found"
        log_info "Install with: sudo apt install python3-venv"
    fi
}

# Generate report
generate_report() {
    section "VALIDATION SUMMARY"
    
    total_tests=$((PASSED + FAILED + WARNINGS))
    
    echo ""
    echo -e "${GREEN}Passed:${NC}   $PASSED"
    echo -e "${YELLOW}Warnings:${NC} $WARNINGS"
    echo -e "${RED}Failed:${NC}   $FAILED"
    echo "Total:    $total_tests"
    echo ""
    
    if [ "$FAILED" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}✅ ALL TESTS PASSED - HARDWARE READY!${NC}"
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        echo "Your Raspberry Pi 5 is ready for Project Cortex v2.0!"
        echo "Next step: Run setup script (./setup_rpi5.sh)"
        return 0
    elif [ "$FAILED" -eq 0 ]; then
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${YELLOW}⚠️  TESTS PASSED WITH WARNINGS${NC}"
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        echo "Hardware is functional but has some warnings."
        echo "Review warnings above before proceeding."
        return 0
    else
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${RED}❌ TESTS FAILED - HARDWARE ISSUES DETECTED${NC}"
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        echo "CRITICAL: Fix failed tests before running Project Cortex."
        echo "Refer to docs/implementation/RPI5-COMPLETE-SETUP-GUIDE.md"
        return 1
    fi
}

# Main
main() {
    echo ""
    echo "================================================"
    echo "  PROJECT CORTEX V2.0 - HARDWARE VALIDATION"
    echo "================================================"
    echo ""
    echo "This script will validate your Raspberry Pi 5"
    echo "hardware configuration for Project Cortex."
    echo ""
    
    # Run all tests
    test_rpi5
    test_memory
    test_disk_space
    test_temperature
    test_camera
    test_gpio
    test_audio
    test_bluetooth
    test_usb_power
    test_python
    
    # Generate report
    generate_report
}

# Run
main
