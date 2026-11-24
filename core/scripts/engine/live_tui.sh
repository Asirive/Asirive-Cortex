#!/bin/sh
# On the box: the live dev TUI (engine + camera + mic).   sh /opt/cortex/scripts/engine/live_tui.sh [args]
# Sets the QNN library paths the NPU needs, then runs python -m cortex_core.tui --live in the cortex venv.
set -eu
. /var/lib/cortex/bench/engine/qnn.env
cd /opt/cortex
CORTEX_DEV_BUILD=1 exec /opt/cortex/venv/bin/python -m cortex_core.tui --live "$@"
