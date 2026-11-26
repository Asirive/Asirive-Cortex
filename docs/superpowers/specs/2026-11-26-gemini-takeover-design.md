# Gemini takeover (2026-11-26)

Haziq's rule: Gemini takes over **only when the local LM is unsure and there is internet**.

## Decisions

- **"Unsure" is the LM's own call.** The LM calls `second_opinion(question)` instead of answering. A first-token
  `<tool_call>` is silent, so nothing wrong is said before the takeover. There is no hedge detection on spoken
  text, no "check that" trigger and no `check` disagreement trigger.
- **Through our gateway.** The box never holds a Gemini key. It posts to `POST /device/second-opinion` on the
  gateway's device listener with its mTLS identity. The gateway calls Gemini `generateContent` with the server's
  key and caps each device at 6 requests a minute and 100 a day.
- **Internet = the gateway answers.** If the box can't connect within 3 s (no internet, no claimed identity, TLS
  refused), the takeover says "I'm not sure, and I can't check online right now." If the gateway answers with an
  error (rate limit, Gemini down, not set up), it says "I'm not sure, and I couldn't check that just now." It
  never guesses and never crashes the turn.

## Flow

1. The user asks. The LM is not sure and calls `second_opinion(question)` (spoken_by `template`, all modes).
2. The brain dispatches it on the tool thread. "Checking." is spoken after 0.7 s, as for every tool.
3. `Takeover.run(question, brain.camera_on)`:
   - Camera on: `capture.fresh_jpeg(cam)` encodes the newest RGB frame to JPEG (Pillow, else ffmpeg), but only
     if it is at most 2 s old. Camera off or stale: no image. No frame leaves the box while the camera is off.
   - `provision.second_opinion_client(p)(question, jpeg)` posts over mTLS: 3 s to connect, 15 s for the answer.
4. The gateway (`internal/gemini`):
   - checks the question (1..500 bytes) and the image (a JPEG under 1 MB);
   - sends Cortex's speaking rules as the system instruction (at most two short sentences, positions relative
     to the user, never colour alone, say plainly when the image doesn't show it);
   - cuts the answer at a sentence end, at most 400 chars.
   Frames and questions are passed through, never stored or logged.
5. The brain speaks Gemini's answer as is through `ce_tool_result(say=...)`, so it is also recorded in the
   conversation and follow-ups can use it. The tool result carries `{"answer", "source": "gemini", "image"}`.

## Configuration

| Where | Setting |
| --- | --- |
| Gateway | `CORTEX_GEMINI_KEY_FILE` (chmod 600) or `CORTEX_GEMINI_KEY`; `CORTEX_GEMINI_MODEL` (default `gemini-2.5-flash`); `CORTEX_GEMINI_BASE` (tests only). No key: 503, and the box says it is not sure. |
| Box | The claimed identity in `--identity-dir` (`/var/lib/cortex/identity`). |

## Not done / not measured

- No tool-eval cases yet for when the real LM should call `second_opinion`. How often it does (or calls it
  instead of answering things it knows) is unmeasured.
- Not run against real Gemini: there is no key on the gateway yet. The default model name is unverified.
- Latency on the box is unmeasured: JPEG encode via ffmpeg plus the round trip.
- The Gemini Live voice switch ("talk to Gemini") is a separate feature and is not built.
