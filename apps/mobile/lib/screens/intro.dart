// ignore_for_file: sort_child_properties_last
import 'package:flutter/material.dart';

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

  static final _steps = <_Step>[
    _Step(
      'Get there\non your own',
      'From your front door to where you are going. Walking routes and buses, told to you one step at a time.',
      'Example: a walking route from home to the hawker centre, 24 minutes, bus 175, spoken',
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('YOUR WALK', style: Cx.label),
        SizedBox(height: 6),
        SizedBox(height: 150, width: double.infinity, child: CustomPaint(painter: _RoutePainter())),
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
        _Say('Something low, straight ahead'),
        _Say('Stairs going down'),
        _Say('Person on your left'),
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
        Align(
            alignment: Alignment.centerRight,
            child: _Bubble('"Hey Cortex, when is my bus?"', me: true, said: 'You say')),
        SizedBox(height: 12),
        Align(
            alignment: Alignment.centerLeft,
            child: _Bubble('Bus 175 comes in 3 minutes.', said: 'Cortex says')),
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
        _Person('HM', 'Hui Min', ['Sees where you are', 'Can call'], lead: true),
        Divider(color: Cx.lineC, height: 24),
        _Person('UB', 'Uncle Ben', ['Sees where you are', 'No calls']),
      ]),
      const CxChip('Family never sees your camera'),
    ),
  ];

  Future<void> _done() async {
    await SessionScope.of(context).markIntroSeen();
  }

  @override
  Widget build(BuildContext context) {
    final s = _steps[i];
    final last = i == _steps.length - 1;
    return CxScreen(children: [
      CxTop(
        back: i > 0,
        logo: i == 0,
        onBack: () => setState(() => i--),
        trailing: CxLink('Skip', semanticLabel: 'Skip introduction', onTap: _done),
      ),
      CxTile(
          minHeight: 300,
          semanticLabel: s.tileLabel,
          child: Column(mainAxisAlignment: MainAxisAlignment.spaceBetween, crossAxisAlignment: CrossAxisAlignment.start, children: [s.tile, s.chips])),
    ], bottom: [
      CxPager(step: i + 1),
      CxTitle(s.title),
      CxText(s.body),
      CxButton(last ? 'Get started' : 'Next', onTap: last ? _done : () => setState(() => i++)),
    ]);
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
  const _Say(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Container(
        constraints: const BoxConstraints(minHeight: 56),
        alignment: Alignment.centerLeft,
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: Cx.lineC))),
        child: Row(children: [
          ExcludeSemantics(
            child: Container(
                width: 34,
                height: 34,
                decoration: const BoxDecoration(color: Cx.accent, shape: BoxShape.circle),
                child: const Icon(Icons.volume_up, size: 18, color: Cx.ground)),
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

/// Dotted route from home to the destination, as in the mockup.
class _RoutePainter extends CustomPainter {
  const _RoutePainter();
  @override
  void paint(Canvas c, Size s) {
    final sx = s.width / 340, sy = s.height / 150;
    Offset p(double x, double y) => Offset(x * sx, y * sy);
    final path = Path()
      ..moveTo(26 * sx, 118 * sy)
      ..cubicTo(70 * sx, 118 * sy, 80 * sx, 70 * sy, 140 * sx, 76 * sy)
      ..cubicTo(190 * sx, 80 * sy, 230 * sx, 104 * sy, 296 * sx, 34 * sy);
    final dot = Paint()..color = Cx.accent;
    for (final m in path.computeMetrics()) {
      for (double d = 0; d < m.length; d += 9) {
        c.drawCircle(m.getTangentForOffset(d)!.position, 1.8, dot);
      }
    }
    c.drawRect(Rect.fromCenter(center: p(26, 118), width: 24, height: 24), dot);
    c.drawCircle(p(296, 34), 16, Paint()..color = Cx.accent.withValues(alpha: .2));
    c.drawCircle(p(296, 34), 8, dot);
  }

  @override
  bool shouldRepaint(covariant CustomPainter old) => false;
}
