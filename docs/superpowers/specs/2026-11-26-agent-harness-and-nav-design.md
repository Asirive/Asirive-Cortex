# Agent harness + offline navigation: design

**Date:** 2026-11-26. **Status:** approved by Haziq, 2026-11-26 ("full authorization to fulfil this plan"). **Owner:** Haziq (IRSPlays).
**Builds on:** `2026-11-24-v4-core-design.md` (§6.3 brain loop, §6.4 modes and tools, §6.6 unprompted speech,
§6.8 navigation) and `docs/architecture/CORTEX-ENGINE.md` (Cortex-EmbD).
**Covers:** tool calls inside Cortex-EmbD, the `brain` mode machine and tool dispatcher, the `nav` service (offline
places, walking, bus and MRT routing, route following), the server-built nav bundle, live LTA through the gateway,
and the phone GPS stream.

---

## 1. Milestone 1: the goal everything serves

**Home → Northpoint City, end to end, walk + bus + MRT, guided by Cortex.** The user says where they want to go;
Cortex finds it, plans the trip offline, and guides every leg: walking turns, "your bus is coming", the stop to get
off at, the MRT ride, and "you've arrived". Only live bus arrivals use the internet.

The home location is **never in git**: it lives in a local config on the box (`/var/lib/cortex/nav/saved_places.json`).

**Pass bar (all on the real trip).** The real trip is run with the assembled glasses when Haziq is back; until then every
system is built and proven with recorded and replayed trips, the C270 and earbuds on the box, and the phone over the tether.

| Check | Bar |
|:---|:---|
| Trip completed with Cortex guidance only (a sighted observer only for safety) | yes |
| Correct bus boarded and correct stop alighted, prompted by Cortex | yes |
| Correct MRT line/direction and station, prompted by Cortex | yes |
| "Your bus is coming" spoken before the bus arrives (online) | yes |
| A tool call spoken aloud as text | never |
| A wrong tool fired by chit-chat | never |
| Plain questions: first sound after question end | < 1 s (unchanged) |
| Tool answers: first sound after question end | < 2 s; "Checking." if a tool takes > 700 ms |
| Brain or nav crash during the trip | none |

## 2. Decisions taken (2026-11-26)

| Topic | Decision |
|:---|:---|
| Tool result → speech | **Hybrid.** Templates for factual results (bus ETA, next turn, stop to alight, arrived). The LM phrases open-ended results (place matches, memory, indoor). |
| Mode switching | **Code drives, model requests.** A deterministic state machine owns the mode; the model can only *request* via `set_mode`, which code validates. |
| Transit scope | **Walk + bus + MRT**, offline. |
| Data delivery | **Server builds a signed nav bundle**; the box downloads it like an OTA artifact. The LTA key stays on the server. |
| Router | **Our own compact router**: A* walking on a prebuilt footpath graph + a RAPTOR-style transit search. |
| Live arrivals | **Through the gateway**: server calls DataMall with its key, caches ~20 s. |
| Place search | **OSM POIs + bus stops + MRT stations + postal codes/addresses**, all offline in the bundle. |
| Dev GPS | **The real phone app over the USB tether.** I build both the box side and the Flutter side. |
| Weak tool calls | **LoRA fine-tune**, on the Windows PC GPU when Haziq is back (the server has no GPU). |
| Acknowledgement | **"Checking." only if a tool has not answered within ~700 ms.** |
| Echo cancellation | **Not now.** It waits for the glasses' real mic/speaker layout. |
| Facing direction | **GPS course + street-relative instructions, plus camera assist** at decision points. No IMU. |
| Field rig | **USB-C PD power bank** in a bag with the box, C270, earbuds and phone. |

## 3. What exists today, and the gaps

- Cortex-EmbD answers questions about the current view in its own voice. It has **no tool calls**: it speaks every
  token it makes, so a tool call would be read aloud.
- The system prompt is fixed at `ce_open` (it heads slot H). Changing it per mode means rebuilding H.
- Context is 4096 tokens, shared with the view image. Tool text must be small.
- `phone_link` has no location op; the app reads GPS only once (`geolocator`, one-shot).
- No nav code, no bundle, no LTA in V4. V3 had LTA and Google Maps tools: **ideas only**, no code reused.
- LTA DataMall has bus stops, routes and frequency bands, **no timetables**, and Singapore has no official GTFS.
  Waits are estimated from frequency; live arrivals replace the estimate when online.

## 4. Tool calls inside Cortex-EmbD (C++)

### 4.1 Format (confirmed from the model's chat template, 2026-11-26)
LFM3-Omni has native tool calling. Its template:
- tools: one JSON object per line inside `<tools>\n...\n</tools>`, appended to the system prompt;
- a call: `<tool_call>\n<function=NAME>\n<parameter=ARG>\nVALUE\n</parameter>\n</function>\n</tool_call>`
  (several calls are separated by a blank line), then `<|im_end|>`;
