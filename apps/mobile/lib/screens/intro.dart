// ignore_for_file: sort_child_properties_last
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../motion.dart';

import '../scope.dart';
import '../theme.dart';
import '../widgets.dart';

class _Step {
  const _Step(this.title, this.body, this.tileLabel, this.tile, this.chips);
  final String title;
  final String body;
  final String tileLabel;
  final Widget tile;
  final Widget chips; // pinned to the foot of the tile
}

/// The four plain-language intro screens shown once per install.
class IntroScreen extends StatefulWidget {
  const IntroScreen({super.key});
  @override
  State<IntroScreen> createState() => _IntroScreenState();
}

class _IntroScreenState extends State<IntroScreen> {
  int i = 0;
  int _dir = 1; // 1 forward, -1 back: which way the steps slide

  void _go(int to) {
    if (to < 0 || to >= _steps.length || to == i) return;
    setState(() {
      _dir = to > i ? 1 : -1;
      i = to;
    });
  }

  static final _steps = <_Step>[
    _Step(
      'Get there\non your own',
      'From your front door to where you are going. Walking routes and buses, told to you one step at a time.',
      'Example: a walking route from home to the hawker centre, 24 minutes, bus 175, spoken',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('YOUR WALK', style: Cx.label),
        SizedBox(height: 6),
        SizedBox(height: 150, width: double.infinity, child: _RouteArt()),
        SizedBox(height: 4),
        _Row('Home', 'Hawker centre'),
      ]),
      const Wrap(spacing: 6, children: [CxChip('24 min', on: true), CxChip('Bus 175'), CxChip('Spoken')]),
    ),
    _Step(
      'Know what\nis ahead',
      'Cortex speaks up about things in your way, like steps or a pole. Warnings work even with no signal, and the speakers leave your ears open to traffic.',
      'Example warnings Cortex speaks',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('WHAT CORTEX TELLS YOU', style: Cx.label),
        SizedBox(height: 8),
        _Say('Something low, straight ahead', at: 0),
        _Say('Stairs going down', at: 1),
        _Say('Person on your left', at: 2),
      ]),
      const Wrap(spacing: 6, children: [CxChip('Works without internet', on: true), CxChip('Ears stay open')]),
    ),
    _Step(
      'Ask about what\nis around you',
      'Just ask. Cortex answers out loud: signs, prices and bus times.',
      'Example question and answer',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('JUST ASK', style: Cx.label),
        SizedBox(height: 14),
        _Chat(),
      ]),
      Wrap(spacing: 6, children: [CxChip('Signs'), CxChip('Prices'), CxChip('Bus times')]),
    ),
    _Step(
      'Family\nclose by',
      'Choose who can see where you are and who can call you. You decide for each person, and can change it any time. Been invited by someone? Use Scan on the next screen.',
      'Example: two people you choose',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('PEOPLE YOU CHOOSE', style: Cx.label),
        SizedBox(height: 12),
        Reveal(delay: Duration(milliseconds: 150), rise: 18, child: _Person('HM', 'Hui Min', ['Sees where you are', 'Can call'], lead: true)),
        Divider(color: Cx.lineC, height: 24),
        Reveal(delay: Duration(milliseconds: 420), rise: 18, child: _Person('UB', 'Uncle Ben', ['Sees where you are', 'No calls'])),
      ]),
      const CxChip('Family never sees your camera'),
    ),
  ];

  Future<void> _done() async {
    await SessionScope.of(context).markIntroSeen();
  }

  /// Swaps [child] when the step changes: the new step slides in from the side you are heading to, the old one
  /// leaves the other way. Only the new one is read by a screen reader.
  Widget _swap(Widget child) => AnimatedSwitcher(
        duration: Motion.of(context, Motion.page),
        switchInCurve: Motion.enter,
        switchOutCurve: Motion.exit,
        layoutBuilder: (cur, prev) => Stack(alignment: Alignment.topLeft, children: [...prev, ?cur]),
        transitionBuilder: (c, a) {
          final incoming = c.key == ValueKey(i);
          final w = SlideTransition(
            position: Tween(begin: Offset((incoming ? .16 : -.16) * _dir, 0), end: Offset.zero).animate(a),
            child: FadeTransition(opacity: a, alwaysIncludeSemantics: incoming, child: c),
          );
          return incoming ? w : ExcludeSemantics(child: IgnorePointer(child: w));
        },
        child: KeyedSubtree(key: ValueKey(i), child: child),
      );

  @override
  Widget build(BuildContext context) {
    final s = _steps[i];
    final last = i == _steps.length - 1;
    return GestureDetector(
      // swipe between steps, like turning pages; the buttons do the same for anyone who cannot swipe
      onHorizontalDragEnd: (d) {
        final v = d.primaryVelocity ?? 0;
        if (v < -250) _go(i + 1);
        if (v > 250) _go(i - 1);
      },
      child: CxScreen(children: [
        CxTop(
          back: i > 0,
          logo: i == 0,
          onBack: () => _go(i - 1),
          trailing: CxLink('Skip', semanticLabel: 'Skip introduction', onTap: _done),
        ),
        _swap(CxTile(
            minHeight: 300,
            semanticLabel: s.tileLabel,
            child: Column(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [s.tile, Reveal(delay: const Duration(milliseconds: 650), child: s.chips)]))),
      ], bottom: [
        CxPager(step: i + 1),
        _swap(Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          CxTitle(s.title),
          const SizedBox(height: 10),
          CxText(s.body),
        ])),
        CxButton(last ? 'Get started' : 'Next', onTap: last ? _done : () => _go(i + 1)),
      ]),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row(this.a, this.b);
  final String a, b;
  @override
  Widget build(BuildContext context) => Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [Text(a, style: Cx.strong), Text(b, style: Cx.strong)]);
}

