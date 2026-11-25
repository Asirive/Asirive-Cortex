# Handoff: cortex-engine, speech out (2026-11-26)

Work is moving from the Windows PC to Haziq's server while Haziq travels. This is where things stand and how
to pick them up.

## Where things are

- **Repo / branch**: `Asirive/Asirive-Cortex`, branch **`v4`**. Head is `d2af51f` (plus this doc).
- **Engine**: `core/tools/cortex-engine` (C++, builds into `libcortex_engine.so`), driven from Python through
  `core/cortex_core/engine/native.py`. The design is in [architecture/CORTEX-ENGINE.md](architecture/CORTEX-ENGINE.md),
  with specs and plans in `docs/superpowers/{specs,plans}/2026-11-24-*`.
- **Box**: Radxa Dragon Q8B, `radxa@192.168.0.228` (**LAN only**). Model LFM3-Omni-2B, vision on the NPU (QNN),
  LM on the CPU (llama.cpp).
  - Deployed code: `/opt/cortex`.
  - Models, bench data and config: `/var/lib/cortex/` (`bench/engine/engine.json`, `bench/engine/qnn.env`,
    `bench/media/*.wav`).

## Done in this stretch (all pushed to v4)

| Commit | What |
|---|---|
| `cb08775` | Answers spoken on the headphone jack; mic muted while Cortex talks |
| `d2bc42a` | TUI: Cortex speaks; space cuts it off |
| `443dce1` | Speech-out measurements |
| `bb49178` | Codec output tied to its answer (a new answer drops the old one's queued sound) |
| `d2af51f` | No echo questions, full-length answers, no stutter (details below) |

### `d2af51f` in short

- **VAD "hallucinating"**: the root cause was echo. The mic (ZV-1F) hears Cortex's own voice from the earbuds
  about 450 ms late, and the old 300 ms mute tail ended before the echo did, so Cortex answered itself.
  - The mic now stays off for `echo_lag + mute_tail_ms` after `sound_end`.
  - `echo_lag` is measured every answer: the first mic chunk 12 dB over the room floor after the answer's first
    loud sample is played.
  - Config key `echo_lag_ms` (default 500) is the starting value. `ce_status` reports `echo_lag_ms`.
- **Answers cut off**:
  - Limits are now `max_tokens` 60 → 512 and `max_speech_s` 30 → 60 (max 90). Python `ask()` and the TUI default
    to `0`, which means use the engine's limit.
  - A new context guard: an answer stops at the end of the context (`stop: "max"`) instead of failing with
    "feedback decode failed". A follow-up starts again from the view when S has less than ⅓ of the context free.
- **Stutter**:
  - Generation runs at about 1.08× real time. The speaker used to resume as soon as any audio arrived, which gave
    66 gaps in a 6 s test.
  - Now a ring that runs dry waits for `rebuffer_ms` (default 1000) of lead before playing again. The same test
    shows 1 gap.
- **Tests**: C++ `engine_tests` **73/73** and box pytest **168 passed, 6 skipped**, both on the box.

## NOT verified yet (first thing to do)

1. **Live echo check with the real earbuds.** It was blocked because the ZV-1F had dropped off USB as a
   webcam/mic: it enumerated only as `054c:0830` with no UVC node and no USB audio card. Someone has to wake the
   camera and put it back in USB streaming mode.
   - Then run the live TUI, ask 3 or 4 questions without speaking, and confirm no `speech_start` fires after
     answers.
   - Also watch `echo_lag_ms` in the status (expect about 400 to 500).
2. **Live stutter check.** Listen for pauses on a long answer; the `gaps` field on `sound_end` should be 0 to 1.
   - If the pause is too long, lower `rebuffer_ms`.
   - If there are still many gaps, raise it.
3. **The probe scripts are probably gone.** `echo.py`, `stutter.py`, `align.py` and `probe.py` were only in
   `/tmp/vadprobe/` on the box, and the box went offline at handoff, so a reboot will have wiped them.
   `echo.py` was: open the engine with `engine.json`, camera and mic, listen, ask 4 questions with
   `eng.ask(q, 0)`, record the mic, and print any `speech_start` with its offset after the last `sound_end`.
   Rewrite it under `core/scripts/engine/` if needed.

## Open ideas (not started)

- **Faster speech generation (~5%)**: every decode in the speech loop asks for logits, so `lm_head` runs on audio
  steps too. Skipping it needs a llama.cpp change, because one output flag controls both embeddings and logits.
  That would cut the 7.5% deficit to about 2%, so the rebuffer pauses would almost disappear.
- Better echo handling than muting: real AEC (echo cancellation) would let the user interrupt Cortex by voice.
  Right now only the button cuts Cortex off.

## How to work on it

Run everything from the repo root.

```sh
# copy the engine to the box, build there, run the C++ tests (filter optional, e.g. speak_api)
sh core/scripts/engine/box_build.sh ""
# Python changes are NOT copied by box_build: send the changed files yourself, e.g.
tar -C core -cf - cortex_core/engine/native.py | ssh radxa@192.168.0.228 'tar -C /opt/cortex -xf -'
# pytest on the box
ssh radxa@192.168.0.228 'cd /opt/cortex && PYTHONPATH=/opt/cortex venv/bin/python -m pytest -q tests'
# live TUI on the box (camera + mic + earbuds)
ssh -t radxa@192.168.0.228 'sh /opt/cortex/scripts/engine/live_tui.sh'
```

Any ad-hoc engine script on the box needs `. /var/lib/cortex/bench/engine/qnn.env` sourced first, or the NPU
fails with `deviceCreate failed`.

**Working from the server**: the box is on the home LAN (`192.168.0.x`). The server needs a route to it, such as
running on the same LAN, a VPN, or Tailscale on both. Otherwise `box_build.sh` cannot reach it. Override the
address with `CORTEX_BOX=user@host`.

## Rules (from Haziq)

- Commit and push **as IRSPlays only**: `git -c user.name=IRSPlays -c user.email=<Haziq's address> commit`.
  - **No** `Co-Authored-By` or Claude tag lines.
  - Push only to `v4`.
- Never put SDK files, model weights, calibration/test photos, NPU binaries, goldens, or voice media/WAVs in git.
- Don't touch or commit the uncommitted work in `apps/`, `infra/`, `cortex.py`, `.gitignore` or `CLAUDE.md`.
  Stage explicit paths only, and never `git checkout` files with uncommitted work.
- Haziq runs every `sudo` step; never type passwords. Ask before downloads.
- Open the NPU only once per process.
- Aim for the end goal: the most efficient end-state approach, staged and verified, not the simplest patch.
  Write a failing test first.
- Haziq wants brutal honesty, no false praise.
