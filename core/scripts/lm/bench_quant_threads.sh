#!/bin/sh
# Q4_0 vs Q4_K_M, and thread placement, on the box. No NPU: answers come from saved NPU features.
#   sh bench_quant_threads.sh [OUT_DIR]
# Settings: t4 = 4 threads unpinned (llama.cpp's default, what cortex-embd used before -t),
#           t4big = 4 threads pinned to the X1C big cores (cpu4-7), t8 = 8 threads on all cores.
set -u
OUT=${1:-/var/lib/cortex/bench/speedups/q_t}
M=/var/lib/cortex/models
BIN=/opt/llama.cpp/b12679/build-cpu/bin
EMBD=/opt/llama.cpp/cortex-embd/cortex-embd
CASES=/var/lib/cortex/bench/npu/test/cases.json
FEATS=/var/lib/cortex/bench/npu/npu_run2
PY="/opt/cortex/venv/bin/python"
export PYTHONPATH=/opt/cortex
mkdir -p "$OUT"
soc() { $PY -c "import json;from cortex_core.npu.run_npu import soc_state;print(json.dumps(soc_state()))"; }
for q in Q4_K_M Q4_0; do
  for s in t4 t4big t8; do
    case $s in t4) t=4; pin="";; t4big) t=4; pin="taskset -c 4-7";; t8) t=8; pin="";; esac
    model="$M/LFM3-Omni-2B-$q.gguf"
    echo "== $q $s $(date +%T)"
    soc > "$OUT/soc_${q}_${s}_before.json"
    $pin "$BIN/llama-bench" -m "$model" -p 220 -n 64 -r 3 -t $t -o json > "$OUT/bench_${q}_${s}.json" 2> "$OUT/bench_${q}_${s}.log"
    $PY -m cortex_core.npu.answer_cases --cases "$CASES" --feat-dir "$FEATS" --embd "$EMBD" --model "$model" \
        --mmproj "$M/mmproj-LFM3-Omni-2B-Q8_0.gguf" --out "$OUT/answers_${q}_${s}.json" --threads $t \
        ${pin:+--taskset 4-7} | tail -1
    soc > "$OUT/soc_${q}_${s}_after.json"
    sleep 30
  done
done
echo BENCH-DONE
