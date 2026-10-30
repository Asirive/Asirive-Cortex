import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../services.dart';
import '../session.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';
import '../shell_nav.dart';
import 'auth.dart';
import 'people.dart';
import 'settings.dart';
import 'setup.dart';

class _Round extends StatelessWidget {
  const _Round({required this.child, required this.label, this.onTap, this.border = Cx.outline, this.fill = Cx.surface});
  final Widget child;
  final String label;
  final VoidCallback? onTap;
  final Color border, fill;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: label,
        excludeSemantics: true,
        child: GestureDetector(
          onTap: onTap,
          child: Container(
              width: 44,
              height: 44,
              alignment: Alignment.center,
              decoration: BoxDecoration(color: fill, shape: BoxShape.circle, border: Border.all(color: border, width: 1.5)),
              child: child),
        ),
      );
}

/// Owner Home, as drawn in the mockups.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  LinkState link = LinkState.cableOut;
  Map<String, dynamic>? offer;
  String? note;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = SessionScope.of(context);
    await s.refresh();
    final l = await s.services.link.state();
    Map<String, dynamic>? o;
    if (s.devices.isNotEmpty && s.token != null) {
      try {
        o = await s.api.updateOffer(s.token!, s.devices.first.id);
      } on ApiException {
        o = null;
      }
    }
    if (mounted) setState(() {
      link = l;
      offer = o;
    });
  }

  String _linkWord() => switch (link) {
        LinkState.connectedOnline => 'Connected',
        LinkState.connectedNoInternet => 'Cable on · no internet',
        LinkState.cableOut => 'Cable out',
      };

  String _status(Session s) {
    final d = s.devices.isEmpty ? null : s.devices.first;
    if (d == null) return 'No glasses are set up yet.';
    final b = d.battery == null ? '' : ' Battery ${d.battery} percent.';
    final u = offer == null ? '' : ' Update ready.';
    return '${d.label.isEmpty ? 'Your Cortex' : d.label} is ${d.online ? 'online' : 'offline'}.$b ${switch (link) {
      LinkState.connectedOnline => 'The pocket box is connected and online.',
      LinkState.connectedNoInternet => 'The pocket box is connected but has no internet.',
      LinkState.cableOut => 'The pocket box is not plugged in to this phone.',
    }}$u';
  }

  Future<void> _pause() async {
    final s = SessionScope.of(context);
    final ok = await confirmSheet(context,
        mono: 'Glasses',
        title: 'Pause the assistant?',
        bodyWidget: Text.rich(TextSpan(style: Cx.body.copyWith(fontSize: 16, color: const Color(0xFFD6DDD0)), children: const [
          TextSpan(text: 'Voice help and navigation stop talking until you resume. '),
          TextSpan(text: 'Obstacle warnings keep running.', style: TextStyle(color: Cx.accent, fontWeight: FontWeight.w700)),
        ])),
        small: 'This works over the USB cable, so the glasses must be plugged in. You can also resume from the glasses.',
        speak: 'Pause the assistant? Voice help and navigation stop talking until you resume. Obstacle warnings keep running. The glasses must be plugged in.',
        cancelLabel: 'Keep it running',
        confirmLabel: 'Pause the assistant',
        danger: false);
    if (!ok) return;
    final done = await s.services.link.pause();
    if (mounted) setState(() => note = done ? 'Assistant paused. Obstacle warnings are still on.' : 'Could not reach the pocket box. Plug it in with the cable and try again.');
  }

  Future<void> _update() async {
    final d = SessionScope.of(context).devices.first;
    final ok = await confirmSheet(context,
        mono: 'Software update',
        title: 'Install the update?',
        bodyWidget: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          CxBullet(Text('Takes about 5 minutes. Keep the cable plugged in.')),
          SizedBox(height: 12),
          CxBullet(Text('The assistant is unavailable while it installs. Do not start it while crossing a road.')),
          SizedBox(height: 12),
          CxBullet(Text('If anything goes wrong, the glasses go back to the version that worked, and tell you.')),
        ]),
        speak: 'Install the update? Takes about 5 minutes. Keep the cable plugged in. The assistant is unavailable while it installs.',
        cancelLabel: 'Not now',
        confirmLabel: 'Install now',
        danger: false);
    if (ok && mounted) push(context, UpdateProgressScreen(device: d, offer: offer!));
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final d = s.devices.isEmpty ? null : s.devices.first;
    final offline = d != null && (link == LinkState.connectedNoInternet);
    final batt = d?.battery ?? 0;
    return CxScreen(tab: true, children: [
      SizedBox(
        height: 48,
        child: Row(children: [
          const CxLogo(),
          const SizedBox(width: 12),
          const Expanded(
              child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('WELCOME', style: TextStyle(fontFamily: 'Anton', fontSize: 28, height: 1, letterSpacing: .84, color: Cx.accent)),
            SizedBox(height: 5),
            Text('ASIRIVE CORTEX', style: TextStyle(fontFamily: 'JetBrainsMono', fontSize: 12, height: 1.0, letterSpacing: 1.7, color: Cx.faint)),
          ])),
          _Round(label: 'Hear my status', onTap: () => s.services.speaker.say(_status(s)), child: const Icon(Icons.volume_up_outlined, size: 22, color: Cx.accent)),
          const SizedBox(width: 12),
          _Round(label: s.hasBoth ? 'Account and side' : 'Account', border: const Color(0xFF8A817C), fill: Colors.transparent, onTap: () => push(context, s.hasBoth ? const SwitchSideScreen() : const AccountScreen()), child: const Icon(Icons.person_outline, size: 22, color: Cx.accent)),
        ]),
      ),
      SizedBox(
        height: 178,
        child: Semantics(
          label: 'Your Cortex glasses connected to the pocket module',
          image: true,
          child: Center(child: Image.asset('assets/images/hero.png', width: 318, height: 178, fit: BoxFit.contain, excludeFromSemantics: true)),
        ),
      ),
      if (d != null)
        // The battery tab sits flush on the search pill: its last 14px overlap the gap below.
        SizedBox(
          height: 52 - 14,
          child: OverflowBox(
            alignment: Alignment.topCenter,
            minHeight: 52,
            maxHeight: 52,
            child: Padding(padding: const EdgeInsets.symmetric(horizontal: 28), child: _BatteryTab(percent: batt, word: _linkWord(), warn: offline, status: _status(s))),
          ),
        )
      else
      Semantics(
        button: true,
        label: 'Find a place. Opens the map',
        excludeSemantics: true,
        child: GestureDetector(
          onTap: () => push(context, const MyMapScreen()),
          child: Container(
            height: 52,
            padding: const EdgeInsets.only(left: 20, right: 8),
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(26)),
            child: const Row(children: [
              Icon(Icons.search, size: 22, color: Cx.faint),
              SizedBox(width: 12),
              Expanded(child: Text('Find a place', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w500, color: Cx.faint))),
              SizedBox(width: 44, height: 44, child: Icon(Icons.map_outlined, size: 22, color: Cx.faint)),
            ]),
          ),
        ),
      ),
      if (d == null)
        _WideTile(title: 'Set up glasses', sub: 'A sighted helper guides you through five steps', icon: Icons.arrow_forward, onTap: () => push(context, const SetupIntroScreen()))
      else if (offline)
        _WideTile(title: 'Glasses are offline', sub: 'Turn on internet sharing on this phone', icon: Icons.wifi_off, bad: true, onTap: () => push(context, const InternetScreen()))
      else if (offer != null)
        _WideTile(title: 'Update ready', sub: 'Tap to read what happens and install', icon: Icons.download, onTap: _update),
      SizedBox(
        height: 128,
        child: Row(children: [
          Expanded(child: _PeopleTile(s)),
          const SizedBox(width: 10),
          Expanded(child: _FollowTile(s)),
        ]),
      ),
      if (d != null)
        Row(children: [
          Expanded(child: _SafetyTile(d)),
          const SizedBox(width: 10),
          _PauseTile(onTap: _pause),
        ]),
      if (note != null) CxNotice(note!),
    ]);
  }
}

