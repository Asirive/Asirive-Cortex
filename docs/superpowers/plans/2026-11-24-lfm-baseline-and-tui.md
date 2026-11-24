# LFM3-Omni Baseline + Dev TUI Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure how fast and heavy LFM3-Omni-2B is on the Dragon Q8B with stock llama.cpp (CPU, then GPU), prove whether the NPU is reachable from Ubuntu, and show the numbers in a branded dev terminal UI.

**Architecture:** A small stdlib-only measurement package (`cortex_core/engine/`) drives a running `llama-server` over its OpenAI-compatible streaming API, reads system numbers from `/proc` and `/sys`, and writes a JSON + Markdown results table. A separate probe checks for the Hexagon NPU. A Textual app (`cortex_core/tui/`, dev builds only) reads the latest results and live system numbers.

**Tech Stack:** Python 3.13+ (box: 3.14), stdlib `urllib`/`json`/`statistics`, pytest, Textual (dev-only), llama.cpp (built from source on the box).

**Spec:** `docs/superpowers/specs/2026-11-24-v4-core-design.md` (sections 6.10, 6.12, 7 steps 1–2).

## Global Constraints

- No V3 code: never import, copy or port from `v3_core/`.
- `cortex_core/engine/` uses the standard library only (nothing added to `core/requirements.txt`).
- Textual is dev-only: goes in a new `core/requirements-dev.txt`, never in `core/requirements.txt`.
- The TUI runs only when `CORTEX_DEV_BUILD=1`; user builds are headless.
- Bench images and audio are dev data: they live on the box under `/var/lib/cortex/bench/media`, never committed to git.
- Target to report against: first audio (or first token when no audio output) < 1.0 s.
- Brand: background `#0A0A08`, accent `#EAFF00`.
- Every new file or behaviour in `core/` updates `core/AGENTS.md` (section 9 table + change log line) in the same commit.
- Commits: author `IRSPlays <haziq@asirive.com>`, no co-author line.
- Code must import and its tests must pass on Windows (dev PC) and Linux (box): every `/proc`, `/sys`, `/dev` path is a parameter with a default.

## Review Focus

1. `llama-server` not running or refusing the connection: the run is recorded as failed with the error text, the bench continues to the next case and still writes its report. (Task 2, Task 3 tests.)
2. A stream that ends without `timings`, or contains a malformed `data:` line: the result keeps what it measured and marks the missing numbers `None`, no exception. (Task 2 test.)
3. `/sys` or `/proc` files missing or unreadable (no battery driver, permission denied): readers return `None`/empty, the TUI shows `n/a`. (Task 1, Task 5 tests.)
4. The server rejects an image or audio case (HTTP 400, e.g. no mmproj loaded): that case is recorded as unsupported with the server's message, not counted in medians. (Task 2, Task 3 tests.)
5. TUI started outside a dev build, or before any baseline exists: refuses with a clear message / shows "no baseline yet". (Task 5 tests.)

---

### Task 1: System readers

**Files:**
- Create: `core/cortex_core/engine/__init__.py` (empty), `core/cortex_core/engine/sysinfo.py`
- Test: `core/tests/test_engine_sysinfo.py`
- Modify: `core/AGENTS.md` (section 9 row "Engine bench", change log)

**Interfaces:**
- Produces:
  - `read_temps_c(root: Path = Path("/sys/class/thermal")) -> dict[str, float]` — `{zone type: °C}` from `thermal_zone*/type` + `temp` (millidegrees / 1000). Unreadable zones skipped.
  - `read_peak_rss_mb(pid: int, proc: Path = Path("/proc")) -> float | None` — `VmHWM` kB / 1024.
  - `read_mem_used_mb(proc: Path = Path("/proc")) -> float | None` — (`MemTotal` − `MemAvailable`) kB / 1024.
  - `read_cpu_times(proc: Path = Path("/proc")) -> tuple[int, int] | None` — (busy, total) jiffies from the `cpu` line of `stat` (idle = idle + iowait).
  - `cpu_load(prev: tuple[int, int], cur: tuple[int, int]) -> float` — busy fraction 0.0–1.0; 0.0 when total did not change.
  - `read_power_w(root: Path = Path("/sys/class/power_supply")) -> float | None` — first supply with `power_now` (µW / 1e6), else `voltage_now` × `current_now` (µV × µA / 1e12); `None` if none.

