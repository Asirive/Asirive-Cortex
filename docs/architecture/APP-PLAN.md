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

---

# Part B — added 2026-10-30

Decisions from reviewing the mockups with the product owner, and the design
rules the Flutter build must follow. The clickable mockups are the visual
reference; `docs/design/app-mockup.css` is the exact stylesheet they use and
`docs/design/asirive-logo.svg` is the brand mark.

## 8. Two sides of one app: owner and companion

The app has two sides. They are different experiences, not one app with a
bonus tab.

| | **Owner** (the person who wears Cortex) | **Companion** (someone who looks after them) |
|---|---|---|
| Needs glasses | yes | no |
| First run | create account → confirm email → pair glasses | open invite link → create account or sign in → accept |
| Sees | own device status, update, people, settings, privacy | only what each owner granted: location and call |
| Controls | grants, invites, pause, beta, data deletion | call, view location |
| Navigation | Home · My people · Settings | Following · Settings |

Rules:

- An account can be one side or both. A companion-only account must never see
  pairing, device or update screens.
- A user who is both gets a visible switch (profile button on Home, and
  Settings → "Switch side"). The last side used is remembered.
- In the current mockups the four-tab bar shows both sides at once. That is the
  "both" case. Owner-only and companion-only bars are the shorter sets above.
- The companion never gets anything the owner did not grant, and the server
  enforces it. The app only reflects it (greyed "not allowed" buttons).

## 9. Internet for the glasses, over USB

The pocket module has no SIM of its own. Its internet comes from the owner's
phone over the same USB-C cable used for pairing.

What the app does and does not do:

- **Recommended for alpha: the phone's own USB tethering.** Android "USB
  tethering" and iPhone "Personal Hotspot" over cable both make the phone look
  like a network adapter to the module. This is done by the phone's operating
  system, not by our app. There is no traffic proxy to build or secure.
- **The app's job** is to make this easy and visible: detect that the module is
  connected, check whether it has internet, and walk the owner through turning
  tethering on when it is not.
- The module keeps its own end-to-end secure channel to the gateway (mTLS), so
  the phone and the mobile network only carry encrypted traffic.
- A custom in-app tunnel (VpnService on Android, Network Extension on iOS) is
  only needed if OS tethering proves unreliable. That is a large piece of
  work with its own app-store review. Decide after field tests.

Screens and states to design (not yet in the mockups):

1. Home connection strip: Connected and online · Connected, **no internet**
   (tether is off) · Not connected (cable out).
2. "Share internet" help screen with steps for iPhone and for Android, and a
   test button that reports "internet reachable from the module".
3. A short heads-up on data use and on battery drain of the phone.
4. First-run pairing includes a "turn on tethering" step after the module is
   found.

Open points:

- iPhone Personal Hotspot over cable and its stability with the module's USB
  gadget mode need a hardware test before the plan is final.
- Background rules: if the phone locks or the app is closed, tethering must
  keep working. Another test item.
- What the glasses do with no internet is a safety matter: obstacle warnings
  must not depend on it (already the design rule for the safety process).

## 10. Design rules

### 10.1 Principles

1. **Built for blind and low-vision owners first.** The app must be fully
   usable with VoiceOver and TalkBack. Visual polish never replaces that.
2. **Bold, flat, high contrast.** Near-black ground, one electric yellow,
   big type. No gradients, no drop shadows, no stock icon-and-label lists.
3. **Show live information, not menus.** Home is tiles that carry real data
   (battery, update, people, safety) instead of a list of links.
4. **Honest copy.** Say only what the system does. Plain words, short
   sentences, no jargon.

### 10.2 Colour

| Token | Value | Use |
|---|---|---|
| `ground` | `#0A0A08` | screen background |
| `surface` | `#131A14` | tiles, lists, search, nav |
| `surface-line` | `#223024` | dividers, nav border |
| `outline` | `#2C3A2E` | outlined buttons, switch off-track, back button |
| `text` | `#F4F4EC` | primary text |
| `text-muted` | `#B6BFB0` | body secondary |
| `text-quiet` | `#9AA394` | labels, helper text, inactive icons |
| `accent` | `#EAFF00` | brand yellow, taken from the Asirive logo |
| `on-accent` | `#0A0A08` | text and icons on yellow |
| `danger` | `#FF8A7D` (text) · `#FF6B5E` (end call) | destructive actions |

Use yellow for: the page title, the single primary action, the active nav item,
progress, and live status. Never more than one yellow filled block competing
with the primary button on a screen unless it is a status tile.

