#!/bin/sh
# PC -> box: copy the engine sources, build on the box, run engine_tests [filter].
#   sh core/scripts/engine/box_build.sh [filter]
# Run from the repo root. Box: radxa@192.168.0.228 (override with CORTEX_BOX).
set -eu
BOX=${CORTEX_BOX:-radxa@192.168.0.228}
here=$(cd "$(dirname "$0")/../.." && pwd)
ssh "$BOX" 'mkdir -p /opt/cortex/tools /opt/cortex/build/cortex-engine'
tar -C "$here/tools" -cf - cortex-engine cortex-npu/cortex_npu.cpp | ssh "$BOX" 'tar -C /opt/cortex/tools -xf -'
ssh "$BOX" "cd /opt/cortex/build/cortex-engine && { [ -f CMakeCache.txt ] || cmake /opt/cortex/tools/cortex-engine >/dev/null; } \
  && cmake --build . -j8 2>&1 | grep -E 'error|warning|Error' | head -40; \
  [ -x ./engine_tests ] && cd /var/lib/cortex/bench/engine 2>/dev/null; /opt/cortex/build/cortex-engine/engine_tests ${1:-}"