- [ ] **Step 1: Write the failing tests** (build fake trees under `tmp_path`)

```python
def test_temps_read_millidegrees(tmp_path):
    z = tmp_path / "thermal_zone0"; z.mkdir()
    (z / "type").write_text("cpu-0\n"); (z / "temp").write_text("48500\n")
    assert read_temps_c(tmp_path) == {"cpu-0": 48.5}

def test_temps_skip_unreadable_zone(tmp_path):
    (tmp_path / "thermal_zone1").mkdir()          # no files
    assert read_temps_c(tmp_path) == {}

def test_peak_rss(tmp_path):
    (tmp_path / "42").mkdir(); (tmp_path / "42" / "status").write_text("Name:\tx\nVmHWM:\t  2048 kB\n")
    assert read_peak_rss_mb(42, tmp_path) == 2.0

def test_peak_rss_missing_pid(tmp_path):
    assert read_peak_rss_mb(99, tmp_path) is None

def test_mem_used(tmp_path):
    (tmp_path / "meminfo").write_text("MemTotal: 8192 kB\nMemFree: 1 kB\nMemAvailable: 2048 kB\n")
    assert read_mem_used_mb(tmp_path) == 6.0

def test_cpu_load():
    assert cpu_load((100, 200), (150, 300)) == 0.5
    assert cpu_load((100, 200), (100, 200)) == 0.0

def test_power_now(tmp_path):
    b = tmp_path / "battery"; b.mkdir(); (b / "power_now").write_text("4500000\n")
    assert read_power_w(tmp_path) == 4.5

def test_power_from_voltage_current(tmp_path):
    b = tmp_path / "usb"; b.mkdir()
    (b / "voltage_now").write_text("5000000\n"); (b / "current_now").write_text("1000000\n")
    assert read_power_w(tmp_path) == 5.0

def test_power_absent(tmp_path):
    assert read_power_w(tmp_path) is None
    assert read_power_w(tmp_path / "nope") is None
```

Also `test_cpu_times` with a fake `stat` line `cpu  10 0 10 70 10 0 0 0` → `(20, 100)`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && python -m pytest tests/test_engine_sysinfo.py -q`
Expected: FAIL (ModuleNotFoundError: cortex_core.engine.sysinfo)

- [ ] **Step 3: Implement the six functions in `core/cortex_core/engine/sysinfo.py`**

Every reader catches `OSError` and `ValueError` and returns `None` / skips; nothing raises.

- [ ] **Step 4: Run tests**

Run: `cd core && python -m pytest tests/test_engine_sysinfo.py -q`
Expected: all pass

- [ ] **Step 5: Update `core/AGENTS.md`** — section 9 row `| Engine bench | cortex_core/engine/ | Building: sysinfo readers |` and a change-log line.

- [ ] **Step 6: Commit**

```bash
git add core/cortex_core/engine core/tests/test_engine_sysinfo.py core/AGENTS.md
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "core/engine: system readers for the LFM baseline"
```

---

### Task 2: Streaming llama-server client with timing

**Files:**
- Create: `core/cortex_core/engine/llama_client.py`
- Test: `core/tests/test_engine_llama_client.py`

**Interfaces:**
- Produces:
  - `@dataclass RunResult: ok: bool; error: str | None; status: int | None; ttft_s: float | None; ttfa_s: float | None; text: str; prefill_tps: float | None; decode_tps: float | None; tokens_out: int | None; wall_s: float`
  - `user_message(text: str, image: Path | None = None, audio: Path | None = None) -> dict` — OpenAI chat `user` message; image as `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,…"}}`, audio as `{"type": "input_audio", "input_audio": {"data": <b64>, "format": "wav"}}`, text part last.
  - `stream_chat(base_url: str, messages: list[dict], *, max_tokens: int = 128, audio_out: bool = False, timeout_s: float = 60.0, clock: Callable[[], float] = time.monotonic, open_url: Callable = urllib.request.urlopen) -> RunResult`
    - POST `{base_url}/v1/chat/completions`, JSON body `{"messages", "max_tokens", "stream": true}`, plus `"modalities": ["text", "audio"]` when `audio_out`.
    - Reads SSE lines `data: {...}` until `data: [DONE]`. `ttft_s` = clock at first chunk with non-empty `choices[0].delta.content` minus start; `ttfa_s` same for first non-empty `choices[0].delta.audio`. `timings` object (any chunk): `prompt_per_second` → `prefill_tps`, `predicted_per_second` → `decode_tps`, `predicted_n` → `tokens_out`.
    - HTTP error → `ok=False`, `status` = code, `error` = response body text (first 300 chars). Connection error/timeout → `ok=False`, `status=None`, `error=str(e)`. Malformed JSON line → skipped. Never raises.

