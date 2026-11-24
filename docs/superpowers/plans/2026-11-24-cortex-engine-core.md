# Cortex Engine Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One C++ library, `libcortex_engine.so`, that holds the LM (Q4_0, llama.cpp) and the NPU vision encoder, keeps the current view read into the LM before the user asks, and answers a typed question with only the question's tokens left to read.

**Architecture:** The C++ library has its own threads.
- A vision pipeline: prepare, then NPU segments via QNN, with ggml attention islands between them.
- An LM worker on cpu4-7 that owns four llama.cpp sequences (H, V, V', S). It reads images in the background in chunks and stops for an ask.
- A small C API for the `brain` process (ctypes) and a `cortex-engine` CLI for benches.

The Python NPU path (`SplitEncoder`) and `cortex-embd answer` are the accuracy oracles.

**Tech Stack:**
- C++17 and CMake on the box (g++, `/opt/llama.cpp/b12679`: llama, mtmd, ggml, plus the vendored nlohmann/json and stb).
- QNN 2.42 through the existing shim source `core/tools/cortex-npu/cortex_npu.cpp`.
- Python 3.14 ctypes for the binding.

**Spec:** `docs/superpowers/specs/2026-11-24-cortex-engine-core-design.md`

## Global Constraints

- One C++ runtime: LM + NPU vision in `libcortex_engine.so`, loaded into `brain`. C++, not Rust.
- LM: `LFM3-Omni-2B-Q4_0.gguf` + `mmproj-LFM3-Omni-2B-Q8_0.gguf`, 4 threads pinned to cpu4-7.
- The engine never runs on `safety`'s cores. The cpusets are config; defaults are LM `4-7` and vision `1-3`.
- The NPU is opened once per process lifetime. A second `ce_open` in the same process is refused.
- Frames are processed in flight only, never written to disk by the engine.
- No polling of the camera: the engine refreshes only on `ce_refresh` (cadence comes from the brain rules).
- Skip threshold: mean token cosine ≥ 0.98 to the current view's features (config `skip_cos`).
- Short answers: default `max_tokens` 60. The system prompt asks for one or two sentences.
- Port check: C++ vision features vs Python NPU features, per-frame mean cosine ≥ 0.999 on the 14 review frames;
  13/13 landscape answers; encode median ≤ 257 ms.
- Success: typed ask with V ready, first token ≤ 0.4 s median; view refresh ≤ 1.4 s; 12/12 cases through the engine.
- No weights, binaries, goldens or photos in git; goldens live in `/var/lib/cortex/bench/engine/golden/` on the box.
- Commit as IRSPlays (`git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit`), no Co-Authored-By. No push.
  Never touch uncommitted `apps/` work.

## Review Focus

1. **Ask while a background read is in progress.** The ask must start within one chunk (≤ ~0.35 s at 64 tokens),
   answer from the last complete V, and report that V's frame id and age. The half-read V' is dropped. Test in Task 5.
2. **Ask before any view exists.** It answers from H alone (text only) with `view_frame_id: -1`; no crash, no wait.
   Test in Task 5.
3. **History outgrowing the context.** Oldest turns are dropped, then H and V are rebuilt; asks keep working. Test
   in Task 5, with a forced small `max_history_tokens`.
4. **NPU or model missing at open, or a QNN execute failure mid-run.** `ce_open` returns NULL with a readable
   `ce_last_error()`. An execute failure emits an `error` event, the view stays the old one, and typed asks still
   work. Test in Task 3 (vision layer) and Task 6 (API).
5. **A second ask while one is streaming.** It is refused with an `error` event `"busy"`; the first is unaffected.
   `ce_cancel` stops the first within one token. Test in Task 6.

---

### Task 1: Engine scaffold, fixed-point and name matching

**Files:**
- Create: `core/tools/cortex-engine/CMakeLists.txt` (targets: `cortex_engine` shared lib, `cortex-engine` CLI,
  `engine_tests`; includes `${LLAMA_ROOT}/vendor` for nlohmann/stb; compiles `../cortex-npu/cortex_npu.cpp` into the
  lib; same LLAMA_ROOT/LLAMA_BUILD cache vars and RPATH as `tools/cortex-embd/CMakeLists.txt`)
- Create: `core/tools/cortex-engine/src/fixed.h`, `src/fixed.cpp`
- Create: `core/tools/cortex-engine/tests/check.h` (a minimal `CHECK(cond)` / `CHECK_NEAR(a,b,tol)` / test registry,
  `engine_tests [filter]` runs all tests or those matching filter; exit code = failures)
- Create: `core/tools/cortex-engine/tests/test_fixed.cpp`
- Create: `core/scripts/engine/box_build.sh` (PC → box: scp `core/tools/cortex-engine` and `core/tools/cortex-npu`
  to `/opt/cortex/tools/`, configure once, `cmake --build` in `/opt/cortex/build/cortex-engine`, then
  `engine_tests "$@"`)

**Interfaces:**
- Produces (`fixed.h`, namespace `ce`):
  - `enum class QType { F32 = 0x0232, U8 = 0x0408, U16 = 0x0416 };`
  - `void to_fixed(const float* x, size_t n, QType t, float scale, int offset, void* out);` — `q = round(x/scale) - offset`, clipped to the type's range (same as `qnn.py:to_fixed`).
  - `void from_fixed(const void* q, size_t n, QType t, float scale, int offset, float* out);` — `(q + offset) * scale`.
  - `std::string sanitize(const std::string& onnx_name);` — non-alnum → `_`, leading `_` stripped.
  - `std::vector<std::string> match_names(const std::vector<std::string>& qnn, const std::vector<std::string>& onnx);` — `qnn.py:match_names` semantics (throws `std::runtime_error` naming the unmatched name).

- [ ] **Step 1: Write the failing tests** in `test_fixed.cpp`:
  - `u16_round_trip`: x = {-1.5, 0, 0.25, 3.0}, scale 1/4096, offset -32768 → `from_fixed(to_fixed(x))` within scale/2 of x.
  - `u8_clips`: x = {-1e6, 1e6}, scale 0.01, offset -128 → q = {0, 255}.
  - `matches_python_values`: the exact q values `qnn.to_fixed(np.array([0.1, -0.2, 0.7], np.float32), UFIXED_16, 3.0517578e-05, -16384)` prints (compute once on the PC with `cortex_core.npu.qnn` and paste them as the expected array).
  - `sanitize_names`: `"/vision_encoder/layers.2/attn/Reshape_209"` → `"vision_encoder_layers_2_attn_Reshape_209"`.
  - `match_names_throws_on_missing`.
- [ ] **Step 2: Run to verify they fail.** Run: `sh core/scripts/engine/box_build.sh fixed`. Expected: build error (no `fixed.h`).
- [ ] **Step 3: Implement `fixed.cpp`** and the CMake targets (the lib may be only `fixed.cpp` for now).
- [ ] **Step 4: Run.** `sh core/scripts/engine/box_build.sh fixed` → Expected: `5 passed, 0 failed`.
- [ ] **Step 5: Commit** — `engine: scaffold, fixed-point and QNN name matching`.

---

### Task 2: Attention island in ggml

**Files:**
- Create: `core/tools/cortex-engine/src/island.h`, `src/island.cpp`
- Create: `core/tools/cortex-engine/tests/test_island.cpp`
- Create: `core/scripts/engine/make_goldens.py` (box, venv; writes `golden/island1_{q,k,v,out}.f32` by running the
  Python split chain on `test_review/t001.jpg` up to and including `cpu1`, and `golden/<stem>.pv.f32` = `prepare()`
  output for each of the 14 review frames)

**Interfaces:**
- Consumes: the island contract read from `cpu1.onnx` (verified 2026-11-24): inputs three `[1, 880, 16, 64]`
  tensors; ops `K→Transpose(0,2,3,1)`, `Q→Transpose(0,2,1,3)`, `MatMul`, `Mul 0.125`, `Softmax(-1)`,
  `V→Transpose(0,2,1,3)`, `MatMul`, `Transpose(0,2,1,3)`, `Reshape [1, 880, 1024]`. No mask.
- Produces:
  - `struct IslandIO { std::string q, k, v, out; };` (ONNX names, from a new `islands` block in `io.json`, written by `make_goldens.py --write-io` after reading each `cpu{k}.onnx` graph to see which input feeds which transpose)
  - `class Island { public: Island(int n_tok, int heads, int dim, float scale, const std::vector<int>& cpus, int n_threads); void run(const float* q, const float* k, const float* v, float* out); double last_ms() const; };` — one reused ggml context + threadpool (`ggml_threadpool_params.cpumask` from `cpus`, `strict_cpu`); `ggml_flash_attn_ext` with K/V cast to F16, scale 0.125.

- [ ] **Step 1: Write the failing tests** in `test_island.cpp`:
  - `island_matches_naive`: random q/k/v at [32, 4, 64] (seeded), compare to a plain C++ triple loop softmax(QKᵀ·s)V → max abs error ≤ 2e-3 (F16 K/V).
  - `island_matches_onnx_golden`: load `golden/island1_*`, run at [880, 16, 64] → cosine ≥ 0.9999 and max abs ≤ 1e-2.
  - `island_timing`: run the golden 10 times on `cpus={1,2,3}` and on `{4,5,6,7}`; print both medians (no assertion — this feeds the ruling below).
- [ ] **Step 2: Run to verify they fail.** First run `make_goldens.py` on the box. `box_build.sh island` → Expected: build error (no `island.h`).
- [ ] **Step 3: Implement `island.cpp`.**
- [ ] **Step 4: Run.** `box_build.sh island` → Expected: 2 passed + timing lines. If the ONNX golden test cannot
  reach cosine 0.9999 with F16 K/V, try F32 K/V. If that still fails, use the spec's fallback (onnxruntime C API for
  islands) and ledger the reason.
