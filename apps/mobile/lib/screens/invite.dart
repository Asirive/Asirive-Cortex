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
  final torch = ValueNotifier<bool>(false);

  @override
  void dispose() {
    torch.dispose();
    super.dispose();
  }

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
      CxTop(
        title: 'Scan',
        trailing: ValueListenableBuilder<bool>(
          valueListenable: torch,
          builder: (context, on, _) => Semantics(
            button: true,
            toggled: on,
            label: on ? 'Torch, on' : 'Torch, off',
            excludeSemantics: true,
            child: GestureDetector(
              onTap: () => torch.value = !on,
              child: Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(color: on ? Cx.accent : Cx.surface, shape: BoxShape.circle, border: Border.all(color: Cx.outline, width: 1.5)),
                child: Icon(on ? Icons.flashlight_on : Icons.flashlight_off_outlined, size: 20, color: on ? Cx.ground : Cx.text),
              ),
            ),
          ),
        ),
      ),
      const CxTitle('Scan a\nQR code'),
      const CxText('Point the camera at the code on an invite from someone using Cortex. The camera is only used to read the code. Can\'t scan? Enter the code instead, or ask the person who invited you to read it out.'),
      Semantics(
        container: true,
        label: 'Camera view',
        child: ClipRRect(
          borderRadius: BorderRadius.circular(Cx.tileRadius),
          child: Container(
            height: 320,
            color: Cx.surface,
            child: Stack(alignment: Alignment.center, children: [
              Positioned.fill(child: s.services.scanView(context, _code, torch)),
              const IgnorePointer(child: SizedBox(width: 200, height: 200, child: CustomPaint(painter: _Brackets()))),
            ]),
          ),
        ),
      ),
      Semantics(liveRegion: true, child: Text(status, textAlign: TextAlign.center, style: Cx.small)),
    ], bottom: [
      CxButton('Enter the code instead', onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => const EnterCodeScreen()))),
    ]);
  }
}

class _Brackets extends CustomPainter {
  const _Brackets();
  @override
  void paint(Canvas c, Size s) {
    final p = Paint()
      ..color = Cx.accent
      ..style = PaintingStyle.stroke
      ..strokeWidth = 5
      ..strokeCap = StrokeCap.square;
    const l = 46.0, m = 3.0;
    final w = s.width, h = s.height;
    c.drawPath(Path()..moveTo(m, l + m)..lineTo(m, m)..lineTo(l + m, m), p);
    c.drawPath(Path()..moveTo(w - l - m, m)..lineTo(w - m, m)..lineTo(w - m, l + m), p);
    c.drawPath(Path()..moveTo(w - m, h - l - m)..lineTo(w - m, h - m)..lineTo(w - l - m, h - m), p);
    c.drawPath(Path()..moveTo(l + m, h - m)..lineTo(m, h - m)..lineTo(m, h - l - m), p);
    final d = Paint()
      ..color = Cx.accent.withValues(alpha: .8)
      ..strokeWidth = 2;
    for (double x = 24; x < 176; x += 10) {
      c.drawLine(Offset(x, h / 2), Offset(x + 4, h / 2), d);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter old) => false;
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
        const SizedBox(height: 12),
        const CxTitle('Enter your\ncode'),
        const CxText('Type the code from your invite.'),
        CxField(label: 'Invite code', controller: code, code: true, hint: 'XXXX-XXX', error: err, help: 'The code is on the invite, under the QR picture.', onSubmit: _go),
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
      const CxTop(logo: true, title: 'Invitation'),
      const SizedBox(height: 8),
      ExcludeSemantics(child: Container(width: 84, height: 84, decoration: const BoxDecoration(color: Cx.accent, shape: BoxShape.circle), child: const Icon(Icons.favorite, size: 36, color: Cx.ground))),
      const CxTitle('You are\ninvited'),
      const CxText('You can be there for them. They choose what you can see, and can change it or remove you at any time. Until they choose, you see nothing.'),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('WHAT THEY CAN SHARE WITH YOU', style: Cx.label),
        const SizedBox(height: 8),
        Text('You may see where they are and call them. Nothing else, and never their camera. They see only your email.', style: Cx.body.copyWith(color: Cx.text)),
      ])),
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
      const Text('Needs a free Cortex account. No glasses required.', textAlign: TextAlign.center, style: Cx.small),
    ]);
  }
}