Contrast: text and interactive icons must reach 4.5:1 against their surface.
`text-quiet` on `surface` passes; do not use anything dimmer for information.
Colour is never the only signal; pair it with text or shape.

### 10.3 Typography

| Role | Font | Size / line | Notes |
|---|---|---|---|
| Hero title | Anton | 52–64 / 0.95 | uppercase, tracking +0.02em, yellow |
| Screen title | Anton | 32–44 / 1.0 | uppercase, tracking +0.03em, yellow (white on call screens) |
| Header greeting | Anton | 28 / 1 | uppercase |
| Big numbers | Anton | 40–44 / 1 | battery, counts; `%` at half size |
| Body | Space Grotesk 400/500 | 15–16 / 1.45 | |
| Row title, button | Space Grotesk 600/700 | 16–17 | |
| Small helper | Space Grotesk 400 | 13 / 1.4 | `text-quiet` |
| Label | JetBrains Mono 500 | 10.5, tracking +0.14em, uppercase | section labels, status words |

Rules: Anton is for short display text only, never paragraphs. All three fonts
are bundled in the app, not fetched at run time. Text scales with the system
text-size setting; layouts must hold at 200%. Use real text, never text baked
into images.

### 10.4 Layout and shape

- Side margin **14 px** on every screen, no exceptions. Everything aligns to it.
- Vertical rhythm: 14 px between blocks, 8 px inside tight groups.
- Radius: tiles and lists **22**, search and buttons are full pills, bottom
  sheets **32**, the logo mark stays square.
- Touch targets: at least 44 × 44, primary buttons 56 high, inputs 52 high.
- The status strip is **flush**: the yellow battery bar sits directly on the
  search pill with no gap, inset by the pill's corner radius, and the
  percentage ends exactly where the yellow ends.
- Sticky actions sit at the bottom above the safe area; the nav bar floats
  16 px from the bottom.

### 10.5 Components

- **Primary button:** yellow pill, black text. One per screen.
- **Secondary button:** outlined pill (`outline`), light text.
- **Danger button:** outlined, `danger` text. Always asks for confirmation.
- **Tile:** `surface` card with a mono label, a number or short value in
  Anton, and one line of detail. A small round arrow marks it as tappable.
- **List:** one `surface` card, 54–60 high rows, hairline dividers.
- **Switch:** yellow when on. Always a real switch control with a spoken name.
- **Chip:** small pill; yellow means active or granted.
- **Navigation bar:** floating pill. The active item is a yellow capsule with
  its label; the others are icon only with spoken names. Settings uses the
  sliders icon, never a sun or gear lookalike.
- **Steps:** numbered circles; done is filled yellow with a tick, current is
  outlined yellow.
- **Progress:** a yellow bar on a dark track, with the number beside it.
- **Bottom sheet:** used for consent (beta). Dimmed background, 32 radius.

### 10.6 Iconography

Outline icons, 2 px stroke, round caps, 22–24 px. Icons never carry meaning
alone: each has a text label or a spoken name. The product-specific "seven
zones" safety bars are the only custom graphic.

### 10.7 Accessibility, as requirements

- Every control has a spoken name and role. No tappable plain text blocks.
- Reading order matches visual order. Progress, status and the call timer are
  announced as they change.
- Large-text and screen-reader passes are part of the definition of done for
  each screen, run in CI where possible (semantics checks).
- Reduced motion is respected. The mockups use no animation; any motion we
  add must be optional.
- Incoming calls and device alerts must be reachable without sight: spoken
  alerts and haptics, not only visuals.

### 10.8 Copy rules

Short, calm, direct. Name the thing (`Pause the assistant`, not `Disable`).
State what happens next. Never claim more than the system does (for example,
say "kept up to 30 days", not "private").

## 11. Updated screen list

Adds to section 2:

| Screen | Side | Status |
|---|---|---|
| Home connection states (online, no internet, cable out) | owner | to design |
| Share internet help (iPhone and Android) | owner | to design |
| Forgot password | both | to design |
| Switch side | both | to design |
| Companion-only Settings | companion | to design |

## 12. Updated build order

1. Foundation: theme from section 10, fonts bundled, API client, secure
   storage, sign-in, create account, verify, reset.
2. Side model: owner and companion navigation, switch, role-aware first run.
3. Owner basics: Home, Settings, Beta, Feedback, Privacy and data.
4. People and invites, companion mode.
5. Calls.
6. Device link: pairing, update, **internet sharing check** (needs hardware).
7. Accessibility and polish.

---

# Part C — review round, 2026-10-30

