# Speech out (step 4 of the parallel engine) — design

Approved by Haziq: 2026-11-24 ("add both and build it ... make full use and is efficient and fast, focus on the end
product, don't simplify"). Parent: `2026-11-24-cortex-engine-core-design.md` (step 4 "speech output in parallel"),
after `2026-11-24-voice-in-design.md`.

## Intent

Cortex answers out loud. The user is visually impaired, so text on a screen is not an answer. The voice is
LFM3-Omni's own speech: the same model and the same conversation memory, so the words spoken are the words the model
means. First sound **< 1 s after the user stops talking** (project target). The TUI still shows the words.

Like the rest of the engine, the work runs in parallel wherever the data allows: sound is made from each frame while
the model generates the next one, playback runs while generation continues, and the camera view keeps being encoded
while Cortex talks.

## Goals

- Every answer (spoken or typed question) is spoken on the box's headphone jack (WCD938x codec, card 0) while it is
  generated, with no gaps in normal use.
- Text of the answer still streams as token events and goes into history as text.
- **Mic off while Cortex speaks** (Haziq, 2026-11-24): from the start of an answer until its audio has played out
  plus a short tail, mic audio is ignored, so Cortex never hears itself. The button (space in the TUI) cuts the answer
  off: generation and playback stop at once.
- **Codec in parallel** (Haziq, 2026-11-24): the codec (codes → sound) runs on its own thread and model context on
  the small cores, overlapping the next frame's backbone + depthformer on the big cores.
- **Vision during speech** (Haziq, 2026-11-24): while an answer holds the big cores, the vision encoder's CPU islands
  run on the small cores instead of waiting, so the next view is encoded during the answer and read into the LM the
  moment the answer ends.
- The headphone route and volume are set by the engine every time it opens (a reboot can no longer leave the jack
  silent).
- Done-event timings: `end_to_sound_ms` (speech end → first sample handed to the sound card), `sound_ms`, `gaps`
  (underruns), `frames`, `frame_ms` (mean big-core time per audio frame), `codec_ms` (mean codec time per frame).

## Non-goals

- Echo cancellation and talking over Cortex by voice. Back with earbuds or an AEC later.
- Bluetooth/PipeWire output, voice choice in the UI, other languages, a second TTS model.
- Speech generation on the NPU or GPU.
- Reading a new view into the LM *during* an answer (the LM context does one decode at a time; batching image tokens
  into speech steps would push speech below real time).

## Anti-goals

- Robot voice, or a TTS that says different words than the model wrote.
- Spoken answers that stutter so badly they are harder to follow than silence.
- Speech starving cpu0 (safety core) or breaking vision.

## Measured facts (box, 2026-11-24)

- llama.cpp b12679 LFM3 speech (`lfm3a_gen_audio_pipeline` in `tools/mtmd/mtmd-helper-gen.cpp`): continuing a
  sequence in MIXED mode alternates **6 text tokens and 12 audio frames**; after `<|text_end|>` only audio. A frame =
  1 backbone decode (feedback embedding) + 3 depthformer passes (MaskGIT schedule 4/4/4 over 12 codebooks, random
  order) + codec decode (GEN_WAV, codec decoder + host ISTFT, stateful). 24 kHz mono float.
- One frame = **80 ms** of audio. `llama-tts`, Q4_0, 4 threads on cpu4-7: **15.9 frames/s = 1.27x real time** with
  the codec in line. Text decode 25.8 tok/s (39 ms/token). Mixed block ≈ 0.99 s work per 0.96 s audio (0.97x) with
  the codec in line — the parallel codec takes it off this path.
- `mtmd_gen_audio_process` holds the mtmd context's single `compute_mutex`, so codec and depthformer on one context
  can never overlap. A second mtmd context costs the mmproj again (~507 MB file; box has ~6.5 GB available).
- The hidden state comes from `llama_get_embeddings_ith(ctx, -1)`: the context needs `llama_set_embeddings(true)`
  while speaking.
- Voice: system prompt line `Speak using a female voice.` (llama.cpp `common_chat_get_speech_system_prompt`).
- The engine bans `<|audio_start|>`/`<|mixed_start|>` today (text only). History H holds text turns only.
- Sound: `plughw:0,0` after UCM verb `HiFi` + device `Headphones`; `HP Volume` 20 of 24. PipeWire has only a dummy
  output for card 0. `libasound.so.2` is installed, its headers are not.

## Approaches considered

1. **Our own LFM3 MIXED loop on the engine's LM context, codec on a second mtmd context and thread (picked).** One
   model and memory; exact transcript; the codec overlaps generation; we own the loop (cancel checks, timings, mic
   gate). Cost: ~250 lines ported from llama.cpp (kept identical, golden-tested against the helper) and ~0.5 GB RAM.
2. llama.cpp's helper as is (codec in line, one context): least code, but sound-making can never overlap generation
   (shared lock) and mixed blocks run at 0.97x. Rejected by the "full use" goal.
3. AUDIO-only mode: no text for the TUI or history. Rejected.
4. Separate TTS on finished text: different voice, later sound. Rejected (anti-goal).
5. Python plays PCM events: real-time audio leaves the brain process. Rejected.

Mic while speaking (Haziq picked): **mic off while speaking, button cuts it off.** Echo cancellation deferred.

## Design

### Speech loop (`src/speech.{h,cpp}`, called by Lm)

- `Speech` is created by `Lm::open` when `speak` is on: finds the control tokens (`<|audio_start|>`,
  `<|mixed_start|>`, `<|text_end|>`, `<|im_end|>`), reads the model's sampling defaults (`mtmd_gen_inp_default`:
  temp, top_k, repetition penalty and window), creates a depthformer `mtmd_gen_state` on the LM's mtmd context.
