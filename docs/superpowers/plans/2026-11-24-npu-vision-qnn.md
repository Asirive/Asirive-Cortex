# NPU Vision Encoder via QNN (approach A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the LFM3-Omni vision encoder on the Dragon Q8B's Hexagon v68 NPU through QNN for a fixed 640 px frame, and measure its speed and answer quality against the CPU path.

**Architecture:** llama.cpp stays the language model. A small C++ tool (`cortex-embd`) built against llama.cpp b12679 dumps the CPU image features (the reference) and answers a question from features supplied in a file. Liquid's `vision_encoder.onnx` is checked against that reference on CPU (onnxruntime), converted and quantised for v68 with Qualcomm's QAIRT tools, then run on the NPU; its features go through `cortex-embd answer` so quality is judged on real answers, not only numbers.

**Tech Stack:** llama.cpp b12679 (mtmd + llama C API), C++17/CMake, Python 3 (numpy, onnxruntime from apt), QAIRT SDK (converter, quantiser, context-binary generator; Haziq's download), `qcom-qnn-sdk-v68` (Radxa apt, runtime on the box).

**Spec:** `docs/superpowers/specs/2026-11-24-npu-vision-design.md`. Approach B (llama.cpp Hexagon v68 port) and the final A-vs-B comparison get their own plan after this one.

## Global Constraints

- Fixed frame size: **640x360** camera frame, prepared to the encoder's fixed input (multiple of 32 px: patch 16 x spatial merge 2), e.g. 640x352; the exact size is decided once in Task 1 and used everywhere.
- Targets: encode **≤300 ms** median of 20 runs after warm-up (stretch ≤100 ms); answer quality = same answers as CPU on ≥10 test frames; feature cosine vs CPU reference **≥0.98 mean**.
- Quantisation first try: **8-bit weights, 16-bit activations** (v68 is fixed-point).
- No Qualcomm SDK files, model weights, converted binaries, calibration or test photos in git. They live under `/var/lib/cortex/` on the box and outside the repo on the PC.
- Commits as `git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit`, no co-author line.
- Python on the box: `/opt/cortex/venv`; unit tests run on the PC venv and on the box, stdlib + numpy only in `cortex_core`.
- Temperatures reported from CPU thermal zones only (the `pmc8280c` PMIC zone reads 88 °C idle).

## Review Focus

1. A frame that is not 640x360 (glasses camera, phone photo, portrait) → prepared to the fixed input by resize + pad, never a crash or a stretched image. Test in Task 1.
2. A dark or low-light frame → quantised encoder still answers like CPU; low-light frames are in both the calibration and the test sets (Task 4) and the table reports them separately (Task 6).
3. The NPU is unavailable at run time (fastrpc busy, skel missing, wrong arch) → a clear error naming what is missing, exit code non-zero, never a hang. Test in Task 6 (`run_vision_npu` with a bad context path).
4. Features in the wrong layout (tokens x dims transposed, or token order changed) → caught by per-token cosine, not averaged away. Test in Task 3 (`cosine_rows` on a shuffled copy).
5. Throttling during the timing loop → CPU frequency recorded next to each timing run (Task 6).

---

### Task 1: Encoder input contract and frame preparation

**Files:**
- Create: `core/cortex_core/npu/__init__.py`, `core/cortex_core/npu/vision_prep.py`
- Test: `core/tests/test_npu_vision_prep.py`

**Interfaces:**
- Produces: `INPUT_W: int`, `INPUT_H: int`, `MEAN: tuple[float,float,float]`, `STD: tuple[float,float,float]` (from `processor_config.json`), `prepare(rgb: numpy.ndarray[H,W,3] uint8) -> numpy.ndarray` shaped exactly as the ONNX encoder's pixel input (layout found in Step 1), dtype float32.

- [ ] **Step 1: Inspect the contract** — with Haziq's OK, download `onnx/vision_encoder.onnx` + `.onnx_data` (722 MB) and `processor_config.json` from `LiquidAI/LFM3-Omni-2B-ONNX` to `/var/lib/cortex/models/onnx/` on the box. Print the graph's input/output names, shapes and dtypes with onnxruntime. Record them, the resize/pad rule and mean/std from `processor_config.json`, and the chosen fixed size in the ledger as a ruling.
- [ ] **Step 2: Write failing tests** — `test_prepare_shape_and_dtype` (640x360 frame → exact input shape, float32); `test_prepare_normalises` (a frame of value 128 → `(128/255 - MEAN)/STD` per channel within 1e-6); `test_prepare_other_sizes` (1920x1080, 480x640 portrait, 100x100 → same output shape, no exception; portrait is padded, not stretched: aspect ratio of the non-pad region within 2 % of the source).
- [ ] **Step 3: Run** `venv python -m pytest tests/test_npu_vision_prep.py -q` — Expected: FAIL (module missing).
- [ ] **Step 4: Implement `prepare`** — resize keeping aspect ratio to fit `INPUT_W x INPUT_H`, pad the rest with the processor's pad value (mean colour if unspecified), normalise, reorder to the graph's layout. numpy only (images decoded elsewhere).
- [ ] **Step 5: Run tests** — Expected: PASS. **Commit** `core/cortex_core/npu core/tests/test_npu_vision_prep.py`, message `npu: vision encoder input contract and frame preparation`.

### Task 2: `cortex-embd` — dump reference features, answer from features

**Files:**
- Create: `core/tools/cortex-embd/CMakeLists.txt`, `core/tools/cortex-embd/main.cpp`, `core/scripts/build_cortex_embd.sh`

**Interfaces:**
- Consumes: llama.cpp b12679 at `/opt/llama.cpp/b12679` (`build-cpu`), model + mmproj in `/var/lib/cortex/models`.
- Produces, on the box at `/opt/cortex-embd/cortex-embd`:
  - `cortex-embd dump -m MODEL --mmproj MMPROJ --image IMG --out FEAT.f32` → writes raw little-endian float32 `[n_tokens, n_embd]` plus `FEAT.json` `{"n_tokens":…, "n_embd":…, "encode_ms":…}`.
  - `cortex-embd answer -m MODEL --feat FEAT.f32 -p PROMPT [-n 60]` → prints the answer, then one JSON line `{"ttft_s":…, "decode_tps":…}`. The features are placed where the image would be, using the same chat template and image markers llama.cpp uses for that image.

- [ ] **Step 1: Write the check script first** — `core/scripts/check_cortex_embd.sh` runs `dump` on `scene_640.jpg`, then `answer` with "What is directly in front of me? One sentence."; exits non-zero unless the answer contains "shark". Run it: Expected: FAIL (binary missing).
- [ ] **Step 2: Implement** `main.cpp` using mtmd (`mtmd_tokenize`, `mtmd_encode_chunk`, `mtmd_get_output_embd`) for `dump`, and `llama_batch` with `embd` for the image positions in `answer`; `build_cortex_embd.sh` builds it with CMake against the b12679 tree. Greedy sampling, `--reasoning off` equivalent (no thinking tokens).
- [ ] **Step 3: Run the check script on the box** — Expected: answer mentions the shark, matching `llama-server` on the same image; `dump`'s `encode_ms` ≈ the 3.3 s baseline.
- [ ] **Step 4: Commit** `core/tools/cortex-embd core/scripts/build_cortex_embd.sh core/scripts/check_cortex_embd.sh`, message `npu: cortex-embd tool (dump CPU image features, answer from features)`.

### Task 3: Compare features; check the ONNX encoder matches llama.cpp

**Files:**
- Create: `core/cortex_core/npu/compare.py`, `core/cortex_core/npu/onnx_ref.py`
- Test: `core/tests/test_npu_compare.py`

**Interfaces:**
- Consumes: `prepare` (Task 1), `FEAT.f32` + `FEAT.json` (Task 2).
- Produces: `load_feat(path: Path) -> numpy.ndarray[n_tokens, n_embd]`; `save_feat(path: Path, a: numpy.ndarray) -> None` (same format as Task 2); `cosine_rows(a, b) -> tuple[float, float]` (mean, min of per-token cosine; raises `ValueError` on shape mismatch); CLI `python -m cortex_core.npu.onnx_ref --onnx PATH --image IMG --out FEAT.f32` (CPU onnxruntime, prints encode ms).

- [ ] **Step 1: Failing tests** — `test_cosine_identical` (== (1.0, 1.0)); `test_cosine_catches_shuffled_tokens` (rows permuted → min < 0.9 for random data); `test_cosine_shape_mismatch_raises`; `test_feat_roundtrip` (save then load equal, json has n_tokens/n_embd).
- [ ] **Step 2: Run** — Expected: FAIL. **Step 3: Implement**. **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: On the box** — `apt` `python3-onnxruntime` is already available; run `onnx_ref` on `scene_640.jpg`, then `cosine_rows` against the Task 2 dump. Expected: same `[n_tokens, n_embd]` and mean cosine ≥0.99. If not: find the preprocessing difference (Task 1 contract) before going on; a remaining gap is a ruling with numbers.
- [ ] **Step 6: Commit** `core/cortex_core/npu core/tests/test_npu_compare.py`, message `npu: feature comparison and ONNX CPU reference`.

### Task 4: Calibration and test frames (with Haziq)

**Files:**
- Create: `core/scripts/npu/capture_frames.sh`
- Data (not git): `/var/lib/cortex/npu/calib/*.jpg` (~50), `/var/lib/cortex/npu/test/*.jpg` (≥10) + `/var/lib/cortex/npu/test/cases.json`

**Interfaces:**
- Produces: `capture_frames.sh <dir> <count> <interval_s>` grabbing 640x360 JPEGs from the ZV-1F (`/dev/video2`); `cases.json` = `[{"image": "t01.jpg", "question": "...", "expect": ["shark"], "light": "normal|low"}]`.

- [ ] **Step 1:** Write the script; run it with Haziq moving the camera: indoor, window light, outdoor-facing, and at least 10 low-light frames for calibration; ≥10 test frames (≥3 low-light) with a question and expected keywords each, written by Haziq or agreed with him.
- [ ] **Step 2:** Run every test case through `llama-server` CPU; keep only cases whose CPU answer contains its keywords (CPU is the bar). Expected: ≥10 kept.
- [ ] **Step 3: Commit** the script only.

### Task 5: Convert and quantise for v68 (Haziq's QAIRT / AI Hub)

**Files:**
- Create: `core/scripts/npu/convert_vision.md` (exact commands as run, tool versions), `core/scripts/npu/make_calib_raw.py`

**Interfaces:**
- Consumes: `prepare` (Task 1), calibration frames (Task 4), `vision_encoder.onnx`.
- Produces: `vision_v68.bin` (QNN context binary for HTP v68 / SC8280XP) on the box at `/var/lib/cortex/npu/`, plus the input/output tensor names it expects.

- [ ] **Step 1:** `make_calib_raw.py <calib_dir> <out_dir>` writes each prepared frame as raw float32 and an `input_list.txt` (QAIRT format). Unit test `test_make_calib_raw` (2 frames → 2 files of the exact byte size, list has 2 lines).
- [ ] **Step 2:** On the conversion host (QAIRT on PC/WSL, or AI Hub compile job for "Snapdragon 8cx Gen 3"): convert with the fixed input shape, quantise 8-bit weights / 16-bit activations with the calibration list, generate the v68 context binary. Record every command and version in `convert_vision.md`. Expected: a context binary; converter reports no unsupported ops (any unsupported op is a finding — record it and the fallback).
- [ ] **Step 3: Commit** `core/scripts/npu`, message `npu: vision encoder conversion for Hexagon v68`.

### Task 6: Run on the NPU, measure, write up

**Files:**
- Create: `core/cortex_core/npu/run_npu.py`, `docs/measurements/2026-11-npu-vision.md`
- Test: `core/tests/test_npu_run.py`

**Interfaces:**
- Consumes: `prepare`, `save_feat`, `cosine_rows`, `cortex-embd answer`, `vision_v68.bin`.
- Produces: `run_vision_npu(context: Path, image: Path, runs: int = 20) -> NpuRun` (`ok`, `error`, `median_ms`, `p90_ms`, `cpu_mhz`, `feat_path`); CLI `python -m cortex_core.npu.run_npu`. Uses the QNN runtime from `qcom-qnn-sdk-v68` (via `qnn-net-run` subprocess first; a direct binding only if the subprocess overhead hides the encode time — ruling).

- [ ] **Step 1: Failing tests** — `test_missing_context_is_clear_error` (non-existent context → `ok False`, error names the file, returns within 5 s); `test_missing_runtime_is_clear_error` (runtime binary absent → error names `qnn-net-run`/the package).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**. **Step 4: Run** — PASS.
- [ ] **Step 5: On the box** — Haziq runs `sudo apt install -y qcom-qnn-sdk-v68`. Then for every test frame: NPU encode timing (20 runs), cosine vs the CPU dump, `cortex-embd answer` with the NPU features; CPU temperature (CPU zones) and frequency during the loop.
- [ ] **Step 6: Write `docs/measurements/2026-11-npu-vision.md`** — setup (QAIRT/QNN versions, quant scheme), table per frame (normal / low light): CPU ms, NPU ms, cosine mean/min, CPU answer, NPU answer, match; summary vs the ≤300 ms and ≥0.98 targets; power if a meter was available, else "not measured"; what it means for approach B.
- [ ] **Step 7: Update** `core/AGENTS.md` (row + change log) and `docs/architecture/CORTEX-ENGINE.md` (Phase 2 status). **Commit** `core/cortex_core/npu core/tests/test_npu_run.py docs/measurements/2026-11-npu-vision.md core/AGENTS.md docs/architecture/CORTEX-ENGINE.md`, message `npu: vision encoder on Hexagon v68 via QNN, measured`.
