# Cortex-EmbD: our parallel inference engine

**Status (2026-11-26):** built and running on the Radxa Dragon Q8B. Code: `core/tools/cortex-engine`, built as
`libcortex_engine.so`. Python binding: `core/cortex_core/engine/native.py`. Measurements are in `docs/measurements/`.
Companion to [V4-ECOSYSTEM.md](V4-ECOSYSTEM.md) §8.

Cortex-EmbD runs LFM3-Omni-2B as Cortex's local brain. It is one native process that **sees, listens, thinks and
speaks at the same time**. Each job runs on the processor and cores that suit it, and they hand work to each other
through queues and memory slots, so no job waits for another to finish:

- the camera frame goes to the NPU;
- the attention maths goes to the big CPU cores;
- the voice encoder goes to the small cores;
- the answer is turned into sound on its own core while the LM makes the next part of it.

| Target | Result |
|:---|:---|
| First sound < 1 s after the user stops talking | **0.6 s** (end of speech → first sound, 600–641 ms) |
| Answers about the *current* view | the view is refreshed in the background about every 1.4 s, and at the start of speech |
| Safety path never starved | Cortex-EmbD never runs on cpu0 |
| Lowest power per answer | NPU for vision (4.7× faster than CPU); scene-skip on still frames; no meter on the box yet |

## 1. Hardware

Radxa Dragon Q8B (Qualcomm SC8280XP), 7 GiB RAM, Ubuntu.

| Unit | Cores | Used for |
|:---|:---|:---|
| cpu0 (A78C) | 1 | **reserved for the safety stack**: Cortex-EmbD never touches it |
| cpu1-3 (A78C, 2.4 GHz) | 3 "small" | audio thread (VAD + voice encoder), codec + speaker on cpu3, islands during an answer |
| cpu4-7 (X1C, 3.0 GHz) | 4 "big" | the LM (llama.cpp, 4 threads), vision attention islands between answers |
| Hexagon NPU (HTP v68) | — | the vision encoder's 7 segments (QNN 2.42, w8a16) |
| Headphone jack (WCD938x) | — | Cortex's voice, via ALSA (`plughw:0,0`, UCM HiFi/Headphones) |

The model is LFM3-Omni-2B, **Q4_0** weights (1.94× faster image prefill than Q4_K_M, same answers), on llama.cpp
b12679 with the mtmd multimodal library.

## 2. The parallel execution model

Five threads, each pinned to its own cores, plus the NPU:

```
          cpu1-3 (small)                          cpu4-7 (big)                    NPU
 ┌──────────────────────────────┐  ┌──────────────────────────────────┐  ┌──────────────┐
 │ AUDIO thread (cpu1-3)        │  │ LM WORKER (cpu4-7)               │  │ vision       │
 │  mic PCM → Silero VAD        │  │  asks, one at a time             │  │ segments 1-7 │
 │  → LFM3 audio encoder        │──►  decodes speech rows into S      │  │ (w8a16)      │
 │  → rows (as the user talks)  │  │  MIXED loop: text + audio frames │  └──────▲───────┘
 │  echo-lag measurement        │  │  frame codes ──────────┐         │         │
 └──────────────────────────────┘  └────────────────────────┼─────────┘         │
 ┌──────────────────────────────┐                           │                   │
 │ CODEC thread (cpu3)          │◄──────────────────────────┘                   │
 │  codes → 24 kHz PCM          │  ┌──────────────────────────────────┐         │
 │  (own mtmd context)          │  │ CONTROL thread                   │─────────┘
 └──────────────┬───────────────┘  │  frame → prep → NPU + 6 islands  │
 ┌──────────────▼───────────────┐  │  → scene-skip → read view into V'│
 │ SPEAKER thread (cpu3)        │  │  (islands on big cores, or on    │
 │  PCM ring → headphone jack   │  │   cpu1-2 while an answer runs)   │
 └──────────────────────────────┘  └──────────────────────────────────┘
```

### What overlaps with what

