import 'package:flutter/material.dart';

import '../scope.dart';
import '../theme.dart';
import '../widgets.dart';

/// Placeholder Home until the owner screens are built (APP-PLAN section 17, steps 2 to 3).
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return CxScreen(children: [
      const CxTop(back: false, trailing: CxLogo()),
      const CxTitle('You are\nsigned in'),
      CxTile(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('ACCOUNT', style: Cx.label),
        const SizedBox(height: 8),
        Text(s.account?.email ?? '', style: Cx.strong),
      ])),
      const CxText('Home, people and settings arrive in the next builds.'),
      CxButton('Sign out', outline: true, onTap: s.signOut),
    ]);
  }
}
