import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

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
    final people = s.links.owned.where((c) => c.state != 'revoked').toList();
    return CxScreen(tab: true, children: [
      const CxTop(back: false, trailing: CxLogo()),
      const CxTitle('My people'),
      const CxText('You choose who can see where you are and who can call you. Nobody sees anything until you allow it.'),
      if (people.isEmpty)
        const CxTile(child: CxText('Nobody yet. Invite someone you trust.'))
      else
        for (final c in people)
          CxTile(
            child: Semantics(
              button: true,
              label: '${c.label}, ${c.state == 'pending' ? 'waiting to accept' : 'active'}. ${c.location ? 'Sees where you are.' : 'Cannot see where you are.'} ${c.call ? 'Can call.' : 'Cannot call.'}',
              excludeSemantics: true,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => push(context, GrantsScreen(link: c)),
                child: Row(children: [
                  CircleAvatar(radius: 24, backgroundColor: c.state == 'active' ? Cx.accent : const Color(0xFF34463A), child: Text(initials(c.label), style: TextStyle(fontWeight: FontWeight.w700, color: c.state == 'active' ? Cx.ground : Cx.text))),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(c.label, style: Cx.strong),
                      const SizedBox(height: 6),
                      Wrap(spacing: 6, runSpacing: 6, children: [
                        if (c.state == 'pending') const CxChip('Waiting to accept') else ...[
                          CxChip(c.location ? 'Sees where you are' : 'No location', on: c.location),
                          CxChip(c.call ? 'Can call' : 'No calls', on: c.call),
                        ],
                      ]),
                    ]),
                  ),
                  const Icon(Icons.chevron_right, color: Cx.faint),
                ]),
              ),
            ),
          ),
      CxButton('Invite someone', onTap: () => push(context, const InviteScreen())),
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
  bool copied = false;

  Future<void> _make() async {
    if (label.text.trim().isEmpty) {
      setState(() => err = 'Add a name so you know who this is for.');
      return;
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
    } on ApiException catch (e) {
      if (mounted) setState(() => err = e.message);
    }
    if (mounted) setState(() => busy = false);
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
      const CxTop(title: 'Invite'),
      CxTitle(i == null ? 'Invite\nsomeone' : 'Share\nthis code'),
      if (i == null) ...[
        const CxText('They get a code to enter or scan in their Cortex app. It works once and expires in 48 hours. They see nothing until you allow it.'),
        CxField(label: 'Their name', controller: label, hint: 'For example, Hui Min', error: err, onSubmit: _make),
      ] else ...[
        CxText('Give this to ${label.text.trim()}. It is shown once, and you cannot see it again.'),
        CxTile(
            semanticLabel: 'Invite code ${i.code.split('').join(' ')}',
            child: Column(children: [
              Text(i.code, style: Cx.display.copyWith(fontSize: 36, letterSpacing: 2)),
              const SizedBox(height: 14),
              Container(
                color: Colors.white,
                padding: const EdgeInsets.all(10),
                child: ExcludeSemantics(child: QrImageView(data: i.link, size: 180)),
              ),
            ])),
        if (copied) const CxNotice('Link copied.'),
      ],
    ], bottom: [
      if (i == null)
        CxButton('Make the invite', onTap: _make, busy: busy)
      else ...[
        CxButton('Copy the link', onTap: () async {
          await Clipboard.setData(ClipboardData(text: i.link));
          if (mounted) setState(() => copied = true);
        }),
        CxButton('Done', outline: true, onTap: () => Navigator.of(context).maybePop()),
      ],
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
    final ok = await confirmSheet(context,
        title: 'Remove ${widget.link.label}?',
        body: '${widget.link.label} stops seeing where you are and can no longer call you. Any call in progress ends. You can invite them again later.',
        confirmLabel: 'Remove',
        cancelLabel: 'Keep ${widget.link.label}',
        danger: true);
    if (!ok) return;
    try {
      await s.api.revoke(s.token!, widget.link.id);
      await s.refresh();
      nav.pop();
    } on ApiException catch (e) {
      if (mounted) setState(() => err = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final pending = widget.link.state == 'pending';
    return CxScreen(children: [
      CxTop(title: widget.link.label),
      CxTitle('What ${widget.link.label}\ncan see'),
      if (pending)
        const CxText('They have not accepted yet. You can choose now and it applies when they join.')
      else
        const CxText('Turn each one on or off. It changes straight away, and you can change it any time.'),
      CxTile(
          child: Column(children: [
        CxSwitch(label: 'See where I am', detail: 'Only my latest place, history kept 30 days', value: loc, onChanged: (v) => _save(v, call)),
        const Divider(color: Cx.line, height: 1),
        CxSwitch(label: 'Call me', detail: 'A voice call. Audio is not recorded', value: call, onChanged: (v) => _save(loc, v)),
      ])),
      const CxText('Never the camera.', small: true),
      if (err != null) CxNotice(err!, error: true),
    ], bottom: [
      CxButton('Remove ${widget.link.label}', outline: true, danger: true, onTap: _remove),
    ]);
  }
}
