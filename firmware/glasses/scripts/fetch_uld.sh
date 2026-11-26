#!/usr/bin/env bash
# Fetch ST's VL53L7CX ultra-lite driver (BSD-3-Clause, from STMicroelectronics/x-cube-tof1) into
# components/vl53l7cx_uld/st/. The driver carries an 84 kB sensor firmware blob, so it is not committed (gitignored).
set -euo pipefail
REPO=https://github.com/STMicroelectronics/x-cube-tof1.git
COMMIT=c12709c3ac802d91dd2a215178f53cb94c024709
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HERE/components/vl53l7cx_uld/st"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git -C "$TMP" init -q
git -C "$TMP" remote add origin "$REPO"
git -C "$TMP" config core.sparseCheckout true
echo "Drivers/BSP/Components/vl53l7cx/" > "$TMP/.git/info/sparse-checkout"
git -C "$TMP" fetch -q --depth 1 --filter=blob:none origin "$COMMIT"
git -C "$TMP" checkout -q FETCH_HEAD
SRC="$TMP/Drivers/BSP/Components/vl53l7cx"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -r "$SRC/modules" "$SRC/porting" "$SRC/LICENSE.md" "$DEST/"
echo "$COMMIT" > "$DEST/COMMIT"
echo "VL53L7CX ULD -> $DEST ($(ls "$DEST/modules" | wc -l) files)"
