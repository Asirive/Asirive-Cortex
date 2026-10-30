# apps/ — AGENTS.md

**Domain:** user-facing surfaces (device CLI today, companion app and web
dashboard next).
**Owner:** app domain agent. Languages: Python (CLI), Dart/Flutter (companion
app, greenfield), TypeScript (web dashboard, greenfield).
**RULE: every new file, module or behavior change in apps/ MUST update this
AGENTS.md in the same change. No exceptions. This file is the first thing the
domain agent reads and the last thing it writes.**

Reference architecture: `docs/architecture/V4-ECOSYSTEM.md`.

---

## What lives here today

| Path | Role | Status |
|:---|:---|:---|
| `cortex/` | Device CLI + Textual TUI launcher (`python -m apps.cortex all`) | Active dev tooling |
| `cortex/__main__.py` | Command router: all, test, test-live, layer0, camera, audio, status, tui | Active |
| `cortex/cli/` | Rich logging setup, command implementations, live TUI | Active |
| `mobile/` | Flutter companion app (owner and companion sides, calls, helper setup). See `mobile/README.md` | Built, untested on device; USB link missing |
| `laptop_dashboard/` | V3 FastAPI/WebSocket browser dashboard + GPU layer-1 service | DEPRECATED: replaced by the companion app + web dashboard. Keep only as message-shape reference |

Root entry wrappers `cortex.py`, `cortex`, `cortex.bat` call into this package.

## The companion app (greenfield, Flutter)

One application, iOS first (majority of blind users are on iOS/VoiceOver),
Android in scope. Two modes:

- **User mode.** Device pairing (QR code in person or remote invite link, USB
  claim), settings, beta opt-in, feedback submission, per-companion permission
  grants (friends, family, certified medical professionals; the user selects
  exactly who sees what), mic controls.
- **Companion mode.** User location (30-day TTL, consented per companion) and
  WhatsApp-style voice calls. NEVER a live camera feed. NEVER stored photos
  or video.

App responsibilities beyond UI: relay (phone GPS over USB to the compute
module, internet via tether), VoIP (WebRTC), provisioning, OTA delivery
(download -> USB -> compute module -> glasses MCU).

Login: Apple ID + email. iOS "Always" location + background navigation mode
while tethered. GPS is used outdoor only.

## The web dashboard (greenfield)

React/Svelte frontend against the Go fleet gateway API: fleet view, update
rings, feedback tab. Dev/alpha on the self-host server, VPS at beta.

## Hard rules

1. Accessibility is the product: VoiceOver/TalkBack support, screen-reader
   labels, no color-only states. The user may be totally blind, partially
   sighted, or a sighted companion.
2. Privacy surfaces: location and calls only for companions; no live feed
   anywhere in the UI; no media in feedback.
3. Keep `python -m apps.cortex` as the stable device CLI contract; document
   any new subcommand here.

## How to run and check

```bash
python -m apps.cortex all        # full system
python -m apps.cortex status     # env / config / layers
python -m apps.cortex test-live  # Gemini Live probe
py -3 -m compileall apps         # syntax gate after changes
```

## Change log (append one line per meaningful change)

- 2026-10-12: AGENTS.md created. laptop_dashboard marked deprecated; Flutter
  app and web dashboard defined as greenfield targets.
- 2026-10-30: `mobile/` Flutter app added and every screen matched to the mockups; tests rewritten (49 pass). USB link, push and device testing still open.
- 2026-10-30: `mobile/lib/box_link.dart` added: real `DeviceLink` over the USB tether network (see `docs/architecture/PHONE-BOX-LINK.md`). `DeviceLink.handOver` now takes the whole claim reply.
- 2026-10-30: `mobile/lib/push.dart` added: the app registers its FCM/APNs address with the gateway after sign-in and clears it on sign-out. Off without Firebase config files; see mobile/README.md for the accounts needed.
