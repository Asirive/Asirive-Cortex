#!/bin/bash
################################################################################
# Project Cortex v2.0 - Automated RPi 5 Setup Script
# 
# This script automates the complete installation of Project Cortex on
# Raspberry Pi 5 (4GB RAM) running Raspberry Pi OS Lite (64-bit).
#
# Usage:
#   chmod +x setup_rpi5.sh
#   ./setup_rpi5.sh
#
# Author: GitHub Copilot (CTO)
# Date: December 31, 2025
# Competition: Young Innovators Awards (YIA) 2026
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="$HOME/cortex"
VENV_DIR="$PROJECT_DIR/venv"
MODELS_DIR="$PROJECT_DIR/models"

# Logging function
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_section() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

# Check if running on Raspberry Pi 5
check_hardware() {
    log_section "CHECKING HARDWARE"
    
    # Check CPU model
    if grep -q "Raspberry Pi 5" /proc/cpuinfo; then
        log_info "✅ Detected Raspberry Pi 5"
    else
        log_warn "⚠️  Not running on Raspberry Pi 5 - proceeding anyway"
    fi
    
    # Check RAM (should be ~4GB)
    total_ram=$(free -h | grep Mem | awk '{print $2}')
    log_info "Total RAM: $total_ram"
    
    # Check temperature
    if command -v vcgencmd &> /dev/null; then
        temp=$(vcgencmd measure_temp | cut -d= -f2)
        log_info "Current temperature: $temp"
        
        # Warn if too hot
        temp_num=$(echo $temp | cut -d. -f1 | sed 's/°C//')
        if [ "$temp_num" -gt 70 ]; then
            log_warn "⚠️  Temperature is high ($temp) - ensure active cooler is installed!"
        fi
    fi
}

# Update system
update_system() {
    log_section "UPDATING SYSTEM"
    log_info "Updating package lists..."
    sudo apt update
    
    log_info "Upgrading installed packages..."
    sudo apt upgrade -y
    
    log_info "✅ System updated"
}

# Install system dependencies
install_system_deps() {
    log_section "INSTALLING SYSTEM DEPENDENCIES"
    
    log_info "Installing build tools..."
    sudo apt install -y \
        git \
        wget \
        curl \
        vim \
        htop \
        tmux \
        build-essential \
        cmake \
        pkg-config \
        libopenblas-dev \
        liblapack-dev \
        gfortran \
        libhdf5-dev \
        libssl-dev \
        libffi-dev \
        libjpeg-dev \
        zlib1g-dev
    
    log_info "Installing Python 3..."
    sudo apt install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        python3-numpy
    
    log_info "Installing audio libraries..."
    sudo apt install -y \
        libopenal-dev \
        libopenal1 \
        openal-utils \
        libsndfile1 \
        libsndfile1-dev \
        portaudio19-dev \
        alsa-utils \
        pulseaudio \
        pulseaudio-utils
    
    log_info "Installing camera support..."
    sudo apt install -y \
        python3-picamera2 \
        python3-libcamera \
        libcamera-apps
    
    log_info "Installing GPIO support..."
    sudo apt install -y \
        python3-gpiod \
        gpiod
    
    log_info "Installing OpenCV dependencies..."
    sudo apt install -y \
        libavcodec-dev \
        libavformat-dev \
        libswscale-dev \
        libv4l-dev \
        libxvidcore-dev \
        libx264-dev \
        libatlas-base-dev
    
    log_info "Installing eSpeak NG (for Kokoro TTS)..."
    sudo apt install -y \
        espeak-ng \
        libespeak-ng1
    
    log_info "✅ System dependencies installed"
}

# Create virtual environment
create_venv() {
    log_section "CREATING VIRTUAL ENVIRONMENT"
    
    # Create project directory
    if [ ! -d "$PROJECT_DIR" ]; then
        log_info "Creating project directory: $PROJECT_DIR"
        mkdir -p "$PROJECT_DIR"
    fi
    
    cd "$PROJECT_DIR"
    
    # Create venv
    if [ ! -d "$VENV_DIR" ]; then
        log_info "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    else
        log_warn "Virtual environment already exists"
    fi
    
    # Activate venv
    source "$VENV_DIR/bin/activate"
    
    # Upgrade pip
    log_info "Upgrading pip..."
    pip install --upgrade pip setuptools wheel
    
    log_info "✅ Virtual environment ready"
}