Three read-only reviews of the mockups were run: a blind owner using a screen
reader, a sighted non-technical companion, and a product/accessibility/contract
reviewer. This part records what changed and what is still open. The clickable
mockups are on the design canvas; their source is committed in
`docs/design/mockups/` (`*.dc.html`, with the shared `docs/design/app-mockup.css`).
The hero photo is the V3 prototype and is a stand-in. The files link each other
with relative `href`s; open them through the canvas to see the flows.

## 13. The flows (40 screens)

Row order on the canvas is the order of use.

1. **Account (everyone):** Sign in · Create account · Check your email ·
   Forgot password · Reset link sent · New password · Signed out.
2. **Set up the glasses with a sighted helper (owner):** Set up with a helper ·
   Helper mode · Helper 2 pair · Owner confirms the box · Helper 3 share
   internet · Helper 4 test sound and touch · Helper 5 hand back.
3. **Owner home:** Home · Home, no internet · My location (map) · Confirm:
   pause assistant · Confirm: install update · Software update.
4. **Owner settings and privacy:** Settings · Voice, sound and text · Join beta
   · Send feedback · Privacy and data · Confirm: delete history · Confirm:
   delete account.
5. **Owner people and sides:** My people · Invite someone · What they can see ·
   Confirm: remove companion · Switch side.
6. **Companion joining:** Accept invite · Create account (invited) · Check
   email (invited).
7. **Companion daily:** Following · Where they are · Incoming call · On a call ·
   Companion settings.

Entry points that have no inbound link on purpose: Accept invite (invite link),
Incoming call (push notification), Home no internet (a connection state),
Signed out (a 401 from the server), Companion settings (companion-only nav).

### Routing rules

- **Sign in routes by account type.** Owner or both → Home. Companion-only →
  Following. The mockup shows the owner path.
- **An invitee never sees owner setup.** Accept → create account or sign in →
  confirm email → Following with the invite applied. The "Step n of 3" counter
  and glasses setup belong only to owner sign-up.
- **Companion-only navigation is two tabs** (Following, Settings). Owner
  navigation is Home · My people · Following (only if also a companion) ·
  Settings. A both-sides user switches from the profile button or Settings.

## 14. Decisions made in this round

1. **Setup is done with a sighted helper, on the owner's phone.** The helper
   sits next to the owner, uses Helper mode, and reads each step aloud. Five
   steps: fit the glasses · plug in and pair · share internet · test sound and
   touch · hand back. The helper needs no account.
   - Helper mode is a **screen lock on the owner's session**, not a separate
     login. It shows only setup steps, has a visible "Stop helper mode" on every
     step and an inactivity timeout, and ends only when the **owner confirms
     with Face ID or passcode**.
   - The owner, not the helper, confirms what matters: the box code is read back
     to the owner ("ending 9QDX, is that what you heard?") and sound/vibration
     are confirmed by the owner.
   - If a real server-enforced scope is wanted later, it needs a short-lived
     "setup session" token that can call only `/claim` and device-link steps.
     Until then the privacy copy says only what the app does.
2. **Blind-assist features** are first-class, not an afterthought: a speaker
   button on Home that reads status, a "Say where I am" button on the map, a
   "Hear this screen" button on setup, a Voice, sound and text screen (speaking
   speed, haptic strength, spoken alerts, text size, extra contrast), and
   confirmations that are spoken and focus-safe (safest option first).
3. **Pause the assistant is local, over USB.** It is not a cloud route. The
   app sends a pause to the module over the cable; obstacle warnings keep
   running. It needs the cable, and the confirm sheet says so. The cloud
   `POST /v1/me/devices/{id}/stop` in the contract is the wrong place for it.
4. **A companion sees nothing until the owner grants it.** The server creates
   the grant with both flags false on accept. The Accept screen therefore says
   "They choose what you can see. Until they choose, you see nothing."
5. **Danger actions always confirm:** remove companion, delete location
   history, delete account (re-enter password), pause the assistant, install an
   update. Sign out is a single tap.
6. **Contrast fixed from the review:** outline colour raised to `#5C6F5F` (3:1
   for switch off-state and button edges); the disabled grey that failed
   (`#6F7869`) is gone; profile ring lightened; label text 12 px minimum.

## 15. Fixed in the mockups from the reviews

Companion route (invite → account → email → Following; two-tab nav; call end
and decline return to Following; Answer first in focus order; Mute and Speaker
are toggle buttons with pressed state); reset password now has a sent state and
a new-password screen; terms and log checkboxes are real checkboxes; the beta
switch is a single control; sliders are focusable with value text; segmented
choices carry a current marker; active nav items carry `aria-current`; Invite
asks for a name or label and shows the real link shape
(`…/companion?code=…`); Privacy no longer implies a viewed-at log; helper
screens use "pocket box" instead of "module"; copy no longer overclaims
(call audio is not recorded but a record that a call happened is kept 30 days;
"Nothing stays on their phone" removed; "a person reads every message" removed).

