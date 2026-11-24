# Cortex engine voice in: measurements (2026-11-24)

Step 3 of the parallel engine: hands-free listening in `libcortex_engine.so`. The button only toggles listening
(`ce_set_listening`); a Silero VAD (v4, ported to C++) finds where speech starts and ends. Speech is encoded by the
LFM3 audio encoder while the user talks and decoded into the conversation slot straight away, so when speech ends
only the last rows, the turn close and the first token remain.

Box: Radxa Dragon Q8B (SC8280XP), cpu0-3 Cortex-A78C, cpu4-7 Cortex-X1C. LFM3-Omni-2B Q4_0, llama.cpp b12679.
Test media on the box only: `/var/lib/cortex/bench/media/` (`question1.wav`, `room_noise.wav`, `conversation.wav` =
2 s noise + question 1 + 2 s noise + question 2 + 1.5 s noise). VAD weights `/var/lib/cortex/models/silero_vad_v4.bin`
(rebuild with `core/scripts/engine/silero_export.py`). Suite: `sh core/scripts/engine/box_build.sh` (40 tests).

## Headline

| | Target | Measured |
|:---|---:|---:|
| VAD end of speech → first answer token (engine, 14 answers) | ≤ 400 ms | **108–306 ms**, median ~150 ms |
| Of that, waiting before generation (`wait_ms`) | — | 50–191 ms |
| VAD silence hangover (added before the above) | — | 500 ms (fixed, `vad_hangover_ms`) |
| Felt delay: user stops talking → first token | < 1 s to first audio | ~0.6–0.8 s (TTS not built yet) |
| Room noise only, listening on | no utterance | **0** utterances, nothing fed to the LM |
| Conversation WAV | 2 questions | **2** utterances, both answered |
| Audio thread cores | never cpu0, never LM cores | cpu1-3 |

## Parts

| | Value |
|:---|---:|
| Silero v4 C++ port vs onnxruntime, max abs diff (goldens) | 4.7e-5 |
| VAD cost per 32 ms chunk | 0.4 ms |
| LFM3 audio encoder, 320 ms of audio on 3 A78 cores | ~21 ms |
| Encoder end flush | 20–57 ms |
| Audio rows | ~13 per second of speech |
| Lm-level speech end → first token (no engine threads) | 127 ms |

## Notes

- The spread in end → first token is `wait_ms`: how many rows the encoder flushes at the end depends on where speech
  stops inside its window, and those rows are decoded before the answer starts.
- Spoken answers were cut short ("The capital of Singapore is **") until text-only sampling: after a spoken question
  LFM3 opens an interleaved text + speech block (`<|mixed_start|>`). The engine bans `<|audio_start|>` and
  `<|mixed_start|>` (logit bias −∞), as llama.cpp's text mode does.
- Next refinement: start answering speculatively after ~250 ms of silence and drop it if speech resumes, to cut most
  of the 500 ms hangover.
