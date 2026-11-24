# Step 1 Quick Speed Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure three cheap speed-ups (Q4_0 weights, a 112-token image canvas, big-core thread placement) before the engine is built around today's numbers.

**Architecture:** Make the canvas size a parameter of the existing NPU vision path (640x352 stays the default and is unchanged), give `cortex-embd` a thread option, add one small Python runner that answers the 12 cases from saved features with any model/thread setting, then run the benches on the box and write the numbers up.

**Tech Stack:** Python 3.14 (numpy, PIL, onnxruntime), C++ (`cortex-embd` on llama.cpp b12679), llama-bench, QAIRT 2.42 in WSL, QNN 2.42 on the box.

**Spec:** `docs/superpowers/specs/2026-11-24-speedup-quick-tests-design.md`

## Global Constraints

- No engine, no audio, no brain changes. No change to the 640x352 path: its defaults, constants and outputs stay identical.
- The 112-token path is added beside the 640x352 one, not instead of it.
- Q4_0 is adopted if it answers 12/12 and reads tokens faster. 112 tokens is **not** adopted automatically: Haziq decides from the table, with both answers shown side by side.
- No weights, photos, calibration data or NPU binaries in git.
- Commit as IRSPlays: `git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit`, no Co-Authored-By line. Do not touch or commit uncommitted `apps/` work. Do not push.
- The NPU is opened once per run inside one supervised child (`run_npu` already does this). Never close and reopen it seconds apart.
- The 112-token WSL build deletes per-segment calibration data as it goes (C: has ~7 GB free).
- Box paths: models `/var/lib/cortex/models/` (`LFM3-Omni-2B-Q4_K_M.gguf`, `LFM3-Omni-2B-Q4_0.gguf`, `mmproj-LFM3-Omni-2B-Q8_0.gguf`); llama.cpp `/opt/llama.cpp/b12679/build-cpu/bin`; big cores X1C = cpu4-7, small A78C = cpu0-3.

## Review Focus

1. **Canvas not a multiple of 32** (e.g. a typo `450x256`): `prepare` must refuse with a clear error, not silently produce a wrong token grid. Test in Task 1.
2. **Default path drift:** calling `prepare(rgb)` / `fit_box(w, h)` with no canvas must give byte-identical output to before. Test in Task 1.
3. **Stand-in size that does not lay out the expected tokens:** `cortex-embd answer` dies with "feature has N tokens, the prompt expects M"; the case runner must report that as the case's answer (`ERROR: ...`), not crash the run. Test in Task 2.
4. **Wrong-shape features on disk** (a 220-token feature fed to the 112 path): the runner must not mix them up; feature files are named per canvas run directory. Covered by Task 2's missing-feature test.
5. **Threads option ignored:** `-t 4` must actually set both `n_threads` and `n_threads_batch`; the bench row must record what was asked. Checked on the box in Task 3 (ttft changes between `-t 4` and `-t 8`).

---

### Task 1: Canvas size as a parameter

**Files:**
- Modify: `core/cortex_core/npu/vision_prep.py`
- Modify: `core/cortex_core/npu/make_calib_raw.py`
- Modify: `core/cortex_core/npu/run_npu.py`
- Test: `core/tests/test_npu_vision_prep.py`, `core/tests/test_npu_make_calib_raw.py`, `core/tests/test_npu_run.py`

**Interfaces:**
- Produces:
  - `vision_prep.CANVAS_220 = (640, 352)`, `vision_prep.CANVAS_112 = (448, 256)`; `INPUT_W, INPUT_H` stay `640, 352`.
  - `fit_box(w: int, h: int, canvas: tuple[int, int] = (INPUT_W, INPUT_H)) -> tuple[int, int]`
  - `prepare(rgb: np.ndarray, canvas: tuple[int, int] = (INPUT_W, INPUT_H)) -> np.ndarray` — shape `[ch/32, cw/32, 2, 2, 1536]`; raises `ValueError` if either side is not a positive multiple of 32.
  - `parse_canvas(s: str) -> tuple[int, int]` in `vision_prep` (`"448x256"` → `(448, 256)`).
  - `make_calib_raw(calib_dir, out_dir, canvas=(INPUT_W, INPUT_H))`; CLI: `python -m cortex_core.npu.make_calib_raw <calib_dir> <out_dir> [WxH]`.
  - `save_npu_feat(path, feat, stand_in=(STAND_IN_W, STAND_IN_H))`; `run_npu` CLI gains `--canvas WxH` (default `640x352`) and `--stand-in WxH` (default `640x360`).