| While… | …this runs in parallel |
|:---|:---|
| the user is talking | the voice encoder turns speech into LM rows (cpu1-3), the LM decodes them into the conversation slot (cpu4-7), the view is refreshed (NPU) |
| the user stops talking | only the last rows, the turn close and the first token remain: **~150 ms to the first token** |
| Cortex is answering | the LM makes frame *n+1* while the codec turns frame *n* into sound (cpu3) and the speaker plays frame *n−k* |
| Cortex is answering | a new camera view is encoded: NPU + islands on cpu1-2, so the next question is about what is in front of the user now |
| the scene is still | frames whose features match the last view (cosine ≥ 0.98) are skipped: no LM read, no power spent |

### The scheduling rules that make it work

1. **The big-cores gate** (`big_cores.h`). The LM and the vision attention islands share cpu4-7.
   - An answer holds the big cores from the ask to its end.
   - An island that arrives during an answer does not wait. It runs on the small-core pool (`island_small_cpus`,
     cpu1-2) instead.
   - An ask waits only for an island that is already running on the big cores: at most one island, about 24 ms.
2. **Preemption.** A background view read gives way to an ask at once, through llama.cpp's abort callback, which
   stops mid-graph. The half-built view is dropped and V stays as it was. Ask → abort costs about 20 ms.
3. **One NPU open per process.** `Vision::shared` opens the NPU once and never closes it. A quick close-and-reopen
   once reset the box through a fastrpc unmap error.
4. **Pinning by the owning thread.** ggml pins whichever thread creates or drives a threadpool to the pool's first
   core.
   - Each thread therefore opens its own part: Vision on the control thread, Lm on the worker.
   - The audio thread never calls `llama_decode`. It hands rows to the worker, so it is never pulled onto an LM core.
   - The caller of `ce_open` is never pinned.
5. **One graph per mtmd context.** The codec has its own mtmd context on its own thread. Sharing the LM's context
   would make the depthformer wait for the codec.

## 3. Memory slots: never re-read what is already read

LFM3 is a hybrid model (conv + attention). llama.cpp can **copy** a sequence's state but cannot **rewind** it, so
Cortex-EmbD keeps four slots and only ever copies or clears them:

| Slot | Holds | Built |
|:---|:---|:---|
| **H** (seq 0) | start + system prompt + finished turns, text only (≤ 1536 tokens; the oldest are dropped) | in the background, after each answer |
| **V** (seq 1) | H + "user: <image>": the current view, ready before anyone asks | in the background |
| **V′** (seq 2) | the next view, built from H + the new image, then swapped in as V when complete | in the background, preemptible |
| **S** (seq 3) | V + question + answer (+ follow-ups): the conversation about this view | at ask time |

- An ask copies V into S (0.13 ms) and reads **only the question**. Time to first token: **115 ms** (it was 1.23 s
  when every ask read the image too).
- A follow-up about the same view continues S.
- When S has less than a third of the context free, or a new view has landed, the follow-up starts again from V.
  Its earlier turns still go into H, so nothing is lost and an answer never hits the end of the context.
- A spoken question builds S while the user is still talking. If a new view lands mid-utterance, S is rebuilt from
  it with all the rows so far.

## 4. The pipelines

### Seeing (vision, on the NPU)
`ce_push_frame` (the latest frame wins) → prep (Pillow-exact bicubic, 640×360 → 640×352 canvas, 1.9 ms) → **7 NPU
segments + 6 CPU attention islands** (≈ 282 ms) → scene-skip check → read 220 image tokens into V′ (≈ 1.13 s on the
big cores; this is the floor of a refresh) → swap into V. Total refresh ≈ **1.42 s**.

Attention stays on the CPU because HTP v68 only multiplies activations at 8 bit, which breaks attention accuracy.
The C++ port matches the Python NPU chain (row cosine 0.99998+).

### Listening (voice in)
- The button toggles listening (`ce_set_listening`). `ce_push_audio` feeds the mic's 16 kHz PCM.
- **Silero VAD v4**, ported to C++ (0.4 ms per chunk, within 4.7e-5 of onnxruntime), finds where speech starts and
  ends.
  - Settings: on 0.5, off 0.35, 96 ms confirm, 320 ms pre-roll, 500 ms hangover.
  - Speech start also triggers a view refresh, so the answer is about what the user was looking at.
- The **LFM3 audio encoder** runs while the user talks: about 21 ms per 320 ms of audio, about 13 rows per second,
  and the rows go straight into S.