class _BatteryTab extends StatelessWidget {
  const _BatteryTab({required this.percent, required this.word, required this.warn, required this.status});
  final int percent;
  final String word;
  final bool warn;
  final String status;
  @override
  Widget build(BuildContext context) => Semantics(
        label: 'Battery $percent percent. $word',
        value: '$percent',
        excludeSemantics: true,
        child: Stack(alignment: Alignment.bottomLeft, children: [
          Positioned(left: 0, right: 0, bottom: 0, child: Container(height: 6, decoration: const BoxDecoration(color: Color(0xFF1B241C), borderRadius: BorderRadius.vertical(top: Radius.circular(4))))),
          FractionallySizedBox(
            widthFactor: (percent.clamp(0, 100)) / 100,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(crossAxisAlignment: CrossAxisAlignment.end, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                  Flexible(
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Row(children: [
                        const Icon(Icons.usb, size: 18, color: Cx.accent),
                        const SizedBox(width: 9),
                        Flexible(child: Text(word.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: Cx.label.copyWith(color: warn ? Cx.danger : Cx.faint))),
                      ]),
                    ),
                  ),
                  Text.rich(
                    TextSpan(children: [
                      TextSpan(text: '$percent', style: const TextStyle(fontFamily: 'Anton', fontSize: 40, height: 1, letterSpacing: .8, color: Cx.accent)),
                      const TextSpan(text: '%', style: TextStyle(fontFamily: 'Anton', fontSize: 20, height: 1, color: Cx.accent)),
                    ]),
                    strutStyle: const StrutStyle(fontFamily: 'Anton', fontSize: 40, height: 1, forceStrutHeight: true),
                  ),
                ]),
              ),
              Container(height: 6, decoration: const BoxDecoration(color: Cx.accent, borderRadius: BorderRadius.vertical(top: Radius.circular(4)))),
            ]),
          ),
        ]),
      );
}

