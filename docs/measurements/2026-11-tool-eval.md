# M0 tool-call eval: stand-in run on the server (2026-11-26)

**This is not the M0 gate.** The gate is LFM3-Omni-2B Q4_0 on the box through the Cortex engine, typed and spoken
(`python -m cortex_core.brain.tool_eval run --spoken ...`). The box was off (it hard-shuts down under sustained NPU
load and only comes back with a power cycle), so this run uses what the server has:

| | |
|:---|:---|
| Model | `LFM3-1.7B-Q4_K_M.gguf` (text-only LFM3; the box runs LFM3-Omni-2B, a different checkpoint) |
| Runtime | llama.cpp b12034 `llama-server --jinja -c 4096 --reasoning off`, i5-12400 CPU, 6 threads |
| Harness | `tool_eval run --llama-server URL`: the same system prompt (`brain/prompt.py`), tools (`contracts/tools/tools.json`), 43 cases and scoring as the box run; llama.cpp's own LFM chat template and tool-call parser instead of the engine's |
| Cases | typed only (35 tool cases, 8 chit-chat; 13 Singlish) |
| Gate | tool >= 90 %, args >= 85 %, 0 chit-chat calls |

## Results

| Run | Tool | Args | Chit-chat calls | Singlish tool | Median ms | Verdict |
|:---|---:|---:|---:|---:|---:|:---|
| Tools as committed before | 95.3 % | 85.7 % | 2 | 100 % | 2988 | FAIL (chit-chat) |
| `bus_arrivals` wording fixed (2 identical runs) | 95.3 % | **94.3 %** | 2 | 92.3 % | 3133 | FAIL (chit-chat) |

## What it found

- **The model left out the bus number.** "How long more for the 969?" became `bus_arrivals {}`.
  - The schema invited it: all arguments optional, and `service` said "empty = all services".
  - 5 of the 6 bus-number cases missed their argument.
  - Fixed in `contracts/tools/tools.json`: the tool says "when the user names a bus number, always pass it as service",
    and `service` says "leave out only if they named no bus". Now 4 of 6 pass.
  - Still failing: "Bus 167 reach already or not?" and "Is the 39 coming soon?".
- **Chit-chat calls.** "What is two plus two?" and "Wah today very hot hor." answer correctly in words, then *also*
  call `set_mode IDLE`.
  - Harmless to the user: Cortex is already IDLE. It still costs a tool round trip.
  - A prompt line ("general questions and small talk need no tool") made the score *worse* (tool 88 %, 3 chit-chat
    calls), so it was reverted.
  - The first run also had "What day comes after Monday?" call `search_places home`. That one would be wrong to
    speak.
- **The output was not stable across runs.** The first run dropped "858" from the bus question, and later runs at
  temperature 0 did not.
- **Not tuned further** against these same 43 cases on a stand-in model, to avoid overfitting the eval.

## Still to do (box, with Haziq there)

1. Find the cause of the shutdowns first (`journalctl -b -1`; power vs heat: the CPU baseline hit 92 °C).
2. `tool_eval wavs`, then `tool_eval run --spoken`. Typed and spoken on LFM3-Omni-2B Q4_0 is the real gate.
3. If chit-chat calls remain:
   - LoRA (planned on the Windows PC), or
   - have the Brain drop a `set_mode` to the mode Cortex is already in, so the turn is not lengthened.