- Per answer, on S (seq 3) right after the question ends at `<|im_end|>\n`: decode `<|im_start|>assistant\n` +
  `<|mixed_start|>` (logits on the last), embeddings on, then the port of the helper's `step_gen` loop:
  - text slot: sample with the engine's greedy sampler (no ban in speak mode, `<|audio_start|>`/`<|mixed_start|>`
    are not reachable mid-answer anyway) → `<|im_end|>` ends the answer; `<|text_end|>` ends the text (audio-only
    from here); other tokens are emitted as token events (control tokens hidden) and decoded.
  - audio slot: `sample_frame` (3 depthformer passes, the same RNG order and sampling as the helper, seeded per
    answer), end-of-audio code → the answer continues in text (as the helper); else the 12 codes go to the codec queue
    and the feedback embedding is decoded into S at the next position.
  - block counting (6 text / 12 audio) exactly as the helper.
  - stops: end of turn, cancel (checked every step), `max_tokens` text tokens, `max_speech_s` (30 s) of audio.
  - after: `pos_[3] = llama_memory_seq_pos_max(seq 3) + 1`, embeddings off, pending turn = transcript text.
- **Codec thread** (pinned `codec_cpus`, default [3]): owns a second mtmd context (mmproj, `codec_threads` threads)
  and its own `mtmd_gen_state`; takes frames of codes from a queue, runs GEN_WAV per frame, pushes PCM to the speaker;
  at the end of an answer flushes the ISTFT tail (GEN_WAV with no codes) and resets its state. A cancelled answer
  clears the queue and resets the state.
- `codec_inline` config (default false) runs the codec in the LM loop instead — kept for the golden test and the A/B
  measurement.

### Speaker (`src/speaker.{h,cpp}`)

- Ring buffer (float, 24 kHz) + a writer thread on `speaker_cpus` (default [3]). `push`, `answer_end`, `stop`
  (drop now), `playing`.
- **Adaptive prebuffer**: playback starts when buffered audio ≥ `prebuffer_ms` (default 200) or the answer's audio
  has ended; if an underrun happens, the next answer's prebuffer grows by 100 ms (cap 800), and it shrinks by 50 ms
  after 3 gapless answers (floor `prebuffer_ms`). Underrun → `snd_pcm_recover`, counted as a gap.
- ALSA through `dlopen("libasound.so.2")` with locally declared prototypes (no package install). Open: UCM
  (`snd_use_case_mgr_open(ucm_card)`, `_verb` = `ucm_verb`, `_enadev` = `ucm_device`), mixer controls from `mixer`
  ({"HPHL Volume": 20, "HPHR Volume": 20}; `HP Volume` is a UCM remap control that does not exist on hw:0), `snd_pcm_open(speaker_device)`, `snd_pcm_set_params(S16_LE, RW interleaved, 1 ch, 24000,
  soft resample, 80 ms latency)`.
