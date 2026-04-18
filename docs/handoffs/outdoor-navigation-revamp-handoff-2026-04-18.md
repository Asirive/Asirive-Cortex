"""
Outdoor Navigation Revamp Handoff

Working context for the next AI agent taking over ProjectCortex outdoor navigation.

Author: GitHub Copilot
Date: April 18, 2026
"""

# Project Context

ProjectCortex is an AI wearable for visually impaired users built around a Raspberry Pi 5. The current workstream is a revamp of outdoor navigation with deeper Gemini integration.

This handoff focuses on:
- the current outdoor navigation architecture
- where Gemini is integrated today
- the main architectural problems
- the recommended redesign direction
- relevant runtime constraints already discovered earlier in the session

# Current High-Level Reality

Outdoor navigation is currently split across multiple control paths:

1. Gemini-online path:
- When Gemini Live is online, voice commands are not locally re-parsed into navigation actions.
- Live audio is continuously streamed to Gemini.
- Gemini decides whether to call tools like `start_outdoor_navigation`, `stop_navigation`, or `get_navigation_state`.

2. Gemini-offline fallback path:
- If Gemini is offline or reconnecting, `main.py` falls back to a legacy keyword-driven navigation handler.
- That code manually parses phrases like `navigate to`, `stop navigation`, `where am i`, `i'm lost`, `resume navigation`, and bus-related commands.

3. Navigation engine path:
- `NavigationEngine` is still the actual executor for route fetching, waypoint progression, GPS-loss behavior, transit logic, arrival, and some voice output.

The result is not a single clean navigation architecture. It is a layered mix of:
- Gemini tool calling
- old keyword routing
- route-state machine logic in `NavigationEngine`

# Key Files

## Main orchestration
- `rpi5/main.py`

Relevant sections:
- Gemini setup and tool callback wiring
- navigation engine initialization
- Gemini nav-event forwarding
- Gemini tool-call handler
- `handle_voice_command()`
- legacy local layer3 navigation fallback

Important line regions observed during analysis:
- navigation engine init: around `1418-1505`
- Gemini nav mode / nav event bridging: around `1940-2368`
- Gemini tool-call handling: around `2205-2368`
- voice command handling and Gemini-online shortcut: around `3190-3360`
- legacy layer3 local navigation flow: around `3652-3810`

## Navigation engine
- `rpi5/layer3_guide/navigation_engine.py`

Relevant regions:
- `start_navigation()`: around `829`
- `stop_navigation()`: around `959`
- `resume_navigation()`: around `990`
- main nav loop: around `1069-1505`
- vision context update: around `1550`
- status export: around `1638`
- retrace logic: around `1676`
- context string export: around `1739`

## Gemini Live tool declaration and transport behavior
- `rpi5/layer2_thinker/gemini_live_handler.py`

Relevant regions:
- system behavior and mode prompt: around `160-260`
- function/tool declarations: around `328-440`
- tool-call receive loop: around `670-717`
- `send_text()`: around `1122`
- `send_context()`: around `1172`

# Current Outdoor Navigation Behavior

## When Gemini is online

`handle_voice_command()` does this:
- stores the confirmed STT transcript
- checks privacy mode and a few local critical commands
- if Gemini Live is connected, it does not resend the query text as a new command
- it relies on the already-streaming live audio path and Gemini tool calling
- it sends a video frame best-effort to Gemini

This means Gemini is expected to infer navigation intent from the live audio stream and then call tools.

## Gemini tools currently exposed for navigation-related behavior

Declared in `gemini_live_handler.py`:
- `get_navigation_state`
- `report_obstacle`
- `get_gps_accuracy`
- `get_bus_arrival`
- `start_outdoor_navigation`
- `guide_indoor`
- `stop_navigation`
- `search_memory`
- `set_system_mode`

Implemented in `main.py` via `_handle_gemini_tool_call()`.

## Guardrails already present

There is a useful safety guard in `_recent_query_supports_tool_call()`:
- high-impact Gemini tools like `start_outdoor_navigation` and `guide_indoor` are checked against the most recent confirmed STT transcript
- if the destination or intent does not match the recent transcript, the tool call is blocked

This is important and should be kept.

## When Gemini is offline

The code falls back to local keyword-based navigation logic in `handle_voice_command()`.

That fallback currently handles:
- start navigation
- ask for origin when GPS is unavailable
- saved-location origin selection
- queue pending navigation until GPS arrives
- stop navigation
- retrace steps / `i'm lost`
- bus queries
- resume navigation
- reverse geocode / `where am i`

