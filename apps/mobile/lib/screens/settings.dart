import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../session.dart';
import '../shell_nav.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';
import 'auth.dart';
import 'people.dart';
import 'setup.dart';

const appVersion = '0.1.0';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final p = s.prefs;
    final owner = s.side == Side.owner;
    return ListenableBuilder(
      listenable: p,
      builder: (context, _) {
        final beta = s.account?.beta == true;
        return CxScreen(tab: true, gap: owner ? 8 : 10, children: [
          const CxTop(back: false, lead: CxTitle('Settings', size: 36, height: 1.05)),
          const CxSection('Account'),
          CxList(children: [
            CxRow(owner ? 'Email and password' : 'Email', detail: s.account?.email, onTap: () => push(context, const AccountScreen())),
            if (owner) CxRow('Voice, sound and text', detail: 'Speaking speed, haptics, text size', onTap: () => push(context, const AssistScreen())),
            if (!owner) CxRow('Voice, sound and text', detail: 'Speaking speed, haptics, text size', onTap: () => push(context, const AssistScreen())),
          ]),
          if (owner) ...[
            const CxSection('Early access'),
            CxList(children: [
              CxSwitch(
                  label: 'Join the beta',
                  detail: 'New features first, more diagnostics shared',
                  value: beta,
                  onChanged: (_) => beta ? _leaveBeta(context) : _joinBeta(context)),
            ]),
          ],
          const CxSection('Notifications'),
          CxList(children: [
            CxSwitch(label: 'Incoming calls', detail: owner ? 'From people you added' : 'From people you follow', value: p.incomingCalls, onChanged: (v) => p.update(incomingCalls: v)),
            if (owner) CxSwitch(label: 'Glasses alerts', detail: 'Offline for a while, update problems', value: p.glassesAlerts, onChanged: (v) => p.update(glassesAlerts: v)),
          ]),
          if (!owner) ...[
            const CxSection('Following'),
            CxList(children: [
              CxRow('People I follow', detail: '${s.links.watching.length} ${s.links.watching.length == 1 ? 'person' : 'people'}. Stop following any of them.', onTap: () => ShellNav.go(AppTab.following, context)),
              if (s.canOwner) CxRow('Switch to owner side', detail: 'If you also wear Cortex', onTap: () => push(context, const SwitchSideScreen())),
              CxRow('I have Cortex glasses', detail: 'Pair them to this account', onTap: () => push(context, const SetupIntroScreen())),
            ]),
          ],
          const CxSection('More'),
          CxList(children: [
            if (owner) CxRow('Privacy and data', onTap: () => push(context, const PrivacyScreen(owner: true))),
            if (owner) CxRow('Send feedback', onTap: () => push(context, const FeedbackScreen())),
            if (owner && s.hasBoth) CxRow('Switch side', detail: 'Now: owner', onTap: () => push(context, const SwitchSideScreen())),
            if (!owner) CxRow('Delete my account', color: Cx.danger, chevron: false, onTap: () => deleteAccountSheet(context)),
            CxRow('Sign out', color: Cx.danger, chevron: false, onTap: () => s.signOut()),
          ]),
          Padding(padding: const EdgeInsets.only(left: 8, top: 4), child: Text('Asirive Cortex $appVersion', style: Cx.small)),
        ]);
      },
    );
  }

  Future<void> _joinBeta(BuildContext context) async {
    final s = SessionScope.of(context);
    await confirmSheet(context,
        mono: 'Early access',
        title: 'Join the beta?',
        bodyWidget: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          CxBullet(Text('You get new features before everyone else.')),
          SizedBox(height: 12),
          CxBullet(Text('Things may be less stable than the regular version.')),
          SizedBox(height: 12),
          CxBullet(Text('Your glasses share more diagnostic details with Asirive. Never camera images or video.')),
          SizedBox(height: 12),
          CxBullet(Text('Leave any time and go back to the stable version.')),
        ]),
        small: 'We record that you agreed, with the date and the version of this text (${s.account?.betaConsent ?? ''}).',
        cancelLabel: 'Not now',
        confirmLabel: 'I agree, join the beta',
        danger: false,
        speak: 'Join the beta? You get new features first. Things may be less stable. Your glasses share more diagnostic details, never camera images or video.',
        onConfirm: () => _setBeta(s, true));
  }

  Future<void> _leaveBeta(BuildContext context) async {
    final s = SessionScope.of(context);
    await confirmSheet(context,
        mono: 'Early access',
        title: 'Leave the beta?',
        body: 'Your glasses go back to the stable version at their next update check.',
        cancelLabel: 'Stay in the beta',
        confirmLabel: 'Leave the beta',
        danger: false,
        onConfirm: () => _setBeta(s, false));
  }

  Future<String?> _setBeta(Session s, bool on) async {
    try {
      await s.api.setBeta(s.token!, on, on ? (s.account?.betaConsent ?? '') : '');
      s.setAccount(await s.api.me(s.token!));
      return null;
    } on ApiException catch (e) {
      return e.message;
    }
  }
}

