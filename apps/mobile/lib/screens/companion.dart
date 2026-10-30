import 'dart:math' as math;

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
  final ages = <String, DateTime?>{}; // owner id -> last seen

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final s = SessionScope.of(context);
      await s.refresh();
      for (final f in s.links.watching.where((f) => f.location)) {
        try {
          final p = await s.api.locationOf(s.token!, f.ownerId);
          if (mounted) setState(() => ages[f.ownerId] = p.at);
        } on ApiException {
          if (mounted) setState(() => ages[f.ownerId] = null);
        }
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final note = s.inviteNote;
    final list = s.links.watching;
    return CxScreen(tab: true, children: [
      const CxTop(back: false, lead: CxTitle('Following', size: 36, height: 1.05)),
      const Padding(padding: EdgeInsets.symmetric(horizontal: 8), child: CxText('You only see what each person allowed.')),
      if (note != null)
        CxTile(
            child: Row(children: [
          Expanded(child: Text(note, style: Cx.body.copyWith(color: Cx.text))),
          Semantics(button: true, label: 'Dismiss', excludeSemantics: true, child: GestureDetector(onTap: () => setState(() => s.inviteNote = null), child: const SizedBox(width: 44, height: 44, child: Icon(Icons.close, size: 20, color: Cx.faint)))),
        ])),
      if (list.isEmpty) const CxTile(child: CxText('Nobody yet. When someone invites you, enter or scan their code here.')),
      for (var i = 0; i < list.length; i++) _PersonTile(f: list[i], first: i == 0, seen: ages[list[i].ownerId]),
      if (list.isNotEmpty) const Padding(padding: EdgeInsets.only(top: 6), child: Center(child: Text('Nothing here uses the camera.', style: Cx.small))),
      CxButton('Enter or scan an invite code', outline: true, onTap: () => push(context, const ScanScreen())),
    ]);
  }
}

