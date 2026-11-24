#!/usr/bin/env bash
# Grab 640x360 JPEGs from the ZV-1F for NPU calibration / test sets.
#   capture_frames.sh <dir> <count> <interval_s> [prefix]
# e.g. capture_frames.sh /var/lib/cortex/bench/npu/calib 50 2 c   -> c001.jpg .. c050.jpg, one every 2 s
# Move the camera between shots. The first second is dropped while auto-exposure settles.
# Frames are personal data: they stay on the box, never in git.
set -euo pipefail
DIR="${1:?dir}"; COUNT="${2:?count}"; EVERY="${3:?interval_s}"; PREFIX="${4:-f}"
DEV="${CORTEX_CAMERA:-}"
if [ -z "$DEV" ]; then
    for d in /sys/class/video4linux/video*; do
        [ "$(cat "$d/name")" = "ZV-1F" ] && { DEV="/dev/$(basename "$d")"; break; }
    done
fi
[ -n "$DEV" ] || { echo "ZV-1F not found (set CORTEX_CAMERA=/dev/videoN)" >&2; exit 1; }
mkdir -p "$DIR"
echo "capturing $COUNT frames from $DEV every ${EVERY}s into $DIR ..."
ffmpeg -hide_banner -loglevel error -f v4l2 -input_format mjpeg -video_size 1280x720 -i "$DEV" -ss 1 \
    -vf "fps=1/${EVERY},scale=640:360:flags=bicubic" -frames:v "$COUNT" -q:v 2 -start_number 1 \
    "$DIR/${PREFIX}%03d.jpg"
ls "$DIR"/"${PREFIX}"*.jpg | wc -l | xargs echo "frames in $DIR with prefix $PREFIX:"