- [ ] **Step 5: Record the core ruling.** If islands on `1-3` take > 25 ms median (6 islands × 25 ms + ~156 ms NPU
  would miss the 257 ms encode bar), set the default island cpus to `4-7` and have the LM worker schedule them
  (Task 5's big-core queue runs island work before background LM chunks). Ledger it as a `Ruling:` with both
  medians either way.
- [ ] **Step 6: Commit** — `engine: ggml attention island (matches ONNX golden)`.

---

### Task 3: NPU vision encoder in C++ (the port check)

**Files:**
- Create: `core/tools/cortex-engine/src/vision.h`, `src/vision.cpp`
- Create: `core/tools/cortex-engine/tests/test_vision.cpp`

**Interfaces:**
- Consumes: `fixed.h` (Task 1), `Island` (Task 2), the shim's C API from `cortex_npu.cpp` (`cnpu_init`, `cnpu_load`,
  `cnpu_num_io`, `cnpu_io_info`, `cnpu_execute`, `cnpu_set_burst`, `cnpu_last_error`), `io.json` (incl. `islands`).
- Produces:
  - `class Vision { public: static std::unique_ptr<Vision> open(const std::string& split_dir, const std::string& qnn_lib_dir, const std::vector<int>& island_cpus, int island_threads, std::string* err); bool encode(const float* pixel_values, std::vector<float>* features, std::string* err); int n_tokens() const; int n_embd() const; const std::map<std::string,double>& last_ms() const; };`
  - `open` returns null with `*err` set when the dir, `io.json`, a `npu*.bin`, or `libQnnHtp.so` is missing; a second `open` in the same process returns null with `"NPU already opened in this process"`.
  - `encode` runs stages in order exactly as `SplitEncoder.encode`: a name→buffer map, NPU stage = quantise each input to its QNN tensor type, execute, dequantise outputs (names bound with `match_names`), island stage = `Island::run`. Output `image_features` [220 × 2048]. Buffers are allocated once at `open`.