- a result: a `tool` turn, `<|im_start|>tool\n<tool_response>\n...\n</tool_response><|im_end|>\n`;
- the assistant turn opens with `<think></think>` when thinking is off.

We use exactly this format, so no fine-tune is needed to teach it. What is unmeasured is how well **Q4_0** picks
our tools and arguments (CORTEX-ENGINE.md §7); M0 measures it.

### 4.2 One fixed tool list
All tools go in the system prompt once, as compact signatures (target ≤ 500 tokens, measured). **No per-mode
rebuild of H.** Mode gating is done in code: the dispatcher refuses a tool the mode does not allow and returns a
short error result.

### 4.3 State line
`ce_set_state(h, text)`: a short line (≤ 40 tokens, e.g. `mode=OUTDOOR_NAV; leg=walk to stop 59009; next=left at
Yishun Ave 2`) read into S before each question, so the model knows where the trip stands without a rebuild.

### 4.4 Holding the sound
In an answer the engine watches the first text tokens. If the answer opens a tool call:
- no audio is made or played for it; sampling switches to text-only until `tool_call_end`;
- the engine emits `{"type":"tool_call","id":..,"text":"name(args)"}` and waits.

The cost of holding audio until the first text token is decided is measured in M0. If LFM3's mixed loop puts audio
before text, the fallback is a text-only first step (one decided token) before the mixed loop starts.

### 4.5 Results
- `ce_tool_result(h, id, text, continue)`: appends the tool response turn to S. With `continue=1`, generation
  resumes and the LM phrases it (open-ended tools). With `continue=0`, the turn is only recorded.
- `ce_say(h, text)`: speaks a fixed sentence in the model's voice (TTS through the same speech loop). It is used for
  templates and for unprompted cues (next turn, bus coming, arrived). Like any answer, it cuts an older answer's sound.
- Both go through the existing big-cores gate, the mute and the history rules.

All engine changes start with failing C++ tests (`engine_tests`) and keep the 73 existing ones green.

## 5. The tool registry (contracts)

One registry, `contracts/tools/tools.json`, shared by LFM and Gemini (design §6.4). Generators make:
the LFM compact prompt, Gemini function declarations, and Python dataclasses for the dispatcher.

Milestone 1 tools:

| Tool | Modes | Result spoken by |
|:---|:---|:---|
| `search_places(query)` | all | LM (top 3 with distance) |
| `plan_trip(place_id)` | IDLE, OUTDOOR_NAV | LM summary ("Walk 4 min, bus 858, then MRT 2 stops, 25 min") |
| `start_navigation()` / `stop_navigation()` | all | template |
| `nav_status()` | nav modes | template |
| `nearby_bus_stops()` | all | LM |
| `services_at_stop(stop)` | all | LM |
| `bus_arrivals(stop?, service?)` | all | template |
| `gps_accuracy()` | all | template |
| `set_mode(mode)` | all | template (accepted / refused) |
| `camera(on)` | all | template |

Later, not M1: `search_memory`, `indoor_guide`, `switch_to_gemini`.

## 6. The brain: modes and dispatch (Python, `cortex_core/brain/`)

`brain` is a library with a service entry point. Today the live TUI hosts the engine in-process; in M1 it hosts the
`Brain` the same way, so nothing changes about how we run it. The headless `python -m cortex_core.brain` service
uses the same class.

### 6.1 Mode machine (code owns it)

| Mode | Entered when | Vision cadence | Unprompted speech |
|:---|:---|:---|:---|
| IDLE | start, trip done, `stop_navigation` | only while the user talks | none |
| OUTDOOR_NAV | `start_navigation`; got off a bus / out of a station | ~2 s | next instruction, arrived |
| BUS_WATCH | within ~40 m of the boarding stop | ~1 s | "your bus is coming", "bus N is here" |
| TRANSIT | on the bus/train (speed + matching the route line) | off (GPS only) | "next stop is yours", "get off now" |
| INDOOR_NAV | station entrance, mall entrance, GPS accuracy drop + camera sees ceiling/walls | 1 s | indoor cues (gantry, escalator, platform) |
| EXPLORE | user asks | builder sets | describes until told to stop |

`set_mode` from the model is a request: code accepts it only if the transition is legal (for example, EXPLORE from
IDLE, or INDOOR_NAV override by "I'm inside").

### 6.2 Dispatcher
Parses the call, checks the mode allows it, runs it (most go to `nav` over the local socket), and starts a 700 ms timer
that says "Checking." if the tool has not answered by then. The result goes back through `ce_say` (template) or
`ce_tool_result(..., continue=1)` (LM). A malformed call gets one short error result and the LM tries once more;
then Cortex says it could not do that.

## 7. The nav service (`cortex_core/nav/`, own process)

- **Bundle loader:** memory-mapped arrays, no parsing at start. RAM target ≤ 300 MB resident (measured).
- **Places:** prefix + trigram index over names, with Singapore aliases ("AMK", "blk", "Northpoint" → Northpoint
  City, MRT station codes), postal codes and block addresses; ranked by match and distance.