class _WideTile extends StatelessWidget {
  const _WideTile({required this.title, required this.sub, required this.icon, required this.onTap, this.bad = false});
  final String title, sub;
  final IconData icon;
  final VoidCallback onTap;
  final bool bad;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: '$title. $sub',
        excludeSemantics: true,
        child: GestureDetector(
          onTap: onTap,
          child: Container(
            height: 76,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: BoxDecoration(
                color: bad ? Cx.surface : Cx.accent,
                borderRadius: BorderRadius.circular(Cx.tileRadius),
                border: bad ? Border.all(color: Cx.dangerLine, width: 1.5) : null),
            child: Row(children: [
              Expanded(
                child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: 'Anton', fontSize: bad ? 26 : 28, height: 1, letterSpacing: .8, color: bad ? Cx.danger : Cx.ground)),
                  const SizedBox(height: 5),
                  Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, fontWeight: FontWeight.w500, color: bad ? Cx.muted : Cx.ground)),
                ]),
              ),
              const SizedBox(width: 14),
              Container(width: 44, height: 44, decoration: BoxDecoration(color: bad ? Cx.danger : Cx.ground, borderRadius: BorderRadius.circular(14)), child: Icon(icon, size: 22, color: bad ? Cx.ground : Cx.accent)),
            ]),
          ),
        ),
      );
}

class _GoTile extends StatelessWidget {
  const _GoTile({required this.label, required this.onTap, required this.child});
  final String label;
  final VoidCallback onTap;
  final Widget child;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: label,
        excludeSemantics: true,
        child: GestureDetector(
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            clipBehavior: Clip.hardEdge,
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
            child: Stack(children: [
              Positioned.fill(child: child),
              Positioned(
                top: -2,
                right: -4,
                child: Container(
                    width: 30,
                    height: 30,
                    decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Cx.outline, width: 1.5)),
                    child: const Icon(Icons.north_east, size: 14, color: Cx.faint)),
              ),
            ]),
          ),
        ),
      );
}

