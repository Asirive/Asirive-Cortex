# LFM3-Omni-2B baseline on the Dragon Q8B (stock llama.cpp, CPU and GPU)

Run 2026-11-24 by Haziq + Claude over SSH. Plan: `docs/superpowers/plans/2026-11-24-lfm-baseline-and-tui.md`, Task 4.
Target from the design: answer starts in **under 1 s**, with fresh vision.

## Setup

| | |
|---|---|
| Board | Radxa Dragon Q8B, Qualcomm SC8280XP (4x Cortex-X1C + 4x Cortex-A78C), 7.3 GB RAM, Adreno 690 |
| OS | Radxa OS = Ubuntu 26.04.1 LTS, kernel 7.0.11-7-qcom, **headless** (multi-user.target), root on a USB drive (SD card was lost) |
| Idle RAM | 0.44 GB used headless (4.4 GB with the GNOME desktop + browser + Claude Desktop) |
| llama.cpp | release **b12679**, built with `core/scripts/build_llama.sh`: `build-cpu` and `build-gpu` |
| GPU backend | **Vulkan** (Mesa Turnip, "Turnip Adreno (TM) 690", 5.5 GB visible). Radxa OS ships no Adreno OpenCL driver (`clinfo`: no platforms), so the OpenCL/Adreno-kernel path could not be tried |
| Model | `LFM3-Omni-2B-Q4_K_M.gguf`, sha256 `9f8d30e9d4fd7a9349d586e077988229b3ca0a0e4ad730897563d1eccc9893e2` (1.10 GB) |
| Projector | `mmproj-LFM3-Omni-2B-Q8_0.gguf`, sha256 `8a25f9d1931244429de404fccacfb7fb933970a36aa5688d2f5069f29c6b27b1` (0.51 GB) — Liquid's own README pairs Q4_K_M with this projector |
| Source | huggingface.co/LiquidAI/LFM3-Omni-2B-GGUF, hashes match the Hub's listed values |
| Licence | **LFM Open License v1.0**: free, commercial use included, while annual revenue is under US$10M; a copy of the licence must go with any redistribution of the model |
| Server | `llama-server -c 4096 --temp 0 --reasoning off` (+ `-ngl 99` for GPU); prompt cache off per request; 1 warm-up + 5 measured runs per case |
| Media | `scene1.jpg`: ZV-1F frame (USB webcam mode), 1280x720, a blue plush shark on a bed in front of a window. `question1/2.wav`: generated with the model's own `llama-tts` (clean synthetic voice, 16 kHz mono) because no voice recordings were available yet. `room_noise.wav`: 5 s of a quiet room from the ZV-1F mic (−42.5 dBFS) |

## NPU probe

`reachable: true`: `/dev/fastrpc-cdsp` and `/dev/fastrpc-cdsp-secure` exist, the `cdsp` and `adsp` remote processors are
`running`, and `libcdsprpc.so` is installed. **No `libQnnHtp*.so`**: Qualcomm's QNN/QAIRT runtime is not installed.
So the NPU is reachable at the driver level; using it needs either QAIRT on the box or llama.cpp's Hexagon backend.

## CPU (`build-cpu`)

| case | ok/failed | first token s (med/p90) | first audio s (med/p90) | prefill tok/s | decode tok/s | prompt tok / cached | server peak RAM MB (so far) | max temp °C | power W (mean/max) | < 1 s? |
|---|---|---|---|---|---|---|---|---|---|---|
| text_short | 5/0 | 0.23 / 0.26 | n/a / n/a | 100.3 | 21.2 | 23 / 0 | 2800 | 68.8 | n/a / n/a | yes |
| image_describe | 5/0 | 14.00 / 14.09 | n/a / n/a | 64.7 | 20.6 | 904 / 0 | 3219 | 92.0 | n/a / n/a | no |
| audio_question | 5/0 | 0.69 / 0.71 | n/a / n/a | 89.2 | 20.9 | 61 / 0 | 3223 | 88.0 | n/a / n/a | yes |
| audio_image | 5/0 | 14.81 / 14.86 | n/a / n/a | 64.8 | 20.0 | 954 / 0 | 3307 | 88.0 | n/a / n/a | no |

## GPU (`build-gpu`, Vulkan, `-ngl 99`)

| case | ok/failed | first token s (med/p90) | first audio s (med/p90) | prefill tok/s | decode tok/s | prompt tok / cached | server peak RAM MB (so far) | max temp °C | power W (mean/max) | < 1 s? |
|---|---|---|---|---|---|---|---|---|---|---|
| text_short | 5/0 | 0.42 / 0.44 | n/a / n/a | 55.3 | 20.1 | 23 / 0 | 692 | 88.0 | n/a / n/a | yes |
| image_describe | 5/0 | 12.19 / 12.24 | n/a / n/a | 74.3 | 20.0 | 904 / 0 | 895 | 88.0 | n/a / n/a | no |
| audio_question | 5/0 | 0.95 / 0.96 | n/a / n/a | 64.7 | 20.1 | 61 / 0 | 899 | 88.0 | n/a / n/a | yes |
| audio_image | 0/5 | n/a / n/a | n/a / n/a | n/a | n/a | n/a / n/a | n/a | 88.0 | n/a / n/a | n/a |

