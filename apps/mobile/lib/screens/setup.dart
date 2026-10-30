import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../services.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';
import 'owner.dart';

const _introSpoken =
    'Set up with a helper. A few steps need eyes: reading the label, plugging in the cable, fitting the glasses. Ask someone you trust to sit with you. It takes about ten minutes. Your helper uses your phone, sitting next to you, in Helper mode. They do not need an account. You stay in charge. This phone reads every step out loud so you can follow. Helper mode locks this phone to the setup steps and ends when setup finishes. You confirm the hand-back with your passcode.';

/// Confirms it is the owner holding the phone. With no passcode on the phone it asks a plain yes/no instead of trapping the owner.
Future<bool> ownerConfirms(BuildContext context, String reason) async {
  final s = SessionScope.of(context);
  final r = await s.services.ownerCheck.confirm(reason);
  if (r == OwnerResult.confirmed) return true;
  if (r == OwnerResult.declined || !context.mounted) return false;
  return confirmSheet(context,
      mono: 'No passcode on this phone',
      title: 'Are you the owner?',
      body: 'This phone has no Face ID, fingerprint or passcode, so it cannot check. Only the owner should say yes. You can set a passcode in the phone settings.',
      cancelLabel: 'No, I am the helper',
      confirmLabel: 'Yes, I am the owner',
      danger: false);
}

class SetupIntroScreen extends StatelessWidget {
  const SetupIntroScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return CxScreen(children: [
      const CxTop(back: false, title: 'Step 3 of 3 · Set up glasses'),
      const CxSpace(10),
      const CxTitle('Set up with\na helper', size: 48, height: .98),
      const CxText('A few steps need eyes: reading the label, plugging in the cable, fitting the glasses. Ask someone you trust to sit with you. It takes about 10 minutes.'),
      Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
        child: Column(children: [
          CxBullet(Text.rich(TextSpan(children: const [TextSpan(text: 'Your helper uses '), TextSpan(text: 'your phone', style: TextStyle(color: Cx.text, fontWeight: FontWeight.w700)), TextSpan(text: ', sitting next to you, in Helper mode. They do not need an account.')]))),
          const SizedBox(height: 12),
          const CxBullet(Text('You stay in charge. This phone reads every step out loud so you can follow.')),
          const SizedBox(height: 12),
          const CxBullet(Text('Helper mode locks this phone to the setup steps and ends when setup finishes. You confirm the hand-back with your passcode.')),
        ]),
      ),
      Semantics(
        button: true,
        label: 'Hear this screen. Cortex reads it aloud',
        excludeSemantics: true,
        child: GestureDetector(
          onTap: () => s.services.speaker.say(_introSpoken),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius), border: Border.all(color: Cx.outline, width: 1.5)),
            child: Row(children: [
              Container(width: 44, height: 44, decoration: const BoxDecoration(color: Cx.accent, shape: BoxShape.circle), child: const Icon(Icons.volume_up, size: 22, color: Cx.ground)),
              const SizedBox(width: 14),
              const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Hear this screen', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text)),
                SizedBox(height: 3),
                Text('Cortex reads it aloud', style: Cx.small),
              ]),
            ]),
          ),
        ),
      ),
    ], bottom: [
      CxButton('Start with my helper', onTap: () => push(context, const HelperFlowScreen())),
      CxButton('Remind me later', outline: true, onTap: () => Navigator.of(context).popUntil((r) => r.isFirst)),
    ]);
  }
}

/// The helper's camera-free way to read the box label: scans the QR on the box and returns its code.
class ScanClaimScreen extends StatefulWidget {
  const ScanClaimScreen({super.key});
  @override
  State<ScanClaimScreen> createState() => _ScanClaimScreenState();
}

class _ScanClaimScreenState extends State<ScanClaimScreen> {
  final torch = ValueNotifier<bool>(false);
  bool done = false;
  @override
  void dispose() {
    torch.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return CxScreen(children: [
      const CxTop(title: 'Scan the box'),
      const CxTitle('Scan the\nbox code'),
      const CxText('Point the camera at the QR code on the label of the pocket box.'),
      ClipRRect(
        borderRadius: BorderRadius.circular(Cx.tileRadius),
        child: SizedBox(
            height: 320,
            child: s.services.scanView(context, (raw) {
              final c = claimCodeFrom(raw);
              if (c != null && !done) {
                done = true;
                Navigator.of(context).pop(c);
              }
            }, torch)),
      ),
    ]);
  }
}

enum _P { helper, pair, confirm, internet, test, done }

class HelperFlowScreen extends StatefulWidget {
  const HelperFlowScreen({super.key});
  @override
  State<HelperFlowScreen> createState() => _HelperFlowScreenState();
}