- [ ] **Step 1: Write the failing tests**

In `test_npu_vision_prep.py`:
```python
def test_prepare_112_canvas_shape():
    out = prepare(frame(640, 360), canvas=CANVAS_112)
    assert out.shape == (8, 14, 2, 2, 1536)

def test_default_canvas_unchanged():
    f = frame(640, 360, 77)
    assert np.array_equal(prepare(f), prepare(f, canvas=(640, 352)))
    assert fit_box(360, 640) == fit_box(360, 640, canvas=CANVAS_220)

def test_fit_box_112_landscape_fills():
    assert fit_box(640, 360, canvas=CANVAS_112) == (448, 256)

@pytest.mark.parametrize("bad", [(450, 256), (448, 0)])
def test_prepare_refuses_off_grid_canvas(bad):
    with pytest.raises(ValueError, match="multiple of 32"):
        prepare(frame(640, 360), canvas=bad)

def test_parse_canvas():
    assert parse_canvas("448x256") == (448, 256)
```
In `test_npu_make_calib_raw.py`: `test_raw_size_112_canvas` — one 640x360 jpg, `make_calib_raw(..., canvas=(448, 256))`, raw file size == `8 * 14 * 2 * 2 * 1536 * 4`.
In `test_npu_run.py`: `test_save_npu_feat_stand_in` — `save_npu_feat(p, feat, stand_in=(448, 252))` writes json with `image_w == 448`, `image_h == 252`; default call still writes 640/360.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_npu_vision_prep.py core/tests/test_npu_make_calib_raw.py core/tests/test_npu_run.py -q`
Expected: FAIL (ImportError on `CANVAS_112` / `parse_canvas`, unexpected keyword `canvas` / `stand_in`).

- [ ] **Step 3: Implement**

Thread `canvas` through `fit_box` and `prepare` (replace every `INPUT_W`/`INPUT_H` use inside them with the canvas sides); check the multiple-of-32 rule at the top of `prepare`. `make_calib_raw` passes `canvas` to `prepare`; the CLI accepts an optional third arg via `parse_canvas`. In `run_npu.main`, add `--canvas` and `--stand-in` (both parsed with `parse_canvas`), pass the canvas to `prepare` and the stand-in to `save_npu_feat`, and add `"canvas"` and `"stand_in"` to each row. Update the module docstring of `vision_prep` to say the canvas is a parameter.

- [ ] **Step 4: Run to verify they pass, then the whole suite**

Run: `python -m pytest core/tests -q`
Expected: the new tests pass; suite 171+new passed, 6 skipped, the same 2 pre-existing Windows-only failures (`test_identity_and_commands`, `test_phone_link`).

- [ ] **Step 5: Commit**

```bash
git add core/cortex_core/npu/vision_prep.py core/cortex_core/npu/make_calib_raw.py core/cortex_core/npu/run_npu.py core/tests/test_npu_vision_prep.py core/tests/test_npu_make_calib_raw.py core/tests/test_npu_run.py
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "npu: canvas size as a parameter (640x352 default unchanged, 448x256 for 112 tokens)"
```

---

### Task 2: Thread option in cortex-embd + a case runner over saved features

**Files:**
- Modify: `core/tools/cortex-embd/main.cpp` (`load()`, `cmd_answer`)
- Create: `core/cortex_core/npu/answer_cases.py`
- Modify: `core/cortex_core/npu/run_npu.py` (`_answer` moves to `answer_cases.answer`; `run_npu` imports it)
- Test: `core/tests/test_npu_answer_cases.py`

**Interfaces:**
- Consumes: features written by `run_npu` (`<stem>.npu.f32` + `.json`), cases.json (`image`, `question`, `expect`, optional `cpu_answer`).
- Produces:
  - `cortex-embd answer ... [-t N]`: sets `cp.n_threads = cp.n_threads_batch = N` when given; default unchanged.
  - `answer(embd: str, model: str, mmproj: str, feat: Path, prompt: str, threads: int | None = None, prefix: list[str] = ()) -> tuple[str, dict]` — runs `[*prefix, embd, "answer", ..., *(["-t", str(threads)] if threads else [])]`; on non-zero exit returns `("ERROR: <stderr tail>", {})`.
  - CLI: `python -m cortex_core.npu.answer_cases --cases C --feat-dir D --embd E --model M --mmproj P --out OUT.json [--threads N] [--taskset 4-7]` — prints one JSON row per case (`image`, `answer`, `match`, `ttft_s`, `decode_tps`, `model`, `threads`, `taskset`) and `matched X/Y`; writes OUT.json.

- [ ] **Step 1: Write the failing tests** (`test_npu_answer_cases.py`, fake `cortex-embd` = a small Python script written to `tmp_path` that echoes its argv into the answer line and prints a stats JSON line; a second fake exits 1 with "feature has 220 tokens, the prompt expects 112")

```python
def test_answer_passes_threads_and_prefix(fake_embd, tmp_path): ...
    # answer(..., threads=4, prefix=[sys.executable]) -> returned text contains "-t 4"; stats["ttft_s"] == 0.5