- From the VAD's end of speech to the first token: **108–306 ms** (median ~150).

### Speaking (speech out)
Every answer comes in LFM3-Omni's own voice, made and played at the same time:

1. **MIXED loop** on the LM: 6 text tokens, then 12 audio frames, and so on. Each audio frame is 80 ms of sound.
   3 depthformer passes reveal its 12 codebooks, then its feedback embedding is decoded into the backbone. The port
   matches llama.cpp's own helper exactly (same text, same PCM for a fixed seed).
2. The **codec thread** turns each frame's codes into 24 kHz PCM, at about 20 ms per frame (4× real time).
3. The **speaker thread** plays a PCM ring on the jack.
   - It starts after a 200 ms prebuffer, which adapts: +100 ms after an answer with a gap, up to 800 ms.
   - If the ring runs dry, it waits for 1 s of lead (`rebuffer_ms`) before playing again. A small production deficit
     then costs one short pause instead of a stutter.
4. **Cuts:** `ce_cancel`, the button or a new answer cuts the sound at once (0 ms). The codec drops queued frames of
   older answers, so nothing of an old answer leaks into a new one.

End of speech → **first sound: 600–641 ms**. Answers end naturally (`eog`). The limits only stop a runaway:
`max_tokens` 512, `max_speech_s` 60, and the end of the context.

### Not hearing itself (echo)
The mic hears Cortex's voice from the earbuds about 450 ms late (device buffer + earbuds + USB/PipeWire capture).
- The mic is off from the answer's start until **echo_lag + 300 ms** after its sound ends.
- `echo_lag` is **measured at every answer**: the first mic chunk 12 dB over the room floor, after the answer's
  first loud sample is played. A later lag is taken at once; an earlier one moves the estimate a quarter of the way.
- So the echo is never taken for a question, and the user is heard again as soon as the echo is over.

## 5. Interfaces

**C API** (`include/cortex_engine.h`). Events come back as JSON lines through one callback.

```c
void* ce_open(const char* config_json, ce_event_cb cb, void* user);
int   ce_push_frame(void* h, const uint8_t* rgb, int w, int h, long frame_id);  // latest frame wins
int   ce_refresh(void* h);                       // prep, encode, skip check, read the view
int   ce_ask(void* h, const char* text, int max_tokens);   // 0 = the engine's limit
int   ce_cancel(void* h);                        // stops the answer and cuts its sound now
int   ce_set_listening(void* h, int on);
int   ce_push_audio(void* h, const float* pcm, int n);     // 16 kHz mono
const char* ce_status(void* h);                  // JSON: threads, affinities, muted, echo_lag_ms, prebuffer_ms...
int   ce_reset_history(void* h);
void  ce_close(void* h);
```

Events: `token`, `done` (`stop`, `ttft_ms`, `frames`, `frame_ms`…), `view`, `speech_start`, `speech_end`,
`sound_start`, `sound_end` (`sound_ms`, `gaps`, `cut`), `error`.

**Python:** `cortex_core.engine.native.Engine`. The live dev TUI is `sh /opt/cortex/scripts/engine/live_tui.sh`
(camera + mic + earbuds). The CLI is `cli.cpp`.

**Config** (JSON to `ce_open`; on the box `/var/lib/cortex/bench/engine/engine.json`):
- `model`, `mmproj`, `split_dir`, `qnn_lib_dir` (required).
- Cores: `lm_cpus`, `vision_cpus`, `island_cpus`, `island_small_cpus`, `audio_cpus`, `codec_cpus`, `speaker_cpus`.
- Vision and LM: `skip_cos`, `max_tokens`, `max_history_tokens`, `system_prompt`.
- Listening: `vad_weights`, `vad_on`, `vad_off`, `vad_hangover_ms`.
- Speaking: `speak`, `voice`, `max_speech_s`, `codec_inline`, `codec_threads`, `prebuffer_ms`, `rebuffer_ms`.
- Echo: `mute_tail_ms`, `echo_lag_ms`.
- Speaker device: `speaker_device`, `ucm_card`, `ucm_verb`, `ucm_device`, `mixer`.