class _HelperFlowScreenState extends State<HelperFlowScreen> with Ticker<HelperFlowScreen> {
  _P page = _P.helper;
  final code = TextEditingController();
  String? err;
  bool busy = false;
  String? tail;
  final tested = <String, bool>{};
  String? testNote;
  DateTime lastTouch = DateTime.now();
  bool locked = false;
  LinkState link = LinkState.cableOut;
  static const idle = Duration(minutes: 5);

  @override
  void initState() {
    super.initState();
    tickEvery(const Duration(seconds: 10), () {
      if (DateTime.now().difference(lastTouch) > idle && !locked && mounted) setState(() => locked = true);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _link());
  }

  Future<void> _link() async {
    final l = await SessionScope.of(context).services.link.state();
    if (mounted) setState(() => link = l);
  }

  @override
  void dispose() {
    code.dispose();
    super.dispose();
  }

  void _go(_P p) => setState(() {
        page = p;
        err = null;
        _link();
      });

  Future<void> _stop() async {
    final nav = Navigator.of(context);
    if (await ownerConfirms(context, 'Confirm it is you to stop helper mode')) nav.pop();
  }

  Future<void> _unlock() async {
    if (await ownerConfirms(context, 'Confirm it is you to carry on') && mounted) {
      setState(() {
        locked = false;
        lastTouch = DateTime.now();
      });
    }
  }

  /// Checks the typed code against the box itself before anything is spent.
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
    try {
      final st = await s.services.link.state();
      if (st == LinkState.cableOut) {
        setState(() {
          busy = false;
          link = st;
          err = 'The pocket box is not plugged in to this phone. Connect the cable, then try again.';
        });
        return;
      }
      final typedTail = c.substring(c.length - 4);
      final fromBox = await s.services.link.boxCodeTail();
      if (fromBox != null && fromBox.toUpperCase() != typedTail) {
        setState(() {
          busy = false;
          err = 'That code does not match the box on the cable. Check the label and try again.';
        });
        return;
      }
      setState(() {
        busy = false;
        link = st;
        tail = fromBox ?? typedTail;
        page = _P.confirm;
      });
    } on Exception {
      if (mounted) setState(() {
        busy = false;
        err = 'Could not talk to the pocket box. Unplug, plug in again and try again.';
      });
    }
  }

  Future<void> _claim() async {
    final s = SessionScope.of(context);
    final c = claimCodeFrom(code.text);
    if (c == null || s.token == null) return;
    setState(() {
      busy = true;
      err = null;
    });
    try {
      final r = await s.api.claim(s.token!, c, boxKey: await s.services.link.boxPublicKey());
      final done = await s.services.link.handOverDeviceToken(r['device_id'] as String, r['device_token'] as String);
      if (!done) {
        setState(() {
          busy = false;
          err = 'The code was accepted but the box did not take it. Unplug, plug in again and ask Asirive support for a new code.';
        });
        return;
      }
      await s.refresh();
      if (mounted) setState(() {
        busy = false;
        page = _P.internet;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() {
        busy = false;
        err = e.code == 'invalid_or_expired' || e.status == 422 ? 'That code is wrong, already used or expired.' : e.message;
      });
    } on Exception {
      if (mounted) setState(() {
        busy = false;
        err = 'Something went wrong. Try again.';
      });
    }
  }

  Future<void> _play(String kind) async {
    final s = SessionScope.of(context);
    final ok = await s.services.link.playTest(kind);
    if (!mounted) return;
    setState(() {
      tested[kind] = ok;
      testNote = ok ? null : 'Could not reach the pocket box. Plug it in with the cable and try again.';
    });
  }

  Future<void> _ready() async {
    final s = SessionScope.of(context);
    final nav = Navigator.of(context);
    if (!await ownerConfirms(context, 'Confirm you have your phone back')) {
      if (mounted) setState(() => err = 'Not confirmed. The owner needs to confirm with face, fingerprint or passcode.');
      return;
    }
    await s.refresh();
    nav.popUntil((r) => r.isFirst);
  }

  Widget _stopLink() => Semantics(
        button: true,
        label: 'Stop helper mode',
        excludeSemantics: true,
        child: GestureDetector(
          onTap: _stop,
          child: const SizedBox(height: 44, child: Padding(padding: EdgeInsets.symmetric(horizontal: 6), child: Center(child: Text('Stop helper mode', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, fontWeight: FontWeight.w600, color: Cx.danger))))),
        ),
      );

  Widget _top(String pill, {VoidCallback? back, bool stop = true, bool mono = false}) => CxTop(
        back: back != null,
        onBack: back,
        lead: mono ? Padding(padding: const EdgeInsets.only(left: 12, right: 8), child: Text(pill.toUpperCase(), style: Cx.label)) : Padding(padding: EdgeInsets.only(left: back == null ? 0 : 12), child: CxPill(pill, icon: pill == 'Helper mode' ? Icons.person_outline : null)),
        trailing: stop ? _stopLink() : null,
      );

