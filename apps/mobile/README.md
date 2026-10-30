# Cortex app (Flutter)

The phone app for Asirive Cortex. Design rules and screens: `docs/architecture/APP-PLAN.md`;
clickable mockups: `docs/design/mockups/`.

## What is built

- Foundation: theme, bundled fonts, shared parts, gateway client, secure token storage
- First open (4 intros, Welcome), account (create, check email, sign in, forgot, signed out)
- Two sides, one account: owner (Home, My people, Settings, plus Following if also a companion)
  and companion-only (Following, Settings). Side is picked from the account and remembered.
- Invite flow: Scan, Enter code, Accept (signed in or out); an invite scanned before sign-in is applied at sign-in
- Owner: Home status and "Hear my status", My location (find, share, open in Maps), Share internet steps and test,
  Software update, Pause the assistant, My people, Invite (code and QR), What they can see, Remove
- Companion: Following, Where they are (age, stale warning, open in Maps), calls
- Calls: outgoing, incoming (the shell watches the inbox), mute and speaker, WebRTC through the gateway
- Settings: Voice, sound and text (saved on the phone), Beta, Feedback, Privacy, delete location history,
  delete account, Switch side, Account
- Glasses setup with a sighted helper: five steps, owner confirms the box code and the hand back,
  "Stop helper mode" on every step, inactivity lock

## Not finished, said plainly

- **Phone-to-box USB link is not built.** `DeviceLink` in `lib/services.dart` is the seam; the default
  `UnavailableLink` reports the cable as out. Until it is built, pairing stops at "plug in the box",
  and Pause and Install update say the box could not be reached. Nothing pretends to succeed.
- Not run on a phone or simulator (this build environment has no iOS or Android SDK). The native
  plugins (camera, location, voice, calls, Face ID) are wired and permissions are in
  `Info.plist` and `AndroidManifest.xml`, but are untested on a device.
- No push notifications yet (incoming calls are found by polling while the app is open). The server
  has push registration; the app needs the platform push setup and a PushKit/CallKit step.
- Email confirm and reset links do not open the app (no deep links yet).
- The Voice, sound and text settings live on the phone; the server has no preferences endpoint.
- "Bold text" replaces the "extra contrast" idea; a true high-contrast colour set is not built.
- The map is coordinates plus "Open in Maps", not an in-app map.
- Reading the screen with a real screen reader and testing at 200% text on a device is still to do.

## Run

```
flutter pub get
flutter run --dart-define=GATEWAY_URL=https://your-gateway.example
flutter test
```

`GATEWAY_URL` defaults to a placeholder, so without it every call reports "Can't reach Cortex".