- [ ] **Step 1: Write the failing tests** (fake `open_url` returning an object with `.status`, iteration over byte lines, and context-manager methods; fake clock that advances 0.1 s per call)

```python
def test_measures_first_token_and_timings(): ...
    # stream: role chunk, content "Hi", content " there", timings chunk, [DONE]
    assert r.ok and r.text == "Hi there"
    assert r.ttft_s == pytest.approx(<clock delta to "Hi" chunk>)
    assert (r.prefill_tps, r.decode_tps, r.tokens_out) == (310.0, 21.5, 2)
    assert r.ttfa_s is None

def test_first_audio_chunk_sets_ttfa(): ...   # delta.audio {"data": "..."} before text

def test_malformed_line_and_missing_timings(): ...
    # "data: {not json" in the middle, no timings chunk
    assert r.ok and r.text == "Hi" and r.decode_tps is None

def test_http_400_is_recorded_not_raised(): ...
    # open_url raises urllib.error.HTTPError(400, body b'{"error":"image input is not supported"}')
    assert not r.ok and r.status == 400 and "not supported" in r.error

def test_connection_refused_is_recorded(): ...
    # open_url raises urllib.error.URLError(ConnectionRefusedError())
    assert not r.ok and r.status is None and r.error

def test_request_body_has_modalities_only_when_audio_out(): ...
    # capture the Request passed to open_url; json.loads(req.data)

def test_user_message_parts(tmp_path): ...
    # image + audio files → parts order: image_url, input_audio, text; data: URLs are base64 of file bytes
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && python -m pytest tests/test_engine_llama_client.py -q`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `RunResult`, `user_message`, `stream_chat`** in `llama_client.py` as specified above (stdlib `urllib.request`, `json`, `base64`).

- [ ] **Step 4: Run tests**

Run: `cd core && python -m pytest tests/test_engine_llama_client.py -q`
Expected: all pass

- [ ] **Step 5: Update `core/AGENTS.md`** (row text: "sysinfo readers, streaming client") and commit

```bash
git add core/cortex_core/engine/llama_client.py core/tests/test_engine_llama_client.py core/AGENTS.md
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "core/engine: streaming llama-server client with first-token/first-audio timing"
```

---

### Task 3: Bench runner, NPU probe, results report

**Files:**
- Create: `core/cortex_core/engine/bench.py`, `core/cortex_core/engine/npu_probe.py`, `core/cortex_core/engine/cases.example.json`
- Test: `core/tests/test_engine_bench.py`, `core/tests/test_engine_npu_probe.py`

