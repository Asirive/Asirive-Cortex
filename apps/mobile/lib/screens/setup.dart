import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../services.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';
import 'owner.dart';

/// Glasses setup is done with a sighted helper sitting next to the owner (APP-PLAN 14.1).
class SetupIntroScreen extends StatelessWidget {
  const SetupIntroScreen({super.key});
  static const spoken =
      'Setting up your glasses. A sighted helper sits next to you and uses this phone. They follow five short steps: fit the glasses, plug in the pocket box, share internet, test the sound and touch, then hand the phone back to you. You confirm each important step yourself.';

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return CxScreen(children: [
      const CxTop(title: 'Set up'),
      const CxTitle('Set up with\na helper'),
      const CxText('Ask someone who can see to sit next to you. They use this phone and read each step out. It takes about ten minutes.'),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final t in const ['Fit the glasses', 'Plug in and pair the pocket box', 'Share internet', 'Test sound and touch', 'Hand the phone back'])
          Padding(padding: const EdgeInsets.symmetric(vertical: 5), child: Text(t, style: Cx.strong.copyWith(fontSize: 16, fontWeight: FontWeight.w600))),
      ])),
      const CxText('The helper does not need an account. Their screen is locked to these steps, and you confirm at the end with your face, fingerprint or passcode.', small: true),
    ], bottom: [
      CxButton('Start with a helper', onTap: () => push(context, const HelperFlowScreen())),
      CxButton('Hear this screen', outline: true, onTap: () => s.services.speaker.say(spoken)),
    ]);
  }
}

class HelperFlowScreen extends StatefulWidget {
  const HelperFlowScreen({super.key});
  @override
  State<HelperFlowScreen> createState() => _HelperFlowScreenState();
}

class _HelperFlowScreenState extends State<HelperFlowScreen> with Ticker<HelperFlowScreen> {
  int step = 0;
  final code = TextEditingController();
  String? err;
  bool busy = false;
  bool paired = false;
  String? tail; // last four characters of the code the helper entered
  bool tailOk = false;
  bool heard = false, felt = false;
  DateTime lastTouch = DateTime.now();
  bool locked = false;

  static const idle = Duration(minutes: 5);

  @override
  void initState() {
    super.initState();
    tickEvery(const Duration(seconds: 10), () {
      if (DateTime.now().difference(lastTouch) > idle && !locked && mounted) setState(() => locked = true);
    });
  }

  @override
  void dispose() {
    code.dispose();
    super.dispose();
  }

  void _touch() {
    lastTouch = DateTime.now();
  }

  Future<void> _stop() async {
    final s = SessionScope.of(context);
    final nav = Navigator.of(context);
    final ok = await s.services.ownerCheck.confirm('Confirm it is you to stop helper mode');
    if (ok) nav.pop();
  }

  Future<void> _unlock() async {
    final s = SessionScope.of(context);
    final ok = await s.services.ownerCheck.confirm('Confirm it is you to carry on');
    if (ok && mounted) setState(() {
      locked = false;
      lastTouch = DateTime.now();
    });
  }

  Future<void> _pair() async {
    final s = SessionScope.of(context);
    final c = claimCodeFrom(code.text);
    if (c == null) {
      setState(() => err = 'That code does not look right. It is eight letters and numbers, like K7QM-4TXD.');
      return;
    }
    setState(() {
      busy = true;
      err = null;
    });
    final st = await s.services.link.state();
    if (st == LinkState.cableOut) {
      setState(() {
        busy = false;
        err = 'The pocket box is not plugged in to this phone. Connect the cable, then try again.';
      });
      return;
    }
    try {
      final r = await s.api.claim(s.token!, c);
      final done = await s.services.link.handOverDeviceToken(r['device_id'] as String, r['device_token'] as String);
      if (!done) {
        setState(() {
          busy = false;
          err = 'The code was accepted but the box did not take it. Unplug, plug in again and ask Asirive support for a new code.';
        });
        return;
      }
      await s.refresh();
      setState(() {
        paired = true;
        tail = c.substring(c.length - 4);
        busy = false;
      });
    } on ApiException catch (e) {
      setState(() {
        busy = false;
        err = e.code == 'error' && e.status == 422 ? 'That code is wrong, already used or expired.' : e.message;
      });
    }
  }

