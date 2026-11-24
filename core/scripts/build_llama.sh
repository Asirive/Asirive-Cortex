#!/usr/bin/env bash
# Build stock llama.cpp for the LFM3-Omni baseline on the Dragon Q8B.
#
#   bash build_llama.sh <tag>          e.g. bash build_llama.sh b12679
#
# Clones https://github.com/ggml-org/llama.cpp at <tag> into /opt/llama.cpp/<tag> and builds two
# CMake Release trees:
#   build-cpu  CPU only (the default backend)
#   build-gpu  OpenCL (Adreno kernels) when an OpenCL platform is installed, otherwise Vulkan
#              (on Radxa OS the Adreno GPU is only reachable through Mesa's Turnip Vulkan driver).
# Prints which GPU backend was used and the paths of both server binaries.
# /opt/llama.cpp must exist and be writable by this user (one-time sudo setup).
set -euo pipefail

TAG="${1:?usage: build_llama.sh <tag>  (a llama.cpp release tag, b11960 or newer)}"
ROOT="/opt/llama.cpp/${TAG}"
JOBS="$(nproc)"

if [ ! -d "${ROOT}/.git" ]; then
    git clone --depth 1 --branch "${TAG}" https://github.com/ggml-org/llama.cpp "${ROOT}"
fi
cd "${ROOT}"
echo "llama.cpp ${TAG} at $(git rev-parse --short HEAD)"

COMMON=(-DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF)

cmake -S . -B build-cpu "${COMMON[@]}"
cmake --build build-cpu --config Release -j "${JOBS}"

GPU_BACKEND=""
if command -v clinfo >/dev/null 2>&1 && clinfo -l 2>/dev/null | grep -q "Platform"; then
    if cmake -S . -B build-gpu "${COMMON[@]}" -DGGML_OPENCL=ON -DGGML_OPENCL_USE_ADRENO_KERNELS=ON; then
        GPU_BACKEND="opencl"
    else
        rm -rf build-gpu
    fi
fi
if [ -z "${GPU_BACKEND}" ]; then
    cmake -S . -B build-gpu "${COMMON[@]}" -DGGML_VULKAN=ON
    GPU_BACKEND="vulkan"
fi
cmake --build build-gpu --config Release -j "${JOBS}"

server_bin() {  # newer releases ship the unified `llama` binary (`llama serve`) next to llama-server
    for b in "$1/bin/llama-server" "$1/bin/llama"; do
        [ -x "$b" ] && { echo "$b"; return 0; }
    done
    echo "MISSING in $1/bin"
}

echo
echo "GPU backend used: ${GPU_BACKEND}"
echo "CPU server: $(server_bin "${ROOT}/build-cpu")"
echo "GPU server: $(server_bin "${ROOT}/build-gpu")"
