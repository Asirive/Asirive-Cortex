# Step 2 of the parallel engine: the engine core (design)

Order approved by Haziq on 2026-11-24 (engine approach A, "go in that order"):
1. Quick speed tests (done, `docs/measurements/2026-11-speedups.md`).
2. **Engine core** (this document).
3. Hands-free mode with streaming audio in.
4. Speech output in parallel.

Layout decided by Haziq on 2026-11-24: **B**, one C++ runtime holding the LM, the NPU vision encoder and (in
step 3) the audio encoder. C++, not Rust. Standing rule: choose the most efficient design for the end goal, not the
simplest one. Build it in stages, each checked against a version that already works.

## Why

Today a question about the view takes 2.3 s to the first word (1.23 s with Q4_0 on 4 cores), almost all of it the
LM reading 220 image tokens after the question arrives. The target is first audio < 1 s after the question ends.

The engine moves that work earlier. The image is encoded and read into the LM's memory *before* the question ends,
so at ask time only the question's tokens remain. Every stage that can overlap with another does.

## Goals

1. **Image ready before the ask.** On a trigger, the engine runs the image pipeline in the background and keeps the
   result ready for questions:
   - the NPU encodes the frame;
   - the LM reads it into a spare memory slot;
   - the slot is swapped in when complete.

   Triggers are listening starting, mode cadence, or an explicit refresh.
2. **Ask costs only the question.** An ask copies the ready slot and reads the question tokens. The answer
   streams token by token with timestamps.
3. **One runtime.** The LM (llama.cpp, Q4_0, 4 threads on cpu4-7) and the NPU vision encoder live in one
   C++ library, ported from today's Python split encoder.
4. **Skip unchanged views.** If a new frame's features are near-identical to the slot's (mean token cosine
   ≥ 0.98, tunable), the LM read is skipped.
5. **Short answers by default.** The system prompt asks for one or two sentences; the default max is 60 tokens.
6. **Measured, not guessed.** The engine timestamps every stage: frame in, encode done, read done, ask, first token,
   last token. A bench CLI reruns the 12 cases through it.

## Non-goals (this step)

- Audio in (step 3) and speech out (step 4). The API leaves room for both.
- Gemini switch, tools execution, navigation logic. Those stay in the brain's Python layer.
- The 112-token canvas. It becomes a flag once this exists.
- LM on the NPU (Phase 2 backbone).

## Constraints

- **Safety first.** `safety` keeps its own pinned cores and `SCHED_FIFO` (core/AGENTS.md §3). The engine never runs
  on them. LM threads go on cpu4-7. The engine's other threads (NPU driver, attention islands) go on the cores left
  over after `safety`'s set. `check` (YOLO-World) is normal priority and may wait.
- **NPU opened once per process lifetime.** It is never closed and reopened in quick succession: that reset the box
  (fastrpc unmap error, 2026-11-24).
- **Frames processed in flight only.** Never stored.
- **Vision cadence comes from the brain rules** (AGENTS.md §3a): IDLE refreshes only while the user speaks,
  INDOOR_NAV every 1 s, OUTDOOR_NAV about every 2 s. The engine refreshes on request and does not poll the camera
  on its own. This keeps idle power low.
- **Camera must be 16:9**, or be recalibrated (`docs/measurements/2026-11-npu-vision.md`).
- **Housekeeping.**
  - No weights, binaries, calibration data or photos in git.
  - Commits as IRSPlays, with no Co-Authored-By line.
  - No pushes unless asked.

## Approaches

| | Layout | Trade-off | Status |
|:---|:---|:---|:---|
| A | C++ LM engine + the existing Python NPU process, joined by shared memory | Fastest to a first number, but two runtimes forever | Rejected by Haziq: not the end state |
| **B** | **One C++ runtime: LM + NPU vision (+ audio in step 3)** | The NPU port is real work, but there are no hand-offs, one thread plan and zero-copy features | **Chosen** |

How B is packaged, which is my call: **`libcortex_engine.so` with a small C API, loaded into the `brain` process.**
The engine runs its own C++ threads and Python only calls in and receives events. This keeps the approved "voice,
perception and agent are one process" rule (AGENTS.md §2) with no socket on the hot path. A thin `cortex-engine`
CLI links the same library for benches.

The rejected alternative was a separate engine daemon behind a socket. That adds a process hop on every token and a
second supervisor target.

How the attention islands are ported, also my call: the 6 CPU attention parts (Q·Kᵀ, softmax, P·V) are written
with **ggml**, which llama.cpp already links, instead of the onnxruntime C API.
- This drops a ~20 MB dependency and a second thread pool competing with llama's.
- onnxruntime stays as the test reference only.
- If ggml cannot match it (cosine below the bar), fall back to the onnxruntime C API and record why.

## Design

### Memory slots (llama.cpp sequences)

