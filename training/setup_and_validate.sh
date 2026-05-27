#!/bin/bash
# setup_and_validate.sh
# One-command setup + validation for RTX 6000 Ada (or any CUDA GPU)
#
# Run on the rented GPU instance:
#   chmod +x setup_and_validate.sh
#   ./setup_and_validate.sh
#
# Author: Haziq (@IRSPlays)
# Date: May 2026

set -e  # Exit on error

echo "=========================================="
echo "CortexLocal Validation Setup"
echo "=========================================="

# ---------------------------------------------------------------------------
# 1. Environment Check
# ---------------------------------------------------------------------------
echo ""
echo "[1/6] Checking environment..."
python3 --version
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || echo "WARNING: nvidia-smi not found"

# ---------------------------------------------------------------------------
# 2. Install System Dependencies
# ---------------------------------------------------------------------------
echo ""
echo "[2/6] Installing system dependencies..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        git \
        wget \
        unzip \
        libgl1-mesa-glx \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libgomp1
fi

# ---------------------------------------------------------------------------
# 3. Install Python Dependencies
# ---------------------------------------------------------------------------
echo ""
echo "[3/6] Installing Python packages..."

# Core
pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Training + model
pip install -q transformers accelerate
pip install -q mamba-ssm

# Data + eval
pip install -q opencv-python pillow tqdm

# Optional: for real COCO download
pip install -q pycocotools

# Verify installations
python3 -c "import torch; print(f'PyTorch: {torch.__version__}, CUDA: {torch.cuda.is_available()}')"
python3 -c "import mamba_ssm; print('mamba_ssm: OK')" || echo "WARNING: mamba_ssm install failed"

# ---------------------------------------------------------------------------
# 4. Download Project Code
# ---------------------------------------------------------------------------
echo ""
echo "[4/6] Downloading project code..."

PROJECT_DIR="$HOME/ProjectCortex"
if [ ! -d "$PROJECT_DIR" ]; then
    # Option A: Git clone (if you push to GitHub)
    # git clone https://github.com/YOUR_USERNAME/ProjectCortex.git "$PROJECT_DIR"
    
    # Option B: Copy from local (if you rsync/scp first)
    # scp -r /local/path/ProjectCortex user@gpu:~/
    
    # Option C: Create minimal structure for validation
    mkdir -p "$PROJECT_DIR"
    echo "Created $PROJECT_DIR"
    echo "NOTE: You need to upload the training/ directory to this server first."
    echo "  Run from your laptop: scp -r training/ user@gpu-ip:~/ProjectCortex/"
fi

cd "$PROJECT_DIR" || exit 1

# ---------------------------------------------------------------------------
# 5. Download COCO (optional, only if --dataset coco)
# ---------------------------------------------------------------------------
echo ""
echo "[5/6] Downloading COCO dataset (optional)..."

COCO_DIR="$PROJECT_DIR/data/coco"
if [ ! -d "$COCO_DIR/val2017" ]; then
    echo "COCO not found. Downloading..."
    mkdir -p "$COCO_DIR"
    cd "$COCO_DIR"
    
    # Download annotations
    wget -q http://images.cocodataset.org/annotations/annotations_trainval2017.zip
    unzip -q annotations_trainval2017.zip
    rm annotations_trainval2017.zip
    
    # Download validation images (smaller, for testing)
    wget -q http://images.cocodataset.org/zips/val2017.zip
    unzip -q val2017.zip
    rm val2017.zip
    
    # Download small train subset (5K images)
    wget -q http://images.cocodataset.org/zips/train2017.zip
    unzip -q train2017.zip
    rm train2017.zip
    
    echo "COCO download complete. Size: $(du -sh . | cut -f1)"
    cd "$PROJECT_DIR"
else
    echo "COCO already exists at $COCO_DIR"
fi

# ---------------------------------------------------------------------------
# 6. Run Validation Tests
# ---------------------------------------------------------------------------
echo ""
echo "[6/6] Running validation tests..."
echo "=========================================="

OUTPUT_BASE="$PROJECT_DIR/outputs/validate"
mkdir -p "$OUTPUT_BASE"

# Test A: Synthetic (fast, proves architecture)
echo ""
echo "--- Test A: Synthetic Dataset ---"
python3 training/validate_architecture.py \
    --dataset synthetic \
    --steps 2000 \
    --batch_size 8 \
    --eval_every 500 \
    --save_every 1000 \
    --output_dir "$OUTPUT_BASE/synthetic" \
    --device cuda

echo ""
echo "Synthetic test complete. Results:"
ls -lh "$OUTPUT_BASE/synthetic/"
cat "$OUTPUT_BASE/synthetic/validation_summary.json" 2>/dev/null || echo "No summary yet"

# Test B: COCO (real images, proves vision-language)
echo ""
echo "--- Test B: COCO Dataset ---"
python3 training/validate_architecture.py \
    --dataset coco \
    --coco_root "$COCO_DIR" \
    --steps 5000 \
    --batch_size 8 \
    --eval_every 1000 \
    --save_every 2000 \
    --output_dir "$OUTPUT_BASE/coco" \
    --device cuda \
    --max_samples 10000

echo ""
echo "COCO test complete. Results:"
ls -lh "$OUTPUT_BASE/coco/"
cat "$OUTPUT_BASE/coco/validation_summary.json" 2>/dev/null || echo "No summary yet"

# ---------------------------------------------------------------------------
# 7. Summary
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "VALIDATION COMPLETE"
echo "=========================================="
echo ""
echo "Results saved to: $OUTPUT_BASE"
echo ""
echo "To download results to your laptop:"
echo "  scp -r user@gpu-ip:~/ProjectCortex/outputs/validate ./local_results/"
echo ""
echo "Next steps:"
echo "  1. Check validation_summary.json in both synthetic/ and coco/"
echo "  2. If loss converges and accuracy > 0%, architecture is VALIDATED"
echo "  3. Proceed to full datacenter GPU training (Stage 1-5)"
echo ""
