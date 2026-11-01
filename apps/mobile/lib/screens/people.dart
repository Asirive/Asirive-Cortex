import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';

import '../api.dart';
import '../scope.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';

String initials(String s) {
  final t = s.trim();
  if (t.isEmpty) return '?';
  final parts = t.split(RegExp(r'\s+'));
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].substring(0, t.length > 1 ? 2 : 1)).toUpperCase();
}

class CxAvatar extends StatelessWidget {
  const CxAvatar(this.text, {super.key, this.size = 52, this.yellow = false, this.fontSize});
  final String text;
  final double size;
  final bool yellow;
  final double? fontSize;
  @override
  Widget build(BuildContext context) => ExcludeSemantics(
        child: Container(
          width: size,
          height: size,
          alignment: Alignment.center,
          decoration: BoxDecoration(shape: BoxShape.circle, color: yellow ? Cx.accent : const Color(0xFF34463A)),
          child: Text(initials(text), style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: fontSize ?? size / 3, fontWeight: FontWeight.w700, color: yellow ? Cx.ground : Cx.text)),
        ),
      );
}

class PeopleScreen extends StatefulWidget {
  const PeopleScreen({super.key});
  @override
  State<PeopleScreen> createState() => _PeopleScreenState();
}

class _PeopleScreenState extends State<PeopleScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => SessionScope.of(context).refresh());
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final active = s.links.owned.where((c) => c.state == 'active').toList();
    final waiting = s.links.owned.where((c) => c.state == 'pending').toList();
    return CxScreen(tab: true, children: [
      const CxTop(back: false, lead: CxTitle('My people', size: 36, height: 1.05)),
      const Padding(padding: EdgeInsets.symmetric(horizontal: 8), child: CxText('Chosen by you. You decide what each one can see.')),
      CxSection('Companions · ${active.length}', top: 6),
      if (active.isEmpty) const CxTile(child: CxText('Nobody yet. Invite someone you trust.')),
      for (final c in active)
        Semantics(
          button: true,
          label: '${c.label}. ${c.location ? 'Sees where you are.' : 'Cannot see where you are.'} ${c.call ? 'Can call.' : 'Cannot call.'}',
          excludeSemantics: true,
          child: GestureDetector(
            onTap: () => push(context, GrantsScreen(link: c)),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
              child: Row(children: [
                CxAvatar(c.label, yellow: active.first == c, size: 52, fontSize: 17),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(c.label, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 18, fontWeight: FontWeight.w700, color: Cx.text)),
                    const SizedBox(height: 7),
                    Wrap(spacing: 6, runSpacing: 6, children: [CxChip(c.location ? 'Location' : 'No location', on: c.location), CxChip(c.call ? 'Calls' : 'No calls', on: c.call)]),
                  ]),
                ),
                Icon(Icons.chevron_right, color: Cx.faintC),
              ]),
            ),
          ),
        ),
      if (waiting.isNotEmpty) CxSection('${waiting.length} invite${waiting.length == 1 ? '' : 's'} waiting', top: 6),
      for (final c in waiting)
        CxDashed(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Invite sent to ${c.label}', style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text)),
                const SizedBox(height: 3),
                Text('Waiting for them to accept', style: Cx.small),
              ]),
            ),
            Semantics(
              button: true,
              label: 'Cancel invite for ${c.label}',
              excludeSemantics: true,
              child: GestureDetector(
                onTap: () async {
                  try {
                    await s.api.revoke(s.token!, c.id);
                    await s.refresh();
                  } on ApiException {
                    // shown again on the next refresh
                  }
                },
                child: const SizedBox(height: 44, child: Center(child: Text('Cancel invite', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, fontWeight: FontWeight.w600, color: Cx.danger)))),
              ),
            ),
          ]),
        ),
    ], bottom: [
      CxButton('Invite someone', icon: Icons.person_add_alt, onTap: () => push(context, const InviteScreen())),
    ]);
  }
}

class InviteScreen extends StatefulWidget {
  const InviteScreen({super.key});
  @override
  State<InviteScreen> createState() => _InviteScreenState();
}

class _InviteScreenState extends State<InviteScreen> {
  final label = TextEditingController();
  Invite? invite;
  String? err;
  bool busy = false;
  String? note;