def test_answer_reports_embd_failure(failing_embd, tmp_path): ...
    # text startswith "ERROR:" and contains "the prompt expects 112"; stats == {}
def test_cli_rows_and_match_count(fake_embd, tmp_path, capsys): ...
    # 2 cases, feat files present; out json has 2 rows with threads/taskset fields; stdout ends "matched 2/2"
def test_cli_missing_feature_is_a_row_not_a_crash(fake_embd, tmp_path): ...
    # one case whose .npu.f32 is absent -> row answer startswith "ERROR: no feature", match False; exit code 0
```
(`--taskset` is turned into the prefix `["taskset", "-c", value]`; the tests use `prefix` directly so they run on Windows.)

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_npu_answer_cases.py -q`
Expected: FAIL with ModuleNotFoundError `cortex_core.npu.answer_cases`.

- [ ] **Step 3: Implement `answer_cases.py`** and switch `run_npu` to import `answer` from it (behaviour of `run_npu` unchanged; its existing tests stay green).

- [ ] **Step 4: Run to verify they pass, then the whole suite**

Run: `python -m pytest core/tests -q`
Expected: new tests pass; same 2 pre-existing failures only.

- [ ] **Step 5: Add `-t` to `cortex-embd`, rebuild on the box**

`load()` takes `int n_threads` (0 = library default) and sets both thread fields when > 0; `cmd_answer` reads `-t`. Copy `main.cpp` to the box and rebuild with the existing build command for `/opt/llama.cpp/cortex-embd`.
Run on box: `cortex-embd answer -m .../Q4_K_M.gguf --mmproj ... --feat /var/lib/cortex/bench/npu/npu_run2/t001.npu.f32 -p "What is this? One sentence." -t 4`
Expected: an answer naming the shark and a stats line; the same command without `-t` still works.

- [ ] **Step 6: Commit**

```bash
git add core/tools/cortex-embd/main.cpp core/cortex_core/npu/answer_cases.py core/cortex_core/npu/run_npu.py core/tests/test_npu_answer_cases.py
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "lm: cortex-embd -t threads; answer_cases runner over saved NPU features"
```

---

### Task 3: Q4_0 vs Q4_K_M and thread placement (box bench)

**Files:**
- Create: `core/scripts/lm/bench_quant_threads.sh` (box script; no unit test — it only calls llama-bench and `answer_cases`)

**Interfaces:**
- Consumes: `answer_cases` CLI (Task 2), features in `/var/lib/cortex/bench/npu/npu_run2/`, cases in `/var/lib/cortex/bench/npu/test_review/`.
- Produces: `/var/lib/cortex/bench/speedups/q_t/` with `bench_<model>_<t>.json` (llama-bench `-o json`) and `answers_<model>_<t>.json`, for model ∈ {Q4_K_M, Q4_0} × setting ∈ {`t4big` = `taskset -c 4-7` + 4 threads, `t8` = 8 threads}.

- [ ] **Step 1: Write the script**

Per model × setting: `llama-bench -m MODEL -p 220 -n 64 -r 3 -t T -o json` (prefixed with `taskset -c 4-7` for `t4big`), then `python -m cortex_core.npu.answer_cases ... --threads T [--taskset 4-7]`. Wait 30 s between configurations so each starts cool. Log `soc_state()` (from `run_npu`) before and after each configuration into the same directory.

- [ ] **Step 2: Run it on the box** (background, `PYTHONPATH=/opt/cortex`, venv python)

Expected: 4 bench files, 4 answer files; each answer file ends `matched N/12`. Pull all JSON back to the PC scratchpad.

- [ ] **Step 3: Check the result against the decision rule**