  Future<void> _handBack() async {
    final s = SessionScope.of(context);
    final nav = Navigator.of(context);
    final ok = await s.services.ownerCheck.confirm('Confirm you have your phone back');
    if (!ok) {
      setState(() => err = 'Not confirmed. The owner needs to confirm with face, fingerprint or passcode.');
      return;
    }
    await s.refresh();
    nav.popUntil((r) => r.isFirst);
  }

  bool get _canNext => switch (step) {
        1 => paired && tailOk,
        3 => heard && felt,
        _ => true,
      };

  Widget _body(BuildContext context) {
    switch (step) {
      case 0:
        return const CxTile(child: CxText('Helper: put the glasses on the owner. The arms rest on the ears with the speakers just in front of them. The pocket box goes in a pocket. Ask the owner if it feels comfortable.', color: Cx.text));
      case 1:
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const CxText('Helper: plug the pocket box into this phone with the cable. Type the code printed on the box.'),
          const SizedBox(height: 14),
          if (!paired) CxField(label: 'Box code', controller: code, hint: 'XXXX-XXXX', error: err, onSubmit: _pair) else ...[
            CxTile(
                child: Text('The box code ends in ${tail!.split('').join(' ')}.', style: Cx.strong)),
            const SizedBox(height: 14),
            CxText('Owner: did you hear the helper read out a code ending in ${tail!.split('').join(' ')}?', color: Cx.text),
            CxSwitch(label: 'Yes, that is what I heard', value: tailOk, onChanged: (v) => setState(() => tailOk = v)),
          ],
        ]);
      case 2:
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const CxText('Helper: the box needs your phone\'s internet over the cable.'),
          const SizedBox(height: 14),
          CxButton('Open the steps and test', outline: true, onTap: () => push(context, const InternetScreen(helper: true))),
        ]);
      case 3:
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const CxText('Helper: ask the owner to say "Hey Cortex". Then tap the arm of the glasses once.'),
          const SizedBox(height: 14),
          CxText('Owner: only you confirm these.', color: Cx.text),
          CxSwitch(label: 'I heard Cortex answer', value: heard, onChanged: (v) => setState(() => heard = v)),
          CxSwitch(label: 'I felt the touch', value: felt, onChanged: (v) => setState(() => felt = v)),
        ]);
      default:
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const CxText('Helper: give the phone back to the owner. Helper mode ends when the owner confirms.'),
          if (err != null) ...[const SizedBox(height: 14), CxNotice(err!, error: true)],
        ]);
    }
  }

  @override
  Widget build(BuildContext context) {
    const titles = ['Fit the\nglasses', 'Plug in\nand pair', 'Share\ninternet', 'Test sound\nand touch', 'Hand\nback'];
    if (locked) {
      return PopScope(
        canPop: false,
        child: CxScreen(children: [
          const CxTop(back: false, title: 'Helper mode'),
          const CxTitle('Paused'),
          const CxText('Helper mode paused because nothing happened for a while. The owner confirms to carry on.'),
        ], bottom: [
          CxButton('Owner: carry on', onTap: _unlock),
          CxButton('Stop helper mode', outline: true, onTap: _stop),
        ]),
      );
    }
    return PopScope(
      canPop: false,
      child: Listener(
        onPointerDown: (_) => _touch(),
        child: CxScreen(children: [
          CxTop(back: false, title: 'Helper mode'),
          Semantics(liveRegion: true, child: Text('STEP ${step + 1} OF 5', style: Cx.label)),
          CxTitle(titles[step]),
          _body(context),
        ], bottom: [
          if (step == 1 && !paired) CxButton('Pair the box', onTap: _pair, busy: busy),
          if (step < 4) CxButton('Next', onTap: _canNext && !(step == 1 && !paired) ? () => setState(() => step++) : null) else CxButton('I have the phone back', onTap: _handBack),
          if (step > 0 && step < 4) CxButton('Back', outline: true, onTap: () => setState(() => step--)),
          CxButton('Stop helper mode', outline: true, danger: true, onTap: _stop),
        ]),
      ),
    );
  }
}
