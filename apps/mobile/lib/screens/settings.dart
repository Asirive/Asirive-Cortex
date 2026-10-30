import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../session.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';

const appVersion = '0.1.0';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final owner = s.side == Side.owner;
    return CxScreen(tab: true, children: [
      const CxTop(back: false, trailing: CxLogo()),
      const CxTitle('Settings'),
      CxTile(
          child: Column(children: [
        CxRow('Voice, sound and text', detail: 'Speed, vibration, size', onTap: () => push(context, const AssistScreen())),
        if (owner) ...[
          const Divider(color: Cx.line, height: 1),
          CxRow('Join the beta', detail: s.account?.beta == true ? 'On' : 'Off', onTap: () => push(context, const BetaScreen())),
          const Divider(color: Cx.line, height: 1),
          CxRow('Send feedback', onTap: () => push(context, const FeedbackScreen())),
        ],
        const Divider(color: Cx.line, height: 1),
        CxRow('Privacy and data', onTap: () => push(context, PrivacyScreen(owner: owner))),
        if (s.hasBoth) ...[
          const Divider(color: Cx.line, height: 1),
          CxRow('Switch side', detail: owner ? 'Now: owner' : 'Now: companion', onTap: () => push(context, const SwitchSideScreen())),
        ],
        const Divider(color: Cx.line, height: 1),
        CxRow('Account', detail: s.account?.email, onTap: () => push(context, const AccountScreen())),
      ])),
      CxText('Asirive Cortex $appVersion', small: true),
    ]);
  }
}

class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return CxScreen(children: [
      const CxTop(title: 'Account'),
      const CxTitle('Your\naccount'),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('EMAIL', style: Cx.label),
        const SizedBox(height: 6),
        Text(s.account?.email ?? '', style: Cx.strong),
      ])),
    ], bottom: [
      CxButton('Sign out', outline: true, onTap: () async {
        Navigator.of(context).popUntil((r) => r.isFirst);
        await s.signOut();
      }),
    ]);
  }
}

class SwitchSideScreen extends StatelessWidget {
  const SwitchSideScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    Future<void> pick(Side side) async {
      await s.switchSide(side);
      if (context.mounted) Navigator.of(context).popUntil((r) => r.isFirst);
    }

    return CxScreen(children: [
      const CxTop(title: 'Switch side'),
      const CxTitle('Which side?'),
      const CxText('You use Cortex yourself and you also look after someone. Pick what you want to see now.'),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('My Cortex', style: Cx.strong.copyWith(fontSize: 20)),
        const SizedBox(height: 4),
        const CxText('Home, my people, my location.', small: true),
        const SizedBox(height: 12),
        CxButton(s.side == Side.owner ? 'Staying on my Cortex' : 'Go to my Cortex', outline: s.side == Side.owner, onTap: () => pick(Side.owner)),
      ])),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('People I look after', style: Cx.strong.copyWith(fontSize: 20)),
        const SizedBox(height: 4),
        const CxText('Where they are, and calls.', small: true),
        const SizedBox(height: 12),
        CxButton(s.side == Side.companion ? 'Staying with people I look after' : 'Go to people I look after', outline: s.side == Side.companion, onTap: () => pick(Side.companion)),
      ])),
    ]);
  }
}

class AssistScreen extends StatelessWidget {
  const AssistScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final p = s.prefs;
    return ListenableBuilder(
      listenable: p,
      builder: (context, _) => CxScreen(children: [
        const CxTop(title: 'Voice, sound, text'),
        const CxTitle('Voice, sound\nand text'),
        CxTile(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('SPEAKING SPEED', style: Cx.label),
          Semantics(
            label: 'Speaking speed',
            value: p.speechRate < 0.4 ? 'slow' : p.speechRate > 0.6 ? 'fast' : 'normal',
            child: Slider(
              value: p.speechRate,
              min: 0.3,
              max: 0.7,
              divisions: 4,
              activeColor: Cx.accent,
              inactiveColor: Cx.line,
              onChanged: (v) {
                p.update(speechRate: v);
                s.services.speaker.setRate(v);
              },
            ),
          ),
          CxButton('Hear a sample', outline: true, onTap: () => s.services.speaker.say('This is how fast Cortex will speak.')),
        ])),
        CxTile(
            child: Column(children: [
          CxChoice<int>(label: 'Vibration strength', options: const {0: 'Off', 1: 'Gentle', 2: 'Strong'}, value: p.haptic, onChanged: (v) => p.update(haptic: v)),
          const SizedBox(height: 8),
          CxSwitch(label: 'Spoken alerts', detail: 'Read out confirmations and warnings in the app', value: p.spokenAlerts, onChanged: (v) => p.update(spokenAlerts: v)),
        ])),
        CxTile(
            child: Column(children: [
          CxChoice<double>(label: 'Text size', options: {1.0: 'Normal', 1.3: 'Large', 1.6: 'Larger', 2.0: 'Largest'}, value: p.textScale, onChanged: (v) => p.update(textScale: v)),
          const SizedBox(height: 8),
          CxSwitch(label: 'Bold text', detail: 'Heavier letters for easier reading', value: p.highContrast, onChanged: (v) => p.update(highContrast: v)),
        ])),
      ]),
    );
  }
}

class BetaScreen extends StatefulWidget {
  const BetaScreen({super.key});
  @override
  State<BetaScreen> createState() => _BetaScreenState();
}

class _BetaScreenState extends State<BetaScreen> {
  bool agreed = false;
  bool busy = false;
  String? msg;