**Interfaces:**
- Consumes: Task 1 readers; Task 2 `stream_chat`, `user_message`, `RunResult`.
- Produces:
  - Cases file (JSON list): `{"id": str, "text": str, "image": str | null, "audio": str | null, "audio_out": bool}`; media paths relative to `--media` dir. `cases.example.json` ships 4 cases: `text_short` ("What can you help me with? Answer in one sentence."), `image_describe` ("What is directly in front of me? One sentence.", image), `audio_question` (audio only, the question is spoken), `audio_image` (spoken question + image). Example media are NOT shipped.
  - `@dataclass Case: id: str; text: str; image: Path | None; audio: Path | None; audio_out: bool`
  - `load_cases(path: Path, media: Path) -> list[Case]` — raises `ValueError` naming the case when a referenced file does not exist.
  - `summarise(runs: list[RunResult]) -> dict` — over `ok` runs only: `n_ok`, `n_failed`, and `median`/`p90` of `ttft_s`, `ttfa_s`, `prefill_tps`, `decode_tps`, `wall_s` (`None` when no values); `unsupported: str | None` = first failure's `error` when every run failed with HTTP 400.
  - `run_bench(cases: list[Case], base_url: str, *, reps: int = 5, warmup: int = 1, pid: int | None = None, chat: Callable = stream_chat) -> dict` — per case: warmup runs discarded, then `reps` runs; after each case records `peak_rss_mb` (if `pid`), `max_temp_c`, `power_w`. Returns `{"cases": {id: summary + sys numbers}, "target_s": 1.0}`; a case whose first-audio median (or first-token median when no audio) is over 1.0 s gets `"over_target": true`.
  - `write_report(result: dict, meta: dict, out_json: Path, out_md: Path, state_dir: Path | None) -> None` — JSON = `{"meta": meta, **result}`; Markdown table columns exactly: `case | ok/failed | first token s (med/p90) | first audio s (med/p90) | prefill tok/s | decode tok/s | peak RAM MB | max temp °C | power W | < 1 s?`; `None` printed as `n/a`. When `state_dir` is given, also writes `state_dir/bench/latest.json` (same JSON) for the TUI.
  - `meta` keys: `backend` ("cpu" | "gpu"), `llama_cpp` (tag), `model` (file name), `mmproj` (file name), `quant`, `date`, `host`.
  - CLI: `python -m cortex_core.engine.bench --server http://127.0.0.1:8080 --cases FILE --media DIR --backend cpu --llama-tag TAG --model FILE --mmproj FILE --quant Q4_K_M --pid PID --reps 5 --out-json F --out-md F --state-dir /var/lib/cortex`
  - `@dataclass NpuReport: fastrpc_nodes: list[str]; dsp: list[dict]; qnn_libs: list[str]; reachable: bool; notes: list[str]`
  - `probe(dev: Path = Path("/dev"), remoteproc: Path = Path("/sys/class/remoteproc"), lib_dirs: tuple[Path, ...] = (Path("/usr/lib"), Path("/usr/lib/aarch64-linux-gnu"), Path("/opt/qcom"))) -> NpuReport`
    - `fastrpc_nodes`: names in `dev` matching `fastrpc-*` or `adsprpc-smd*`.
    - `dsp`: `{"name", "state"}` for each `remoteproc*` (`name`, `state` files).
    - `qnn_libs`: paths of `libQnnHtp*.so` found up to 3 levels under each lib dir.
    - `reachable` = at least one fastrpc node AND a dsp whose name contains `cdsp` with state `running`. `notes` explains each missing piece in plain words.
  - CLI: `python -m cortex_core.engine.npu_probe [--out FILE]` prints the report as JSON; `--out` also writes it (used as `state_dir/bench/npu.json`).

- [ ] **Step 1: Write the failing tests**