class _PeopleTile extends StatelessWidget {
  const _PeopleTile(this.s);
  final Session s;
  @override
  Widget build(BuildContext context) {
    final people = s.links.owned.where((c) => c.state == 'active').toList();
    final n = people.length;
    return _GoTile(
      label: 'My people, $n',
      onTap: () => ShellNav.go(AppTab.people, context),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        const Text('MY PEOPLE', style: TextStyle(fontFamily: 'JetBrainsMono', fontSize: 12, height: 1.0, letterSpacing: 1.7, color: Cx.faint)),
        Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(n.toString().padLeft(2, '0'), style: const TextStyle(fontFamily: 'Anton', fontSize: 44, height: .95, letterSpacing: .9, color: Cx.text)),
          const SizedBox(height: 6),
          SizedBox(
            height: 28,
            child: Stack(children: [
              for (var i = 0; i < math.min(n, 3); i++)
                Positioned(
                  left: i * 20.0,
                  child: Container(
                    width: 28,
                    height: 28,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(shape: BoxShape.circle, color: i == 0 ? Cx.chipFill : const Color(0xFF34463A), border: Border.all(color: Cx.surface, width: 2)),
                    child: Text(initials(people[i].label), style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 11, fontWeight: FontWeight.w700, color: Cx.text)),
                  ),
                ),
            ]),
          ),
        ]),
      ]),
    );
  }
}

class _FollowTile extends StatelessWidget {
  const _FollowTile(this.s);
  final Session s;
  @override
  Widget build(BuildContext context) {
    final f = s.links.watching.isEmpty ? null : s.links.watching.first;
    return _GoTile(
      label: f == null ? 'Where I am' : 'Following ${f.ownerEmail}',
      onTap: () => f == null ? push(context, const MyMapScreen()) : ShellNav.go(AppTab.following, context),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(f == null ? 'WHERE I AM' : 'FOLLOWING', style: const TextStyle(fontFamily: 'JetBrainsMono', fontSize: 12, height: 1.0, letterSpacing: 1.7, color: Cx.faint)),
        const Icon(Icons.place_outlined, size: 26, color: Cx.accent),
        Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(f == null ? 'My location' : f.ownerEmail, maxLines: 1, overflow: TextOverflow.ellipsis, style: Cx.strong),
          Text(f == null ? 'See and share' : 'Where they are', style: Cx.small.copyWith(color: Cx.muted)),
        ]),
      ]),
    );
  }
}

class _SafetyTile extends StatelessWidget {
  const _SafetyTile(this.d);
  final Device d;
  @override
  Widget build(BuildContext context) {
    final ok = d.safety == 'OK';
    final text = switch (d.safety) {
      'OK' => 'Working normally',
      'DEGRADED' => 'Recovered, keep an eye',
      'FAULT' => 'Needs attention',
      _ => 'Not reported yet',
    };
    final color = ok ? Cx.accent : (d.safety == 'FAULT' ? Cx.danger : Cx.faint);
    return Container(
      height: 72,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
      child: Semantics(
        container: true,
        label: 'Safety. $text',
        excludeSemantics: true,
        child: Row(children: [
          Expanded(
            child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('SAFETY', style: Cx.label),
              const SizedBox(height: 5),
              Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: Cx.strong),
            ]),
          ),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            for (final h in const [14.0, 22.0, 30.0, 34.0, 30.0, 22.0, 14.0])
              Container(width: 8, height: h, margin: const EdgeInsets.only(left: 4), decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(2))),
          ]),
        ]),
      ),
    );
  }
}

class _PauseTile extends StatelessWidget {
  const _PauseTile({required this.onTap});
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: 'Pause the assistant',
        excludeSemantics: true,
        child: GestureDetector(
          onTap: onTap,
          child: Container(
            width: 88,
            height: 72,
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
            child: const Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Icon(Icons.pause_circle_outline, size: 24, color: Cx.accent),
              SizedBox(height: 4),
              Text('PAUSE', style: TextStyle(fontFamily: 'JetBrainsMono', fontSize: 12, letterSpacing: 1.7, color: Cx.text)),
            ]),
          ),
        ),
      );
}

