# Gemini takeover (2026-11-26)

Haziq's rule: Gemini takes over **only when the local LM is unsure and there is internet**.

## Decisions

- **"Unsure" is the LM's own call.** The LM calls `second_opinion(question)` instead of answering. A first-token
  `<tool_call>` is silent, so nothing wrong is said before the takeover. There is no hedge detection on spoken
  text, no "check that" trigger and no `check` disagreement trigger.
- **Through our gateway.** The box never holds a Gemini key. It posts to `POST /device/second-opinion` on the
  gateway's device listener with its mTLS identity. The gateway asks Gemini with the server's key and caps each
  device at 6 requests a minute and 100 a day.
- **Video, not a photo (Haziq, same day).** Gemini 3.8 Live Extended Thinking, thinking LOW, gets the last few
  seconds at one frame a second, so it can reason about motion and spatial layout.
- **Internet = the gateway answers.** If the box can't connect within 3 s (no internet, no claimed identity, TLS
  refused), the takeover says "I'm not sure, and I can't check online right now." If the gateway answers with an
  error (rate limit, Gemini down, not set up), it says "I'm not sure, and I couldn't check that just now." It
  never guesses and never crashes the turn.

## Flow

1. The user asks. The LM is not sure and calls `second_opinion(question)` (spoken_by `template`, all modes).
2. The brain dispatches it on the tool thread. "Checking." is spoken after 0.7 s, as for every tool.
3. `Takeover.run(question, brain.camera_on)`:
   - The camera thread keeps a `FrameRing`: one RGB frame a second, the newest 4, in RAM only.
   - Camera on: `capture.fresh_clip(cam, since)` encodes those frames to JPEG (Pillow, else ffmpeg), oldest
     first. Only frames taken since the camera was last turned on (`Brain.camera_since`), the newest at most
     2 s old, and one run without gaps. Camera off: no frames. Frames taken while it was off are never sent.
   - `provision.second_opinion_client(p)(question, frames)` posts `{question, frames_jpeg}` over mTLS: 3 s to
     connect, 30 s for the answer.
4. The gateway (`internal/gemini`):
   - checks the question (1..500 bytes) and the frames (at most 6, each a JPEG under 512 kB);
   - opens a Gemini Live WebSocket session (`BidiGenerateContent`, key in the `x-goog-api-key` header):
     model `gemini-3.8-live-extended-thinking`, `thinkingLevel` LOW, `responseModalities` AUDIO with
     `outputAudioTranscription` (this model refuses TEXT);
   - sends Cortex's speaking rules as the system instruction (at most two short sentences, never invent numbers,
     names or routes it cannot read, positions relative to the user, never colour alone, no filler, say plainly
     when the frames don't show it);
   - sends the frames inline in one user turn, then the question, and reads the transcription sentence by
     sentence until `interactionStatus` IDLE (25 s cap), at most 400 chars of whole sentences.
   Frames and questions are passed through, never stored or logged.
5. The brain speaks Gemini's answer as is through `ce_tool_result(say=...)`, so it is also recorded in the
   conversation and follow-ups can use it. The tool result carries `{"answer", "source": "gemini", "frames"}`.

## What the real API did (2026-11-26, synthetic frames: a bus "858" moving left, pole on the left)

| Try | Result |
| --- | --- |
| `responseModalities` TEXT | Refused (close 1007). AUDIO + transcription works. |
| 4 frames sent at once on `realtimeInput.video`, then the question | Not seen: "the frames do not show any bus" (3/3). |
| Same, paced 1 s apart | Seen (3/3), but costs 4 s before the question can go. |
| 4 frames inline in the user turn (used) | Seen and motion right 3/3; through the gateway 2/2: 7–8 s to the full answer. |
| First system prompt, without "never invent" | Once said "route 27 to Hammersmith" (made up); with the rule, not again. |
| The model may speak a filler first ("Checking the arrival details") | The prompt forbids filler; the client still waits for IDLE. |

About 3,000–3,400 input tokens per question with 3–4 frames.

### Streaming the answer (built 2026-11-26)

Gemini's transcription arrives at speaking pace, so on a two-sentence answer the first sentence is finished seconds
before the turn ends. The box asks with `Accept: application/x-ndjson`; the gateway sends `{"sentence"}` for each
sentence once Gemini has started the next one (a fragment later, not a sentence later), then
`{"done", "answer", "rest"}`. The box speaks each early sentence at once (after "Checking.") and hands `rest` to the
engine as the template, so the whole answer is in the tool result and nothing is said twice. The last sentence is
always held back, because the engine has no "record without speaking" call. A drop mid-answer is now an error, not
a short answer: the box says "Sorry, I lost the rest of that answer." With no frames, Gemini is told "The camera is
off" (it used to answer "the frames do not show...").

Real API through the gateway (4 synthetic frames): first sentence spoken at 3.4 s and 3.9 s, whole answer at 6.3 s
and 7.4 s. A one-sentence answer gains nothing (it ends with the turn).

## Configuration

| Where | Setting |
| --- | --- |
| Gateway | `CORTEX_GEMINI_KEY_FILE` (chmod 600) or `CORTEX_GEMINI_KEY`; `CORTEX_GEMINI_MODEL` (default `gemini-3.8-live-extended-thinking`); `CORTEX_GEMINI_BASE` (tests only, a ws:// URL). No key: 503, and the box says it is not sure. |
| Box | The claimed identity in `--identity-dir` (`/var/lib/cortex/identity`). |

## Not done / not measured

- No tool-eval cases yet for when the real LM should call `second_opinion`. How often it does (or calls it
  instead of answering things it knows) is unmeasured.
- Only synthetic frames so far. Real camera frames (blur, glare, crowds) are untested.
- Latency on the box is unmeasured: 4 JPEG encodes via ffmpeg plus the round trip. On the server the first
  sentence is heard at about 3.5–4 s (streamed), the whole answer at 6–7.5 s.
- The Gemini Live voice switch ("talk to Gemini") is a separate feature and is not built.
