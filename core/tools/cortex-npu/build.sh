#!/bin/sh
# Build libcortex_npu.so on the box. QNN_INCLUDE = the QAIRT SDK's include/QNN dir (2.42.0, matching the
# box's qcom-qnn-sdk-v68 runtime). Headers stay outside git.
set -eu
: "${QNN_INCLUDE:?set QNN_INCLUDE to <qairt>/include/QNN}"
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here/libcortex_npu.so}
g++ -O2 -std=c++17 -shared -fPIC -Wall -I"$QNN_INCLUDE" "$here/cortex_npu.cpp" -ldl -o "$out"
echo "built $out"