- `speaker_device`: `"null"` (counts samples), `"wav:<path>"` (writes a WAV; tests and listening without a card), or
  an ALSA name.
- Events: `{"type":"sound_start","at_ms":..}`, `{"type":"sound_end","sound_ms":..,"gaps":..,"cut":bool}`.

### Vision during speech (island pools)

- `Island` gets two thread pools: big (`island_cpus`, 4-7) and small (`island_small_cpus`, default [1, 2]).
- The `BigCores` gate no longer makes islands wait for an ask: while an ask holds the big cores, an island runs on the
  small pool at once; otherwise it takes the big cores as today (an ask still waits for a running big-core island).
- The view's `Lm::read_view` still waits for the LM lock, i.e. reads the encoded view as soon as the answer ends.

### Engine: mic gate, button, config, status

- `muted` from the start of any answer until `sound_end` + `mute_tail_ms` (300). While muted the audio thread drops
  mic audio; when the gate opens the VAD is reset. No self-barge-in.
- `ce_cancel` stops generation, clears the codec queue and stops playback.
- `ce_status`: `talking` (Cortex audio playing; `speaking` already means the user's open utterance), `muted`,
  `prebuffer_ms`.
- Config: `speak` (default true), `voice` "female", `speaker_device` "plughw:0,0", `ucm_card` "hw:0", `ucm_verb`
  "HiFi", `ucm_device` "Headphones", `mixer` {"HPHL Volume": 20, "HPHR Volume": 20}, `prebuffer_ms` 200, `mute_tail_ms` 300,
  `max_speech_s` 30, `codec_cpus` [3], `codec_threads` 1, `speaker_cpus` [3], `island_small_cpus` [1, 2],
  `codec_inline` false. A speaker that fails to open: error event, the engine answers in text only.
- Core map while speaking: cpu0 safety; cpu1-2 audio/vision control + small-pool islands; cpu3 codec + speaker;
  cpu4-7 LM (backbone + depthformer). Thread counts are tuned by measurement (see Tests).

### Python binding and live TUI

- `native.py`: `sound_start`/`sound_end` routed with their answer; `Engine.cancel()` stops speech too.
- TUI: space while Cortex speaks = cut it off (listening stays on); otherwise toggles listening. Status shows
  SPEAKING / mic muted; LAST ANSWER shows end_to_sound, sound length, gaps, frame and codec ms.

### Tests

- Golden: our loop (`codec_inline`, fixed seed) vs llama.cpp's helper on the same prompt → identical codes and PCM.
  Then threaded codec vs inline → identical PCM.
- Speaker: ring/prebuffer/adaptive/gap logic with a fake sink; WAV sink writes a valid 24 kHz file.
- Engine: typed question with `speaker_device = "wav:..."` → tokens, ≥ 1 s audio, `sound_start` before `done`;
  cancel mid-speech stops within 200 ms with `sound_end.cut`; mic audio while speaking gives no speech_start; spoken
  question → spoken answer with `end_to_sound_ms` < 1000; islands on the small pool during an answer (view event
  arrives before the answer ends).
- Measurements (doc): frames/s inline vs threaded codec; codec ms on 1 vs 2 small cores; gaps over the 12 bench
  questions; end_to_sound; island time on small vs big cores; answer transcripts vs text-mode answers.
- By ear: Haziq hears the answer on the speaker.

## Left to the builder

- Ring size, ALSA period size, queue depths, how control tokens are cleaned from shown text.
- Final thread counts from the measurements (defaults above are the starting point).

## Risks

- Mixed-mode speed: if the threaded codec still leaves big-core time ≥ 80 ms per frame in mixed blocks, the adaptive
  prebuffer absorbs it (higher first-sound time on long answers). Measured and reported.
- Small-core contention during speech (codec + speaker + islands + control). Codec has its own core; islands get the
  other two; measured.
- Mixed-mode answer quality may differ from text mode; checked on the 12 bench questions.
- The helper code is experimental upstream; we pin b12679 and the golden test catches drift.
- RAM +~0.5 GB for the codec's mtmd context.
