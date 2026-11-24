# Engine step 3: hands-free voice in (design, as built)

**Why:** a blind user asks questions by talking, not typing; the answer must start soon after they stop. Step 3 of
the parallel engine (`docs/architecture/CORTEX-ENGINE.md`).

**Decided by Haziq:** the button only toggles automatic listening; the VAD decides where each question starts and
ends. Everything else was delegated ("choose the best ... make it work"), so the calls below are Claude's.

## Approaches

1. **Batch:** VAD finds the end, then encode the whole utterance and read it. Simple; costs the full encode + read
   (~0.5–1 s for a 3 s question) after speech ends. Rejected: too slow.
2. **Streaming (chosen):** encode in pieces while the user talks (LFM3 mtmd audio stream) and decode rows into the
   conversation slot S as they arrive. After the end only the tail remains (108–306 ms measured).
3. **Separate ASR (Whisper) then text:** a second model, more RAM and latency, and loses LFM3's native audio input.
   Rejected.

## Design

- `Listener` (Silero VAD v4 port, `src/vad.cpp`): pre-roll 320 ms, start after 96 ms ≥ 0.5, end after 500 ms
  < 0.35, 96 ms tail, 30 s cap.
- Audio thread (cpu1-3) runs the Listener and `AudioIn` (encode only; it never calls llama_decode, because a thread
  that decodes on the LM pool gets pinned to cpu4). The LM worker decodes all rows.
- Speech start: refresh the view, cancel a running answer (barge-in), refuse typed asks while the user speaks.
- Speech end: preempt background reads, answer under the big-core gate.
- A spoken turn is kept in history as its audio rows (no transcript).
- Text-only sampling: `<|audio_start|>` and `<|mixed_start|>` banned.

## Calls made under delegation (cost if wrong)

- Silero v4, not v5/v6 (the v5 download was declined). Cost: slightly worse VAD on hard noise; swap the weights file.
- A short question that ends before the speech-start view is read uses the previous view. Cost: an answer about a
  view up to ~1.4 s old.
- Barge-in cancels the answer immediately. Cost: a cough cancels an answer; the VAD's 96 ms confirm limits this.
- No transcript of spoken turns. Cost: the app cannot show what the user said.
- `end_to_first_ms` test budget 400 ms (measured 108–306). Cost: a slow regression under 400 ms passes.