**Tests:** `sh core/scripts/engine/box_build.sh [filter]` copies the sources to the box, builds there and runs
`engine_tests`. Currently 73/73, covering:
- the ports against goldens (vision, islands, VAD, speech);
- the scheduler, preemption, cuts, echo and context limits;
- the speaker.

## 6. Numbers (12 test cases, 2026-11-24 to 11-26)

| | Value |
|:---|---:|
| Time to first token, view ready | 115 ms median |
| Voice: end of speech → first token | 108–306 ms |
| Voice: end of speech → first sound | 600–641 ms |
| View refresh (prep + NPU encode + LM read) | 1.42 s |
| Vision encode, NPU + islands | 282 ms (CPU only: 1190 ms) |
| Answers right, fresh conversation per case | 12/12 (text and spoken) |
| LM decode | ~24 tokens/s (~42 ms per decode with a view in context) |
| Speech made vs played | ~1.08× real time → about one 1 s pause per 13 s of speech |
| Peak RSS (spoken) | 3.81 GB |

Tried and rejected for the LM: flash attention (no gain), Vulkan GPU (slower and unstable), more than 4 threads
(slower), Q4_K_M (half the prefill speed).

Details: `docs/measurements/2026-11-{lfm3-omni-baseline,speedups,npu-vision,engine-core,voice-in,speech-out}.md`.

## 7. Known limits and next steps

- **Speech is about 8% slower than real time.** The rebuffer turns this into rare pauses, not stutter. To remove it:
  - skip `lm_head` on audio steps (~5%; needs a llama.cpp change, because one output flag controls both logits and
    embeddings);
  - a faster depthformer (its 3 passes per frame are the bulk).
- **No voice barge-in while Cortex talks.** The mic is muted, and only the button cuts Cortex off. Real echo
  cancellation (AEC) would allow interrupting by voice.
- **The 500 ms VAD hangover** sits before every answer. Next: start answering speculatively after about 250 ms of
  silence, and drop the answer if speech resumes.
- **View refresh 1.42 s** (target 1.4). Options: islands + read on cpu1-7, or a 112-token canvas.
- **History bias**: a long-running conversation can drag old topics into a new view (11/12 vs 12/12). Whether to
  drop history on a scene change is a product decision.
- **Untested:** tool calls on Q4_0, power (no meter on the box), and the product camera (all tests used the
  ZV-1F; frames must be 16:9).
- The live earbud check of the echo and stutter fixes is pending (see [../HANDOFF.md](../HANDOFF.md)).

## 8. How we got here

| Step | Result |
|:---|:---|
| 0. Baseline (stock llama.cpp) | voice 0.2–0.7 s on CPU, vision 3.3 s; GPU slower; NPU reachable |
| NPU vision | vision encoder on the NPU via QNN: 255 ms per frame vs 1190 ms on CPU, 13/13 |
| 1. Quick speed tests | Q4_0 weights adopted, LM on the 4 big cores |
| 2. Engine core | one C++ process; background view read; slots H/V/V′/S; TTFT 1.23 s → 115 ms |
| 3. Voice in | Silero VAD port, streaming audio encoder, rows into S while the user talks |
| 4. Speech out | MIXED loop, codec thread, speaker ring, islands on small cores during answers |
| 4b. Live fixes | answers tied to their sound, adaptive echo mute, full-length answers, rebuffer instead of stutter |

The original plan said a custom runtime would be built "only if needed". It was needed: stock llama.cpp could not
overlap vision, listening and speaking, or keep an image read ready before the question. Cortex-EmbD is that
runtime, and it keeps llama.cpp and QNN as the kernels underneath.

## 9. Non-negotiables

- Safety T0-T3 never depends on the model and is never starved by it (cpu0 is never used by Cortex-EmbD).
- Images and video are never stored; frames are processed in flight only.
- The local brain meets the same function-calling contract as Gemini, or Gemini stays primary for that tool.
- Gemini Live remains the online fallback and escalation path; local leads.

## 10. Open items

- [ ] Weights license review (commercial use, redistribution on device)
- [ ] Power: watts per interaction and idle (needs a meter), tied to the battery choice
- [ ] Escalation policy to Gemini (triggers, thresholds, UX)
- [ ] Tool registry schema shared by both brains (infra contracts); tool calls on Q4_0
