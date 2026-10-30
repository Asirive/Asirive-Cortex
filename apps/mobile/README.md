# Cortex app (Flutter)

The phone app for Asirive Cortex. Design rules and screens: `docs/architecture/APP-PLAN.md`;
clickable mockups: `docs/design/mockups/`.

## Built so far (plan section 17, step 1)

- Theme, bundled fonts (Anton, Space Grotesk, JetBrains Mono) and shared parts in `lib/theme.dart`, `lib/widgets.dart`
- Gateway client for the account calls (`lib/api.dart`), token in secure storage (`lib/session.dart`)
- First open: four intro screens, Welcome (shown once per install)
- Account: create, check email, sign in, forgot password, signed-out screen
- A placeholder Home with Sign out

Not built yet: invite scan/enter code, Accept, owner Home, people, calls, glasses setup. The Welcome
invite button opens a "coming soon" page. Email links (confirm, reset) are not opened in the app yet,
so a new account is confirmed from the email link in a browser, then signed in here.

## Run

```
flutter pub get
flutter run --dart-define=GATEWAY_URL=https://your-gateway.example
flutter test
```

`GATEWAY_URL` defaults to a placeholder, so without it every call reports "Can't reach Cortex".