class _Say extends StatelessWidget {
  const _Say(this.text, {required this.at});
  final String text;
  final int at; // order: each warning arrives after the last, as Cortex would say them
  @override
  Widget build(BuildContext context) {
    final when = Duration(milliseconds: 180 + 300 * at);
    return Reveal(delay: when, rise: 10, child: _line(when));
  }

  Widget _line(Duration when) => Container(
        constraints: const BoxConstraints(minHeight: 56),
        alignment: Alignment.centerLeft,
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: Cx.lineC))),
        child: Row(children: [
          ExcludeSemantics(
            child: PopIn(
              delay: when + const Duration(milliseconds: 60),
              child: Container(
                  width: 34,
                  height: 34,
                  decoration: const BoxDecoration(color: Cx.accent, shape: BoxShape.circle),
                  child: const Icon(Icons.volume_up, size: 18, color: Cx.ground)),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(child: Text(text, style: Cx.strong.copyWith(fontSize: 16, fontWeight: FontWeight.w600))),
        ]),
      );
}

class _Bubble extends StatelessWidget {
  const _Bubble(this.text, {this.me = false, required this.said});
  final String text, said;
  final bool me;
  @override
  Widget build(BuildContext context) => Semantics(
        label: '$said: $text',
        excludeSemantics: true,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 300),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: me ? null : Cx.accent,
            border: me ? Border.all(color: Cx.outlineC, width: 1.5) : null,
            borderRadius: BorderRadius.circular(20),
          ),
          child: Text(text,
              style: TextStyle(
                  fontFamily: 'SpaceGrotesk',
                  fontSize: 16,
                  fontWeight: me ? FontWeight.w500 : FontWeight.w700,
                  color: me ? Cx.text : Cx.ground)),
        ),
      );
}

class _Person extends StatelessWidget {
  const _Person(this.initials, this.name, this.chips, {this.lead = false});
  final String initials, name;
  final List<String> chips;
  final bool lead;
  @override
  Widget build(BuildContext context) => Row(children: [
        ExcludeSemantics(
          child: CircleAvatar(
              radius: 24,
              backgroundColor: lead ? Cx.accent : const Color(0xFF34463A),
              child: Text(initials,
                  style: TextStyle(fontWeight: FontWeight.w700, color: lead ? Cx.ground : Cx.text))),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: Cx.strong),
            const SizedBox(height: 6),
            Wrap(spacing: 6, runSpacing: 6, children: [
              for (var k = 0; k < chips.length; k++) CxChip(chips[k], on: k == 0),
            ]),
          ]),
        ),
      ]);
}

/// The question, Cortex "thinking" (three dots), then the answer. Both bubbles are always in the semantics tree, so a
/// screen reader reads the whole exchange at once instead of waiting for the animation.
class _Chat extends StatefulWidget {
  const _Chat();
  @override
  State<_Chat> createState() => _ChatState();
}