class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return CxScreen(children: [
      const CxTop(title: 'Your account'),
      const CxTitle('Your\naccount'),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('EMAIL', style: Cx.label),
        const SizedBox(height: 6),
        Text(s.account?.email ?? '', style: Cx.strong),
      ])),
      CxButton('Change password', outline: true, onTap: () => push(context, ForgotScreen(email: s.account?.email ?? ''))),
    ], bottom: [
      CxButton('Sign out', outline: true, danger: true, onTap: () async {
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

    final owner = s.side == Side.owner;
    Widget card(bool yellow, String mono, String big, String d, bool current, Side side) => Expanded(
          child: Semantics(
            button: true,
            label: '$mono. $big. $d${current ? '. Current' : ''}',
            excludeSemantics: true,
            child: GestureDetector(
              onTap: () => pick(side),
              child: Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(color: yellow ? Cx.accent : Cx.surface, borderRadius: BorderRadius.circular(28), border: yellow ? null : Border.all(color: Cx.lineC)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                    Text(mono.toUpperCase(), style: Cx.label.copyWith(color: yellow ? Cx.ground : Cx.faintC)),
                    if (current) Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4), decoration: BoxDecoration(color: Cx.ground, borderRadius: BorderRadius.circular(99)), child: const Text('Current', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 12, fontWeight: FontWeight.w700, color: Cx.accent))),
                  ]),
                  Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(big.toUpperCase(), style: TextStyle(fontFamily: 'Anton', fontSize: 44, height: 1, letterSpacing: 1.3, color: yellow ? Cx.ground : Cx.text)),
                    const SizedBox(height: 10),
                    Text(d, style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, fontWeight: FontWeight.w500, height: 1.4, color: yellow ? Cx.ground : Cx.mutedC)),
                  ]),
                ]),
              ),
            ),
          ),
        );
    final n = s.links.watching.length;
    return CxScreen(children: [
      const CxTop(title: 'Your account'),
      const CxTitle('Switch side'),
      const CxText('Your account can wear Cortex and look after other people.'),
      SizedBox(height: 260, child: Column(children: [
        card(owner, 'I wear Cortex', 'Owner', 'My glasses, my people, my settings and my privacy.', owner, Side.owner),
      ])),
      SizedBox(height: 260, child: Column(children: [
        card(!owner, 'I look after someone', 'Companion', '$n ${n == 1 ? 'person' : 'people'}. See where they are and call them.', !owner, Side.companion),
      ])),
      Center(child: Text('We remember the side you used last.', style: Cx.small)),
    ]);
  }
}