This logic is separate from the Gemini tool-call path even though both drive the same engine.

# NavigationEngine Findings

`NavigationEngine` is still the true navigation backend.

It currently owns:
- route fetching from Google Maps
- transit route parsing
- waypoint interpolation
- navigation loop timing
- waypoint advancement
- transit leg transitions
- GPS loss detection
- indoor/outdoor/transit mode switching
- breadcrumb retrace
- some TTS prompts
- nav-event emission for Gemini

It also exposes:
- `get_status()` for route progress
- `get_context_string()` for a summarized state string
- `update_vision_context()` and `get_vision_summary()` for contextual awareness

## Critical mismatch

The engine still behaves conceptually like a spatial-audio outdoor guidance system, but the beam guidance has been scrapped.

Evidence:
- comments say `spatial audio` and `beam` are scrapped
- `spatial_audio` is kept only for compatibility in the engine
- `_speak_turn()` is intentionally silent because the original design assumed the beam direction itself was the guidance
- user-facing strings in `main.py` still say things like `Follow the audio beam`

This creates a real UX inconsistency:
- the code assumes silent turn guidance exists
- the beam no longer exists
- Gemini 3.1 background proactive turns are intentionally suppressed in many cases
- therefore outdoor guidance can become weak or ambiguous at exactly the wrong moments

# Gemini Integration Findings

## What is good

Gemini is already reasonably integrated as a tool-calling copilot.

It can:
- start outdoor navigation
- activate indoor guidance
- stop navigation
- inspect nav state
- inspect GPS accuracy
- query bus arrivals
- search memory

The system prompt also has explicit mode-driven behavior for:
- `IDLE`
- `OUTDOOR_NAV`
- `INDOOR_NAV`
- `BUS_WATCH`
- `TRANSIT`
- `EXPLORE`

## What is not reliable today

Gemini is not currently a dependable proactive outdoor turn-by-turn narrator on this runtime.

Reasons:
- mid-session context injection is disabled for Gemini 3.1 Live in `send_context()`
- synthetic background turns are intentionally suppressed on Gemini 3.1 to avoid 1007 invalid-argument session failures
- cross-stream ordering is not guaranteed between live audio, video, and text
- prior runtime investigation showed that proactive system-triggered Gemini turns can destabilize Live sessions

So the system currently tries to treat Gemini like a live outdoor nav companion while also having to suppress many of the mechanisms that would make that possible.

# Previously Established Runtime Constraints

These were discovered earlier in the session and matter for any redesign:

1. Gemini 3.1 Live is fragile with mixed mid-session updates.
- `send_client_content` mid-session is not safe on this path.
- synthetic text turns during continuous audio can trigger 1007 failures.

2. Manual VAD turn boundaries matter.
- every valid VAD segment must produce a matching activity end event.

3. Tool handling must stay synchronous and non-blocking for the receive loop.

4. High-impact tool calls should remain gated against recent confirmed STT.

5. Cross-stream ordering between audio/video/text should not be assumed.

These constraints strongly argue against a design where Gemini is the sole real-time outdoor navigation controller.

# Main Problems To Solve

## 1. Multiple orchestration paths

There are currently separate outdoor-nav flows for:
- Gemini tool calling
- local offline keyword parsing
- dashboard command handling

All of them should end up hitting one authoritative orchestration layer.

## 2. Beam-based language and assumptions are stale

The product still says `follow the audio beam` even though the beam logic is gone.

## 3. Guidance responsibility is unclear

Right now:
- `NavigationEngine` owns route execution
- Gemini owns some intent and some situational narration
- the old local code still owns full outdoor command parsing in fallback mode

The system boundary is blurry.

## 4. Outdoor guidance is under-specified without beam audio

If beam guidance is removed, the outdoor system needs a deterministic verbal guidance model for:
- continue straight
- approaching turn
- execute turn
- crossing ahead
- GPS degraded
- off-route
- re-route
- arrival

## 5. Indoor and outdoor behavior are entangled

The engine switches to indoor mode when GPS disappears, but Gemini session behavior and outdoor turn narration are constrained by the Live session limitations.

# Recommended Direction

## Core recommendation

Make outdoor navigation deterministic and local-first, with Gemini as a copilot.

Do not make Gemini the sole owner of real-time outdoor turn execution.