class _PersonTile extends StatelessWidget {
  const _PersonTile({required this.f, required this.first, required this.seen});
  final Following f;
  final bool first;
  final DateTime? seen;
  @override
  Widget build(BuildContext context) {
    final sub = !f.location ? 'Has not shared location with you' : (seen == null ? 'Looking for their location' : 'Last seen ${ago(seen!)}');
    Widget btn(String label, IconData? icon, VoidCallback? onTap, {bool outline = false, bool off = false}) => Expanded(
          child: Semantics(
            button: true,
            enabled: onTap != null,
            label: off ? '$label, not shared' : label,
            excludeSemantics: true,
            child: GestureDetector(
              onTap: onTap,
              child: Container(
                height: 48,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                    color: outline || off ? Colors.transparent : Cx.accent,
                    borderRadius: BorderRadius.circular(24),
                    border: outline ? Border.all(color: Cx.outline, width: 1.5) : (off ? Border.all(color: Cx.outline, width: 1.5) : null)),
                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  if (icon != null) ...[Icon(icon, size: 18, color: outline ? Cx.text : Cx.ground), const SizedBox(width: 8)],
                  Text(label, style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, fontWeight: FontWeight.w700, color: off ? Cx.faint : (outline ? Cx.text : Cx.ground))),
                ]),
              ),
            ),
          ),
        );
    return CxTile(
        child: Column(children: [
      Row(children: [
        CxAvatar(f.ownerEmail, yellow: first, size: 52, fontSize: 17),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(f.ownerEmail, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 18, fontWeight: FontWeight.w700, color: Cx.text)),
            const SizedBox(height: 3),
            Text(sub, style: Cx.small.copyWith(fontSize: 14)),
          ]),
        ),
      ]),
      const SizedBox(height: 14),
      Row(children: [
        f.location ? btn('Where', Icons.place_outlined, () => push(context, WhereTheyAreScreen(person: f))) : btn('Where · not shared', null, null, off: true),
        const SizedBox(width: 10),
        btn(f.call ? 'Call' : 'Call · not allowed', f.call ? Icons.call_outlined : null, f.call ? () => push(context, CallScreen(name: f.ownerEmail, toAccountId: f.ownerId)) : null, outline: f.call, off: !f.call),
      ]),
    ]));
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
    final name = widget.person.ownerEmail;
    return Scaffold(
      body: Stack(children: [
        Positioned(top: 0, left: 0, right: 0, height: 560, child: Semantics(label: 'Map placeholder', image: true, child: CustomPaint(painter: LocationMapPainter(found: pt != null)))),
        Positioned(top: math.max(MediaQuery.of(context).padding.top, 28), left: Cx.margin, child: const CxBack()),
        Positioned(
          left: 8,
          right: 8,
          bottom: 8 + MediaQuery.of(context).padding.bottom,
          child: Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(32), border: Border.all(color: Cx.line)),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                CxAvatar(name, yellow: true, size: 52, fontSize: 17),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(name.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: Cx.label),
                    const SizedBox(height: 6),
                    Text(pt == null ? (loading ? 'LOOKING' : 'NO LOCATION') : '${pt.lat.toStringAsFixed(4)}, ${pt.lon.toStringAsFixed(4)}', style: const TextStyle(fontFamily: 'Anton', fontSize: 28, height: 1, letterSpacing: .84, color: Cx.text)),
                  ]),
                ),
              ]),
              const SizedBox(height: 14),
              Semantics(
                liveRegion: true,
                child: Text(
                    pt == null ? (msg ?? 'Looking for their location.') : 'Updated ${ago(pt.at)}.${stale ? ' This may be out of date.' : ''} Location is kept up to 30 days and they can clear it at any time.',
                    style: Cx.body.copyWith(fontSize: 14, color: stale ? Cx.danger : Cx.muted)),
              ),
              const SizedBox(height: 14),
              Row(children: [
                Expanded(child: SizedBox(height: 52, child: CxButton(widget.person.call ? 'Call' : 'Calls off', icon: Icons.call_outlined, small: true, onTap: widget.person.call ? () => push(context, CallScreen(name: name, toAccountId: widget.person.ownerId)) : null))),
                const SizedBox(width: 10),
                Expanded(child: SizedBox(height: 52, child: CxButton('Open in Maps', outline: true, small: true, onTap: pt == null ? null : () => s.services.opener.open(Uri.parse('https://maps.google.com/?q=${pt.lat},${pt.lon}'))))),
              ]),
              const SizedBox(height: 10),
              CxButton('Refresh', outline: true, small: true, onTap: _load),
            ]),
          ),
        ),
      ]),
    );
  }
}

class LocationMapPainter extends CustomPainter {
  const LocationMapPainter({required this.found});
  final bool found;
  @override
  void paint(Canvas c, Size s) {
    c.drawRect(Offset.zero & s, Paint()..color = const Color(0xFF0F130F));
    final road = Paint()..color = const Color(0xFF1A221B)..strokeWidth = 16..strokeCap = StrokeCap.round..style = PaintingStyle.stroke;
    final lane = Paint()..color = const Color(0xFF141B15)..strokeWidth = 6..strokeCap = StrokeCap.round..style = PaintingStyle.stroke;
    for (final y in [110.0, 250.0, 390.0, 500.0]) {
      c.drawLine(Offset(-10, y), Offset(s.width + 10, y + 30), road);
    }
    for (final x in [60.0, 200.0, 320.0]) {
      c.drawLine(Offset(x, -10), Offset(x - 40, s.height + 10), road);
    }
    for (final y in [50.0, 180.0, 320.0, 450.0]) {
      c.drawLine(Offset(-10, y), Offset(s.width + 10, y - 20), lane);
    }
    if (found) {
      c.drawCircle(const Offset(215, 260), 34, Paint()..color = Cx.accent.withValues(alpha: .16));
      c.drawCircle(const Offset(215, 260), 13, Paint()..color = Cx.accent);
      c.drawCircle(const Offset(215, 260), 13, Paint()..color = Cx.ground..style = PaintingStyle.stroke..strokeWidth = 4);
    }
  }

  @override
  bool shouldRepaint(covariant LocationMapPainter old) => old.found != found;
}