- [ ] **Step 1: Write the failing tests** in `test_vision.cpp`:
  - `open_missing_dir_is_clear_error`: `open("/nope", ...)` → null, err contains `/nope`.
  - `open_twice_refused` (runs after a successful open in the same test binary process).
  - `port_check`: for each `golden/<stem>.pv.f32` of the 14 review frames, encode and compare to
    `/var/lib/cortex/bench/npu/test_review/<stem>.npu.f32` (Python NPU features) → per-frame mean cosine ≥ 0.999 on
    the 13 landscape frames; print per-frame cosine, encode median of 10, and `last_ms` per stage. (`p001_portrait`
    is printed, not asserted: out of scope.)
- [ ] **Step 2: Run to verify they fail.** `box_build.sh vision` → Expected: build error.
- [ ] **Step 3: Implement `vision.cpp`.**
- [ ] **Step 4: Run.** `box_build.sh vision` → Expected: 3 passed; encode median printed ≤ 257 ms. If the median
  misses, the failure output lists `last_ms` per stage. Fix the hot stage (it is code, not the plan) before moving on.
- [ ] **Step 5: Commit** — `engine: NPU vision encoder in C++ (port check vs Python features)`.

---

### Task 4: Frame preparation in C++

**Files:**
- Create: `core/tools/cortex-engine/src/prep.h`, `src/prep.cpp`
- Create: `core/tools/cortex-engine/tests/test_prep.cpp`