- **Walking router:** A* over the OSM footpath graph (footways, crossings, overhead bridges, underpasses, covered
  links), with costs that prefer signalled crossings and avoid stairs-only paths when a ramp exists. Python + NumPy
  first; C only if a route takes > 1 s (measured).
- **Transit router:** RAPTOR over bus routes (LTA) and MRT lines (OSM + LTA station codes). Waits come from LTA
  frequency bands by time of day (mean wait = half the headway). Transfers are walking paths from the walking graph.
  Returns up to 3 itineraries; picks fewest transfers within +5 min of the fastest.
- **Route follower:** matches GPS to the active leg, gives instructions by distance ("in 30 m, turn left at ..."),
  detects off-route with hysteresis (no flapping), and replans. It emits nav events to `brain`
  (instruction, approaching stop, board, alight, arrived, off-route).
- **Live arrivals:** asks `link`, which asks the gateway. Offline → the frequency estimate, said as an estimate.

## 8. The nav bundle (server, `infra/navbundle/`)

A job on the home server, run on demand and weekly:
1. Singapore OSM extract (Geofabrik Malaysia-Singapore-Brunei, clipped to SG).
2. LTA DataMall static: BusStops, BusRoutes, BusServices (key from the server's secret store, never committed).
3. MRT/LRT from OSM, matched to LTA station codes.
4. Postal codes and addresses (OneMap).
5. Build the walking graph, the transit tables and the place index; write versioned arrays; sign with the OTA key
   tooling (`cortex-sign`).

Delivery: an OTA artifact type `nav_bundle`, verified like firmware and swapped atomically. **For the first M1 runs
the signed bundle is copied by hand**; the OTA path follows inside M1.

## 9. GPS from the phone

- `phone_link`: a new `location` stream: the app sends `{lat, lon, acc_m, speed, course, t}` at 1 Hz while
  navigating, plus on demand. `link` forwards it to `nav` over the local socket.
- Flutter (`apps/mobile`): a `geolocator` position stream sent over the existing box link, kept alive while the
  screen is off (Android foreground service with a visible notice).
- Every stream is also written to a dev recording on the box, so real walks can be replayed in tests.

## 10. Build order (each step ends with numbers or a pass in `docs/`)

| Step | What | Gate |
|:---|:---|:---|
| **M0** | Tool-call eval on Q4_0 (≈40 English + Singlish requests, typed **and** spoken WAVs); measure tool-call token time, `ce_say` latency, prompt size | ≥ 90% right tool, ≥ 85% exact args, 0 calls on chit-chat. Fail → LoRA on the Windows PC |
| M1a | Engine: tool-call event + sound hold, `ce_tool_result`, `ce_say`, `ce_set_state` (C++ tests first) | engine_tests green, tool calls never spoken |
| M1b | `contracts/tools/tools.json` + generators; `nav.proto` for brain↔nav↔link | codegen tests |
| M1c | `infra/navbundle`: build the bundle on the server | bundle size, build time, spot-checked stops and paths |
| M1d | `nav`: places, walking, transit, follower | golden routes incl. Home → Northpoint; route < 1 s on the box |
| M1e | `link` location op + Flutter stream; live arrivals via gateway | phone → box at 1 Hz; arrivals within 20 s of LTA |
| M1f | `brain`: mode machine, dispatcher, templates, "Checking."; TUI panels (mode, tool calls, route, GPS) | replayed trips pass |
| M1g | Field test Home → Northpoint with the glasses, when Haziq is back and they are assembled; record, fix, repeat | §1 pass bar |

`core/AGENTS.md` is updated in the same change as every step (its own rule), and its stale status lines are fixed first.

## 11. Open items and risks

- **Which way the user faces** (decided 2026-11-26: GPS course + street-relative, plus camera assist). The rig has
  no IMU and a pocketed phone gives a poor heading. While walking, GPS course sets left/right. When standing still,
  instructions are relative to streets and landmarks ("walk along Yishun Ave 2 towards the bus stop"). Camera assist:
  at decision points (a turn, a stop, a station exit) the brain asks the LM about the current view (street sign,
  landmark, bus stop pole) to confirm the user faces the right way before saying left/right. The camera check is
  measured in M1f and dropped from the pass bar if it is too slow or wrong.
- **Portable rig for the field test** (decided: USB-C PD power bank). Box + power bank + C270 + earbuds + phone in a
  bag. Before M1g: check the box's PD needs and measure the draw over a trip-length run.
- **LFM3 tool skill on Q4_0 is unmeasured** (CORTEX-ENGINE.md §7). M0 decides.
- **Tool calls add decode time** before the first sound; the "Checking." line covers it, M0 measures it.
- **OneMap terms** for bulk postal-code download must be checked before step M1c; OSM data needs ODbL attribution in the app.
- **No timetables**: offline waits are estimates; said as estimates.
- **MRT indoor guidance** (gantries, platforms) is camera-only and depends on LM vision quality with the C270.
- **Context room**: tool list + state line + view + history must fit 4096 tokens; M0 measures.