/// Where I am. A map needs a tile provider, so this draws the position and offers Open in Maps.
class MyMapScreen extends StatefulWidget {
  const MyMapScreen({super.key});
  @override
  State<MyMapScreen> createState() => _MyMapScreenState();
}

class _MyMapScreenState extends State<MyMapScreen> {
  Point? p;
  String? msg;
  bool busy = false;

  Future<void> _locate() async {
    setState(() {
      busy = true;
      msg = null;
    });
    final s = SessionScope.of(context);
    final got = await s.services.location.current();
    if (!mounted) return;
    if (got == null) {
      setState(() {
        busy = false;
        msg = 'Location is off or not allowed. Turn it on in your phone settings, then try again.';
      });
      return;
    }
    try {
      await s.api.putLocation(s.token!, got.lat, got.lon, got.accuracy);
      if (mounted) msg = 'Shared with the people you allowed.';
    } on ApiException catch (e) {
      if (mounted) msg = e.message;
    }
    if (mounted) setState(() {
      p = got;
      busy = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final sharing = s.links.owned.where((c) => c.state == 'active' && c.location).toList();
    return Scaffold(
      body: Stack(children: [
        Positioned(top: 0, left: 0, right: 0, height: 520, child: Semantics(label: 'Map placeholder showing your position', image: true, child: CustomPaint(painter: _MapPainter(found: p != null)))),
        Positioned(
          top: math.max(MediaQuery.of(context).padding.top, 28),
          left: Cx.margin,
          right: Cx.margin,
          child: const Row(children: [CxBack()]),
        ),
        Positioned(
          left: 8,
          right: 8,
          bottom: 8 + MediaQuery.of(context).padding.bottom,
          child: Container(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
            decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(32), border: Border.all(color: Cx.line)),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(p == null ? 'YOU · NOT FOUND YET' : 'YOU · UPDATED NOW', style: Cx.label),
              const SizedBox(height: 6),
              Semantics(
                liveRegion: true,
                child: Text(p == null ? 'WHERE I AM' : '${p!.lat.toStringAsFixed(4)}, ${p!.lon.toStringAsFixed(4)}', style: const TextStyle(fontFamily: 'Anton', fontSize: 28, height: 1, letterSpacing: .84, color: Cx.text)),
              ),
              const SizedBox(height: 14),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                decoration: BoxDecoration(color: Cx.ground, borderRadius: BorderRadius.circular(22)),
                child: Row(children: [
                  SizedBox(
                    width: 34.0 + math.max(0, math.min(sharing.length, 3) - 1) * 24,
                    height: 34,
                    child: Stack(children: [
                      for (var i = 0; i < math.min(sharing.length, 3); i++)
                        Positioned(
                          left: i * 24.0,
                          child: Container(
                            width: 34,
                            height: 34,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(shape: BoxShape.circle, color: i == 0 ? Cx.accent : const Color(0xFF34463A), border: Border.all(color: Cx.ground, width: 2)),
                            child: Text(initials(sharing[i].label), style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 12, fontWeight: FontWeight.w700, color: i == 0 ? Cx.ground : Cx.text)),
                          ),
                        ),
                    ]),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(sharing.isEmpty ? 'Nobody can see this' : '${sharing.length} ${sharing.length == 1 ? 'person' : 'people'} can see this', style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, fontWeight: FontWeight.w600, color: Cx.text)),
                      if (sharing.isNotEmpty) Text(sharing.map((c) => c.label).join(', '), maxLines: 1, overflow: TextOverflow.ellipsis, style: Cx.small),
                    ]),
                  ),
                  Semantics(
                    button: true,
                    label: 'Manage who can see my location',
                    excludeSemantics: true,
                    child: GestureDetector(
                        onTap: () => ShellNav.go(AppTab.people, context),
                        child: const SizedBox(height: 44, child: Center(child: Text('Manage', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, fontWeight: FontWeight.w600, color: Cx.accent))))),
                  ),
                ]),
              ),
              if (msg != null) ...[const SizedBox(height: 12), CxNotice(msg!)],
              const SizedBox(height: 14),
              CxButton(p == null ? 'Find and share my location' : 'Update and share', onTap: _locate, busy: busy, icon: Icons.near_me_outlined),
              const SizedBox(height: 10),
              CxButton('Say where I am',
                  outline: true,
                  onTap: () => s.services.speaker.say(p == null
                      ? 'I have not found your position yet. Press Find and share my location first.'
                      : 'Your position is found, accurate to about ${p!.accuracy.round()} metres. ${sharing.isEmpty ? 'Nobody can see it.' : '${sharing.length} people can see it.'}')),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: CxButton('Open in Maps', outline: true, onTap: p == null ? null : () => s.services.opener.open(Uri.parse('https://maps.google.com/?q=${p!.lat},${p!.lon}')))),
                const SizedBox(width: 10),
                Expanded(child: CxButton('Clear history', outline: true, onTap: () => push(context, const PrivacyScreen(owner: true)))),
              ]),
            ]),
          ),
        ),
      ]),
    );
  }
}