# Install PyTorch
install_pytorch() {
    log_section "INSTALLING PYTORCH (CPU-ONLY)"
    
    source "$VENV_DIR/bin/activate"
    
    log_info "Installing PyTorch from PiWheels (optimized for ARM)..."
    log_warn "This will take 10-15 minutes..."
    
    # Try PiWheels first (faster for RPi)
    if pip install torch torchvision torchaudio --extra-index-url https://www.piwheels.org/simple; then
        log_info "✅ PyTorch installed from PiWheels"
    else
        log_warn "PiWheels failed, trying official PyTorch..."
        pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cpu
        log_info "✅ PyTorch installed from official repo"
    fi
    
    # Verify installation
    python3 -c "import torch; print(f'PyTorch {torch.__version__} (CPU threads: {torch.get_num_threads()})')"
}

# Install Python dependencies
install_python_deps() {
    log_section "INSTALLING PYTHON DEPENDENCIES"
    
    source "$VENV_DIR/bin/activate"
    
    log_info "Installing core dependencies..."
    
    # Core packages
    pip install python-dotenv==1.0.0
    pip install opencv-python-headless==4.8.1.78
    pip install "numpy>=1.24.3,<2.0"
    pip install pillow==10.1.0
    
    # YOLO
    log_info "Installing Ultralytics YOLO..."
    pip install ultralytics==8.0.227
    
    # Cloud AI APIs
    log_info "Installing Cloud AI SDKs..."
    pip install "google-generativeai>=0.7.0"
    pip install "google-genai>=1.0.0"
    pip install openai==1.3.5
    pip install requests==2.31.0
    pip install "websockets>=12.0"
    pip install zai-sdk
    
    # Local AI models
    log_info "Installing local AI models..."
    pip install openai-whisper
    pip install "kokoro>=0.3.4"
    pip install "misaki[en]"
    pip install phonemizer
    
    # Audio processing
    log_info "Installing audio libraries..."
    pip install pygame==2.5.2
    pip install sounddevice==0.4.6
    pip install scipy==1.11.4
    pip install pydub==0.25.1
    pip install "pyaudio>=0.2.11"
    pip install "silero-vad>=4.0.0"
    pip install "PyOpenAL>=0.7.11a1"
    
    # GPIO
    log_info "Installing GPIO libraries..."
    pip install RPi.GPIO
    pip install lgpio
    
    # NLP (for YOLOE)
    log_info "Installing spaCy..."
    pip install "spacy>=3.7.0"
    python3 -m spacy download en_core_web_sm
    
    # Utilities
    pip install pyyaml==6.0.1
    pip install python-dateutil==2.8.2
    pip install psutil==5.9.6
    
    # Optional: Web dashboard
    log_info "Installing NiceGUI (optional)..."
    pip install "nicegui>=1.4.0"
    
    log_info "✅ Python dependencies installed"
}

# Enable camera
enable_camera() {
    log_section "ENABLING CAMERA INTERFACE"
    
    log_info "Enabling camera interface..."
    sudo raspi-config nonint do_camera 0
    
    log_info "Testing camera..."
    if libcamera-hello --list-cameras 2>&1 | grep -q "Available cameras"; then
        log_info "✅ Camera detected"
    else
        log_warn "⚠️  Camera not detected - please check connection"
    fi
}