  Future<Invite?> _make() async {
    if (invite != null) return invite;
    if (label.text.trim().isEmpty) {
      setState(() => err = 'Add a name so you know who this is for.');
      return null;
    }
    final s = SessionScope.of(context);
    setState(() {
      busy = true;
      err = null;
    });
    try {
      final i = await s.api.invite(s.token!, label.text.trim());
      await s.refresh();
      if (mounted) setState(() => invite = i);
      return i;
    } on ApiException catch (e) {
      if (mounted) setState(() => err = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
    return null;
  }

  @override
  void dispose() {
    label.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final i = invite;
    return CxScreen(children: [
      const CxTop(title: 'New invite'),
      const CxTitle('Invite\nsomeone'),
      CxField(label: 'Their name or label', controller: label, hint: 'For example, Hui Min', error: err, onSubmit: _make),
      CxTile(
        semanticLabel: i == null ? 'The invite code appears here once you share the link' : 'Invite code ${i.code.split('').join(' ')}',
        child: Row(children: [
          ExcludeSemantics(
            child: Container(
              width: 96,
              height: 96,
              color: Colors.white,
              padding: const EdgeInsets.all(6),
              child: i == null ? const Icon(Icons.qr_code_2, size: 80, color: Color(0xFFB0B0B0)) : QrImageView(data: i.link, size: 84, padding: EdgeInsets.zero),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(i == null ? 'SCAN IN PERSON' : 'CODE · SHOWN ONCE', style: Cx.label),
              const SizedBox(height: 6),
              Text(i == null ? 'asirive://companion?code=…' : i.code, style: TextStyle(fontFamily: 'JetBrainsMono', fontSize: i == null ? 13 : 22, height: 1.3, color: Cx.accent, letterSpacing: i == null ? 0 : 3)),
              const SizedBox(height: 6),
              Text(i == null ? 'Or send the link below.' : 'Give them this code, or let them scan.', style: Cx.small),
            ]),
          ),
        ]),
      ),
      if (note != null) CxNotice(note!),
    ], bottom: [
      CxButton('Share the link', icon: Icons.ios_share, busy: busy, onTap: () async {
        final inv = await _make();
        if (inv == null) return;
        try {
          await SharePlus.instance.share(ShareParams(text: 'Join me on Asirive Cortex: ${inv.link}\nCode: ${inv.code}'));
        } on Exception {
          await Clipboard.setData(ClipboardData(text: inv.link));
          if (mounted) setState(() => note = 'Sharing is not available here, so the link was copied.');
        }
      }),
      CxButton('Copy link', outline: true, onTap: () async {
        final inv = await _make();
        if (inv == null) return;
        await Clipboard.setData(ClipboardData(text: inv.link));
        if (mounted) setState(() => note = 'Link copied.');
      }),
      Text('The link works once and expires in 48 hours. No camera, ever.', textAlign: TextAlign.center, style: Cx.small),
    ]);
  }
}

class GrantsScreen extends StatefulWidget {
  const GrantsScreen({super.key, required this.link});
  final Companion link;
  @override
  State<GrantsScreen> createState() => _GrantsScreenState();
}

class _GrantsScreenState extends State<GrantsScreen> {
  late bool loc = widget.link.location;
  late bool call = widget.link.call;
  String? err;

  Future<void> _save(bool l, bool c) async {
    final s = SessionScope.of(context);
    final oldL = loc, oldC = call;
    setState(() {
      loc = l;
      call = c;
      err = null;
    });
    try {
      await s.api.setGrants(s.token!, widget.link.id, location: l, call: c);
      await s.refresh();
    } on ApiException catch (e) {
      if (mounted) setState(() {
        loc = oldL;
        call = oldC;
        err = e.message;
      });
    }
  }

  Future<void> _remove() async {
    final s = SessionScope.of(context);
    final nav = Navigator.of(context);
    final name = widget.link.label;
    final ok = await confirmSheet(context,
        mono: 'My people',
        title: 'Remove $name?',
        body: '$name will no longer see where you are and cannot call you. You can invite them again later.',
        cancelLabel: 'Keep $name',
        confirmLabel: 'Remove $name',
        onConfirm: () async {
          try {
            await s.api.revoke(s.token!, widget.link.id);
            await s.refresh();
            return null;
          } on ApiException catch (e) {
            return e.message;
          }
        });
    if (ok) nav.pop();
  }

  @override
  Widget build(BuildContext context) {
    final name = widget.link.label;
    return CxScreen(children: [
      const CxTop(title: 'Companion'),
      Row(children: [
        CxAvatar(name, size: 72, yellow: true, fontSize: 24),
        const SizedBox(width: 16),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            CxTitle(name, size: 40),
            const SizedBox(height: 8),
            Text('COMPANION', style: Cx.label),
          ]),
        ),
      ]),
      CxSection('$name can', top: 10),
      CxList(children: [
        CxSwitch(label: 'See my location', detail: 'Where I am now and my last few minutes. Kept up to 30 days.', tall: true, value: loc, onChanged: (v) => _save(v, call)),
        CxSwitch(label: 'Call me', detail: 'Rings my phone. I can always decline.', tall: true, value: call, onChanged: (v) => _save(loc, v)),
      ]),
      CxDashed(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('NEVER SHARED', style: Cx.label),
          SizedBox(height: 6),
          Text('Camera images, video, or anything you say to the assistant.', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, height: 1.45, color: Cx.mutedC)),
        ]),
      ),
      Padding(padding: EdgeInsets.symmetric(horizontal: 8), child: Text('Changes apply straight away. Turning location off does not delete what was already recorded. Use Privacy and data for that.', style: Cx.small)),
      if (err != null) CxNotice(err!, error: true),
    ], bottom: [
      CxButton('Remove $name', outline: true, danger: true, onTap: _remove),
    ]);
  }
}