class AssistScreen extends StatelessWidget {
  const AssistScreen({super.key});
  String _speed(double r) => r < .4 ? 'Slow' : r > .6 ? 'Fast' : 'Normal';
  String _size(double t) => t < 1.15 ? 'Normal' : t < 1.5 ? 'Slightly larger' : t < 1.8 ? 'Larger' : 'Largest';
  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final p = s.prefs;
    return ListenableBuilder(
      listenable: p,
      builder: (context, _) => CxScreen(gap: 8, children: [
        const CxTop(lead: Padding(padding: EdgeInsets.only(left: 12), child: CxTitle('Voice, sound\nand text', size: 30))),
        const CxSection('Speech', top: 4),
        CxList(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10), children: [
          Column(children: [
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
              const Text('Speaking speed', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text)),
              Text(_speed(p.speechRate), style: Cx.small),
            ]),
            CxSlider(
                label: 'Speaking speed',
                value: ((p.speechRate - .3) / .4).clamp(0, 1),
                valueText: _speed(p.speechRate),
                onChanged: (v) {
                  final r = .3 + v * .4;
                  p.update(speechRate: r);
                  s.services.speaker.setRate(r);
                }),
          ]),
          CxSwitch(label: 'Read my status when I open the app', value: p.readStatusOnOpen, onChanged: (v) => p.update(readStatusOnOpen: v)),
        ]),
        const CxSection('Touch and sound', top: 4),
        CxList(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10), children: [
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Haptic strength', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text)),
              const SizedBox(height: 10),
              _Seg(options: const ['Low', 'Medium', 'High'], index: p.haptic, label: 'Haptic strength', onChanged: (i) => p.update(haptic: i)),
            ]),
          ),
          CxSwitch(label: 'Spoken alerts', detail: 'Calls, offline glasses, update problems', value: p.spokenAlerts, onChanged: (v) => p.update(spokenAlerts: v)),
        ]),
        const CxSection('Text and contrast', top: 4),
        CxList(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10), children: [
          Column(children: [
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
              const Text('Text size', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text)),
              const Text('Aa', style: TextStyle(fontFamily: 'Anton', fontSize: 28, height: 1, color: Cx.accent)),
            ]),
            CxSlider(label: 'Text size', value: (p.textScale - 1).clamp(0, 1), valueText: _size(p.textScale), onChanged: (v) => p.update(textScale: 1 + v)),
          ]),
          CxSwitch(label: 'Extra contrast', detail: 'Brighter text, stronger outlines', value: p.highContrast, onChanged: (v) => p.update(highContrast: v)),
        ]),
        SizedBox(height: 50, child: CxButton('Hear a sample', outline: true, small: true, icon: Icons.volume_up_outlined, onTap: () => s.services.speaker.say('This is how fast Cortex will speak.'))),
      ]),
    );
  }
}