```python
# test_engine_bench.py — fake chat returns scripted RunResults
def test_warmup_discarded_and_medians(): ...       # warmup=1 slow run not in median
def test_failed_runs_excluded_from_medians(): ...  # 3 ok + 2 connection errors → n_ok 3, n_failed 2
def test_all_400_marks_unsupported(): ...          # summary["unsupported"] contains server message
def test_over_target_flag(): ...                   # first-token median 1.4 s, no audio → over_target True
def test_bench_continues_after_failed_case(): ...  # case 1 all fail, case 2 ok → both in result
def test_load_cases_missing_media(tmp_path): ...   # ValueError mentioning the case id
def test_report_files(tmp_path): ...
    # md contains the exact header row; None → "n/a"; state_dir/bench/latest.json exists and equals out_json

# test_engine_npu_probe.py — fake /dev, /sys trees in tmp_path
def test_reachable_when_fastrpc_and_cdsp_running(tmp_path): ...
def test_not_reachable_without_fastrpc(tmp_path): ...   # notes mention fastrpc
def test_cdsp_offline(tmp_path): ...                    # state "offline" → reachable False, note mentions cdsp
def test_finds_qnn_lib(tmp_path): ...                   # opt/qcom/a/b/libQnnHtp.so found
def test_missing_dirs_do_not_raise(tmp_path): ...       # all roots point at non-existent paths
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && python -m pytest tests/test_engine_bench.py tests/test_engine_npu_probe.py -q`
Expected: FAIL (modules missing)

- [ ] **Step 3: Implement `bench.py` and `npu_probe.py`** to the interfaces above (`statistics.median`; p90 = value at index `ceil(0.9 * n) - 1` of the sorted list).

- [ ] **Step 4: Run all core tests**

Run: `cd core && python -m pytest -q`
Expected: all pass (existing tests unchanged)

- [ ] **Step 5: Update `core/AGENTS.md`** (row: "Built: readers, client, bench, NPU probe. Not run on the box yet") and commit

```bash
git add core/cortex_core/engine core/tests/test_engine_bench.py core/tests/test_engine_npu_probe.py core/AGENTS.md
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "core/engine: bench runner, NPU probe and results report"
```

---

### Task 4: Run the baseline on the Dragon Q8B (hardware task)

**Files:**
- Create: `core/scripts/build_llama.sh`, `docs/measurements/2026-11-lfm3-omni-baseline.md`
- Modify: `core/AGENTS.md`, `docs/architecture/CORTEX-ENGINE.md` (Phase 0 status line)

**Interfaces:**
- Consumes: Task 3 CLIs.
- Produces: `/var/lib/cortex/bench/latest.json` and `/var/lib/cortex/bench/npu.json` on the box (read by Task 5).

- [ ] **Step 1: Write `core/scripts/build_llama.sh`** — args: `<tag>`. Clones `https://github.com/ggml-org/llama.cpp` at that tag into `/opt/llama.cpp/<tag>`, builds two trees with CMake Release: `build-cpu` (default) and `build-gpu` (`-DGGML_OPENCL=ON`, the backend with Adreno kernels; if it fails to configure, retry with `-DGGML_VULKAN=ON` and print which one was used). Prints the paths of both `llama-server` binaries. Uses the newest release tag ≥ `b11960` at the time of running (record the exact tag).

- [ ] **Step 2: Push code and build on the box**

Run (dev PC): `python cortex.py sync to` then on the box: `bash /opt/cortex/scripts/build_llama.sh <tag>`
Expected: both `llama-server` binaries exist; `build-gpu/bin/llama-server --list-devices` shows the Adreno GPU.

- [ ] **Step 3: Get the model** — official Liquid AI LFM3-Omni-2B GGUF, `Q4_K_M` main model plus its multimodal projector (mmproj). Place in `/var/lib/cortex/models/`. Record exact file names and `sha256sum` in the results doc. Note the licence terms shown on the model page (design doc open item).

- [ ] **Step 4: Prepare dev media** in `/var/lib/cortex/bench/media/` (not git): 2–3 JPEGs of a real scene taken with the Sony camera, 2 WAV files (16 kHz mono) of Haziq asking the questions in `cases.example.json`. Copy `cases.example.json` to `/var/lib/cortex/bench/cases.json` and point it at these files.

