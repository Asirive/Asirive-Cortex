#!/usr/bin/env bash
# Build core/tools/cortex-embd on the box against the llama.cpp tree from build_llama.sh.
#   bash build_cortex_embd.sh [llama_tag]      -> /opt/llama.cpp/cortex-embd/cortex-embd
set -euo pipefail
TAG="${1:-b12679}"
SRC="$(cd "$(dirname "$0")/../tools/cortex-embd" && pwd)"
OUT=/opt/llama.cpp/cortex-embd
cmake -S "${SRC}" -B "${OUT}" -DCMAKE_BUILD_TYPE=Release -DLLAMA_ROOT="/opt/llama.cpp/${TAG}"
cmake --build "${OUT}" -j "$(nproc)"
echo "built ${OUT}/cortex-embd"