class _MapPainter extends CustomPainter {
  const _MapPainter({required this.found});
  final bool found;
  @override
  void paint(Canvas c, Size s) {
    c.drawRect(Offset.zero & s, Paint()..color = const Color(0xFF0F130F));
    final road = Paint()..color = const Color(0xFF1A221B)..strokeWidth = 16..strokeCap = StrokeCap.round..style = PaintingStyle.stroke;
    final lane = Paint()..color = const Color(0xFF141B15)..strokeWidth = 6..strokeCap = StrokeCap.round..style = PaintingStyle.stroke;
    for (final y in [120.0, 260.0, 400.0]) {
      c.drawLine(Offset(-10, y), Offset(s.width + 10, y + 30), road);
    }
    for (final x in [70.0, 210.0, 330.0]) {
      c.drawLine(Offset(x, -10), Offset(x - 40, s.height + 10), road);
    }
    for (final y in [60.0, 190.0, 330.0, 460.0]) {
      c.drawLine(Offset(-10, y), Offset(s.width + 10, y - 20), lane);
    }
    if (found) {
      c.drawCircle(const Offset(215, 285), 34, Paint()..color = Cx.accent.withValues(alpha: .16));
      c.drawCircle(const Offset(215, 285), 13, Paint()..color = Cx.accent);
      c.drawCircle(const Offset(215, 285), 13, Paint()..color = Cx.ground..style = PaintingStyle.stroke..strokeWidth = 4);
    }
  }

  @override
  bool shouldRepaint(covariant _MapPainter old) => old.found != found;
}

/// "Share your internet": steps for iPhone or Android and a test. Used on its own and inside helper mode.
class InternetBody extends StatefulWidget {
  const InternetBody({super.key, this.onContinue});
  final VoidCallback? onContinue; // set in helper mode: "Setting up? Continue to step 4"
  @override
  State<InternetBody> createState() => _InternetBodyState();
}