class _Seg extends StatelessWidget {
  const _Seg({required this.options, required this.index, required this.onChanged, required this.label});
  final List<String> options;
  final int index;
  final ValueChanged<int> onChanged;
  final String label;
  @override
  Widget build(BuildContext context) => Semantics(
        container: true,
        label: label,
        child: Container(
          padding: const EdgeInsets.all(4),
          decoration: BoxDecoration(color: Cx.ground, borderRadius: BorderRadius.circular(26)),
          child: Row(children: [
            for (var i = 0; i < options.length; i++)
              Expanded(
                child: Semantics(
                  button: true,
                  selected: i == index,
                  label: '${options[i]}${i == index ? ', current' : ''}',
                  excludeSemantics: true,
                  child: GestureDetector(
                    onTap: () => onChanged(i),
                    child: Container(
                      height: 44,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(color: i == index ? Cx.accent : Colors.transparent, borderRadius: BorderRadius.circular(22)),
                      child: Text(options[i], style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, fontWeight: FontWeight.w700, color: i == index ? Cx.ground : Cx.faintC)),
                    ),
                  ),
                ),
              ),
          ]),
        ),
      );
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
        CxTitle(sent ? 'Thank you' : 'Tell us\nwhat happened'),
        CxText(sent ? 'We received it. Only your message and the app version were sent, with no photos or recordings.' : 'Your message goes to the Asirive team.'),
        if (!sent) CxField(label: 'Your message', controller: text, error: err, lines: 7),
        if (!sent)
          CxYellowLink('See exactly what will be sent', center: false, onTap: () => confirmSheet(context,
              mono: 'Feedback',
              title: 'What is sent',
              body: 'Your message exactly as you wrote it, and the app version ($appVersion). Nothing else: no audio, images, video or device log.',
              cancelLabel: 'Close',
              confirmLabel: 'Send now',
              danger: false,
              onConfirm: () async {
                await _send();
                return err;
              })),
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
    final seen = s.links.owned.where((c) => c.state == 'active' && c.location).toList();
    Future<void> clearHistory() async {
      final ok = await confirmSheet(context,
          mono: 'Privacy and data',
          title: 'Delete location history?',
          body: 'Your recorded locations are deleted for everyone. Sharing keeps working and starts a fresh trail. This cannot be undone.',
          cancelLabel: 'Keep it',
          confirmLabel: 'Delete location history',
          onConfirm: () async {
            try {
              await s.api.clearLocation(s.token!);
              return null;
            } on ApiException catch (e) {
              return e.message;
            }
          });
      if (ok && context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Location history deleted.')));
    }

    return CxScreen(children: [
      const CxTop(title: 'Settings'),
      const CxTitle('Privacy\nand data'),
      if (owner)
        CxTile(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('WHO CAN SEE MY LOCATION', style: Cx.label),
          const SizedBox(height: 6),
          if (seen.isEmpty) Padding(padding: EdgeInsets.symmetric(vertical: 10), child: Text('Nobody right now.', style: Cx.body)),
          for (final c in seen)
            Container(
              constraints: const BoxConstraints(minHeight: 44),
              child: Row(children: [
                ExcludeSemantics(child: CircleAvatar(radius: 16, backgroundColor: Cx.chipFill, child: Text(initials(c.label), style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Cx.text)))),
                const SizedBox(width: 12),
                Expanded(child: Text(c.label, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text))),
                Text('Can see', style: Cx.small),
              ]),
            ),
          const SizedBox(height: 6),
          Text('Kept up to 30 days, then deleted automatically.', style: Cx.small),
          const SizedBox(height: 12),
          SizedBox(height: 48, child: CxButton('Delete my location history', outline: true, danger: true, small: true, onTap: clearHistory)),
        ])),
      CxDashed(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('NEVER STORED', style: Cx.label),
          SizedBox(height: 6),
          Text('Camera images and video. Calls are voice only and the audio is not recorded. A short record that a call happened is kept 30 days.', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, height: 1.45, color: Cx.mutedC)),
        ]),
      ),
    ], bottom: [
      Padding(padding: EdgeInsets.symmetric(horizontal: 8), child: Text('Deleting your account removes your companions and location history, and unlinks your glasses. This cannot be undone.', style: Cx.small)),
      CxButton('Delete account', outline: true, danger: true, onTap: () => deleteAccountSheet(context)),
    ]);
  }
}

/// Confirm with the password inside the sheet; the server says if it is wrong.
Future<void> deleteAccountSheet(BuildContext context) async {
  final s = SessionScope.of(context);
  final pw = TextEditingController();
  final nav = Navigator.of(context);
  final ok = await confirmSheet(context,
      mono: 'Account',
      title: 'Delete your account?',
      body: 'This removes your account, your companions and your location history, and unlinks your glasses. It cannot be undone.',
      extra: CxField(label: 'Enter your password to confirm', controller: pw, obscure: true, autofill: const [AutofillHints.password]),
      cancelLabel: 'Keep my account',
      confirmLabel: 'Delete my account',
      onConfirm: () async {
        if (pw.text.isEmpty) return 'Enter your password to confirm.';
        try {
          await s.api.deleteAccount(s.token!, pw.text);
          return null;
        } on ApiException catch (e) {
          return e.message;
        }
      });
  pw.dispose();
  if (ok) {
    nav.popUntil((r) => r.isFirst);
    await s.signOut();
  }
}