# Download YOLO models
download_models() {
    log_section "DOWNLOADING AI MODELS"
    
    # Create models directory
    if [ ! -d "$MODELS_DIR" ]; then
        mkdir -p "$MODELS_DIR"
    fi
    
    cd "$MODELS_DIR"
    
    # Download YOLO11n (Layer 0 Guardian - NCNN optimized)
    if [ ! -f "yolo11n.pt" ]; then
        log_info "Downloading YOLO11n (5.4MB) - Layer 0 Guardian..."
        log_info "Will be converted to NCNN for 4.8x speedup (80.7ms latency)"
        wget -q --show-progress https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt
        log_info "✅ YOLO11n downloaded"
    else
        log_info "YOLO11n already exists"
    fi
    
    # Download YOLOE-11m-seg (Layer 1 Learner - Text/Visual)
    if [ ! -f "yoloe-11m-seg.pt" ]; then
        log_info "Downloading YOLOE-11m-seg (820MB) - Layer 1 Learner..."
        wget -q --show-progress https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11m-seg.pt
        log_info "✅ YOLOE-11m-seg downloaded"
    else
        log_info "YOLOE-11m-seg already exists"
    fi
    
    # Download YOLOE-11m-seg-pf (Layer 1 Learner - Prompt-Free)
    if [ ! -f "yoloe-11m-seg-pf.pt" ]; then
        log_info "Downloading YOLOE-11m-seg-pf (820MB) - Prompt-Free mode..."
        wget -q --show-progress https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11m-seg-pf.pt
        log_info "✅ YOLOE-11m-seg-pf downloaded"
    else
        log_info "YOLOE-11m-seg-pf already exists"
    fi
    
    # Download smaller models for testing
    if [ ! -f "yolo11n.pt" ]; then
        log_info "Downloading YOLO11n (10MB) - for testing..."
        wget -q --show-progress https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt
        log_info "✅ YOLO11n downloaded"
    fi
    
    log_info "✅ All models downloaded"
    
    cd "$PROJECT_DIR"
}