  Future<void> _set(bool on) async {
    final s = SessionScope.of(context);
    setState(() => busy = true);
    try {
      await s.api.setBeta(s.token!, on, on ? (s.account?.betaConsent ?? '') : '');
      final fresh = await s.api.me(s.token!);
      s.setAccount(fresh);
      if (mounted) setState(() => msg = on ? 'You are in the beta. Your glasses switch at their next update check.' : 'You left the beta. Your glasses switch back at their next update check.');
    } on ApiException catch (e) {
      if (mounted) setState(() => msg = e.message);
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final on = s.account?.beta == true;
    return CxScreen(children: [
      const CxTop(title: 'Beta'),
      const CxTitle('Join the\nbeta'),
      const CxText('Beta gets new features earlier. They can be rougher, and Asirive receives a little more diagnostic information to fix problems faster. You can leave at any time.'),
      if (!on)
        CxSwitch(label: 'I have read and agree', detail: 'I understand beta software and the extra diagnostic information.', value: agreed, onChanged: (v) => setState(() => agreed = v)),
      if (msg != null) CxNotice(msg!),
    ], bottom: [
      if (on)
        CxButton('Leave the beta', outline: true, onTap: () => _set(false), busy: busy)
      else
        CxButton('Join the beta', onTap: agreed ? () => _set(true) : null, busy: busy),
    ]);
  }
}

class FeedbackScreen extends StatefulWidget {
  const FeedbackScreen({super.key});
  @override
  State<FeedbackScreen> createState() => _FeedbackScreenState();
}

class _FeedbackScreenState extends State<FeedbackScreen> {
  final text = TextEditingController();
  bool busy = false;
  bool sent = false;
  String? err;

  Future<void> _send() async {
    final s = SessionScope.of(context);
    if (text.text.trim().isEmpty) {
      setState(() => err = 'Write a message first.');
      return;
    }
    setState(() {
      busy = true;
      err = null;
    });
    try {
      await s.api.feedback(s.token!, text.text.trim(), appVersion);
      if (mounted) setState(() => sent = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => err = e.message);
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  void dispose() {
    text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(title: 'Feedback'),
        CxTitle(sent ? 'Thank you' : 'Send\nfeedback'),
        if (sent)
          const CxText('We received it. The message and your app version are sent, with no photos or recordings.')
        else ...[
          const CxText('Tell us what happened or what you would change. We send your message and app version only.'),
          CxField(label: 'Message', controller: text, error: err, lines: 6),
        ],
      ], bottom: [
        if (!sent) CxButton('Send', onTap: _send, busy: busy),
      ]);
}

class PrivacyScreen extends StatelessWidget {
  const PrivacyScreen({super.key, required this.owner});
  final bool owner;

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    Future<void> clearHistory() async {
      final ok = await confirmSheet(context,
          title: 'Delete location history?',
          body: 'This removes the places stored for the last 30 days. People you share with lose access to it. This cannot be undone.',
          confirmLabel: 'Delete history',
          danger: true);
      if (!ok || !context.mounted) return;
      try {
        await s.api.clearLocation(s.token!);
        if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Location history deleted.')));
      } on ApiException catch (e) {
        if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    }

    return CxScreen(children: [
      const CxTop(title: 'Privacy'),
      const CxTitle('Privacy\nand data'),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('WHAT WE KEEP', style: Cx.label),
        const SizedBox(height: 8),
        const CxText('Your email. Location history for 30 days, only if you share it. A record that a call happened, kept 30 days. Call audio is not recorded. No camera pictures or video are sent to Asirive.'),
      ])),
      if (owner) CxButton('Delete my location history', outline: true, onTap: clearHistory),
      CxButton('Delete my account', outline: true, danger: true, onTap: () => push(context, const DeleteAccountScreen())),
    ]);
  }
}

class DeleteAccountScreen extends StatefulWidget {
  const DeleteAccountScreen({super.key});
  @override
  State<DeleteAccountScreen> createState() => _DeleteAccountScreenState();
}

class _DeleteAccountScreenState extends State<DeleteAccountScreen> {
  final pw = TextEditingController();
  String? err;
  bool busy = false;

  Future<void> _delete() async {
    final s = SessionScope.of(context);
    final nav = Navigator.of(context);
    if (pw.text.isEmpty) {
      setState(() => err = 'Enter your password to confirm.');
      return;
    }
    final ok = await confirmSheet(context,
        title: 'Delete everything?',
        body: 'Your account, people, location history, call records and feedback are deleted. Your glasses are released so someone else can set them up. This cannot be undone.',
        confirmLabel: 'Delete my account',
        danger: true);
    if (!ok) return;
    setState(() => busy = true);
    try {
      await s.api.deleteAccount(s.token!, pw.text);
      nav.popUntil((r) => r.isFirst);
      await s.signOut();
    } on ApiException catch (e) {
      if (mounted) setState(() {
        err = e.message;
        busy = false;
      });
    }
  }

  @override
  void dispose() {
    pw.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(title: 'Delete account'),
        const CxTitle('Delete my\naccount'),
        const CxText('This removes your account and everything linked to it. Enter your password to go on.'),
        CxField(label: 'Password', controller: pw, obscure: true, error: err),
      ], bottom: [
        CxButton('Keep my account', onTap: () => Navigator.of(context).maybePop()),
        CxButton('Delete my account', outline: true, danger: true, onTap: _delete, busy: busy),
      ]);
}