Expected output to record: pp220 t/s and tg t/s per row; matched count and ttft median per row. Q4_0 is "adopted" only if 12/12 and pp220 t/s higher than Q4_K_M at the same setting. Record as a ledger line; if `t4big` and `t8` give the same ttft (± 2%), check `-t` reached llama.cpp (Review Focus 5) before trusting the row.

- [ ] **Step 4: Commit**

```bash
git add core/scripts/lm/bench_quant_threads.sh
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "lm: Q4_0 vs Q4_K_M and big-core thread bench script"
```

---

### Task 4: 112-token NPU encoder (WSL build + box run)

**Files:**
- Modify: `core/scripts/npu/build_segments_wsl.sh` (output dir from `CORTEX_NPU_OUT`, default `$HOME/qairt/seg`)
- Modify: `core/scripts/npu/convert_vision.md` (the 112-token recipe: decompose `--shape 8,14,2,2,1536`, calib raw at `448x256`, build with `CORTEX_NPU_OUT=$HOME/qairt/seg112`)

**Interfaces:**
- Consumes: `make_calib_raw ... 448x256` and `run_npu --canvas 448x256 --stand-in WxH` (Task 1); `answer_cases` not needed (run_npu answers itself).
- Produces: on the box `/var/lib/cortex/models/npu-vision-112/` (`npu*.bin`, `cpu*.onnx`, `io.json`); results in `/var/lib/cortex/bench/speedups/npu112/results.json`.

- [ ] **Step 1: Find the stand-in size** — on the box, `cortex-embd dump` a grey jpg at each of `448x256`, `448x252`, `456x256` and read `n_tokens` from the printed JSON. Expected: at least one gives 112. Record the smallest that does as a ledger ruling. If none does (llama.cpp's LFM processor enforces a minimum token count), stop the task and record the finding: the 112 path cannot be answered through `cortex-embd` without engine changes, which is a step 2 question.

- [ ] **Step 2: Build in WSL** — `decompose --shape 8,14,2,2,1536` → BASIC fold → `split_stages` (same 6 MHA cut points) → `make_calib_raw <52 frames> calib_raw 448x256` → `CORTEX_NPU_OUT=$HOME/qairt/seg112 build_segments_wsl.sh` (run in background).
Expected: `npu0..npu12: OK` for all 7 segments; per-segment calib dirs deleted.

- [ ] **Step 3: Copy to the box and run**

`run_npu --split /var/lib/cortex/models/npu-vision-112 --canvas 448x256 --stand-in <from step 1> --onnx vision_encoder.onnx --cases .../test/cases.json --model Q4_K_M ... --out-dir .../speedups/npu112 --runs 20`
Expected: 13 landscape rows (12 test + 1080p) with NPU median ms, cos mean/min vs ONNX at 448x256, tok<0.9, answer, ttft; `matched N/13` (portrait row reported but out of scope). If the ONNX model refuses the 8x14 input, rule and use the decomposed 448x256 `vision_std.onnx` as the CPU reference instead.

- [ ] **Step 4: Commit**

```bash
git add core/scripts/npu/build_segments_wsl.sh core/scripts/npu/convert_vision.md
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "npu: 112-token (448x256) encoder build recipe"
```

---

### Task 5: Write up the numbers

**Files:**
- Create: `docs/measurements/2026-11-speedups.md`
- Modify: `docs/architecture/CORTEX-ENGINE.md` (Phase 2 status line), `core/AGENTS.md` (change-log line)

- [ ] **Step 1: Write the doc**

Tables: (1) llama-bench pp220 / tg64 for Q4_K_M vs Q4_0 at `t4big` and `t8`; (2) 12-case answers per model × setting with matched count and ttft; (3) 112 vs 220 tokens: NPU encode ms, cos mean/min, tok<0.9, ttft, with the 220 and 112 answers **side by side** per frame. Then the combined estimate of one full image read (NPU encode + prefill of the image tokens) for: today, Q4_0 only, 112 only, both. State the Q4_0 decision per the rule, and leave 112 marked "Haziq decides". Same honest-caveats style as `2026-11-npu-vision.md` (narrow test set, no power meter).

- [ ] **Step 2: Check every number in the doc against the pulled JSON**

Run: a short script in the scratchpad that loads each results/answers/bench JSON and prints the values the tables use.
Expected: every table cell matches.

- [ ] **Step 3: Commit**

```bash
git add docs/measurements/2026-11-speedups.md docs/architecture/CORTEX-ENGINE.md core/AGENTS.md
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "docs: step 1 speed-up measurements (Q4_0, 112 tokens, thread placement)"
```
