# Safety (head-level ToF) in simulation, 2026-11-26

V3 safety was broken (spam, no ground logic), so V4 safety is new code (`core/cortex_core/safety/`), designed against
a simulator written independently of it (`core/tests/safety_sim.py`). **Nothing here has run on real hardware**: no
glasses, no VL53L7CX, no ESP32 USB transport yet. These numbers say the logic is sound under the modelled physics,
not that the product works.

## What it does

- Input per frame (15 Hz): 8x8 ToF distances + the IMU over that frame (mean accel, summed gyro), from the
  ESP32-S3 over USB (transport not built).
- Tilt from a complementary filter (gyro + gravity). Every zone is turned into a level-frame point.
- Eye height: set at fitting (the app asks), refined from the floor whenever it is seen steeply within 2.2 m.
- Band: zones between 0.8 m and eye height + 0.25 m, within 0.4 m of the walking line, split left / centre / right.
- **Grounded test** (the core idea): the nearest object in a sector is flood-filled in the image; each of its
  columns on the walking line walks down. Support at cane height = grounded (wall, pole, person): the cane finds it,
  never warned. A ray reaching under it = overhanging (branch, sign, tailgate, header): warned. Columns vote;
  support needs 2:1; a "pass" right beside a supporting column is ignored (partial-coverage edge).
- **Warning policy**: time to contact. "ahead" at about 1.6 s (1.3 s while the object has never been seen open
  underneath), "close" at 0.7 s or 0.5 m. Each obstacle at most once per level; cooldowns; tracks hand over between
  sectors; a warned obstacle is remembered by bearing (integrated yaw) and distance for 30 s, so scanning while
  standing does not re-warn. No new first warnings while the head swings faster than 150 deg/s.
- Vibration only (left / right / both motors). Blind (sensor error, no frames, lens covered 2 s) = "degraded"
  vibration + the baked-in audio cue, repeated every 5 s, never silent. Bad config = the whole default set.

## Simulator

- Sensor: 60 deg FoV per axis (assumed; confirm on the part), 4x4 sub-rays per zone, a zone needs 25 % coverage;
  the reported distance is the mean of the nearest chained surface (sub-ray gaps < 0.10 m). Range limit
  3.5 m x reflectance (floor 0.8), noise 8 mm + 1.5 %, 3 % dropouts, glass invisible.
- Walker: random speed, eye height (about 1.45-1.75 m), head pitch, step bob / sway / roll at cadence, yaw sway,
  look-around events. IMU synthesised with gyro bias up to 0.5 deg/s and noise.
- Timing: the frame is the world at mid-integration; a warning reaches the skin 5 ms (USB) + 40 ms (motor) later.
- Lead = contact time - warning on the skin. Must-warn needs >= 0.7 s, or, when the target can only be seen from
  `max_range x reflectance` (sunlight, dark targets), that visible time - 0.35 s (3 confirming frames + latency):
  the logic cannot beat physics, and the table says so.
- "Fitted" = eye height from setup within +-5 cm of the truth; "unfitted" = the 1.6 m default, learned from the floor.
- Processing time is pure Python on the server (median 0.025 ms/frame); the box is slower, but the frame is 66 ms.

Run: `cd core && python -m tests.safety_sim --seeds 100 [--unfitted]`. Quick gate: `tests/test_safety_sim.py`
(10 seeds each, about 25 s) + unit tests `tests/test_safety.py`.

## Results, 100 seeds, fitted

