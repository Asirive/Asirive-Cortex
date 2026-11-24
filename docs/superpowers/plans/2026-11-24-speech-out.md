# Speech out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cortex speaks every answer in LFM3-Omni's own voice on the headphone jack while it generates, with the codec,
playback and vision encoding running in parallel on the small cores.

**Architecture:** Our own port of llama.cpp's LFM3 MIXED loop runs on the engine's LM context (seq 3, big cores).
Each audio frame's 12 codes go to a codec thread that owns a second mtmd context on cpu3 and turns them into PCM; PCM
goes into a speaker ring played through ALSA (dlopen) by a writer thread. While an answer holds the big cores the
vision islands run on a small-core pool. The engine mutes the mic from answer start to the end of playback.

**Tech Stack:** C++17, llama.cpp b12679 (`llama`, `mtmd`, `ggml`), libasound.so.2 via dlopen, nlohmann/json, Python
ctypes binding, Textual TUI.

**Spec:** `docs/superpowers/specs/2026-11-24-speech-out-design.md`

## Global Constraints

- Box: radxa@192.168.0.228, llama.cpp pinned at `/opt/llama.cpp/b12679`. Build + C++ tests: from the repo root on the
  PC, `bash core/scripts/engine/box_build.sh <filter>` (copies sources, builds, runs `engine_tests <filter>`).
- Cores: cpu0 never used (safety). LM on cpu4-7. Codec + speaker on `codec_cpus`/`speaker_cpus` [3]. Small-pool
  islands on `island_small_cpus` [1, 2].
- Audio out: 24 kHz mono; one frame = 12 codes = 80 ms. MIXED blocks: 6 text tokens / 12 audio frames.
- Config defaults (verbatim from the spec): `speak` true, `voice` "female", `speaker_device` "plughw:0,0", `ucm_card`
  "hw:0", `ucm_verb` "HiFi", `ucm_device` "Headphones", `mixer` {"HPHL Volume": 20, "HPHR Volume": 20}, `prebuffer_ms` 200,
  `mute_tail_ms` 300, `max_speech_s` 30, `codec_cpus` [3], `codec_threads` 1, `speaker_cpus` [3],
  `island_small_cpus` [1, 2], `codec_inline` false.
- Adaptive prebuffer: +100 ms after an answer with an underrun (cap 800), −50 ms after 3 gapless answers (floor
  `prebuffer_ms`).
