import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';
import 'calls.dart';
import 'invite.dart';
import 'people.dart';

class FollowingScreen extends StatefulWidget {
  const FollowingScreen({super.key});
  @override
  State<FollowingScreen> createState() => _FollowingScreenState();
}

class _FollowingScreenState extends State<FollowingScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => SessionScope.of(context).refresh());
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final note = s.inviteNote;
    final list = s.links.watching;
    return CxScreen(tab: true, children: [
      const CxTop(back: false, trailing: CxLogo()),
      const CxTitle('Following'),
      if (note != null) CxTile(child: CxText(note, color: Cx.text)),
      if (list.isEmpty)
        const CxTile(child: CxText('Nobody yet. When someone invites you, enter or scan their code here.'))
      else
        for (final f in list)
          CxTile(
            child: Semantics(
              button: true,
              label: '${f.ownerEmail}. ${f.location ? 'You can see where they are.' : 'You cannot see where they are yet.'} ${f.call ? 'You can call them.' : 'You cannot call them yet.'}',
              excludeSemantics: true,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => push(context, WhereTheyAreScreen(person: f)),
                child: Row(children: [
                  CircleAvatar(radius: 24, backgroundColor: Cx.accent, child: Text(initials(f.ownerEmail), style: const TextStyle(fontWeight: FontWeight.w700, color: Cx.ground))),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(f.ownerEmail, style: Cx.strong),
                      const SizedBox(height: 6),
                      Wrap(spacing: 6, runSpacing: 6, children: [
                        CxChip(f.location ? 'You see where they are' : 'No location yet', on: f.location),
                        CxChip(f.call ? 'You can call' : 'No calls yet', on: f.call),
                      ]),
                    ]),
                  ),
                  const Icon(Icons.chevron_right, color: Cx.faint),
                ]),
              ),
            ),
          ),
      CxButton('Enter or scan an invite code', outline: true, onTap: () => push(context, const ScanScreen())),
    ]);
  }
}

class WhereTheyAreScreen extends StatefulWidget {
  const WhereTheyAreScreen({super.key, required this.person});
  final Following person;
  @override
  State<WhereTheyAreScreen> createState() => _WhereTheyAreScreenState();
}

class _WhereTheyAreScreenState extends State<WhereTheyAreScreen> {
  Point? p;
  String? msg;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = SessionScope.of(context);
    setState(() {
      loading = true;
      msg = null;
    });
    try {
      final got = await s.api.locationOf(s.token!, widget.person.ownerId);
      if (mounted) setState(() => p = got);
    } on ApiException catch (e) {
      if (mounted) setState(() => msg = e.code == 'not_allowed' ? 'They have not shared their location with you.' : e.code == 'not_found' ? 'No location yet. It appears when they share it.' : e.message);
    }
    if (mounted) setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final pt = p;
    final stale = pt != null && DateTime.now().difference(pt.at).inMinutes > 30;
    return CxScreen(children: [
      CxTop(title: 'Where they are'),
      CxTitle('Where\nthey are'),
      CxText(widget.person.ownerEmail),
      CxTile(
        semanticLabel: pt == null ? (loading ? 'Looking for their location' : (msg ?? 'No location')) : 'Last seen ${ago(pt.at)}${stale ? '. This may be out of date.' : ''}',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('LAST SEEN', style: Cx.label),
          const SizedBox(height: 8),
          if (loading) const Text('Looking', style: Cx.body) else if (pt == null) Text(msg ?? 'No location', style: Cx.body) else ...[
            Text(ago(pt.at), style: Cx.strong.copyWith(fontSize: 22)),
            Text('${pt.lat.toStringAsFixed(5)}, ${pt.lon.toStringAsFixed(5)}', style: Cx.small),
            if (stale) Padding(padding: const EdgeInsets.only(top: 8), child: Text('This may be out of date.', style: Cx.small.copyWith(color: Cx.danger))),
          ],
        ]),
      ),
    ], bottom: [
      if (pt != null) CxButton('Open in Maps', onTap: () => s.services.opener.open(Uri.parse('https://maps.google.com/?q=${pt.lat},${pt.lon}'))),
      CxButton('Refresh', outline: true, onTap: _load),
      CxButton(widget.person.call ? 'Call' : 'Calls not allowed yet', outline: true, onTap: widget.person.call ? () => push(context, CallScreen(name: widget.person.ownerEmail, toAccountId: widget.person.ownerId)) : null),
    ]);
  }
}