- [ ] **Step 5: NPU probe**

Run: `cd /opt/cortex && venv/bin/python -m cortex_core.engine.npu_probe --out /var/lib/cortex/bench/npu.json`
Expected: JSON printed; `reachable` true or false with notes. Either result is a finding; record it.

- [ ] **Step 6: CPU baseline**

Run: start `build-cpu/bin/llama-server -m <model> --mmproj <mmproj> --port 8080 -c 4096`, note its PID, then
`venv/bin/python -m cortex_core.engine.bench --server http://127.0.0.1:8080 --cases /var/lib/cortex/bench/cases.json --media /var/lib/cortex/bench/media --backend cpu --llama-tag <tag> --model <file> --mmproj <file> --quant Q4_K_M --pid <PID> --out-json /var/lib/cortex/bench/cpu.json --out-md /var/lib/cortex/bench/cpu.md --state-dir /var/lib/cortex`
Expected: report written; each case either has numbers or an `unsupported` message. If `audio_out` cases are unsupported by the server build, record "speech output not available in stock llama-server" and that first-audio is n/a.

- [ ] **Step 7: GPU baseline** — same as Step 6 with `build-gpu/bin/llama-server … -ngl 99` and `--backend gpu`, outputs `gpu.json` / `gpu.md`.

- [ ] **Step 8: Power** — if `power_w` is n/a in both reports (no battery driver), read watts from a USB-C power meter during one `image_describe` run per backend and note them by hand in the results doc as "measured with meter".

- [ ] **Step 9: Write `docs/measurements/2026-11-lfm3-omni-baseline.md`** — sections: setup (board, OS, llama.cpp tag, model files + sha256, quant, licence note), NPU probe result, CPU table, GPU table (paste the `.md` tables), idle draw, findings vs the 1 s target, what this means for the NPU split (one paragraph each, plain words).

- [ ] **Step 10: Update docs and commit** — `core/AGENTS.md` (row: "Baseline run on the Q8B, see docs/measurements/…"), `CORTEX-ENGINE.md` Phase 0: "Done 2026-MM-DD, see …".

```bash
git add core/scripts/build_llama.sh docs/measurements core/AGENTS.md docs/architecture/CORTEX-ENGINE.md
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "LFM3-Omni baseline on the Dragon Q8B (CPU and GPU) and NPU probe result"
```

---

### Task 5: Dev terminal UI skeleton

**Files:**
- Create: `core/requirements-dev.txt`, `core/cortex_core/tui/__init__.py`, `core/cortex_core/tui/state.py`, `core/cortex_core/tui/app.py`, `core/cortex_core/tui/app.tcss`, `core/cortex_core/tui/__main__.py`
- Test: `core/tests/test_tui.py`
- Modify: `core/AGENTS.md`