`audio_image` on GPU: the server died with `vk::DeviceLostError` (Turnip driver lost the GPU). The server log also says
Flash Attention runs on the CPU for this model ("missing support"); a run with `-fa off` was no better (text_short 0.44 s, 19.8 tok/s).
GPU RAM is lower only because the weights sit in GPU-mapped memory, not in the server's own RSS.

## Image size sweep (CPU, same photo, `image_describe`)

| width | prompt tokens | first token s (med/p90) | answer |
|---|---|---|---|
| 1280 px | 904 | 13.97 / 14.23 | "A teal plush shark toy is directly in front of you." |
| 640 px | 244 | 3.33 / 3.39 | "A blue plush shark toy is directly in front of you." |
| 384 px | 108 | 1.57 / 1.58 | "A teal plush **pillow** is directly in front of me." (wrong) |

## Speech in and out (CPU)

| test | result |
|---|---|
| ASR of `question1.wav` | "What is the capital of Singapore and how big is it?" — exact, first token 0.66 s |
| ASR of `question2.wav` | "What is the animal in front of me, and what color is it?" — exact, 0.69 s |
| Answer to spoken q1 | "The capital of Singapore is Singapore, and it covers an area of about 710 square kilometers." — 0.62 s |
| ASR of 5 s quiet room, nobody speaking | **"Thank you." — 3 out of 3 times** (hallucination) |
| `llama-tts`, CPU | 4.0 s of speech in 4.4 s: **0.91x real time** (3.2 s in ~4.9 s incl. model load for the question clips) |
| `llama-tts`, GPU (Vulkan) | **0.00 s of audio** — broken on this driver |

Speech output was not measured through the chat API: in stock llama.cpp, LFM3-Omni speaks through `llama-tts` and the
`/v1/realtime` WebSocket of `llama serve`, not `/v1/chat/completions`. First-audio is therefore n/a in the tables above.

## Power and thermals

**Power: not measured.** The only power-supply entries on the board are its two USB-C (UCSI) ports, offline at 0 V / 0 A;
the board has no battery/fuel gauge. (The first GPU text run printed "0.00 W"; that was a reader bug, now fixed:
offline and zero supplies count as unknown.) Watts per query and idle draw need a **USB-C/DC power meter** — still to do.

**Temperature: the "max temp" column is not the CPU.** It is the hottest thermal zone, and the `pmc8280c-thermal`
power-chip sensor reads **88 °C even at idle**. CPU clocks stayed at their maximum (2.4 / 3.0 GHz) after the runs, so no
throttling was seen. A CPU-only temperature needs the bench to read the CPU zones only — still to do.

## Findings vs the 1 s target

- **Talking works today.** Text and voice questions start answering in 0.2–0.7 s on CPU, with exact speech recognition
  on clean speech and ~21 tokens/s decode. The voice path is inside the 1 s target with room to spare.
- **Vision does not.** A 1280x720 frame costs ~14 s before the first word; 640 px costs 3.3 s and is the smallest size
  that still gave the right answer (384 px called the shark a pillow). Image encoding is the whole problem: decode speed
  is the same with or without an image.
- **The GPU does not help yet.** Vulkan on Turnip is slower than CPU for text (0.42 vs 0.23 s), only slightly faster for
  images (12.2 vs 14.0 s), crashed on audio+image, and cannot run TTS. It is not usable for the brain on this OS today.
- **Speaking is slower than real time on CPU (0.91x)**, so whole-sentence TTS would leave gaps; speech has to be streamed
  in chunks, or moved off the CPU.
- **Silence becomes "Thank you."** The ASR invents words from a quiet room. This confirms the design: the button/VAD gate
  must decide when speech exists, and the model must never be fed silence.

## What this means for the NPU split

The design already said vision must be encoded in the background and kept fresh (target ≤300 ms old). These numbers show
why and how much: at 640 px the CPU needs ~3 s per frame, ten times the budget, so the **vision encoder is the first thing
to move to the NPU**. The language model block is already fast enough on CPU for short answers; it can stay there until the
encoder is solved. The NPU is reachable at the driver level but has no QNN runtime, so the next step is to get QAIRT (or
llama.cpp's Hexagon backend) running on the CDSP and time the projector there. Until then, a stopgap is to encode one
640 px frame in the background every few seconds and answer from that cached encoding, which keeps the answer itself under
1 s at the cost of the picture being a few seconds old. TTS on CPU at 0.91x also argues for an NPU or streamed TTS path.

## Still to do

- Power meter: idle draw and watts per `image_describe` on CPU.
- Real voice recordings from Haziq (English and Singlish, with background noise) through the ZV-1F mic.
- CPU-only temperature in the bench.
- Bluetooth: the board shows no Wi-Fi/Bluetooth hardware (no PCI device, no `/sys/class/bluetooth`), so the CMF Buds
  could not be paired; needs the M.2 module seated or a USB dongle.
