import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'scope.dart';
import 'screens/auth.dart';
import 'screens/invite.dart';
import 'services.dart';
import 'shell.dart';
import 'screens/intro.dart';
import 'screens/welcome.dart';
import 'session.dart';
import 'theme.dart';
import 'widgets.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final session = Session(Api(), const SecureStore())..start();
  runApp(CortexApp(session: session));
}

class CortexApp extends StatefulWidget {
  const CortexApp({super.key, required this.session});
  final Session session;
  @override
  State<CortexApp> createState() => _CortexAppState();
}

class _CortexAppState extends State<CortexApp> {
  final navKey = GlobalKey<NavigatorState>();
  StreamSubscription<Uri>? _sub;
  Session get session => widget.session;

  @override
  void initState() {
    super.initState();
    session.services.links.initial().then((u) {
      if (u != null) _open(u);
    });
    _sub = session.services.links.stream.listen(_open);
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  /// asirive://verify?token=, asirive://reset?token=, asirive://companion?code=
  Future<void> _open(Uri u) async {
    final nav = navKey.currentState;
    if (nav == null) return;
    final token = u.queryParameters['token'] ?? '';
    switch (u.host) {
      case 'verify':
        try {
          await session.api.verify(token);
          nav.push(MaterialPageRoute<void>(builder: (_) => const EmailConfirmedScreen()));
        } on ApiException catch (e) {
          nav.push(MaterialPageRoute<void>(builder: (_) => EmailConfirmedScreen(ok: false, message: e.message)));
        }
      case 'reset':
        nav.push(MaterialPageRoute<void>(builder: (_) => NewPasswordScreen(token: token)));
      case 'companion':
        final c = inviteCodeFrom(u.queryParameters['code'] ?? '');
        if (c != null) nav.push(MaterialPageRoute<void>(builder: (_) => AcceptScreen(code: c)));
    }
  }

  @override
  Widget build(BuildContext context) => SessionScope(
        session: session,
        child: MaterialApp(
          navigatorKey: navKey,
          title: 'Asirive Cortex',
          debugShowCheckedModeBanner: false,
          theme: Cx.theme(),
          builder: (context, child) => ListenableBuilder(
            listenable: session.prefs,
            builder: (context, _) => MediaQuery(
              data: MediaQuery.of(context).copyWith(
                  textScaler: TextScaler.linear(session.prefs.textScale),
                  boldText: session.prefs.highContrast),
              child: child!,
            ),
          ),
          home: const _Gate(),
        ),
      );
}

/// Chooses the root screen from the session. Pushed screens sit above it, so
/// sign-in pops back to this gate and it swaps to Home.
class _Gate extends StatelessWidget {
  const _Gate();
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    switch (s.phase) {
      case Phase.loading:
        return const Scaffold(body: Center(child: CxLogo(size: 64)));
      case Phase.signedIn:
        return const Shell();
      case Phase.signedOut:
        if (s.expired) return const SignedOutScreen();
        return s.introSeen ? const WelcomeScreen() : const IntroScreen();
    }
  }
}