class _InternetBodyState extends State<InternetBody> {
  bool android = false;
  LinkState st = LinkState.cableOut;
  bool? reachable;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final l = await SessionScope.of(context).services.link.state();
      if (mounted) setState(() => st = l);
    });
  }

  Future<void> _test() async {
    setState(() {
      busy = true;
      reachable = null;
    });
    final link = SessionScope.of(context).services.link;
    final now = await link.state();
    final ok = now == LinkState.cableOut ? false : await link.internetFromBox();
    if (mounted) setState(() {
      st = now;
      reachable = ok;
      busy = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final cable = st != LinkState.cableOut;
    final steps = android
        ? [('Open Settings, then Network, then Hotspot and tethering', 'On your Android phone'), ('Turn on USB tethering', 'Allow it if the phone asks')]
        : [('Open Settings, then Personal Hotspot', 'On your iPhone'), ('Turn on Allow Others to Join', 'Tap Trust if the phone asks')];
    final status = reachable == null ? (cable ? 'Not tested yet' : 'Cable not plugged in') : (reachable! ? 'Reachable' : 'Not reachable yet');
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        padding: const EdgeInsets.all(4),
        decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(26)),
        child: Row(children: [
          for (final e in const {false: 'iPhone', true: 'Android'}.entries)
            Expanded(
              child: Semantics(
                button: true,
                selected: android == e.key,
                label: '${e.value}${android == e.key ? ', current' : ''}',
                excludeSemantics: true,
                child: GestureDetector(
                  onTap: () => setState(() => android = e.key),
                  child: Container(
                    height: 44,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(color: android == e.key ? Cx.accent : Colors.transparent, borderRadius: BorderRadius.circular(22)),
                    child: Text(e.value, style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, fontWeight: FontWeight.w700, color: android == e.key ? Cx.ground : Cx.faint)),
                  ),
                ),
              ),
            ),
        ]),
      ),
      const SizedBox(height: 14),
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
        child: Column(children: [
          CxStep(1, 'Cable plugged in', cable ? 'Pocket box found on the USB-C port' : 'Plug the pocket box into this phone', state: cable ? 'done' : 'now'),
          const SizedBox(height: 8),
          CxStep(2, steps[0].$1, steps[0].$2, state: cable ? 'now' : 'todo'),
          const SizedBox(height: 8),
          CxStep(3, steps[1].$1, steps[1].$2),
        ]),
      ),
      const SizedBox(height: 14),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('CHECK FROM THE GLASSES', style: Cx.label),
        const SizedBox(height: 10),
        Semantics(
          liveRegion: true,
          child: Row(children: [
            ExcludeSemantics(child: Container(width: 12, height: 12, decoration: BoxDecoration(shape: BoxShape.circle, color: reachable == true ? Cx.accent : Cx.danger))),
            const SizedBox(width: 10),
            Text(status, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text)),
          ]),
        ),
        const SizedBox(height: 10),
        SizedBox(height: 48, child: CxButton('Test now', onTap: _test, busy: busy, small: true)),
      ])),
      if (widget.onContinue != null) CxYellowLink('Setting up? Continue to step 4', center: false, onTap: widget.onContinue!),
      const Padding(padding: EdgeInsets.fromLTRB(8, 4, 8, 0), child: Text('Uses your mobile data and some phone battery. Obstacle warnings keep working without internet.', style: Cx.small)),
    ]);
  }
}

class InternetScreen extends StatelessWidget {
  const InternetScreen({super.key});
  @override
  Widget build(BuildContext context) => const CxScreen(children: [
        CxTop(title: 'Share internet'),
        SizedBox(height: 2),
        CxTitle('Share your\ninternet'),
        CxText('The glasses use this phone\'s internet through the USB cable.'),
        InternetBody(),
      ]);
}

class UpdateScreen extends StatefulWidget {
  const UpdateScreen({super.key, required this.device});
  final Device device;
  @override
  State<UpdateScreen> createState() => _UpdateScreenState();
}

class _UpdateScreenState extends State<UpdateScreen> {
  bool loading = true;
  Map<String, dynamic>? offer;
  String? msg;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _check());
  }

  Future<void> _check() async {
    final s = SessionScope.of(context);
    try {
      final o = await s.api.updateOffer(s.token!, widget.device.id);
      if (mounted) setState(() {
        offer = o;
        loading = false;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() {
        msg = e.message;
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(title: 'Software update'),
        CxTitle(offer == null ? 'Software\nupdate' : 'Update\nready', size: 52, height: .98),
        if (loading)
          const CxText('Checking for updates')
        else if (offer == null && msg == null)
          CxText('You are up to date${widget.device.firmware.isEmpty ? '' : ' on version ${widget.device.firmware}'}.')
        else if (offer != null)
          const CxText('A new version is ready for your pocket box.'),
        if (msg != null) CxNotice(msg!),
      ], bottom: [
        if (offer != null)
          CxButton('Install update', onTap: () async {
            final nav = Navigator.of(context);
            final ok = await confirmSheet(context,
                mono: 'Software update',
                title: 'Install the update?',
                bodyWidget: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  CxBullet(Text('Takes about 5 minutes. Keep the cable plugged in.')),
                  SizedBox(height: 12),
                  CxBullet(Text('The assistant is unavailable while it installs. Do not start it while crossing a road.')),
                  SizedBox(height: 12),
                  CxBullet(Text('If anything goes wrong, the glasses go back to the version that worked, and tell you.')),
                ]),
                cancelLabel: 'Not now',
                confirmLabel: 'Install now',
                danger: false);
            if (ok) nav.push(MaterialPageRoute<void>(builder: (_) => UpdateProgressScreen(device: widget.device, offer: offer!)));
          }),
      ]);
}

