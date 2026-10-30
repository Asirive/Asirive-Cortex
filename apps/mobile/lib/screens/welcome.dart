// ignore_for_file: sort_child_properties_last
import 'package:flutter/material.dart';

import '../theme.dart';
import '../widgets.dart';
import 'auth.dart';
import 'soon.dart';

class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    void go(Widget w) => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => w));
    return CxScreen(children: [
      const CxTop(back: false, trailing: CxLogo()),
      const SizedBox(height: 8),
      const Text('ASIRIVE CORTEX', style: Cx.label),
      const CxTitle("Let's get\nyou started"),
      const CxText('Set up your own Cortex, or join someone who invited you.'),
    ], bottom: [
      const Text('I USE CORTEX', style: Cx.label),
      CxButton('Create an account', onTap: () => go(const CreateAccountScreen())),
      CxButton('Sign in', outline: true, onTap: () => go(const SignInScreen())),
      const SizedBox(height: 6),
      const Text('SOMEONE INVITED ME', style: Cx.label),
      CxButton('Scan or enter invite code',
          outline: true,
          onTap: () => go(const SoonScreen(
              title: 'Join with an invite',
              body: 'Scanning and typing an invite code arrive in the next build.'))),
    ]);
  }
}