**Interfaces:**
- Produces: `bool prepare(const uint8_t* rgb, int w, int h, int canvas_w, int canvas_h, float* out, std::string* err);`
  — the `vision_prep.prepare` contract: fit inside the canvas keeping aspect (stretch a < 32 px leftover, else
  centre-pad with 0.0), bicubic resize, `(x/255 - 0.5)/0.5`, block layout `[ch/32, cw/32, 2, 2, 1536]` with the frame
  repeated in both time slots. Refuses w or h ≤ 0, and a canvas not a multiple of 32.
  Resize = PIL's BICUBIC (separable, a = -0.5, support scaled by the downscale factor), so the output tracks Python.

- [ ] **Step 1: Write the failing tests:**
  - `prepare_matches_python`: decode each review JPEG with stb_image, `prepare` → vs `golden/<stem>.pv.f32`: max abs
    ≤ 0.02, mean abs ≤ 0.002.
  - `prepare_end_to_end`: `prepare` + `Vision::encode` on `t001`, `t008` → cosine ≥ 0.998 to the Python NPU features.
  - `prepare_refuses_bad_input`: w = 0 → false, err set; canvas 650×352 → false.
- [ ] **Step 2: Run to verify they fail.** `box_build.sh prep` → build error.
- [ ] **Step 3: Implement `prep.cpp`.**
- [ ] **Step 4: Run.** `box_build.sh prep` → Expected: 3 passed; print prepare ms (expect ≤ 15 ms for 640×360).
- [ ] **Step 5: Commit** — `engine: frame preparation (matches vision_prep)`.

---

### Task 5: LM worker with slots, background read and ask

**Files:**
- Create: `core/tools/cortex-engine/src/lm.h`, `src/lm.cpp`
- Create: `core/tools/cortex-engine/tests/test_lm.cpp`

**Interfaces:**
- Consumes: llama.cpp + mtmd (`llama_memory_seq_cp`, `llama_memory_seq_rm`, `llama_set_abort_callback`,
  `mtmd_tokenize`, `mtmd_helper_eval_chunk_single`, `mtmd_helper_decode_image_chunk` with `seq_id`).
- Produces:
  - `struct LmConfig { std::string model, mmproj, system_prompt; std::vector<int> cpus = {4,5,6,7}; int n_ctx = 4096; int chunk = 64; int max_history_tokens = 1536; };`
  - `struct AskResult { std::string text; double ttft_ms, total_ms; int n_out; long view_frame_id; double view_age_ms; bool cancelled; };`
  - `class Lm { public: static std::unique_ptr<Lm> open(const LmConfig&, std::string* err); bool read_view(const float* features, int n_tok, long frame_id, std::string* err); AskResult ask(const std::string& q, int max_tokens, const std::function<void(const std::string&)>& on_token); void cancel(); void reset_history(); double copy_ms() const; int history_tokens() const; };`
  - Slots: seq 0 = H, 1 = V, 2 = V', 3 = S. `read_view` builds V' = copy(H) + user-turn prefix + image (chunked by
    `chunk`), then swaps V'↔V ids. An ask sets the abort flag; a read in progress returns false with
    `"preempted"` and V' is cleared. `ask` = copy(V or H)→S, read question suffix, greedy generate, then append the
    Q/A text turn to H (image not kept in history), then trigger a rebuild of V from H + the last features.
  - Prompt pieces come from the same chat template as `cortex-embd` (`chat_prompt`), split at the media marker:
    prefix (before marker) goes into V, suffix (`"\n" + q + end-of-turn + assistant start`) at ask time.