/// The install in progress. The percentage is only shown when the link reports it.
class UpdateProgressScreen extends StatefulWidget {
  const UpdateProgressScreen({super.key, required this.device, required this.offer});
  final Device device;
  final Map<String, dynamic> offer;
  @override
  State<UpdateProgressScreen> createState() => _UpdateProgressScreenState();
}

class _UpdateProgressScreenState extends State<UpdateProgressScreen> {
  String phase = 'sending'; // sending | sent | failed
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final s = SessionScope.of(context);
      final ok = await s.services.link.installUpdate(widget.offer);
      if (!mounted) return;
      setState(() => phase = ok ? 'sent' : 'failed');
      final id = widget.offer['release_id'] ?? widget.offer['releaseId'];
      if (ok && id is String && s.token != null) {
        try {
          await s.api.reportUpdate(s.token!, widget.device.id, id, 'committed');
        } on ApiException {
          // the box reports its own outcome too
        }
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final failed = phase == 'failed';
    return CxScreen(children: [
      const CxTop(title: 'Software update'),
      CxTitle(failed ? 'Update\nstopped' : 'Updating', size: 52, height: .98),
      Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(color: failed ? Cx.surface : Cx.accent, borderRadius: BorderRadius.circular(Cx.tileRadius)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(failed ? 'COULD NOT REACH THE POCKET BOX' : (phase == 'sent' ? 'SENT TO GLASSES' : 'SENDING TO GLASSES'), style: Cx.label.copyWith(color: failed ? Cx.danger : Cx.ground)),
          const SizedBox(height: 12),
          if (!failed)
            ClipRRect(borderRadius: BorderRadius.circular(4), child: LinearProgressIndicator(minHeight: 8, value: phase == 'sent' ? 1 : null, backgroundColor: const Color(0x330A0A08), color: Cx.ground)),
          const SizedBox(height: 12),
          Text(failed ? 'Plug the pocket box into this phone with the cable and try again.' : 'Keep the cable plugged in.', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, fontWeight: FontWeight.w500, color: failed ? Cx.text : Cx.ground)),
        ]),
      ),
      CxTile(
          child: Column(children: [
        CxStep(1, 'Get the update', 'Checked on your phone', state: failed ? 'now' : 'done'),
        const SizedBox(height: 8),
        CxStep(2, 'Send to glasses', failed ? 'Stopped' : (phase == 'sent' ? 'Done' : 'In progress'), state: failed ? 'todo' : (phase == 'sent' ? 'done' : 'now')),
        const SizedBox(height: 8),
        const CxStep(3, 'Install', 'Starts when the transfer ends'),
        const SizedBox(height: 8),
        const CxStep(4, 'Restart and check', 'The glasses say when they are ready'),
      ])),
      const Padding(padding: EdgeInsets.symmetric(horizontal: 8), child: Text('If anything goes wrong, the glasses go back to the version that worked. You will hear a message and see it here.', style: Cx.small)),
    ], bottom: [
      CxButton(failed ? 'Back to Home' : 'Keep going in the background', outline: true, onTap: () => Navigator.of(context).popUntil((r) => r.isFirst)),
    ]);
  }
}