## Proposed architecture

### 1. Introduce a single navigation coordinator

Create one authoritative orchestration surface, either by refactoring `NavigationEngine` or adding a new `OutdoorNavigationCoordinator`.

This layer should own:
- start / stop / resume / cancel
- route planning
- pending origin workflow
- pending GPS workflow
- off-route handling
- degraded GPS handling
- handoff to indoor mode
- session state and summaries

Everything else should call this layer:
- Gemini tool calls
- local fallback commands
- dashboard navigation commands

### 2. Keep Gemini at the intent and context layer

Gemini should handle:
- intent understanding
- destination normalization and clarification
- reading signs and landmarks
- natural language Q&A about the route
- situational scene understanding
- bus/POI/landmark explanation

Gemini should not be the sole critical-turn scheduler.

### 3. Move outdoor turn prompts back into deterministic local logic

If no beam exists, local code must speak short route-critical prompts itself.

Examples:
- `Turn left in 10 meters.`
- `Crosswalk ahead. Wait and listen for traffic.`
- `Continue straight for about 50 meters.`
- `GPS weak. I may be less accurate. Slow down.`

Gemini can add value around those prompts, but should not replace them.

### 4. Expose pull-based tools for Gemini instead of relying on pushed context

Given current Gemini 3.1 Live limitations, the model should request navigation state when needed.

Useful tool surface additions could include:
- `get_navigation_state`
- `get_route_leg_summary`
- `get_off_route_status`
- `get_gps_confidence`
- `get_navigation_session_summary`

This is safer than trying to constantly inject background navigation context.

### 5. Preserve local fallback as a thin adapter only

Offline fallback should not contain a separate outdoor navigation implementation.

Instead it should:
- parse the command minimally
- call the same coordinator methods used by Gemini tools

### 6. Remove stale beam terminology

Every user-facing line that says `follow the audio beam` should be removed or rewritten unless the beam is being brought back.

# Good Refactor Sequence

If the next AI takes this on, a safe order would be:

1. Document the canonical navigation states and transitions.
2. Extract all outdoor-navigation start/stop/origin/pending-GPS logic behind one coordinator API.
3. Convert the local fallback path to call that coordinator.
4. Convert the Gemini tool handlers to call the same coordinator.
5. Replace beam-based turn assumptions with deterministic local voice prompts.
6. Add route/session summary tools for Gemini.
7. Only then decide whether Gemini should proactively narrate some events on top.

# Immediate Tactical Changes Worth Making

These are relatively high-value and low-risk:

1. Remove `follow the audio beam` text from outdoor navigation responses.
2. Stop assuming silent beam direction is enough for turn execution.
3. Consolidate the duplicated `start navigation` logic into one method.
4. Consolidate `pending destination` and `awaiting origin` handling so both Gemini and fallback use the same code.
5. Keep the recent-confirmed-STT gate for Gemini tool calls.

# Open Design Questions For The Next AI

1. Is spatial audio actually coming back for outdoor navigation, or is outdoor guidance now voice-first?
2. Should Gemini be allowed to ask clarifying route questions live, or should that be limited to a pre-navigation setup phase?
3. Should off-route detection and reroute narration be entirely local, with Gemini only explaining what changed?
4. How should indoor handoff be represented to the user when GPS is lost mid-route?
5. Should bus and transit be first-class substates in the same outdoor session coordinator?

# Additional Broader Session Context

There was prior work in this session around Gemini-only runtime stabilization on the Pi:
- YOLO / Layer 0 / Layer 1 loading paths were disabled for Gemini-only mode
- camera pixel format handling was fixed
- manual-VAD lifecycle and Gemini 3.1 Live session issues were investigated
- proactive Gemini background turns were reduced or disabled on 3.1 because they could destabilize sessions
- memory compatibility fixes and playback overlap fixes were made earlier

That history matters because any new outdoor-nav design must respect the existing Gemini 3.1 Live stability constraints.

# Bottom-Line Handoff Summary

Current diagnosis:
- the system already has Gemini-integrated outdoor navigation
- but the architecture is split, duplicated, and internally inconsistent
- the deepest issue is not lack of Gemini integration but lack of a single authoritative navigation orchestration layer
- outdoor guidance still assumes a beam-based interaction model that no longer exists in practice

Recommended principle:
- make the navigation core deterministic and local-first
- make Gemini the conversational and visual copilot on top of that core
- unify all entrypoints into one coordinator
