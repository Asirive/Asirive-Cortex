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

## Phone-to-box link and push (built, untested on hardware)

- **Box link:** `lib/box_link.dart` talks to the box over the USB tether network (finds it by a UDP
  beacon, signs every command). Box side: `core/cortex_core/link/phone_link.py`. Spec:
  `docs/architecture/PHONE-BOX-LINK.md`. Tested app-against-fake-box and box-against-itself; the two
  share signature test vectors.
- **Push:** `lib/push.dart` registers the phone with the gateway (`PUT /v1/me/push`) after sign-in and
  forgets it on sign-out. The gateway already sends the "Incoming call" alert; tapping it opens the app,
  which finds the ringing call. Without the config files below, push is simply off and the app polls.

### Turning push on (needs your accounts)

1. **Firebase** (free): create a project at console.firebase.google.com. Add an Android app with id
   `com.asirive.cortex_app`, download `google-services.json` into `android/app/`. Add an iOS app with the
   bundle id from Xcode, download `GoogleService-Info.plist` into `ios/Runner/` (add it in Xcode).
2. **Apple** (Developer Program, paid, needed anyway for the App Store): in developer.apple.com, Certificates,
   Identifiers & Profiles, Keys, create a key with "Apple Push Notifications service" ticked and download the
   `.p8` file once. Note its Key ID and your Team ID. In Xcode, Runner target, Signing & Capabilities, add
   "Push Notifications" and "Background Modes: Remote notifications". In Firebase, Project settings, Cloud
   Messaging, upload the same `.p8` for the iOS app.
3. **Gateway:** `CORTEX_FCM_SERVICE_ACCOUNT` (a Firebase service-account JSON), `CORTEX_APNS_KEY` (the `.p8` path),
   `CORTEX_APNS_KEY_ID`, `CORTEX_APNS_TEAM_ID`, `CORTEX_APNS_TOPIC` (the bundle id). See `infra/gateway/README.md`.

## Not finished, said plainly

- Not run on a phone or simulator (this build environment has no iOS or Android SDK). The native
  plugins (camera, location, voice, calls, Face ID, Firebase) are wired and permissions are in
  `Info.plist` and `AndroidManifest.xml`, but are untested on a device. Whether the phone's hotspot
  lets the broadcast beacon through on a given phone model is the first thing to check with the box.
- On the box, the sound/touch test and update install report failure until the audio/haptic service and
  the OTA agent are connected to the link; the app says "could not reach the box" for those.
- A call that arrives with the app fully closed shows the alert, but there is no CallKit/ConnectionService
  ringing screen yet.
- The Voice, sound and text settings live on the phone; the server has no preferences endpoint.
- The "Extra contrast" switch currently turns on bold text only; a true high-contrast colour set is not built.
- Email links (`asirive://verify`, `reset`, `companion`) are handled in the app, but the web fallback pages are not built.
- Grants can only be changed for people who accepted; invites that are still waiting can only be cancelled.
- The map is coordinates plus "Open in Maps", not an in-app map.
- Reading the screen with a real screen reader and testing at 200% text on a device is still to do.

## How closely it matches the mockups

Every screen was compared side by side with its mockup (47 screens). Same layout, spacing, type and
colours. Known differences: the map is a placeholder, the hero photo is the
V3 prototype picture, the Accept screen has no inviter name or companion kind (the server has no
invite preview), the invite cannot set starting permissions, and the Notifications switches are saved
on the phone only.

## Run

```
flutter pub get
flutter run --dart-define=GATEWAY_URL=https://your-gateway.example
flutter test
```

`GATEWAY_URL` defaults to a placeholder, so without it every call reports "Can't reach Cortex".
