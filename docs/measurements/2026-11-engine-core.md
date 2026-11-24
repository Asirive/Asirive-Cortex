# Cortex engine core: measurements (2026-11-24)

Step 2 of the parallel engine: `libcortex_engine.so` (core/tools/cortex-engine) holds the NPU vision encoder and
LFM3-Omni-2B (Q4_0, llama.cpp b12679) in one native runtime. The latest frame is encoded and read into the LM's memory
in the background, so an ask only reads the question. Plan: `docs/superpowers/plans/2026-11-24-cortex-engine-core.md`.

Box: Radxa Dragon Q8B (SC8280XP), cpu0-3 Cortex-A78C, cpu4-7 Cortex-X1C, 7 GiB RAM. QNN 2.42, HTP v68.
Raw data on the box: `/var/lib/cortex/bench/engine/` (`native_bench_fresh.json`, `native_bench_history.json`); the
engine test suite (`sh core/scripts/engine/box_build.sh`, 25 tests) prints the port, island and LM numbers below.

## Headline

| | Target | Measured |
|:---|---:|---:|
| Time to first token, view ready (12 cases) | ≤ 400 ms | **115 ms** median (93–133) |
| Answers matching (one conversation per case) | 12/12 | **12/12** |
| Answers matching (one running conversation) | — | 11/12 (see caveats) |
| View refresh: prep + encode + read | ≤ 1.4 s | **1.42 s** median (max 1.46) — missed by ~20 ms |
| Still scene: frames skipped | — | 10/10 (cos 1.0) |
| Engine threads on cpu0 (safety) | never | never |
| Peak RSS (bench process) | — | 3.09 GiB |

Before (step 1, cortex-embd one shot, Q4_0, 4 big cores): TTFT 1.23 s, because every ask read the image too.

## Vision encoder port (C++ vs the Python NPU chain)

| | Value |
|:---|---:|
| Features vs Python NPU features, mean row cosine (14 frames) | 0.99998–0.99999 |
| Prep (Pillow-exact bicubic, 640x360 → 640x352 canvas) | 1.9 ms (bit-exact on 14 frames) |
| Encode median over 14 frames | 281.7 ms |
| — NPU segments (7): quantise / execute / dequantise | 5.0 / 125.1 / 4.2 ms |
| — CPU attention islands (6) | 148.7 ms |

## Attention islands: core choice

One island = softmax(Q·Kᵀ/8)·V, 16 heads × 64, 880 tokens; ggml flash attention, F32 K/V.

| Cores | Median per island |
|:---|---:|
| cpu1-3 (A78C) | 59.4 ms |
| cpu4-7 (X1C) | 23.5 ms |
| cpu1-7 | 21.9 ms |

Ruling: islands on cpu4-7. An ask goes ahead of the next island (big-core gate), so it waits at most one island.
The Python chain measured 257 ms using all 8 cores including cpu0; the engine never touches cpu0.

## Time to first token

| Case | TTFT |
|:---|---:|
| Ask with the view ready (LM test, 5 asks) | 116 ms median |
| Ask through the C API (12 cases, fresh / running conversation) | 115 / 122 ms median |
| Follow-up about the same view (continues the conversation slot) | 133 ms |
| Ask that preempts a background view read | 136 ms |
| Slot copy (llama.cpp sequence copy, unified KV) | 0.13 ms |
| Cancel → done event | 12 ms |

The answer for t001 is identical, token for token, to `cortex-embd answer -t 4` with the same features.

## View refresh

| Stage | Median (12 cases) |
|:---|---:|
| Prep | 1.9 ms |
| Encode (NPU + islands) | 282–288 ms |
| Read 220 image tokens into the LM (cpu4-7) | 1131 ms (fresh), 1143 ms (373-token history) |
| **Total** | **1420 / 1427 ms** |

The read is the floor: ~195 image tokens/s prefill on the four X1C cores. Splitting the read into 64-token batches
for preemption bought nothing (1134 vs 1121 ms) because llama's abort callback stops a read mid-graph; it now reads
the whole image in one batch. The finished question/answer turn joins the history in the background right after the
answer, so it is off the next refresh (that turn had added ~190 ms to every read before).

## Threads

`ce_status` affinities in both bench runs: `control` (prep, NPU, islands, background reads) and `lm` (asks) both on
cpu4. ggml pins whichever thread creates or drives a threadpool to the pool's first core, so the configured
`vision_cpus` (1-3) are not used in practice. The caller of `ce_open` is never pinned: the engine creates both pools
on its own threads.

## Caveats

- **History bias.** With one running conversation, t012 ("the device with the cable plugged in", a power bank) was
  answered "smartphone": the two previous turns were about smartphones. With a fresh conversation per case it is
  right (12/12). Whether to drop history on a scene change is a product decision, not made here.
- Refresh is 1.42 s against a 1.4 s target. Options: island + read on cpu1-7, or the 112-token canvas (deferred).
- Typed questions only; voice input and spoken output are steps 3 and 4.
- 12 test frames from one camera (ZV-1F), not the product camera.
- No power meter on the box, so no energy numbers.
- Tool calls are untested on Q4_0.
- Peak RSS 3.09 GiB includes the mmproj vision weights, which mtmd loads even though the NPU does the encoding
  (only the prompt layout is used).
- QNN prints teardown errors at process exit (after all output). Harmless, not silenced yet.
