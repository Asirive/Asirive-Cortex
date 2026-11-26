#!/usr/bin/env bash
# For the host tests only (core/tests/test_glasses_firmware.py): TinyUSB's headers, to build the USB descriptors on
# the server and check them byte by byte. The ESP-IDF build gets TinyUSB from the component manager instead.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HERE/.deps/tinyusb"
TAG=v0.21.0.6
rm -rf "$DEST"
git clone -q --depth 1 --branch "$TAG" --filter=blob:none --sparse https://github.com/espressif/tinyusb.git "$DEST"
git -C "$DEST" sparse-checkout set src
echo "TinyUSB $TAG headers -> $DEST/src"