## 16. Still open

**Design**

- Cable-out state on Home (only "no internet" is drawn).
- Ringing, no answer, "phone on silent", "location is stale" and "no one
  followed yet" states for the companion.
- Android steps on the Share internet screen.
- Real selected states for toggles (the mockup is static).
- Mockup screens are fixed at 844 px and fit at normal text size. The real app
  scrolls, with a sticky bottom action bar, and must hold at 200% text. The
  My people "Invite someone" button overlaps the list once there are three or
  more people; it must become a sticky footer.
- Bottom sheets use an 8 px margin, not the 14 px rule.

**Server and contract changes the screens need**

| Need | Today | Change |
|---|---|---|
| Invite preview before sign-in | none (accept needs a session) | public preview route, or drop the name from Accept |
| Initial grants and label on invite | `POST /companions` takes only `label` | add grants; show relationship label |
| Map: street name, activity, trail | Point = lat, lon, accuracy, ts | add `place`, `activity` or geocode on device; history route for the trail |
| Location age | latest point can be 30 days old | always show age; "last seen" after about 15 min |
| Pause assistant | contract says cloud route | local USB command; remove from cloud contract |
| Internet check from the box | none | module probe over the USB link, surfaced in `/me/devices` |
| Voice, sound and text settings | no store | `/me/prefs`, synced to the module |
| Helper mode | UI-only | optional scoped setup-session token |
| Change password, change email | missing | add (gaps 1 and 2) |
| Feedback for companions | 400 unless the account has a device | allow, or hide for companions |
| Session expiry | fixed 30 days, no 401 UX | Signed out screen keeps the user's place |
| Viewed-at log | not stored | decide whether to add |

## 17. Updated build order

1. Foundation: theme, bundled fonts, API client, secure storage, the Account
   flow (including reset and signed-out handling).
2. Side model and routing by account type; companion join flow.
3. Owner basics and the blind-assist settings; confirmations.
4. People, invites, grants; companion Following and map.
5. Calls, including Answer-first accessibility and push.
6. Device link: helper-led setup, pause over USB, internet check, update.
7. Accessibility pass on every screen with a real screen reader, then 200% text.

## 18. First open (added 2026-10-30, revised after three-agent review)

Row 0 on the canvas: four intro screens, Welcome, Scan, Enter code and Code
error. Accept (invite) follows.

**Routing at launch.** No session on the phone: Intro 1, then Welcome. Session
present: straight to Home (owner) or Following (companion). The intro shows once
per install; Skip and Get started both mark it seen. An invite link opens Accept
directly and skips the intros. Intros can be replayed from Settings ("How Cortex
works", to build).

- **Intro 1 to 4** use the same tiles and chips as the rest of the app: *Get
  there on your own* (route), *Know what is ahead* (spoken warnings), *Ask about
  what is around you* (signs, prices, bus times by voice), *Family close by*
  (people you choose; "Family never sees your camera"). Intro 4 tells invitees to
  use Scan on the next screen. Each tile is marked as an example for screen
  readers; the pager reads "Step n of 4"; Skip reads "Skip introduction".
- **Welcome** splits the choice: *I use Cortex* (Create an account, Sign in) and
  *Someone invited me* (Scan or enter invite code).
- **Scan** explains the camera is only used to read the code, announces progress
  in a live region, and the torch button has a pressed state. "Enter the code
  instead" is a full yellow button, so it is not hidden for screen reader users.
- **Enter code** has a code field and a **Code error** state (typo or expired).
  Camera-permission-denied state is still to draw.
- **Accept** now has Back and Not now, says what the invitee may see, and that
  the owner sees only their name.
- Rule: onboarding reuses the same margins, headline sizes (44), tiles and
  buttons; tiles use min-height so 200% text can grow. Skip and pager styles now
  live in `cortex.css`.

**Copy decisions (owner, 2026-10-30):**
- "Works without internet" and "ears stay open to traffic": kept on Intro 2.
  Open speakers confirmed. Offline warnings are planned, so this line is only true
  once the offline safety path ships; it must not go live before then.
- "Nothing is saved" on Scan: not needed, removed for good.
- "Menus" as a readable item: not confirmed, left out.
- Bus times come from live arrivals data, so the example is illustrative.

**Still open:** camera-permission-denied state, whether helper pairing can start
from Scan (pairing needs an existing session), replay entry in Settings.
