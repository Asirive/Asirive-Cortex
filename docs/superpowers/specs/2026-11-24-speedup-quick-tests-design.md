# Step 1 of the parallel engine: quick speed tests (design)

Approved order (Haziq, 2026-11-24): engine approach A, our own C++ engine process. Step 1 is this document.
The later steps are: 2 engine core (image held in the model's memory), 3 hands-free mode (voice detection, speech
encoded while talking), 4 speech output in parallel.

## Why

Today the model needs 2.3-2.9 s before its first word, because it must read 220 image tokens on the CPU
(~95 tokens/s). The engine (step 2) will hide most of that by reading the image before the user asks. But hands-free
mode wants a fresh frame read as often as possible, so every second saved per image read matters. Two cheap
speed-ups should be measured before the engine is built around today's numbers.

## Goals

1. **Faster CPU format.** Compare Liquid's official `LFM3-Omni-2B-Q4_0.gguf` with the current Q4_K_M.
   The CPU (4x Cortex-X1C + 4x Cortex-A78C) has the dot-product instructions that llama.cpp's fast Q4_0 path needs.
   - Speed: llama-bench prompt reading at 220 tokens, and generation, at 4 threads on the X1C cores and at 8 threads.
   - Quality: the 12 test cases answered from the existing NPU features with each model, plus time to first word.
2. **Fewer image tokens.** A 448x256 canvas gives 14x8 = 112 tokens instead of 220.
   - Rebuild the NPU split encoder at that shape: same recipe, same 52 calibration frames.
   - Measure NPU encode time, cosine vs ONNX on CPU at the same shape, the 12 answers, and time to first word.
3. **Thread placement.** Prompt reading pinned to the 4 big cores vs all 8. This sets how many cores steps 3-4 can
   keep for speech.

## Non-goals

No engine, no audio, no brain changes. No change to the 640x352 path. The 112-token path is added beside it,
not instead of it.

## Decision rule

- Q4_0 is adopted if it answers 12/12 and reads tokens faster.
- 112 tokens is **not** adopted automatically: it trades detail for speed. Haziq decides from the table, with both
  answers shown side by side.

## Constraints

- Download needs Haziq's OK: `LiquidAI/LFM3-Omni-2B-GGUF` → `LFM3-Omni-2B-Q4_0.gguf`, 1.05 GB, sha256
  `6d2273a383b92dd7c5db0eb4c8dfeae13e805b485a6621c4b391ae179c2b5f28`, into `/var/lib/cortex/models/` (42 GB free).
- No weights, photos or NPU binaries in git. Commits are made as IRSPlays.
- The 112-token rebuild runs in WSL on the PC (~40-60 min, C: has ~7 GB free; the per-segment calibration data is
  deleted as it goes, as before).

## Left to the builder

- The exact llama-bench flags.
- Which cores are the X1C cores (read from sysfs).
- The stand-in image size that makes llama.cpp lay out exactly 112 tokens (`cortex-embd answer` refuses a mismatch,
  so it is found by trying).
- How `vision_prep` takes the canvas size as a parameter.

## Output

`docs/measurements/2026-11-speedups.md`: one table per test, and the combined estimate of a full image read with
both speed-ups.