**Interfaces:**
- Consumes: Task 1 readers; files `state_dir/bench/latest.json` and `state_dir/bench/npu.json` (Task 3 formats).
- Produces:
  - `@dataclass Snapshot: temps_c: dict[str, float]; mem_used_mb: float | None; cpu_load: float | None; power_w: float | None; baseline: dict | None; npu: dict | None`
  - `class Collector(state_dir: Path = Path("/var/lib/cortex"), proc: Path = Path("/proc"), thermal: Path = Path("/sys/class/thermal"), power: Path = Path("/sys/class/power_supply"))` with `snapshot() -> Snapshot` (keeps the previous CPU times to compute load; first call gives `cpu_load=None`; unreadable/invalid JSON files → `None`).
  - `fmt(value: float | None, unit: str, digits: int = 1) -> str` → `"48.5 °C"` or `"n/a"`.
  - `class CortexTUI(App)` — `CSS_PATH = "app.tcss"`, constructor `CortexTUI(collector: Collector, refresh_s: float = 1.0)`. Header text `ASIRIVE CORTEX · DEV`. Four `Static` panels with ids `system` (CPU load, RAM used, hottest zone + name, power), `engine` (latest baseline: backend, model, per-case first-token/first-audio medians and decode tok/s, `< 1 s?`; or `no baseline yet`), `npu` (`reachable` yes/no + notes; or `not probed yet`), `log` (a `RichLog`, app messages). Refreshes every `refresh_s`. Bindings: `q` quit, `?` help (lists the keys).
  - `app.tcss`: screen background `#0A0A08`, panel borders and titles `#EAFF00`, body text light grey.
  - `main(argv: list[str] | None = None, env: Mapping[str, str] = os.environ) -> int` — when `env.get("CORTEX_DEV_BUILD") != "1"`: prints exactly `The terminal UI is for developer builds only (set CORTEX_DEV_BUILD=1).` and returns 2. Otherwise runs `CortexTUI(Collector(Path(argv state dir or default)))` and returns 0. `--state-dir` optional arg.
- `requirements-dev.txt`: `-r requirements.txt`, `textual==<exact version installed>`, `pytest>=8`.

- [ ] **Step 1: Write the failing tests**

```python
def test_refuses_outside_dev_build(capsys):
    assert main([], env={}) == 2
    assert capsys.readouterr().out.strip() == "The terminal UI is for developer builds only (set CORTEX_DEV_BUILD=1)."

def test_snapshot_without_files(tmp_path):
    s = Collector(tmp_path, tmp_path, tmp_path, tmp_path).snapshot()
    assert s.baseline is None and s.npu is None and s.cpu_load is None

def test_snapshot_reads_latest_and_npu(tmp_path): ...   # writes bench/latest.json, bench/npu.json
def test_bad_json_is_none(tmp_path): ...                 # "{" in latest.json → baseline None
def test_fmt():
    assert fmt(48.46, "°C") == "48.5 °C" and fmt(None, "W") == "n/a"

async def test_app_shows_no_baseline_and_quits(tmp_path):
    app = CortexTUI(Collector(tmp_path, tmp_path, tmp_path, tmp_path), refresh_s=0.05)
    async with app.run_test() as pilot:
        assert "no baseline yet" in str(app.query_one("#engine", Static).renderable)
        assert app.query_one("#npu", Static) and app.query_one("#system", Static)
        await pilot.press("q")
    assert app.return_code in (0, None)

async def test_app_shows_baseline(tmp_path): ...  # latest.json with one case → case id and "decode" figure appear in #engine
```

(Use `pytest.mark.asyncio` only if the repo has `pytest-asyncio`; otherwise wrap with `asyncio.run(...)` inside a sync test.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd core && pip install -r requirements-dev.txt && python -m pytest tests/test_tui.py -q`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `state.py`, `app.py`, `app.tcss`, `__main__.py`** to the interfaces above. Textual's `Static.update()` with Rich `Text`/`Table` for panel content; `set_interval(refresh_s, …)` for refresh.

- [ ] **Step 4: Run all core tests**

Run: `cd core && python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Try it on the box** — `CORTEX_DEV_BUILD=1 venv/bin/python -m cortex_core.tui` over SSH. Expected: four panels in brand colours, live CPU/RAM/temperature, the baseline from Task 4 (or "no baseline yet"), NPU result; `q` quits. Without the env var: the refusal line.

- [ ] **Step 6: Update `core/AGENTS.md`** (section 9 row `| TUI | cortex_core/tui/ | Skeleton: system, engine, NPU, log panels; dev builds only |`, change log) and commit

```bash
git add core/requirements-dev.txt core/cortex_core/tui core/tests/test_tui.py core/AGENTS.md
git -c user.name=IRSPlays -c user.email=haziq@asirive.com commit -m "core/tui: dev terminal UI skeleton (system, engine baseline, NPU panels)"
```