  @override
  Widget build(BuildContext context) {
    if (locked) {
      return PopScope(
        canPop: false,
        child: CxScreen(children: [
          const CxTop(back: false, title: 'Helper mode'),
          const CxTitle('Paused'),
          const CxText('Helper mode paused because nothing happened for a while. The owner confirms to carry on.'),
        ], bottom: [
          CxButton('Owner: carry on', onTap: _unlock),
          CxButton('Stop helper mode', outline: true, danger: true, onTap: _stop),
        ]),
      );
    }
    final cable = link != LinkState.cableOut;
    final Widget body = switch (page) {
      _P.helper => CxScreen(children: [
          _top('Helper mode', back: () => Navigator.of(context).maybePop()),
          const CxTitle('Hi, helper'),
          const CxText("Use the owner's phone and sit next to them. Read each step aloud and let the owner decide. About 10 minutes."),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
            child: const Column(children: [
              CxStep(1, 'Fit the glasses', 'Sit level, camera clear, cable tucked behind the ear', state: 'now'),
              SizedBox(height: 8),
              CxStep(2, 'Plug in and pair', 'Read the 8-character code from the label on the pocket box'),
              SizedBox(height: 8),
              CxStep(3, 'Share internet', 'Turn on tethering on this phone'),
              SizedBox(height: 8),
              CxStep(4, 'Test sound and touch', 'The owner confirms they heard and felt it'),
              SizedBox(height: 8),
              CxStep(5, 'Hand the phone back', 'The owner takes over'),
            ]),
          ),
          CxDashed(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            child: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text("OWNER'S PRIVACY", style: Cx.label),
              SizedBox(height: 6),
              Text('As helper you only see setup steps. You cannot see their location, people or settings.', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, height: 1.45, color: Cx.muted)),
            ]),
          ),
        ], bottom: [
          CxButton('Start step 1', onTap: () => _go(_P.pair)),
        ]),
      _P.pair => CxScreen(children: [
          _top('Helper · step 2 of 5', back: () => _go(_P.helper)),
          const CxTitle('Connect\nyour glasses', size: 52, height: .98),
          const CxText("This links the pocket box on the cable to the owner's account. It is done once."),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
            child: Column(children: [
              CxStep(1, 'Plug in the pocket box', 'USB-C cable between the box and this phone', state: cable ? 'done' : 'now'),
              const SizedBox(height: 8),
              CxStep(2, 'Pocket box found', cable ? 'It is waiting for a pairing code' : 'Shows up once the cable is in', state: cable ? 'done' : 'todo'),
              const SizedBox(height: 8),
              CxStep(3, 'Enter the code', '8 characters, on the label of the pocket box', state: cable ? 'now' : 'todo'),
            ]),
          ),
          CxField(label: 'Pairing code', controller: code, code: true, hint: 'XXXX-XXXX', error: err, onSubmit: _pair),
          SizedBox(
            height: 48,
            child: CxButton('Helper: scan the box code instead', outline: true, small: true, icon: Icons.qr_code_scanner, onTap: () async {
              final got = await Navigator.of(context).push<String>(MaterialPageRoute(builder: (_) => const ScanClaimScreen()));
              if (got != null && mounted) setState(() => code.text = got);
            }),
          ),
        ], bottom: [
          CxButton('Pair glasses', onTap: _pair, busy: busy),
          const Text('Helper: read the code to the owner from the box label.', textAlign: TextAlign.center, style: Cx.small),
        ]),
      _P.confirm => CxScreen(children: [
          _top('Helper · step 2 of 5'),
          const Text('FOR THE OWNER', style: Cx.label),
          const CxTitle('Is this\nyour box?', size: 48, height: .98),
          Semantics(
              liveRegion: true,
              child: Text('Your phone says: "The pocket box on the cable ends in ${tail!.split('').join(' ')}. Is that the code you heard?"', style: Cx.body.copyWith(fontSize: 17, color: Cx.text))),
          Container(
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
            child: Column(children: [
              const Text('BOX CODE ENDS', style: Cx.label),
              const SizedBox(height: 6),
              Text(tail!, semanticsLabel: tail!.split('').join(' '), style: const TextStyle(fontFamily: 'Anton', fontSize: 72, height: 1, letterSpacing: 8.6, color: Cx.accent)),
            ]),
          ),
          Semantics(
            button: true,
            label: 'Hear it again',
            excludeSemantics: true,
            child: GestureDetector(
              onTap: () => SessionScope.of(context).services.speaker.say('The pocket box ends in ${tail!.split('').join(' ')}.'),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius), border: Border.all(color: Cx.outline, width: 1.5)),
                child: Row(children: [
                  Container(width: 44, height: 44, decoration: const BoxDecoration(color: Cx.accent, shape: BoxShape.circle), child: const Icon(Icons.volume_up, size: 22, color: Cx.ground)),
                  const SizedBox(width: 14),
                  const Text('Hear it again', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text)),
                ]),
              ),
            ),
          ),
          if (err != null) CxNotice(err!, error: true),
        ], bottom: [
          SizedBox(height: 64, child: CxButton('Yes, that is my box', onTap: _claim, busy: busy)),
          CxButton('No, enter the code again', outline: true, danger: true, onTap: () => _go(_P.pair)),
        ]),
      _P.internet => CxScreen(children: [
          _top('Helper · step 3 of 5', back: () => _go(_P.confirm), mono: true),
          const CxTitle('Share your\ninternet'),
          const CxText("The glasses use this phone's internet through the USB cable."),
          InternetBody(onContinue: () => _go(_P.test)),
        ]),
      _P.test => CxScreen(children: [
          _top('Helper · step 4 of 5', back: () => _go(_P.internet)),
          const CxTitle('Test sound\nand touch'),
          const CxText('Ask the owner to wear the glasses and listen. Play each test, then ask what they heard and felt.'),
          for (final t in const [
            ('sound', 'Play a sound', 'A short tone in the glasses', Icons.volume_up),
            ('vibrate', 'Make the glasses vibrate', 'The owner should feel a pulse', Icons.vibration),
            ('voice', 'Say a word', 'Owner says "Cortex". The glasses answer.', Icons.mic_none),
          ])
            Semantics(
              button: true,
              label: '${t.$2}. ${t.$3}${tested[t.$1] == true ? '. Played' : ''}',
              excludeSemantics: true,
              child: GestureDetector(
                onTap: () => _play(t.$1),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                  decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
                  child: Row(children: [
                    Container(width: 48, height: 48, decoration: const BoxDecoration(color: Cx.accent, shape: BoxShape.circle), child: Icon(tested[t.$1] == true ? Icons.check : t.$4, size: 24, color: Cx.ground)),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(t.$2, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 17, fontWeight: FontWeight.w600, color: Cx.text)),
                        const SizedBox(height: 2),
                        Text(t.$3, style: Cx.small),
                      ]),
                    ),
                  ]),
                ),
              ),
            ),
          if (testNote != null) CxNotice(testNote!, error: true),
        ], bottom: [
          const Text('Did the owner hear and feel all three?', textAlign: TextAlign.center, style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, fontWeight: FontWeight.w600, color: Cx.text)),
          CxButton('Yes, all good', onTap: tested.length == 3 && tested.values.every((v) => v) ? () => _go(_P.done) : null),
          CxButton('No, try again', outline: true, onTap: () => setState(() {
                tested.clear();
                testNote = null;
              })),
        ]),
      _P.done => CxScreen(children: [
          _top('Helper · step 5 of 5', stop: false),
          const SizedBox(height: 6),
          ExcludeSemantics(child: Container(width: 84, height: 84, color: Cx.accent, child: const Icon(Icons.check, size: 44, color: Cx.ground))),
          const CxTitle('Hand the\nphone back', size: 52, height: .98),
          const CxText('Setup is done. Thank you, helper. The owner takes over now and confirms with their passcode.'),
          CxTile(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('CORTEX SAYS OUT LOUD', style: Cx.label),
            const SizedBox(height: 8),
            Text('"Setup is done. Your glasses are ready. Your helper can step away. Press the big button when you are ready."', style: Cx.body.copyWith(fontSize: 16, color: Cx.text)),
          ])),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
            child: const Column(children: [
              CxStep(1, 'Helper mode closed', 'Setup steps can no longer be opened', state: 'done'),
              SizedBox(height: 8),
              CxStep(2, 'Glasses paired and online', 'Sound and touch confirmed', state: 'done'),
            ]),
          ),
          if (err != null) CxNotice(err!, error: true),
        ], bottom: [
          SizedBox(height: 68, child: CxButton("Owner: I'm ready", onTap: _ready)),
          const Text('Face ID or passcode ends Helper mode.', textAlign: TextAlign.center, style: Cx.small),
        ]),
    };
    if (page == _P.done) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && page == _P.done && !_spoken) {
          _spoken = true;
          SessionScope.of(context).services.speaker.say('Setup is done. Your glasses are ready. Your helper can step away. Press the big button when you are ready.');
        }
      });
    }
    return PopScope(canPop: false, child: Listener(onPointerDown: (_) => lastTouch = DateTime.now(), child: body));
  }

  bool _spoken = false;
}
