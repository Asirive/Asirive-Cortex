// ignore_for_file: sort_child_properties_last
import 'package:flutter/material.dart';

import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';
import 'auth.dart';
import 'invite.dart';

class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return CxScreen(children: [
      const CxTop(back: false, trailing: CxLogo()),
      const SizedBox(height: 4),
      SizedBox(
        height: 200,
        child: Semantics(label: 'Cortex glasses and pocket box', image: true, child: Center(child: Image.asset('assets/images/hero.png', width: 318, height: 200, fit: BoxFit.contain, excludeFromSemantics: true))),
      ),
      const SizedBox(height: 4),
      Text('ASIRIVE CORTEX', style: Cx.label),
      const CxTitle("Let's get\nyou started"),
      const CxText('Set up your own Cortex, or join someone who invited you.'),
    ], bottom: [
      Text('I USE CORTEX', style: Cx.label),
      CxButton('Create an account', onTap: () => push(context, const CreateAccountScreen())),
      CxButton('Sign in', outline: true, onTap: () => push(context, const SignInScreen())),
      const SizedBox(height: 0),
      Padding(padding: EdgeInsets.only(top: 6), child: Text('SOMEONE INVITED ME', style: Cx.label)),
      CxButton('Scan or enter invite code', outline: true, icon: Icons.qr_code_scanner, onTap: () => push(context, const ScanScreen())),
    ]);
  }
}
