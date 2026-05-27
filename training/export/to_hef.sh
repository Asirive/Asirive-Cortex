#!/bin/bash
# Hailo HEF Compilation Script
# Run on x86 Linux workstation with Hailo SW Suite installed.
#
# Usage: bash training/export/to_hef.sh <onnx_path> <output_dir>
#
# Author: Haziq (@IRSPlays)
# Date: May 2026

set -e

ONNX_PATH="${1:-models/cortex_local/cortex_local.onnx}"
OUTPUT_DIR="${2:-models/cortex_local/}"
CALIB_DIR="${3:-training/export/calibration_data/}"

mkdir -p "$OUTPUT_DIR"

echo "[Hailo] Step 1/4: Parse ONNX..."
hailo parser onnx "$ONNX_PATH" --output "$OUTPUT_DIR/cortex_local.hailo"

echo "[Hailo] Step 2/4: Optimize..."
hailo optimize "$OUTPUT_DIR/cortex_local.hailo" --output "$OUTPUT_DIR/cortex_local_opt.hailo"

echo "[Hailo] Step 3/4: Quantize..."
hailo quantize "$OUTPUT_DIR/cortex_local_opt.hailo" \
    --calib-set "$CALIB_DIR" \
    --output "$OUTPUT_DIR/cortex_local_quant.hailo"

echo "[Hailo] Step 4/4: Compile HEF..."
hailo compile "$OUTPUT_DIR/cortex_local_quant.hailo" \
    --output "$OUTPUT_DIR/cortex_local.hef" \
    --performance-calibration

echo "[Hailo] Done. Output: $OUTPUT_DIR/cortex_local.hef"