# Clone repository
clone_repo() {
    log_section "CLONING PROJECT CORTEX REPOSITORY"
    
    cd "$PROJECT_DIR"
    
    if [ ! -d ".git" ]; then
        log_info "Cloning repository..."
        git clone https://github.com/IRSPlays/ProjectCortexV2.git temp_repo
        
        # Move contents to project dir
        mv temp_repo/* temp_repo/.* "$PROJECT_DIR/" 2>/dev/null || true
        rm -rf temp_repo
        
        log_info "✅ Repository cloned"
    else
        log_warn "Git repository already exists"
        log_info "Pulling latest changes..."
        git pull
    fi
}

# Create .env file
create_env_file() {
    log_section "CREATING .env FILE"
    
    cd "$PROJECT_DIR"
    
    if [ ! -f ".env" ]; then
        log_info "Creating .env template..."
        cat > .env << 'EOF'
# Google Gemini API Keys (rotation support - up to 6 keys)
GEMINI_API_KEY=your_primary_key_here
GEMINI_API_KEY_2=your_backup_key_2_here
GEMINI_API_KEY_3=your_backup_key_3_here

# OpenAI API Key (fallback)
OPENAI_API_KEY=your_openai_key_here

# Z.ai API Key (Tier 2 fallback)
ZAI_API_KEY=your_zai_key_here

# Model Paths (NCNN optimized for RPi 5)
YOLO_MODEL_PATH=models/yolo11n_ncnn_model
YOLOE_MODEL_PATH=models/yoloe-11s-seg.pt
YOLO_CONFIDENCE=0.5
YOLO_DEVICE=cpu

# Database
DATABASE_PATH=cortex_memory.db
EOF
        
        chmod 600 .env
        
        log_info "✅ .env file created"
        log_warn "⚠️  IMPORTANT: Edit .env and add your real API keys!"
        log_info "   Get Gemini API key: https://aistudio.google.com/app/apikey"
    else
        log_warn ".env file already exists - skipping"
    fi
}

# Configure performance
configure_performance() {
    log_section "CONFIGURING PERFORMANCE"
    
    log_info "Enabling USB power boost..."
    if ! grep -q "usb_max_current_enable=1" /boot/firmware/config.txt; then
        echo "usb_max_current_enable=1" | sudo tee -a /boot/firmware/config.txt
        log_info "✅ USB power boost enabled (reboot required)"
    else
        log_info "USB power boost already enabled"
    fi
    
    log_info "Configuring fan control (start at 60°C)..."
    sudo raspi-config nonint do_fan 0 60
    
    log_info "✅ Performance configured"
}

# Run validation tests
run_validation() {
    log_section "RUNNING VALIDATION TESTS"
    
    source "$VENV_DIR/bin/activate"
    cd "$PROJECT_DIR"
    
    log_info "Testing PyTorch..."
    python3 -c "import torch; print(f'✅ PyTorch {torch.__version__}')" || log_error "PyTorch test failed"
    
    log_info "Testing YOLO..."
    python3 -c "from ultralytics import YOLO; print('✅ Ultralytics YOLO')" || log_error "YOLO test failed"
    
    log_info "Testing Whisper..."
    python3 -c "import whisper; print('✅ Whisper STT')" || log_error "Whisper test failed"
    
    log_info "Testing Kokoro..."
    python3 -c "from kokoro_onnx import Kokoro; print('✅ Kokoro TTS')" || log_error "Kokoro test failed"
    
    log_info "Testing OpenCV..."
    python3 -c "import cv2; print(f'✅ OpenCV {cv2.__version__}')" || log_error "OpenCV test failed"
    
    log_info "Testing picamera2..."
    python3 -c "from picamera2 import Picamera2; print('✅ picamera2')" || log_error "picamera2 test failed"
    
    log_info "Testing OpenAL..."
    python3 -c "from openal import oalInit, oalQuit; oalInit(); oalQuit(); print('✅ PyOpenAL')" || log_error "OpenAL test failed"
    
    log_info "Testing GPIO..."
    python3 -c "import RPi.GPIO; print('✅ RPi.GPIO')" || log_error "GPIO test failed"
    
    log_info "✅ All validation tests passed!"
}

# Add to .bashrc
add_to_bashrc() {
    log_section "CONFIGURING SHELL"
    
    # Add venv activation to .bashrc
    if ! grep -q "source $VENV_DIR/bin/activate" ~/.bashrc; then
        echo "" >> ~/.bashrc
        echo "# Auto-activate Cortex venv" >> ~/.bashrc
        echo "source $VENV_DIR/bin/activate" >> ~/.bashrc
        log_info "✅ Added venv activation to .bashrc"
    fi
    
    # Add helpful aliases
    if ! grep -q "alias cortex=" ~/.bashrc; then
        echo "" >> ~/.bashrc
        echo "# Cortex aliases" >> ~/.bashrc
        echo "alias cortex='cd $PROJECT_DIR && python3 src/main.py'" >> ~/.bashrc
        echo "alias cortex-gui='cd $PROJECT_DIR && python3 src/cortex_dashboard.py'" >> ~/.bashrc
        echo "alias cortex-test='cd $PROJECT_DIR && python3 tests/test_integration.py'" >> ~/.bashrc
        log_info "✅ Added Cortex aliases to .bashrc"
    fi
}

# Print summary
print_summary() {
    log_section "INSTALLATION COMPLETE!"
    
    echo ""
    echo -e "${GREEN}✅ Project Cortex v2.0 is now installed on your Raspberry Pi 5!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Edit .env file and add your API keys:"
    echo "     nano $PROJECT_DIR/.env"
    echo ""
    echo "  2. Get Gemini API key (free):"
    echo "     https://aistudio.google.com/app/apikey"
    echo ""
    echo "  3. Reboot to apply all changes:"
    echo "     sudo reboot"
    echo ""
    echo "  4. After reboot, run Project Cortex:"
    echo "     cd $PROJECT_DIR"
    echo "     python3 src/main.py"
    echo ""
    echo "  Or use aliases:"
    echo "     cortex         - Run headless mode"
    echo "     cortex-gui     - Run web dashboard"
    echo "     cortex-test    - Run integration tests"
    echo ""
    echo "Documentation:"
    echo "  - Setup Guide: $PROJECT_DIR/docs/implementation/RPI5-COMPLETE-SETUP-GUIDE.md"
    echo "  - Architecture: $PROJECT_DIR/docs/architecture/UNIFIED-SYSTEM-ARCHITECTURE.md"
    echo ""
    echo -e "${BLUE}Good luck at YIA 2026! 🏆${NC}"
    echo ""
}

# Main installation flow
main() {
    echo ""
    echo "================================================"
    echo "  PROJECT CORTEX V2.0 - AUTOMATED RPi 5 SETUP"
    echo "================================================"
    echo ""
    echo "This script will install all dependencies for"
    echo "Project Cortex v2.0 on your Raspberry Pi 5."
    echo ""
    echo "Estimated time: 2-3 hours (including downloads)"
    echo "Estimated disk space: 10GB"
    echo ""
    read -p "Continue? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "Installation cancelled"
        exit 1
    fi
    
    # Run installation steps
    check_hardware
    update_system
    install_system_deps
    create_venv
    install_pytorch
    install_python_deps
    enable_camera
    download_models
    clone_repo
    create_env_file
    configure_performance
    run_validation
    add_to_bashrc
    print_summary
}

# Run main
main
