#!/usr/bin/env bash
# Regenerate Python contract types from contracts/proto. Needs: pip install grpcio-tools
set -euo pipefail
cd "$(dirname "$0")/../.."
out=core/cortex_core/contracts/gen
rm -rf "$out" && mkdir -p "$out"
python3 -m grpc_tools.protoc -Icontracts/proto --python_out="$out" contracts/proto/cortex/v1/*.proto
find "$out" -type d -exec touch {}/__init__.py \;
echo "generated into $out"
