import 'package:flutter/material.dart';

import '../scope.dart';
import '../services.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';
import 'auth.dart';

/// Scan an invite QR code. Typing the code is always one tap away.
class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});
  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  String status = 'Looking for a code. Hold the invite steady in front of the camera.';
  bool handled = false;

  void _code(String raw) {
    if (handled) return;
    final c = inviteCodeFrom(raw);
    if (c == null) {
      setState(() => status = 'That is not a Cortex invite. Try again, or enter the code.');
      return;
    }
    handled = true;
    SessionScope.of(context).services.speaker.say('Code found.');
    setState(() => status = 'Code found.');
    Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => AcceptScreen(code: c)));
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return CxScreen(children: [
      const CxTop(title: 'Scan'),
      const CxTitle('Scan a\nQR code'),
      const CxText('Point the camera at the code on an invite from someone using Cortex. The camera is only used to read the code. Cannot scan? Enter the code instead, or ask the person who invited you to read it out.'),
      Semantics(
        container: true,
        label: 'Camera view',
        child: ClipRRect(borderRadius: BorderRadius.circular(Cx.tileRadius), child: SizedBox(height: 300, child: s.services.scanView(context, _code))),
      ),
      Semantics(liveRegion: true, child: Text(status, textAlign: TextAlign.center, style: Cx.small)),
    ], bottom: [
      CxButton('Enter the code instead', onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => const EnterCodeScreen()))),
    ]);
  }
}

class EnterCodeScreen extends StatefulWidget {
  const EnterCodeScreen({super.key});
  @override
  State<EnterCodeScreen> createState() => _EnterCodeScreenState();
}

class _EnterCodeScreenState extends State<EnterCodeScreen> {
  final code = TextEditingController();
  String? err;

  void _go() {
    final c = inviteCodeFrom(code.text);
    if (c == null) {
      setState(() => err = 'That code did not work. Check it for a typo, or ask for a new invite.');
      return;
    }
    push(context, AcceptScreen(code: c));
  }

  @override
  void dispose() {
    code.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(title: 'Invite code'),
        const CxTitle('Enter your\ncode'),
        const CxText('Type the code from your invite.'),
        CxField(label: 'Invite code', controller: code, hint: 'XXXX-XXX', error: err, help: 'The code is on the invite, under the QR picture.', onSubmit: _go),
      ], bottom: [
        CxButton('Continue', onTap: _go),
        CxButton('Scan instead', outline: true, onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => const ScanScreen()))),
      ]);
}

/// Shows the invitation. Signed in: accept right here. Signed out: make an account or sign in first.
class AcceptScreen extends StatefulWidget {
  const AcceptScreen({super.key, required this.code});
  final String code;
  @override
  State<AcceptScreen> createState() => _AcceptScreenState();
}

class _AcceptScreenState extends State<AcceptScreen> {
  bool busy = false;
  String? err;

  Future<void> _accept() async {
    final s = SessionScope.of(context);
    final nav = Navigator.of(context);
    setState(() {
      busy = true;
      err = null;
    });
    s.pendingInvite = widget.code;
    await s.applyPendingInvite();
    await s.refresh();
    if (!mounted) return;
    if (s.inviteNote != null && !s.inviteNote!.startsWith('You are now')) {
      setState(() {
        err = s.inviteNote;
        s.inviteNote = null;
        busy = false;
      });
      return;
    }
    setState(() => busy = false);
    nav.popUntil((r) => r.isFirst);
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final signedIn = s.token != null;
    return CxScreen(children: [
      const CxTop(title: 'Invitation'),
      const CxTitle('You are\ninvited'),
      const CxText('Someone you know wants you to look after them. They choose what you can see, and can change it or remove you at any time. Until they choose, you see nothing.'),
      const CxTile(child: CxText('You may be allowed to see where they are and to call them. Never their camera. They see only your email.')),
      if (err != null) CxNotice(err!, error: true),
    ], bottom: [
      if (signedIn)
        CxButton('Accept', onTap: _accept, busy: busy)
      else ...[
        CxButton('Accept and create account', onTap: () {
          s.pendingInvite = widget.code;
          push(context, const CreateAccountScreen());
        }),
        CxButton('I already have an account', outline: true, onTap: () {
          s.pendingInvite = widget.code;
          push(context, const SignInScreen());
        }),
      ],
      CxButton('Not now', outline: true, onTap: () {
        s.pendingInvite = null;
        Navigator.of(context).popUntil((r) => r.isFirst);
      }),
      const CxText('Needs a free Cortex account. No glasses required.', small: true),
    ]);
  }
}