- [ ] **Step 1: Write the failing tests** (`test_lm.cpp`, Q4_0 model, features from `npu_run2/t001.npu.f32`, empty history, system prompt = the one `cortex-embd` uses):
  - `ask_matches_cortex_embd`: `read_view(t001)` then `ask("What is the large toy in front of me? One sentence.", 60)` → text equals the `cortex-embd answer -t 4` output for the same features, model and prompt (run it from the test via `popen`).
  - `ask_ttft_with_view_ready`: median ttft of 5 asks ≤ 400 ms; print median and `copy_ms()`.
  - `ask_preempts_background_read`: start `read_view(t008)` on a thread, ask after 200 ms → ask returns with `view_frame_id` = t001's id, ttft ≤ 400 + chunk time; `read_view` returned false `"preempted"`.
  - `ask_without_view`: fresh `Lm`, ask → non-empty text, `view_frame_id == -1`.
  - `history_overflow_drops_oldest`: `max_history_tokens = 64`, ask 4 times → all return text; `history_tokens() <= 64`.
- [ ] **Step 2: Run to verify they fail.** `box_build.sh lm` → build error.
- [ ] **Step 3: Implement `lm.cpp`.**
- [ ] **Step 4: Run.** `box_build.sh lm` → Expected: 5 passed. If ttft misses 400 ms, print the split (copy, question
  read, first sample) and ledger it, without loosening the test. If the miss is `copy_ms > 50`, apply the spec's
  fallback (answer directly in V, rebuild V afterwards) and rerun.
- [ ] **Step 5: Commit** — `engine: LM slots, background view read with preemption, ask`.

---

### Task 6: C API, scheduler, skip check, CLI

**Files:**
- Create: `core/tools/cortex-engine/include/cortex_engine.h`, `src/engine.cpp`, `src/cli.cpp`
- Create: `core/tools/cortex-engine/tests/test_api.cpp`

**Interfaces:**
- Consumes: `Vision` (Task 3), `prepare` (Task 4), `Lm` (Task 5).
- Produces (C, `extern "C"`):
  - `typedef void (*ce_event_cb)(const char* json_line, void* user);`
  - `void* ce_open(const char* config_json, ce_event_cb cb, void* user);` / `const char* ce_last_error(void);`
  - `int ce_push_frame(void* h, const uint8_t* rgb, int w, int hgt, long frame_id);` (copies into a one-slot latest-frame buffer, returns immediately)
  - `int ce_refresh(void* h);` (queue: prepare → encode → skip check → `read_view`; returns immediately)
  - `int ce_ask(void* h, const char* text, int max_tokens);` (returns immediately; `-1` + `error {"busy"}` event if an ask is running)
  - `int ce_cancel(void* h); int ce_reset_history(void* h); const char* ce_status(void* h); void ce_close(void* h);`
  - Events (one JSON object per callback): `{"type":"token","text":…}`, `{"type":"done","ttft_ms":…,"total_ms":…,"n_out":…,"view_frame_id":…,"view_age_ms":…,"cancelled":…}`, `{"type":"view","frame_id":…,"skipped":…,"cos":…,"prep_ms":…,"encode_ms":…,"read_ms":…}`, `{"type":"error","what":…}`.
  - Config JSON keys: `model, mmproj, split_dir, qnn_lib_dir, system_prompt, lm_cpus, vision_cpus, island_cpus, skip_cos (0.98), max_tokens (60), max_history_tokens`.
  - `ce_status` includes each engine thread's name, TID and CPU affinity mask (from `sched_getaffinity`).
  - Threads: control/vision thread on `vision_cpus`, LM worker on `lm_cpus`. If Task 2's ruling moved the islands to
    the big cores, the LM worker runs them from its queue with priority ask > island > background read.
  - CLI: `cortex-engine --config C.json --frames DIR --ask "…" [--repeat N]` pushes each JPEG (stb_image), refreshes,
    waits for its `view` event, asks, and prints every event line.