| Scenario | Must | Pass | Lead p10 / median (s) | Failures (seed: why) |
|:--|:--|--:|:--|:--|
| branch ahead | warn | 100/100 | 1.10 / 1.40 |  |
| signboard right | warn | 100/100 | 1.34 / 1.50 |  |
| tailgate at waist | warn | 99/100 | 1.46 / 1.69 | 69: 3 warnings for one obstacle |
| shelf on the left | warn | 100/100 | 1.27 / 1.51 |  |
| low door header | warn | 99/100 | 0.95 / 1.43 | 15: lead 0.50s < 0.70s |
| pipe at head height | warn | 100/100 | 1.37 / 1.65 |  |
| truck mirror | warn | 100/100 | 1.13 / 1.42 |  |
| branch, looking down | warn | 100/100 | 1.12 / 1.41 |  |
| branch, fast walker | warn | 100/100 | 0.88 / 0.88 |  |
| branch, slow walker | warn | 100/100 | 1.40 / 1.60 |  |
| branch in sunlight | warn | 70/100 | 0.53 / 0.70 | 0: lead 0.61s < 0.65s; 1: lead 0.45s < 0.46s; 8: lead 0.69s < 0.70s ... |
| dark sign | warn | 84/100 | 0.64 / 0.79 | 17: lead 0.60s < 0.60s; 20: lead 0.60s < 0.62s; 24: lead 0.66s < 0.68s ... |
| branch over a trunk 1 m behind | warn | 100/100 | 1.11 / 1.35 |  |
| door swings open | warn fast | 100/100 | 0.45 / 0.45 |  |
| open path, looking around | stay quiet | 100/100 |  |  |
| wall ahead, stop 0.8 m | stay quiet | 96/100 |  | 12: false alarm at 2.31s; 57: false alarm at 2.11s; 62: false alarm at 6.45s ... |
| pole ahead | stay quiet | 94/100 |  | 10: false alarm at 2.18s; 37: false alarm at 3.71s; 45: false alarm at 1.65s ... |
| person standing ahead | stay quiet | 97/100 |  | 26: false alarm at 1.78s; 50: false alarm at 1.51s; 61: false alarm at 1.51s |
| ceiling 2.3 m | stay quiet | 100/100 |  |  |
| stairs up | stay quiet | 100/100 |  |  |
| looking at the phone | stay quiet | 100/100 |  |  |
| branch beside the path | stay quiet | 100/100 |  |  |
| parked car beside | stay quiet | 100/100 |  |  |
| canopy 2.4 m | stay quiet | 100/100 |  |  |
| glass wall (sensor can't see glass) | stay quiet | 100/100 |  |  |
| standing 0.6 m from a branch, scanning | <= 2 warnings | 100/100 |  |  |

Processing per frame (this machine, pure Python): median 0.025 ms, p99 0.230 ms, max 1.551 ms over 264148 frames.

## Results, 100 seeds, unfitted (1.6 m default)

| Scenario | Must | Pass | Lead p10 / median (s) | Failures (seed: why) |
|:--|:--|--:|:--|:--|
| branch ahead | warn | 100/100 | 1.10 / 1.40 |  |
| signboard right | warn | 100/100 | 1.31 / 1.50 |  |
| tailgate at waist | warn | 98/100 | 1.41 / 1.67 | 44: lead 0.37s < 0.70s; 69: 3 warnings for one obstacle |
| shelf on the left | warn | 100/100 | 1.26 / 1.50 |  |
| low door header | warn | 100/100 | 0.95 / 1.41 |  |
| pipe at head height | warn | 100/100 | 1.36 / 1.60 |  |
| truck mirror | warn | 100/100 | 1.12 / 1.41 |  |
| branch, looking down | warn | 100/100 | 1.12 / 1.44 |  |
| branch, fast walker | warn | 100/100 | 0.88 / 0.88 |  |
| branch, slow walker | warn | 100/100 | 1.40 / 1.60 |  |
| branch in sunlight | warn | 70/100 | 0.53 / 0.70 | 0: lead 0.61s < 0.65s; 1: lead 0.45s < 0.46s; 8: lead 0.69s < 0.70s ... |
| dark sign | warn | 84/100 | 0.64 / 0.79 | 17: lead 0.60s < 0.60s; 20: lead 0.60s < 0.62s; 24: lead 0.66s < 0.68s ... |
| branch over a trunk 1 m behind | warn | 100/100 | 1.11 / 1.37 |  |
| door swings open | warn fast | 100/100 | 0.45 / 0.45 |  |
| open path, looking around | stay quiet | 100/100 |  |  |
| wall ahead, stop 0.8 m | stay quiet | 98/100 |  | 80: false alarm at 2.18s; 81: false alarm at 7.04s |
| pole ahead | stay quiet | 92/100 |  | 1: false alarm at 3.44s; 24: false alarm at 1.98s; 37: false alarm at 3.71s ... |
| person standing ahead | stay quiet | 96/100 |  | 23: false alarm at 1.65s; 50: false alarm at 1.51s; 54: false alarm at 4.38s ... |
| ceiling 2.3 m | stay quiet | 100/100 |  |  |
| stairs up | stay quiet | 100/100 |  |  |
| looking at the phone | stay quiet | 100/100 |  |  |
| branch beside the path | stay quiet | 100/100 |  |  |
| parked car beside | stay quiet | 100/100 |  |  |
| canopy 2.4 m | stay quiet | 100/100 |  |  |
| glass wall (sensor can't see glass) | stay quiet | 100/100 |  |  |
| standing 0.6 m from a branch, scanning | <= 2 warnings | 100/100 |  |  |

Processing per frame (this machine, pure Python): median 0.025 ms, p99 0.229 ms, max 1.460 ms over 264148 frames.

## Honest reading

- Overhangs in the path (branch, sign, tailgate, shelf, header, pipe, mirror): 99-100 %, median lead 1.35-1.7 s.
  Misses: one door header (seed 15, lead 0.50 s: the far door posts and the doorway share zones, read as support
  until 1.9 m) and, unfitted, one tailgate (seed 44, 0.37 s).
- Sunlight / dark targets: 70 % / 84 % even against the physics-bounded bar, and median lead only 0.7-0.8 s: the
  sensor sees them from 1.2-1.4 m. The warning comes, but late. Real sunlight range must be measured.
- False alarms: walls 2-4 %, poles 6-8 %, people 3-4 % of approaches. Each is one "ahead" pulse for something the
  cane would have found. Causes seen: a far object read before its foot is in view; thin poles flickering at the zone
  edge. Tried and rejected: weighting far support lower (fixed the door case, doubled wall/pole false alarms).
- Glass is invisible to ToF: no warning, by physics.
- Standing and scanning next to a branch: never more than 2 warnings in 20 s (100/100).
- Without fitting (1.6 m default, learned from the floor) the results are about the same here: walls are slightly
  better, poles and people slightly worse. The sim only spans eye heights 1.45-1.75 m; a short user or a child is
  far from 1.6 m, so fitting stays required.

## Lessons from iterating (each found by the simulator, not by guessing)

1. Grazing or near-range-limit floor reads high (a zone only sees the near part of its floor strip): ground fixes
   only from rays >= 20 deg down, within 2.2 m.
2. Zone quantization: a zone is 7.5 deg, so an object's lower edge reads lower than it is (a waist-high tailgate's
   edge read at 0.7 m = "support"). Support must be half a zone below the band at its range.
3. Point lists cannot tell door posts from a doorway: walk down each image column of the object and vote.
4. A thin pole's foot covers part of a zone and flickers: grounded evidence is asymmetric (+3 / -1) with hysteresis.
5. A track that restarts far and then reads near looked like a sudden approach: a 0.6 m jump either way is a new
   surface.
6. Standing still re-warned on every head turn: remember warned obstacles by bearing + distance.

## Not done

ESP32-S3 USB transport (dedicated CDC), the real VL53L7CX + IMU driver, motor driver and the degraded cue sink
(entry point still reports "degraded" on purpose), SCHED_FIFO/mlockall in-process, eye-height question in the app,
real-world tuning (sunlight range, FoV, mounting angle on the bridge).