class _ChatState extends State<_Chat> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2300));
  bool _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    Motion.off(context) ? _c.value = 1 : _c.forward();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  double _span(double a, double b) => Motion.enter.transform(((_c.value - a) / (b - a)).clamp(0.0, 1.0));

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          final ask = _span(.02, .2), dots = _c.value > .24 && _c.value < .64, answer = _span(.62, .8);
          return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Align(
              alignment: Alignment.centerRight,
              child: _Rise(t: ask, child: const _Bubble('"Hey Cortex, when is my bus?"', me: true, said: 'You say')),
            ),
            const SizedBox(height: 12),
            Stack(children: [
              Align(
                alignment: Alignment.centerLeft,
                child: _Rise(t: answer, child: const _Bubble('Bus 175 comes in 3 minutes.', said: 'Cortex says')),
              ),
              if (dots) Positioned(left: 0, top: 0, child: ExcludeSemantics(child: _Dots(phase: (_c.value - .24) / .4))),
            ]),
          ]);
        },
      );
}

class _Rise extends StatelessWidget {
  const _Rise({required this.t, required this.child});
  final double t;
  final Widget child;
  @override
  Widget build(BuildContext context) => Opacity(
        opacity: t,
        alwaysIncludeSemantics: true,
        child: Transform.translate(offset: Offset(0, 12 * (1 - t)), child: Transform.scale(scale: .92 + .08 * t, child: child)),
      );
}

/// Three dots bouncing one after another, in a bubble like Cortex's.
class _Dots extends StatelessWidget {
  const _Dots({required this.phase});
  final double phase; // 0..1 over the thinking time
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 17),
        decoration: BoxDecoration(color: Cx.accent.withValues(alpha: .9), borderRadius: BorderRadius.circular(20)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          for (var k = 0; k < 3; k++)
            Transform.translate(
              offset: Offset(0, -4 * math.max(0, math.sin((phase * 3 - k * .18) * 2 * math.pi))),
              child: Container(
                margin: EdgeInsets.only(right: k < 2 ? 5 : 0),
                width: 7,
                height: 7,
                decoration: const BoxDecoration(color: Cx.ground, shape: BoxShape.circle),
              ),
            ),
        ]),
      );
}

/// The walk from home to the hawker centre draws itself: home appears, the dotted route runs out to the destination,
/// the pin drops and sends out one ring.
class _RouteArt extends StatefulWidget {
  const _RouteArt();
  @override
  State<_RouteArt> createState() => _RouteArtState();
}

class _RouteArtState extends State<_RouteArt> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1900));
  bool _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    Motion.off(context) ? _c.value = 1 : _c.forward();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CustomPaint(painter: _RoutePainter(_c));
}

class _RoutePainter extends CustomPainter {
  _RoutePainter(this.t) : super(repaint: t);
  final Animation<double> t;

  double _span(double a, double b, [Curve c = Curves.easeOutCubic]) => c.transform(((t.value - a) / (b - a)).clamp(0.0, 1.0));

  @override
  void paint(Canvas c, Size s) {
    final sx = s.width / 340, sy = s.height / 150;
    Offset p(double x, double y) => Offset(x * sx, y * sy);
    final path = Path()
      ..moveTo(26 * sx, 118 * sy)
      ..cubicTo(70 * sx, 118 * sy, 80 * sx, 70 * sy, 140 * sx, 76 * sy)
      ..cubicTo(190 * sx, 80 * sy, 230 * sx, 104 * sy, 296 * sx, 34 * sy);
    final dot = Paint()..color = Cx.accent;
    final home = _span(0, .14, Curves.easeOutBack);
    if (home > 0) c.drawRect(Rect.fromCenter(center: p(26, 118), width: 24 * home, height: 24 * home), dot);
    final run = _span(.08, .7, Curves.easeInOutCubic);
    for (final m in path.computeMetrics()) {
      final end = m.length * run;
      for (double d = 0; d <= end; d += 9) {
        c.drawCircle(m.getTangentForOffset(d)!.position, 1.8, dot);
      }
    }
    final pin = _span(.66, .8, Curves.easeOutBack);
    if (pin > 0) {
      c.drawCircle(p(296, 34), 16 * pin, Paint()..color = Cx.accent.withValues(alpha: .2));
      c.drawCircle(p(296, 34), 8 * pin, dot);
    }
    final ring = _span(.74, 1);
    if (ring > 0 && ring < 1) {
      c.drawCircle(p(296, 34), 10 + 22 * ring,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2
            ..color = Cx.accent.withValues(alpha: .6 * (1 - ring)));
    }
  }

  @override
  bool shouldRepaint(covariant _RoutePainter old) => old.t != t;
}
