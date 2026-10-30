import 'package:flutter/material.dart';

import 'api.dart';
import 'scope.dart';
import 'screens/auth.dart';
import 'screens/home.dart';
import 'screens/intro.dart';
import 'screens/welcome.dart';
import 'session.dart';
import 'theme.dart';
import 'widgets.dart';

void main() {
  final session = Session(Api(), const SecureStore())..start();
  runApp(CortexApp(session: session));
}

class CortexApp extends StatelessWidget {
  const CortexApp({super.key, required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) => SessionScope(
        session: session,
        child: MaterialApp(
          title: 'Asirive Cortex',
          debugShowCheckedModeBanner: false,
          theme: Cx.theme(),
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
        return const HomeScreen();
      case Phase.signedOut:
        if (s.expired) return const SignedOutScreen();
        return s.introSeen ? const WelcomeScreen() : const IntroScreen();
    }
  }
}
