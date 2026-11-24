# Speech out — measurements (2026-11-24)

Step 4 of the parallel engine: every answer is spoken in LFM3-Omni-2B's own voice (MIXED text + audio, "Speak using
a female voice."), streamed to the headphone jack while it is made. Box: Radxa Dragon Q8B, LFM3-Omni-2B Q4_0, LM on
cpu4-7, codec thread on cpu3, speaker thread on cpu3, islands on cpu1-2 during an answer.

Raw data on the box: `/var/lib/cortex/bench/engine/speech_bench_{speak_threaded,speak_codec23,speak_inline,text}.json`
(`python -m cortex_core.engine.native_bench --fresh --still 0`, 12 cases, "One sentence.", `wav:` sink paced at
real time).

## 12 cases, spoken vs text

| config | matched | first token (median) | LM ms / 80 ms frame | codec ms / frame | gapless answers | prebuffer after 12 | peak RSS |
|---|---|---|---|---|---|---|---|
| text only (`speak:false`) | 12/12 | 115 ms | — | — | — | — | 3.24 GB |
| **spoken, codec thread on [3], 1 thread (default)** | **12/12** | 180 ms | 77.8 | 19.8 | **8/12** | 550 ms | 3.81 GB |
| spoken, codec thread on [2,3], 2 threads | 12/12 | 164 ms | 77.1 | 18.6 | 8/12 | 550 ms | 3.81 GB |
| spoken, codec inline on the LM cores | 12/12 | 163 ms | 84.7 | 4.4 | 5/12 | 800 ms | 3.25 GB |

Generation time / audio length per case, default config: 1.18, 1.22, 1.24, 1.16, 1.15, 1.13, 1.22, 1.15, 1.23, 1.26,
1.09, 1.13. **Real time needs ≤ 1.0.** (Generation includes the first token and the text tokens interleaved with the
audio: 6 text tokens per 12 audio frames.)

Spoken answers to the 12 photos read well (all 12 name the object; e.g. "The large toy in front of you is a teal plush
shark."). The low-quality MIXED answers seen in Task 2 ("I understand, you are a good boy…") were text-only prompts
without a view; with a view in context the spoken answers match the text answers.

## Spoken question → first sound (C++ tests, `wav:` sink)

| | end of speech → first token | end of speech → first sound |
|---|---|---|
| `speak_api_spoken_question_end_to_sound` (2 runs) | 148–188 ms | **600–641 ms** (target < 1000 ms: met) |

First sound = first token + the first audio frames + 200 ms prebuffer.

## Cuts and the mic

| | measured |
|---|---|
| `ce_cancel` → `sound_end` (cut) | 0 ms (the speaker cut is synchronous) |
| LM cancel → ask returns (Task 2) | 21–48 ms |
| mic during an answer | dropped from the answer's start to 300 ms after its sound ends; a question played over an answer gives no `speech_start` |
| answer with no audio | `sound_end` with sound_ms 0, no `sound_start`, mic back after the tail |
| speaker that will not open | error `speaker: …`, answers in text, mic never muted |

## Vision during an answer

A view refreshed during a 32 s spoken answer: encode 658 ms (islands on cpu1-2) instead of waiting for the answer;
the read follows done (2.2 s, longer history after a long answer; 1.1 s fresh).

## Real jack

`plughw:0,0` with UCM HiFi/Headphones and HPHL/HPHR Volume 20 (0 dB): a 6.08 s answer played, 1 gap, no ALSA
errors. Not yet checked by ear (see below).

## What did not meet target, and why

- **Gapless on ≥ 11/12: not met (8/12).** The LM makes audio 9–26 % slower than it plays (77–80 ms per frame on
  the LM + the interleaved text tokens, against 80 ms of audio per frame) once a view is in the context; without a
  view it is 63–64 ms per frame. Every long answer runs the ring dry once or twice. The adaptive prebuffer (+100 ms
  per answer with a gap, cap 800) rises to 550 ms and covers short answers only. A gap is a pause mid-sentence, not
  lost audio. Fixes that move the ratio below 1.0 are follow-ups: a faster depthformer (3 passes per frame, the
  bulk of the 78 ms), or a longer up-front prebuffer that trades first-sound latency for smoothness.
- Codec on [2,3] with 2 threads: no gain over [3] (18.6 vs 19.8 ms per frame, already 4x real time); [3] keeps cpu2
  free for the islands and the audio thread. Inline codec costs the LM 7 ms per frame and makes gaps worse.

Defaults kept: `codec_cpus [3]`, `codec_threads 1`, `codec_inline false`, `prebuffer_ms 200` (adaptive).
