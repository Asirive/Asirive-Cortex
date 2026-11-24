#!/usr/bin/env bash
# Check cortex-embd end to end on the box: dump CPU features for a photo, answer from those features.
# Passes only if the answer still names the shark in the bench photo (same answer as llama-server).
set -uo pipefail
BIN=/opt/llama.cpp/cortex-embd/cortex-embd
M=/var/lib/cortex/models
IMG="${1:-/var/lib/cortex/bench/media/scene_640.jpg}"
EXPECT="${2:-shark}"
OUT=/var/lib/cortex/bench/npu/ref/check.f32
mkdir -p "$(dirname "$OUT")"
[ -x "$BIN" ] || { echo "FAIL: $BIN not built"; exit 1; }
"$BIN" dump -m $M/LFM3-Omni-2B-Q4_K_M.gguf --mmproj $M/mmproj-LFM3-Omni-2B-Q8_0.gguf --image "$IMG" --out "$OUT" || exit 1
ANS=$("$BIN" answer -m $M/LFM3-Omni-2B-Q4_K_M.gguf --mmproj $M/mmproj-LFM3-Omni-2B-Q8_0.gguf --feat "$OUT" \
      -p "What is directly in front of me? One sentence.") || exit 1
echo "$ANS"
echo "$ANS" | head -1 | grep -qi "$EXPECT" && echo "PASS" || { echo "FAIL: answer does not mention '$EXPECT'"; exit 1; }