LFM3 is a hybrid model (convolution and attention layers). llama.cpp can copy a sequence's whole state but cannot
rewind it, as verified in `llama-memory-recurrent.cpp`. So the engine never rewinds. It keeps clean slots and
answers in copies.

| Slot | Holds | Changes when |
|:---|:---|:---|
| H | system prompt + tool definitions + conversation so far | after each answer: the Q and A text is appended (tens of tokens) |
| V | H + current view image | swapped in when a background read finishes |
| V' | H + next view image (being built) | background read in progress |
| S | scratch: V + question + answer | every ask (copied from V) |

- Prompt order follows the chat template, where the image marker comes before the question:
  `[system][history][user: <image> question][assistant: …]`.
- After an answer, H grows by that turn. V is then stale, because its history is old. It is rebuilt from H plus the
  last image features, with no NPU needed: one LM read, ~1.05 s, in the background.
- Context: n_ctx 4096 shared, with history capped by the builder's rule (oldest turns dropped, which means
  rebuilding H).

### Threads and cores

| Thread | Cores | Job |
|:---|:---|:---|
| LM (llama.cpp pool, 4 threads) | cpu4-7 | background reads, question reads, generation |
| Vision driver | non-`safety` small core | quantise → NPU segment → attention island → … per frame |
| Attention islands (ggml, 2-3 threads) | non-`safety` small cores | the 6 CPU parts of the vision encoder |
| Control | any | API calls, scheduling, events |

**Pipelining:** frame N+1 can encode on the NPU and small cores while frame N is read by the LM on the big cores.

**Ask always wins.** Background reads go in chunks of 64 tokens, and the ask flag is checked between chunks. llama's
abort callback is the fallback. On an ask, the background read stops and the answer uses the last *complete* V,
whose age the result reports. Nothing waits behind background work.

### API (C, used from Python via ctypes)

- `ce_open(config_json) -> handle`: loads the model, mmproj, NPU binaries and system prompt; builds H. This is the
  only NPU open.
- `ce_push_frame(h, rgb, w, h, frame_id)`: non-blocking. Keeps the newest frame only.
- `ce_refresh(h)`: encode the newest frame, skip-check it, and read it into V'.
- `ce_ask(h, text, max_tokens, on_event)`: streams token events, then a done event with timings.
- `ce_cancel(h)`, `ce_reset_history(h)`, `ce_status(h) -> json`, `ce_close(h)`.
- Events are JSON lines: `token`, `done {ttft_ms, n_out, view_age_ms, view_frame_id}`,
  `view {frame_id, skipped, encode_ms, read_ms}`, and `error`.

### Port check (stage gate for the NPU part)

The C++ vision path must reproduce the Python `SplitEncoder` on the 14 review frames:
- per-frame mean cosine ≥ 0.999 to the Python NPU features (same binaries, same quantisation);
- answers 13/13 on landscape frames;
- encode median ≤ the Python path's 257 ms.

## Build order inside step 2

Each stage ends with a measurement.
1. **LM core.** Slots H/V/V'/S, background read with preemption, ask, events and timings. Images come from the
   saved NPU features. Measure ask → first token with V ready, and history rebuild time.
2. **NPU port.** Quantise/dequantise plus the QNN calls (reusing `libcortex_npu.so` code) plus ggml attention
   islands. Pass the port check above.
3. **Frames in, skip check.** `ce_push_frame`/`ce_refresh` end to end from a JPEG sequence; measure skip rate on a
   still scene.
4. **Python binding and bench CLI.** ctypes wrapper in `cortex_core/engine/`, plus the 12 cases through the engine.

## Success criteria

- Typed question with V ready: **first token ≤ 0.4 s** median (estimate today, ~15-30 question tokens at Q4_0
  prompt speed). If it misses, the doc says where the time went.
- Full view refresh (frame → V ready): ≤ 1.4 s on 4 big cores, with NPU encode overlapped.
- 12/12 test answers through the engine.
- `safety`'s cores never used by the engine (checked with per-thread affinity in `ce_status`).
- Peak RSS reported (model + mmproj + 4 slots + NPU).

## Left to the builder

- The exact ggml graph for the attention islands.
- History cap and system prompt wording (short answers).
- Which small cores the vision threads get, once `safety`'s cpuset is fixed. The default is cpu1-3, with cpu0 left
  to the OS and `safety`.
- Event delivery from C++ threads to Python: a callback, or a queue polled with the GIL released.

## Risks

- **Slot copy cost.** Copying V to S for hybrid memory should be cheap, but it is unmeasured. If it costs more than
  ~50 ms, answer straight from V and rebuild V afterwards.
- **Q4_0 on text and tool calls is untested.** Stage 1 re-checks typed questions; tool calls are re-checked when the
  brain wires them in.
- **ggml island accuracy.** The onnxruntime C API is the fallback, with the reason recorded.