- [ ] **Step 1: Write the failing tests** (`test_api.cpp`):
  - `open_bad_config_is_error`: missing `split_dir` → NULL, `ce_last_error()` names it.
  - `refresh_then_ask_events`: push t001, refresh → one `view` (skipped false), ask → ≥ 1 `token` then `done` with `view_frame_id` = t001's id.
  - `same_frame_is_skipped`: push t001 again, refresh → `view` with `skipped: true`, `cos ≥ 0.98`, no `read_ms`.
  - `second_ask_busy_and_cancel`: ask; immediately ask again → `error busy`; `ce_cancel` → `done` with `cancelled: true` within 100 ms.
  - `npu_execute_failure_keeps_typed_asks` (fault injection: config `fail_encode_after: 1`, test-only key, ignored when absent) → `error` event on the second refresh, view frame id unchanged, a following ask still gets `done`.
  - `threads_stay_off_safety_cores`: `ce_status` affinities ⊆ configured sets and never include cpu0.
- [ ] **Step 2: Run to verify they fail.** `box_build.sh api` → build error.
- [ ] **Step 3: Implement `engine.cpp` and `cli.cpp`.**
- [ ] **Step 4: Run.** `box_build.sh api` → Expected: 6 passed. Then the whole binary: `box_build.sh` → all tests pass.
- [ ] **Step 5: Commit** — `engine: C API, scheduler, scene-skip, CLI`.

---

### Task 7: Python binding, 12-case bench, write-up

**Files:**
- Create: `core/cortex_core/engine/native.py`, `core/cortex_core/engine/native_bench.py`
- Create: `core/tests/test_engine_native.py`
- Create: `docs/measurements/2026-11-engine-core.md`
- Modify: `core/AGENTS.md` (status row + change-log line), `docs/architecture/CORTEX-ENGINE.md` (Phase 2 status)

**Interfaces:**
- Consumes: the C API (Task 6).
- Produces:
  - `native.parse_event(line: str) -> dict` (validates `type` ∈ {token, done, view, error}; raises `ValueError` otherwise)
  - `class Engine: __init__(self, lib: str | Path, config: dict)`; `push_frame(rgb: np.ndarray, frame_id: int)`; `refresh()`; `ask(text: str, max_tokens: int = 60) -> Iterator[dict]` (yields token events, ends with done or error); `cancel()`; `status() -> dict`; `close()`. Events cross from the C callback into a `queue.Queue`; the callback holds the GIL only to enqueue.
  - `python -m cortex_core.engine.native_bench --lib … --config … --cases …/test/cases.json --out results.json` runs push → refresh → wait for view → ask, once per case. Rows: answer, match (the `expect` keywords), ttft_ms, view encode/read ms, view age. It prints `matched N/12`.

- [ ] **Step 1: Write the failing tests** (`test_engine_native.py`, run on Windows without the lib):
  - `test_parse_event_types`, `test_parse_event_rejects_unknown_type`.
  - `test_engine_missing_lib_is_clear_error` (`Engine("nope.so", {})` → `OSError` naming the path).
  - `test_bench_row_from_events` (feed a canned event list into the bench's row builder → match, ttft_ms, view fields).
- [ ] **Step 2: Run to verify they fail.** `python -m pytest core/tests/test_engine_native.py -q` → ModuleNotFoundError.
- [ ] **Step 3: Implement `native.py` and `native_bench.py`.**
- [ ] **Step 4: Run.** `python -m pytest core/tests -q` → new tests pass; only the 2 pre-existing Windows-only failures.
- [ ] **Step 5: Box bench.** `native_bench` on the 12 cases. Expected: `matched 12/12`; ttft median ≤ 400 ms; view
  refresh (prep + encode + read) median ≤ 1.4 s. Also measure peak RSS (`/proc/<pid>/status` VmHWM) and
  `ce_status` affinities.
- [ ] **Step 6: Write `docs/measurements/2026-11-engine-core.md`**: tables for the port check, island timing and core
  ruling, ttft split, refresh split, skip rate on a still scene, RSS, and affinities. Then the honest caveats (typed
  questions only, 12 frames, no power meter, tool calls untested on Q4_0). Check every cell against the pulled JSON
  with a scratchpad script.
- [ ] **Step 7: Commit** — `engine: Python binding, 12-case bench, measurements`.