- Voice line appended to the system prompt: `Speak using a female voice.`
- No ALSA headers: declare the used libasound prototypes locally; `dlopen("libasound.so.2")`.
- Open the NPU once per process. Never commit SDK files, weights, goldens, test media or WAVs.
- Commits: `git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit`, no co-author line, explicit `git add`
  paths only (never the user's uncommitted `apps/`, `infra/`, `cortex.py`, `.gitignore`, `CLAUDE.md`). No push.

## Review Focus

1. Cancel (space) while frames are still queued in the codec thread: playback must stop at once and the next answer
   must not start with the old answer's tail (codec state reset, ring cleared) — pinned in Task 3 and Task 5.
2. An answer that is all text then `<|im_end|>` with zero audio frames (model ends before any audio): no `sound_start`,
   a `sound_end` with sound_ms 0, mic unmuted after the tail — pinned in Task 5.
3. Speaker device that fails to open (card busy / wrong name): engine still opens, error event, answers in text,
   mic gate still lifts at done + tail — pinned in Task 5.
4. A typed ask arriving while the previous answer is still playing out (generation done, ring not empty): it must cut
   the old playback, not queue behind it — pinned in Task 5.
5. `max_speech_s` reached mid-sentence: stops with stop="max", transcript so far goes to history, the next turn's
   position is consistent (`pos_[3]` re-synced) — pinned in Task 2.

---

### Task 1: Speaker (ring, adaptive prebuffer, sinks, ALSA via dlopen)

**Files:**
- Create: `core/tools/cortex-engine/src/speaker.h`, `core/tools/cortex-engine/src/speaker.cpp`
- Test: `core/tools/cortex-engine/tests/test_speaker.cpp`

**Interfaces:**
- Produces:
  ```cpp
  namespace ce {
  struct SpeakerConfig {
      std::string device = "plughw:0,0", ucm_card = "hw:0", ucm_verb = "HiFi", ucm_device = "Headphones";
      std::vector<std::pair<std::string, int>> mixer = {{"HP Volume", 20}};
      int prebuffer_ms = 200, rate = 24000;
      std::vector<int> cpus = {3};
  };
  class Sink {  // blocking writer, like ALSA
  public:
      virtual ~Sink() = default;
      virtual int write(const int16_t* s, int n) = 0;  // frames written; < 0 = underrun (recovered by the sink)
      virtual void drop() = 0;                          // discard what the device still holds
  };
  // "null" (paced at real time, counts frames), "wav:<path>" (writes a 24 kHz mono 16-bit WAV, paced), else ALSA.
  std::unique_ptr<Sink> open_sink(const SpeakerConfig& c, std::string* err);
  struct SoundEvent { std::string type; double at_ms = 0, sound_ms = 0; int gaps = 0; bool cut = false; };
  class Speaker {
  public:
      Speaker(const SpeakerConfig& c, std::unique_ptr<Sink> sink, std::function<void(const SoundEvent&)> on_event);
      ~Speaker();
      void begin();                       // new answer (cuts any audio still playing, as stop())
      void push(const float* pcm, int n); // float [-1, 1] at 24 kHz
      void end();                         // this answer's audio is complete; play out and emit sound_end
      void stop();                        // cut now: drop ring + device, sound_end{cut:true}
      bool playing() const;               // between sound_start and sound_end
      int prebuffer_ms() const;           // current adaptive value
  };
  }
  ```
  `at_ms` is milliseconds on `std::chrono::steady_clock` since its epoch (same clock the engine uses for speech_end).

- [ ] **Step 1: Write the failing tests** in `tests/test_speaker.cpp` with a `FakeSink` (speed factor; records written
  samples; can be told to report one underrun):
  - `speaker_waits_for_prebuffer`: config prebuffer 200 ms; push 150 ms → no `sound_start` after 100 ms; push 100 ms
    more → `sound_start` within 50 ms; `end()` → `sound_end` with `sound_ms` within ±5 of 250, `gaps == 0`.
  - `speaker_short_answer_plays_on_end`: push 80 ms then `end()` → plays (sound_start, sound_end sound_ms ≈ 80).
  - `speaker_zero_audio_answer`: `begin(); end();` → no sound_start, one sound_end with sound_ms 0, cut false.
  - `speaker_stop_cuts_now`: push 2 s at 1x, wait for sound_start, `stop()` → sound_end within 50 ms, `cut == true`,
    sink got < 1 s of samples, `playing() == false`.
  - `speaker_begin_cuts_previous`: push 2 s, `begin()` → previous answer's sound_end has `cut == true`.
  - `speaker_dry_ring_counts_gap_and_grows_prebuffer`: push 200 ms, wait 400 ms, push 200 ms, end → `gaps == 1`;
    `prebuffer_ms() == 300`. Three gapless answers later → `250`. Cap: after 7 gap answers → `800`.
  - `speaker_wav_sink_writes_valid_file`: `open_sink({device:"wav:/tmp/ce_spk.wav"})`, push 0.5 s of a 440 Hz sine,
    end, destroy → file size == 44 + 24000 bytes, header rate 24000, 1 channel, 16 bits.
  - `speaker_float_to_s16_clips`: push values 2.0 and −2.0 → sink receives 32767 and −32768 (or −32767).
- [ ] **Step 2: Run to verify they fail**
  Run: `bash core/scripts/engine/box_build.sh speaker`
  Expected: build fails, `speaker.h` not found.
- [ ] **Step 3: Implement `speaker.{h,cpp}`.** Ring: float `std::vector` of 30 s at 24 kHz with head/tail under a
  mutex + cv; writer thread pinned to `cpus` writes 20 ms periods (480 frames) once `buffered ≥ prebuffer` or ended.
  A dry ring after sound_start and before `end()` = one gap; the writer waits for data (the device underruns; ALSA
  sink recovers with `snd_pcm_recover`). ALSA sink: `dlopen("libasound.so.2")`, local prototypes for
  `snd_pcm_open/set_params/writei/recover/drop/drain/close`, `snd_use_case_mgr_open/set/close`,
  `snd_ctl_open/close`, `snd_ctl_elem_value_*`, `snd_ctl_elem_id_*`, `snd_ctl_elem_write` (`_malloc`/`_free`
  variants since sizes are unknown without headers). Open order: UCM (`_verb`, `_enadev`) → mixer values → pcm
  `set_params(SND_PCM_FORMAT_S16_LE=2, SND_PCM_ACCESS_RW_INTERLEAVED=3, 1, 24000, soft_resample 1, 80000 us)`.
  A UCM or mixer failure is not fatal (logged into `*err` only if the pcm open also fails).
- [ ] **Step 4: Run** `bash core/scripts/engine/box_build.sh speaker` — Expected: all `speaker_*` PASS.
- [ ] **Step 5: By-ear smoke** on the box: add `engine_tests` filter `speaker_alsa_tone` (skipped unless env
  `CE_SPEAKER_DEVICE` is set) that plays 1 s of 440 Hz through the ALSA sink. Run with
  `CE_SPEAKER_DEVICE=plughw:0,0`; Expected: PASS and a tone in the headphones (ask Haziq), `gaps == 0`.
- [ ] **Step 6: Commit** `src/speaker.h src/speaker.cpp tests/test_speaker.cpp` — "engine: speaker ring with
  adaptive prebuffer, ALSA via dlopen".

### Task 2: LFM3 MIXED speech loop on the LM (codec inline)

**Files:**
- Create: `core/tools/cortex-engine/src/speech.h`, `core/tools/cortex-engine/src/speech.cpp`
- Modify: `core/tools/cortex-engine/src/lm.h` (LmConfig + AskResult fields, `on_pcm` hook), `src/lm.cpp`
  (`open`: speech setup; `generate`: speak path)
- Test: `core/tools/cortex-engine/tests/test_speech.cpp`

**Interfaces:**
- Produces:
  ```cpp
  namespace ce {
  class Codec {  // codes -> PCM on one mtmd context (stateful ISTFT)
  public:
      static std::unique_ptr<Codec> open(mtmd_context* ctx, std::string* err);  // borrows ctx, own gen_state
      bool decode(const int32_t* codes, std::vector<float>* pcm);  // 12 codes -> 1920 samples appended
      bool flush(std::vector<float>* pcm);                         // tail (GEN_WAV with no codes); then reset
      void reset();
      double last_ms() const;
  };
  struct SpeakIo {
      std::function<void(const std::string&)> on_token;          // shown text pieces (control tokens hidden)
      std::function<void(const int32_t* codes)> on_frame;        // 12 codes per audio frame
      std::function<bool()> cancelled;
  };
  struct SpeakResult { std::string text; int n_text = 0, frames = 0; double frame_ms = 0; std::string stop; };
  // Runs the MIXED loop on `seq` from `*pos` (the assistant header already decoded); advances *pos.
  SpeakResult speak_mixed(llama_context* lctx, mtmd_context* mctx, llama_sampler* text_sampler, int seq, int* pos,
                          int max_tokens, int max_frames, uint32_t seed, const SpeakIo& io);
  }
  ```
  `LmConfig` gains `bool speak = false; std::string voice = "female"; int max_speech_s = 30; bool codec_inline = true;
  uint32_t seed = 0;` (0 = new seed per answer) and
  `std::function<void(const float* pcm, int n, bool end)> on_pcm;` (end=true: answer audio complete, n may be 0).
  `AskResult` gains `int frames = 0; double frame_ms = 0, codec_ms = 0, sound_ms = 0;` (`sound_ms` = frames × 80).
- Consumes: nothing from Task 1 (Lm calls `on_pcm`; the engine wires it to the Speaker in Task 5).

- [ ] **Step 1: Write the failing tests** in `tests/test_speech.cpp` (box model files from `api_test::config()`):
  - `speech_matches_helper_golden`: same prompt (`<|im_start|>system\nSpeak using a female voice.<|im_end|>\n
    <|im_start|>user\nSay hello in one short sentence.<|im_end|>\n<|im_start|>assistant\n`), seed 1234, on two fresh
    contexts: (a) llama.cpp `mtmd_helper_gen_audio` in MIXED mode collecting text + PCM; (b) `speak_mixed` +
    `Codec::decode`/`flush`. CHECK identical text, identical frame count, and max |pcm_a − pcm_b| ≤ 1e-4.
    (Read `tools/mtmd/mtmd-helper.h` in b12679 for the helper's exact signature and output callback.)
  - `speech_lm_answer_speaks`: `Lm` with `speak = true`, `codec_inline = true`, `on_pcm` collecting; `ask("What is
    two plus two? Answer in a few words.", 60, …)` → `r.stop == "eog"`, `r.frames ≥ 12`, collected samples ≥ 24000,
    last `on_pcm` call has `end == true`, `r.text` non-empty and has no `<|` substring.
  - `speech_follow_up_continues`: a second `ask` right after on the same view → also speaks, `r.stop == "eog"`
    (proves `pos_[3]` re-synced and embeddings toggled back).
  - `speech_max_speech_s_stops`: `max_speech_s = 1` on "Count from one to thirty." → `r.stop == "max"`,
    `r.frames ≤ 13`, `has_pending_turns()`, then a follow-up `ask` succeeds with `stop == "eog"`.
  - `speech_cancel_stops_within_200ms`: cancel from another thread 1 s into a long answer → returns within 200 ms,
    `r.cancelled`, `on_pcm(…, end=true)` called once.
  - `speech_off_is_text_only`: `speak = false` → `r.frames == 0`, `on_pcm` never called (today's behaviour).
- [ ] **Step 2: Run to verify they fail**
  Run: `bash core/scripts/engine/box_build.sh speech_`
  Expected: build fails, `speech.h` not found.
- [ ] **Step 3: Implement `speech.cpp`** as a line-for-line port of `lfm3a_gen_audio_pipeline`'s step loop in
  b12679 `tools/mtmd/mtmd-helper-gen.cpp` (~1905-2310): same block counts, same `sample_frame` (MaskGIT 4/4/4,
  `std::mt19937` seeded with `seed`, `std::shuffle` order, rep penalty / top_k / temp from `mtmd_gen_inp_default`),
  same end-of-audio rule (any code == last vocab index), same feedback `GEN_CODE` pass and `decode_embd_batch` of
  `fb` at `*pos` with logits on, h_state from `llama_get_embeddings_ith(lctx, -1)`. `speak_mixed` decodes
  `<|mixed_start|>` itself first. Stops: `<|im_end|>` → "eog", `cancelled()` (checked before each slot) → "cancel",
  `n_text ≥ max_tokens` → "max", `frames ≥ max_frames` → "max". `frame_ms` = mean wall time per frame excluding
  codec.
- [ ] **Step 4: Wire into `Lm`.** In `Lm::open` with `speak`: append `\nSpeak using a female voice.` to the system
  prompt, find control tokens, create the inline `Codec` on `mctx_`, and do not install the sampler ban. In
  `generate` with `speak`: `llama_set_embeddings(ctx_, true)`, call `speak_mixed` (`max_frames = max_speech_s *
  1000 / 80`), inline codec → `on_pcm`, then `on_pcm(nullptr, 0, true)` after `flush`, `llama_set_embeddings(ctx_,
  false)`, `pos_[3] = llama_memory_seq_pos_max(llama_get_memory(ctx_), 3) + 1`; the turn's answer text is
  `SpeakResult::text`.
- [ ] **Step 5: Run** `bash core/scripts/engine/box_build.sh speech_` then `bash core/scripts/engine/box_build.sh`
  (whole suite) — Expected: all PASS; existing text-mode tests unchanged.
- [ ] **Step 6: Commit** `src/speech.h src/speech.cpp src/lm.h src/lm.cpp tests/test_speech.cpp` — "engine: LFM3
  mixed speech loop on the LM, golden-matched to llama.cpp".

### Task 3: Codec on its own context and thread

**Files:**
- Modify: `src/speech.h`, `src/speech.cpp` (add `CodecThread`), `src/lm.h`, `src/lm.cpp` (LmConfig
  `codec_cpus`, `codec_threads`; `codec_inline` default false; second mtmd context)
- Test: `tests/test_speech.cpp`

**Interfaces:**
- Produces:
  ```cpp
  class CodecThread {
  public:
      // opens its own mtmd context on `mmproj` with n_threads, pinned to cpus; PCM comes out through on_pcm
      static std::unique_ptr<CodecThread> open(const std::string& mmproj, const std::vector<int>& cpus, int n_threads,
                                               std::function<void(const float*, int, bool end)> on_pcm,
                                               std::string* err);
      void push(const int32_t* codes);  // copies 12 codes, returns at once
      void end();                       // after the queued frames: flush tail, on_pcm(..., end=true), reset
      void clear();                     // drop queued frames, reset state, on_pcm(nullptr, 0, true)
      double mean_ms() const;           // mean codec time per frame, this answer
  };
  ```
  `LmConfig` gains `std::vector<int> codec_cpus = {3}; int codec_threads = 1;`; `codec_inline` default becomes false.

- [ ] **Step 1: Write the failing tests:**
  - `speech_threaded_codec_matches_inline`: same question + seed 1234 with `codec_inline = true` and `false` →
    identical frame count and max |Δpcm| ≤ 1e-5; `r.codec_ms > 0` in the threaded run.
  - `speech_threaded_codec_overlaps`: threaded run's `frame_ms` < inline run's `frame_ms` − 0.5 × inline
    `codec_ms` (the codec left the big-core path). Print both.
  - `speech_cancel_clears_codec_queue`: cancel 1 s in, then a new ask → the first PCM block of the new answer equals
    (≤ 1e-5) the first block of the same ask run on a fresh Lm with the same seed (no old tail, state reset).
- [ ] **Step 2: Run** `bash core/scripts/engine/box_build.sh speech_` — Expected: FAIL (no `CodecThread`).
- [ ] **Step 3: Implement `CodecThread`** (bounded queue of `std::array<int32_t,12>`, cv; thread pins itself with
  the engine's `pin_self` helper and opens the context from inside so ggml threads inherit `cpus`) and use it in
  `Lm::generate` when `!codec_inline` (`on_frame` → `push`; after the loop `end()`, or `clear()` on cancel).
- [ ] **Step 4: Run** `bash core/scripts/engine/box_build.sh speech_` then the whole suite — Expected: PASS.
  Record inline vs threaded frames/s and codec ms (1 vs 2 threads on [3] / [2,3]) in the ledger for Task 7.
- [ ] **Step 5: Commit** `src/speech.h src/speech.cpp src/lm.h src/lm.cpp tests/test_speech.cpp` — "engine: codec
  on its own context and small-core thread".

### Task 4: Vision islands on the small cores during an answer

**Files:**
- Create: `src/big_cores.h` (move `BigCores` out of `engine.cpp`)
- Modify: `src/island.h`, `src/island.cpp`, `src/vision.h`, `src/vision.cpp`, `src/engine.cpp`
- Test: `tests/test_island.cpp`, `tests/test_big_cores.cpp`

**Interfaces:**
- Produces:
  ```cpp
  // big_cores.h
  struct BigCores {
      bool island_enter();          // true = big cores taken; false = an ask holds them: run on the small pool now
      void island_exit(bool big);
      void ask_enter();             // waits only for a running big-core island
      void ask_exit();
  };
  // island.h
  Island(int n_tok, int heads, int dim, float scale, const std::vector<int>& cpus, int n_threads,
         const std::vector<int>& small_cpus = {});
  void run(const float* q, const float* k, const float* v, float* out, bool small = false);
  // vision.h
  static std::shared_ptr<Vision> shared(split_dir, qnn_lib_dir, island_cpus, island_threads,
                                        const std::vector<int>& island_small_cpus, std::string* err);
  void set_island_gate(std::function<bool()> enter, std::function<void(bool big)> exit);
  ```
- [ ] **Step 1: Write the failing tests:**
  - `big_cores_island_goes_small_during_ask`: `ask_enter()`; `island_enter()` returns `false` within 5 ms;
    `ask_exit()`; `island_enter()` returns `true`.
  - `big_cores_ask_waits_for_big_island`: `island_enter()` true; `ask_enter()` on another thread blocks until
    `island_exit(true)`.
  - `island_small_pool_matches_big`: same random q/k/v, `run(..., false)` vs `run(..., true)` → max |Δ| ≤ 1e-6;
    print both `last_ms()`.
- [ ] **Step 2: Run** `bash core/scripts/engine/box_build.sh big_cores` and `... island_small` — Expected: FAIL.
- [ ] **Step 3: Implement.** Second ggml threadpool on `small_cpus` (n_threads = size). Vision calls `enter()`
  before each island and `run(..., !big)`. Engine config key `island_small_cpus` (default [1, 2]).
- [ ] **Step 4: Run** the two filters and then `bash core/scripts/engine/box_build.sh api_` — Expected: PASS
  (existing vision/api tests unchanged).
- [ ] **Step 5: Commit** `src/big_cores.h src/island.h src/island.cpp src/vision.h src/vision.cpp src/engine.cpp
  tests/test_island.cpp tests/test_big_cores.cpp` — "engine: vision islands run on the small cores during an answer".

### Task 5: Engine — speaker, mic gate, cancel, events, status, config

**Files:**
- Modify: `src/engine.cpp`, `include/cortex_engine.h` (event + status docs), `tests/events.h` (test config gets
  `"speak": false` unless a test sets it)
- Test: `tests/test_speak_api.cpp`

**Interfaces:**
- Consumes: Task 1 `Speaker`, `open_sink`, `SoundEvent`; Task 2/3 `LmConfig::{speak, voice, max_speech_s,
  codec_inline, codec_cpus, codec_threads, on_pcm}`, `AskResult::{frames, frame_ms, codec_ms, sound_ms}`; Task 4 gate.
- Produces (events and status, for Task 6):
  - `{"type":"sound_start","at_ms":…}` and `{"type":"sound_end","sound_ms":…,"gaps":…,"cut":bool}`; both carry
    `"voice": true` when the answer is to a spoken question.
  - `done` adds `frames`, `frame_ms`, `codec_ms`, `sound_ms`; spoken answers add `end_to_sound_ms` (speech_end →
    sound_start).
  - `ce_status` adds `talking` (Cortex audio playing — `speaking` is already the user's open utterance),
    `muted`, `prebuffer_ms`.
- [ ] **Step 1: Write the failing tests** in `tests/test_speak_api.cpp`, config with `speak: true`,
  `speaker_device: "wav:/tmp/ce_answer.wav"`:
  - `speak_api_typed_ask_is_spoken`: refresh t001, ask → `sound_start` arrives before `done`; `done.frames ≥ 12`;
    `sound_end.cut == false`, `sound_end.sound_ms ≥ 1000`; WAV file > 48 044 bytes.
  - `speak_api_cancel_stops_sound`: ask a long question, after `sound_start` call `ce_cancel` → `sound_end` within
    200 ms with `cut == true`, `status.talking == false`.
  - `speak_api_new_ask_cuts_playout`: ask; at `done` (audio still playing) ask again → a `sound_end{cut:true}` for
    the first answer arrives before the second `sound_start`.
  - `speak_api_mic_muted_while_talking`: listening on; during an answer push the t-speech WAV fixture used by
    `test_listen.cpp` → no `speech_start`; `status.muted == true` during, `false` ≥ `mute_tail_ms` after
    `sound_end`.
  - `speak_api_zero_audio_answer_unmutes`: force with `max_speech_s: 0` → `done.frames == 0`, `sound_end.sound_ms
    == 0`, no `sound_start`, `muted == false` 400 ms after done.
  - `speak_api_bad_speaker_falls_back_to_text`: `speaker_device: "plughw:9,9"` → `ce_open` succeeds, an `error`
    event whose `what` starts with `"speaker:"`, ask → tokens + done, `done.frames == 0`.
  - `speak_api_spoken_question_end_to_sound`: listening on, push the speech fixture → `done.voice`,
    `done.end_to_sound_ms < 1000` (print it).
  - `speak_api_view_encoded_during_answer`: ask a long question, `ce_refresh` with t008 after `sound_start` → a
    `view` event's `encode_ms` is reported before `done` (read may follow done).
- [ ] **Step 2: Run** `bash core/scripts/engine/box_build.sh speak_api` — Expected: FAIL (no sound events).
- [ ] **Step 3: Implement.** Parse the config keys from Global Constraints. Open the Speaker on the control thread
  after the LM; a failed sink → `error("speaker: …")` and `LmConfig::speak` stays on but `on_pcm` drops audio and
  `frames` are not produced (`speak` set false before `Lm::open` — decide by opening the sink first). Worker: before
  each answer `speaker->begin()` and `muted = true`; `on_pcm` → `push` / `end`; `done` gets the new fields.
  `SoundEvent` → event (`sound_end` sets `mute_until = now + mute_tail_ms`). Audio thread: while `muted` or
  `now < mute_until`, drop chunks; on the falling edge reset the VAD. `ce_cancel` → `lm->cancel()` +
  `speaker->stop()`. Status keys as above.
- [ ] **Step 4: Run** `bash core/scripts/engine/box_build.sh speak_api` then the whole suite — Expected: PASS.
- [ ] **Step 5: Commit** `src/engine.cpp include/cortex_engine.h tests/events.h tests/test_speak_api.cpp` —
  "engine: answers spoken on the headphone jack, mic muted while talking".

### Task 6: Python binding and live TUI

**Files:**
- Modify: `core/cortex_core/engine/native.py`, `core/cortex_core/tui/live_state.py`, `core/cortex_core/tui/live.py`,
  `core/cortex_core/tui/live_app.py`
- Test: `core/tests/test_native_route.py` (or the existing native test file), `core/tests/test_live_state.py`,
  `core/tests/test_live_tui.py`

**Interfaces:**
- Consumes: Task 5 events/status.
- Produces: `LiveState.talking: bool`, `LiveState.muted: bool`; `LiveSession.button() -> str` returning `"cut"` or
  `"listen"`/`"stop listening"`.
- [ ] **Step 1: Write the failing tests:**
  - `test_sound_events_are_known_and_routed`: `"sound_start"`, `"sound_end"` in `EVENT_TYPES`; `route_event(
    {"type":"sound_end","voice":True}, False) == "voice"`; `route_event({"type":"sound_start"}, True) == "answer"`.
  - `test_live_state_talking_flags`: apply sound_start → `talking`; sound_end → not; done with `end_to_sound_ms`
    320, `sound_ms` 2400, `gaps` 0 → last answer timings hold them.
  - `test_space_while_talking_cuts_the_answer` (TUI, FakeEngine emits sound_start then waits): press space →
    `eng.cancelled == 1`, `eng.listening` unchanged; status shows "SPEAKING" before, not after.
- [ ] **Step 2: Run** `cd core && python -m pytest tests/test_native_route.py tests/test_live_state.py
  tests/test_live_tui.py -q` — Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the event types and routing, `LiveState` flags and timings, `LiveSession.button()`
  (cancel when talking), status line "SPEAKING · mic muted", LAST ANSWER row with end_to_sound / sound / gaps /
  frame ms / codec ms. `live_tui.sh`'s engine config gains `"speak": true`.
- [ ] **Step 4: Run** `cd core && python -m pytest -q` — Expected: all PASS.
- [ ] **Step 5: Commit** the four modules + tests — "tui: Cortex speaks, space cuts it off".

### Task 7: On the box — by ear, measurements, docs

**Files:**
- Create: `docs/measurements/2026-11-speech-out.md`
- Modify: `core/AGENTS.md` (engine row + changelog), `core/tools/cortex-engine/README.md` if it lists config keys

- [ ] **Step 1:** Run `bash core/scripts/engine/live_tui.sh` on the box with the headphones; Haziq asks three
  questions out loud and one typed; Expected: he hears every answer, space cuts one off, no self-triggering.
- [ ] **Step 2:** Measure with the 12 bench questions (`native_bench.py` with `speak: true`, `wav:` sink): frames/s
  inline vs threaded, codec ms on [3] vs [2,3], gaps per answer, end_to_sound (spoken fixture), island ms small vs
  big during an answer, transcripts vs text-mode answers. Expected: end_to_sound < 1000 ms, gaps 0 on ≥ 11/12.
- [ ] **Step 3:** Set final defaults from the numbers (thread counts, prebuffer) in `engine.cpp` and the spec's
  "Left to the builder"; write the measurements doc (tables, raw numbers, what did not meet target and why).
- [ ] **Step 4:** Run the whole C++ suite and `cd core && python -m pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** docs + default changes + `docs/superpowers/specs/2026-11-24-speech-out-design.md` +
  this plan — "docs: speech out measurements".
