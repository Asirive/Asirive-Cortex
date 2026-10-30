# Cortex App — screens, plan and server gaps

**Status:** draft for review, 2026-10-30. Mockups (18 screens, clickable): the
"Cortex App Mockups" canvas shared in the build session. This file is the written
companion: what each screen needs from the server, what is missing, and the order
to build in.

Scope: the Flutter app described in `V4-ECOSYSTEM.md` §5 (one app, wearer mode and
companion mode). Server contract: `contracts/openapi/app.yaml`.

---

## 1. Design principles

- **Built for blind and low-vision wearers first.** Every control is a real
  button/switch with a spoken label, tap targets are at least 48 px, text is large,
  contrast is high, nothing depends on colour alone. Everything must work with
  VoiceOver and TalkBack before it is called done.
- **Companions are the sighted side.** Same app, different tab. They only ever see
  what the wearer granted (location, call). Never the camera.
- **The app is a relay, not a brain.** It pairs, updates, shares and calls. The
  assistant and the safety alerts run on the pocket module and must never depend
  on the app being open.
- **Honest copy.** The text on screen states only what the server really does
  (30-day location retention, voice-only unrecorded calls, no camera).

## 2. Screens and what each one needs

| # | Screen | Server endpoints | Status |
|---|---|---|---|
| 1 | Sign in | `POST /v1/auth/login` | ready |
| 2 | Create account | `POST /v1/auth/register` | ready |
| 3 | Check your email | `POST /v1/auth/verify`, `/resend` | ready |
| – | Forgot password | `POST /v1/auth/reset-request`, `/reset` | ready (screen not mocked yet) |
| 4 | Pair glasses | `POST /v1/claim` plus the phone↔module USB/BLE link | server ready, **link not built** |
| 5 | Home | `GET /v1/me/devices` | ready; battery/safety fields need confirming |
| 6 | Pause the assistant | `POST /v1/me/devices/{id}/stop` | **not implemented** |
| 7 | Software update | `GET/POST /v1/me/devices/{id}/update` plus module hand-off | server ready, **hand-off not built** |
| 8 | Settings | `GET /v1/me`, `PUT /v1/me/beta`, `PUT /v1/me/push` | partly ready (see gaps) |
| 9 | Join beta | `PUT /v1/me/beta` (consent version `beta-2026-10`) | ready |
| 10 | My people | `GET /v1/companions` | ready |
| 11 | Invite someone | `POST /v1/companions` | ready |
| 12 | What they can see | `PUT /v1/companions/{id}/grants`, `DELETE /v1/companions/{id}` | ready |
| 13 | Send feedback | `POST /v1/feedback` | ready |
| 14 | Privacy and data | `DELETE /v1/me/location`, `DELETE /v1/me` | ready |
| 15 | Accept invite | `POST /v1/companions/accept` | ready |
| 16 | Following | `GET /v1/companions` (people I follow) | ready |
| 17 | Where they are | `GET /v1/companion/users/{id}/location` | ready |
| 18 | Incoming call / On a call | `POST /v1/calls`, `/answer`, `/ice`, `/end`, `GET /v1/calls/inbox`, `/ice-servers` | ready; push needs real keys |

## 3. Server gaps found while drawing the screens

These are small and are the first server tasks once the design is agreed.

1. **Change password** (signed in). Today only the email reset flow exists.
2. **Change email.** Not present.
3. **Pause / stop the assistant** (`/me/devices/{id}/stop`): in the contract, not
   implemented. The module already has an owner-stop handler; the gateway needs
   the route and the audit entry.
4. **Cancel an open invite.** Confirm that `DELETE /v1/companions/{id}` covers an
   unaccepted invite, or add a route.
5. **"Who viewed my location".** The Privacy screen lists who *can* see it. A
   viewed-at log is not stored. Decide whether to add it.
6. **Device status fields** for Home (battery, safety summary, software version,
   last seen): confirm that `GET /v1/me/devices` returns them from the live
   heartbeat, and that the module's heartbeat carries real safety status (today
   it reports degraded until the safety process publishes).
7. **Accept-invite deep link** (`cortex.asirive.com/i/<code>`): needs a small
   landing page and universal/app links configuration.
8. **Export my data** is not mocked and not built. Add if required by policy.

## 4. Things the app cannot do until other work lands

- **Pairing and updates** need the phone↔module link (USB first, BLE later) that
  carries the claim reply to the module and the update file to the module. This
  is device-side work (`core/`) plus a native-capable Flutter plugin.
- **Calls ringing on iOS** need PushKit + CallKit. A normal push cannot make the
  phone ring like a call. Android can ring with a high-priority FCM message.
- **Background location** (wearer's phone sends position while the app is
  closed) needs the iOS "Always" permission and Android foreground-service work.
  App-store review will ask for a clear reason.

## 5. Technical choices (proposed)

- Flutter, iOS first, Android kept working.
- State: Riverpod. Navigation: go_router (needed for invite deep links).
- API client generated from `contracts/openapi/app.yaml`, so the app and the
  gateway cannot drift.
- Tokens in the OS secure store (Keychain / Keystore). Never in plain prefs.
- Calls: `flutter_webrtc`, using the gateway's signalling and TURN credentials.
- Push: `firebase_messaging` (FCM) on Android, APNs on iOS.
- Maps: platform maps (no API key in the app) for the location screen.
- Accessibility tests run in CI (semantics tree checks) from the first screen.

## 6. Build order

1. **Foundation:** project skeleton, theme (the mockup tokens), API client,
   secure token storage, sign-in / create account / verify / reset. Runs against
   the real gateway.
2. **Wearer basics:** Home, Settings, Beta, Feedback, Privacy and data.
3. **People:** My people, Invite, grants, Accept invite (deep link).
4. **Companion mode:** Following, Where they are.
5. **Calls:** signalling, in-call UI, push; Android first, then PushKit/CallKit.
6. **Device link:** pairing and software update once the module side exists.
7. **Polish:** screen-reader pass on every screen, large-text pass, store
   listing, privacy labels.

Steps 1–4 need no hardware and can be built and tested now. Steps 5–6 are gated
by the push keys and the device link.

## 7. Open questions for the product owner

- Wearer-facing text: should the assistant read the app screens aloud itself, or
  rely on the phone's screen reader?
- "Pause the assistant": confirm that obstacle warnings keep running while paused
  (the mockup says so).
- Which companion relationship labels exist (Family, Friend, Medical professional)
  and does "Medical professional" need any verification or just a label?
- Should a companion be able to invite someone else, or only the wearer?
- Languages needed at launch.
