# Step 1 speed tests: Q4_0 and thread placement (2026-11-24)

Plan: `docs/superpowers/plans/2026-11-24-speedup-quick-tests.md`. Spec: `docs/superpowers/specs/2026-11-24-speedup-quick-tests-design.md`.
Scope cut (Haziq, 2026-11-24): only the weights format and thread tests ran. The 112-token canvas is deferred until
the engine exists, where it becomes a one-flag experiment.

## Setup

- Box: Radxa Dragon Q8B (SC8280XP). Big cores cpu4-7 = Cortex-X1C 2995 MHz, small cpu0-3 = Cortex-A78C 2438 MHz.
- llama.cpp b12679 CPU build. `llama-bench -p 220 -n 64 -r 3` (220 = the image tokens of one 640x352 frame).
- Quality: the 12 test cases answered by `cortex-embd answer` from the NPU features of the vision run
  (`npu_run2`), greedy, "One sentence.", via `python -m cortex_core.npu.answer_cases`.
- Script: `core/scripts/lm/bench_quant_threads.sh`. 30 s pause between settings; CPU stayed at 62-67 °C.
- Settings: **t4** = 4 threads, no pinning (llama.cpp's default, what `cortex-embd` used until now);
  **t4big** = 4 threads pinned to cpu4-7; **t8** = 8 threads on all cores.

## Results

| weights | setting | prompt read (t/s, 220 tok) | generate (t/s, 64 tok) | answers right | time to first word, median (min-max) |
|:---|:---|---:|---:|:---|:---|
| Q4_K_M | t4 | 107.6 | 24.4 | 12/12 | 2.35 s (2.29-2.40) |
| Q4_K_M | t4big | 108.1 | 24.4 | 12/12 | 2.32 s (2.29-2.35) |
| Q4_K_M | t8 | 154.8 | 22.6 | 12/12 | 1.65 s (1.61-1.69) |
| **Q4_0** | t4 | 209.6 | 25.7 | 12/12 | 1.24 s (1.22-1.40) |
| **Q4_0** | **t4big** | **209.7** | **25.8** | **12/12** | **1.23 s (1.20-1.24)** |
| Q4_0 | t8 | 245.5 | 23.7 | 12/12 | 1.04 s (1.02-1.08) |

## Answers, Q4_K_M vs Q4_0 (t4big)

6 of 12 are word for word the same (t001, t002, t004, t005, t007, t010). The other 6 name the same object and differ
in detail:

| frame | Q4_K_M | Q4_0 |
|:---|:---|:---|
| t003 | The plush toy is teal (a blue-green) with a white belly. | The plush toy is teal (blue-green) with a white underside. |
| t006 | A black computer mouse is in front of you. | A black computer mouse is in front of you, resting on a gray fabric surface. |
| t008 | This is a television remote control. | This is a television remote control resting on a gray bedspread. |
| t009 | A white television remote control is lying on the bed. | A white remote control is lying on the bed. |
| t011 | This is a smartphone (an iPhone), shown with its screen on and home button visible. | The device is a smartphone, shown with its screen on and home button visible. |
| t012 | ...a black portable power bank (power station). | ...a black and silver portable power bank. |

Q4_0 dropped "iPhone" (t011) and "television" (t009) once each, and added scene detail elsewhere. No wrong object.

## Decisions

- **Q4_0 is adopted** (spec rule: 12/12 and faster). It reads image tokens **1.94x faster** at 4 threads
  (209.7 vs 108.1 t/s) and generates 6% faster. The box has the dot-product instructions its fast path uses.
- **The LM gets the 4 big cores.** 8 threads is only 15% faster to first word with Q4_0 (1.04 vs 1.23 s), generates
  8% slower, and takes every core, which would starve the safety path and speech. The small cores stay free for
  the L0 Guardian, audio and speech.
- Pinning to cpu4-7 changed nothing measurable vs unpinned 4 threads (the scheduler already puts them on the big
  cores), but the engine pins anyway so the core split is guaranteed.

## What it means for the engine

One full image read (NPU encode ~255 ms + 220-token prefill at ~210 t/s ≈ 1.05 s) is now **~1.3 s**, down from ~2.3 s.
In hands-free mode the engine can refresh the view in the background about once every 1.3 s on 4 cores. Answer time
after the question is then the question tokens only (estimate, to be measured in step 2).

## Caveats

- Same narrow 12-frame set as the NPU vision run (5 objects, one room). It shows Q4_0 ≈ Q4_K_M here, not in the world.
- Text, tool calls and audio questions were not tested with Q4_0. Step 2 must re-check them.
- No power meter: speed only.
