import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'theme.dart';

/// Screen shell: 14px side margin, dark ground, safe area. [bottom] is pinned
/// to the foot of the screen when the content is short, and scrolls with it when not.
class CxScreen extends StatelessWidget {
  const CxScreen({super.key, required this.children, this.bottom = const [], this.tab = false, this.gap = 14});
  final double gap;
  final List<Widget> children;
  final List<Widget> bottom;

  /// True on a main tab, which leaves room for the floating nav bar.
  final bool tab;

  List<Widget> _gap(List<Widget> l) => [for (var i = 0; i < l.length; i++) ...[l[i], if (i < l.length - 1 && l[i] is! CxSpace) SizedBox(height: gap)]];
  List<Widget> _bot(List<Widget> l) => [for (var i = 0; i < l.length; i++) ...[l[i], if (i < l.length - 1) const SizedBox(height: 10)]];

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          top: false,
          bottom: false,
          child: LayoutBuilder(
            builder: (context, box) {
              final top = math.max(MediaQuery.of(context).padding.top, 28.0);
              final bottomInset = MediaQuery.of(context).padding.bottom;
              final padBottom = tab ? 100.0 + bottomInset : math.max(24.0, bottomInset + 16);
              return SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(Cx.margin, top, Cx.margin, padBottom),
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: box.maxHeight - top - padBottom),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _gap(children)),
                    if (bottom.isNotEmpty)
                      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _bot(bottom)),
                  ],
                ),
              ),
            );
            },
          ),
        ),
      );
}

class CxLogo extends StatelessWidget {
  const CxLogo({super.key, this.size = 44});
  final double size;
  @override
  Widget build(BuildContext context) => ExcludeSemantics(
        child: SizedBox(width: size, height: size, child: CustomPaint(painter: _LogoPainter())),
      );
}

class _LogoPainter extends CustomPainter {
  @override
  void paint(Canvas c, Size s) {
    final u = s.width / 100;
    c.drawRect(Offset.zero & s, Paint()..color = Cx.accent);
    final p = Paint()..color = Colors.black;
    for (final r in const [
      [20, 20, 20, 40], [20, 70, 20, 10], [60, 40, 20, 40], [60, 20, 20, 10], [40, 40, 20, 20]
    ]) {
      c.drawRect(Rect.fromLTWH(r[0] * u, r[1] * u, r[2] * u, r[3] * u), p);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter old) => false;
}

class CxBack extends StatelessWidget {
  const CxBack({super.key, this.onTap});
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: 'Back',
        excludeSemantics: true,
        child: GestureDetector(
          onTap: onTap ?? () => Navigator.of(context).maybePop(),
          child: Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(color: Cx.surface, shape: BoxShape.circle, border: Border.all(color: Cx.outlineC, width: 1.5)),
            child: const CustomPaint(painter: _Chevron()),
          ),
        ),
      );
}

class _Chevron extends CustomPainter {
  const _Chevron();
  @override
  void paint(Canvas c, Size s) {
    final p = Paint()
      ..color = Cx.text
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final u = s.width / 44;
    c.drawPath(Path()..moveTo(25 * u, 16 * u)..lineTo(18 * u, 22 * u)..lineTo(25 * u, 28 * u), p);
  }

  @override
  bool shouldRepaint(covariant CustomPainter old) => false;
}

/// Top row: back button (or logo), a mono label, and anything on the right.
class CxTop extends StatelessWidget {
  const CxTop({super.key, this.back = true, this.onBack, this.title, this.trailing, this.logo = false, this.lead});
  final bool back;
  final VoidCallback? onBack;
  final String? title;
  final Widget? trailing;
  final bool logo;
  final Widget? lead;
  @override
  Widget build(BuildContext context) => ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 48),
        child: Row(children: [
          if (back) CxBack(onTap: onBack),
          if (back && logo) const SizedBox(width: 12),
          if (logo) const CxLogo(),
          Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: lead ?? (title == null ? null : Padding(padding: EdgeInsets.only(left: back || logo ? 12 : 0), child: Text(title!.toUpperCase(), style: Cx.label))),
            ),
          ),
          ?trailing,
        ]),
      );
}

class CxTitle extends StatelessWidget {
  const CxTitle(this.text, {super.key, this.size = 44, this.height = 1.0});
  final String text;
  final double size;
  final double height;
  @override
  Widget build(BuildContext context) => Semantics(
      header: true,
      child: Text(text.toUpperCase(), style: Cx.display.copyWith(fontSize: size, height: height, letterSpacing: size * 0.03)));
}

class CxText extends StatelessWidget {
  const CxText(this.text, {super.key, this.small = false, this.color});
  final String text;
  final bool small;
  final Color? color;
  @override
  Widget build(BuildContext context) =>
      Text(text, style: (small ? Cx.small : Cx.body).copyWith(color: color));
}

class CxButton extends StatelessWidget {
  const CxButton(this.label, {super.key, required this.onTap, this.outline = false, this.busy = false, this.danger = false, this.icon, this.small = false});
  final IconData? icon;
  final bool small;
  final String label;
  final VoidCallback? onTap;
  final bool outline;
  final bool danger;
  final bool busy;
  @override
  Widget build(BuildContext context) {
    final fg = outline ? (danger ? Cx.danger : Cx.text) : Cx.ground;
    return Semantics(
      button: true,
      enabled: onTap != null && !busy,
      label: busy ? '$label, working' : label,
      excludeSemantics: true,
      child: GestureDetector(
        onTap: busy ? null : onTap,
        child: Container(
          height: small ? 48 : 56,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: outline ? Colors.transparent : (onTap == null ? Cx.outlineC : Cx.accent),
            borderRadius: BorderRadius.circular(28),
            border: outline ? Border.all(color: danger ? Cx.dangerLine : Cx.outlineC, width: 1.5) : null,
          ),
          child: busy
              ? SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2.5, color: fg))
              : Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  if (icon != null) ...[Icon(icon, size: 20, color: fg), const SizedBox(width: 8)],
                  Text(label, style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: small ? 16 : 17, fontWeight: FontWeight.w700, color: fg)),
                ]),
        ),
      ),
    );
  }
}

class CxChip extends StatelessWidget {
  const CxChip(this.label, {super.key, this.on = false});
  final String label;
  final bool on;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: on ? Cx.accent : Cx.chipFill, borderRadius: BorderRadius.circular(99)),
        child: Text(label,
            style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 12, fontWeight: FontWeight.w700, color: on ? Cx.ground : Cx.text)),
      );
}

class CxTile extends StatelessWidget {
  const CxTile({super.key, required this.child, this.minHeight = 0, this.semanticLabel});
  final Widget child;
  final double minHeight;
  final String? semanticLabel;
  @override
  Widget build(BuildContext context) {
    final box = Container(
      constraints: BoxConstraints(minHeight: minHeight),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
      child: child,
    );
    return semanticLabel == null ? box : Semantics(container: true, label: semanticLabel, child: box);
  }
}

class CxField extends StatelessWidget {
  const CxField({
    super.key,
    required this.label,
    required this.controller,
    this.hint,
    this.obscure = false,
    this.keyboard,
    this.error,
    this.autofill,
    this.help,
    this.onSubmit,
    this.lines = 1,
    this.code = false,
  });
  final String label;
  final TextEditingController controller;
  final String? hint;
  final bool obscure;
  final TextInputType? keyboard;
  final String? error;
  final String? help;
  final Iterable<String>? autofill;
  final VoidCallback? onSubmit;
  final int lines;
  final bool code;

  @override
  Widget build(BuildContext context) {
    final multi = lines > 1;
    final border = error == null ? Cx.lineC : Cx.danger;
    OutlineInputBorder ob(Color c, double w) => OutlineInputBorder(
        borderRadius: BorderRadius.circular(multi ? 22 : (code ? 32 : 26)), borderSide: BorderSide(color: c, width: w));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(padding: const EdgeInsets.only(left: 8, bottom: 8), child: Text(label.toUpperCase(), style: Cx.label)),
      SizedBox(
        height: multi ? null : (code ? 64 : 52),
        child: TextField(
          controller: controller,
          obscureText: obscure,
          keyboardType: multi ? TextInputType.multiline : keyboard,
          minLines: multi ? lines : null,
          maxLines: multi ? lines : 1,
          expands: false,
          textAlign: code ? TextAlign.center : TextAlign.start,
          autofillHints: autofill,
          textCapitalization: code ? TextCapitalization.characters : TextCapitalization.none,
          onSubmitted: onSubmit == null ? null : (_) => onSubmit!(),
          style: code
              ? const TextStyle(fontFamily: 'JetBrainsMono', fontSize: 24, letterSpacing: 4.8, color: Cx.accent, fontWeight: FontWeight.w500)
              : const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, color: Cx.text, fontWeight: FontWeight.w500),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: TextStyle(color: Cx.faintC, letterSpacing: code ? 4.8 : 0),
            contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: multi ? 16 : 0),
            filled: true,
            fillColor: Cx.surface,
            isCollapsed: false,
            enabledBorder: ob(border, 1.5),
            focusedBorder: ob(error == null ? Cx.accent : Cx.danger, 2),
          ),
        ),
      ),
      if (error != null)
        Padding(
            padding: const EdgeInsets.only(left: 8, top: 8),
            child: Semantics(liveRegion: true, child: Text(error!, style: Cx.small.copyWith(color: Cx.danger)))),
      if (help != null && error == null) Padding(padding: const EdgeInsets.only(left: 8, top: 8), child: Text(help!, style: Cx.small)),
    ]);
  }
}

/// A real checkbox, 26px, yellow when on.
class CxCheck extends StatelessWidget {
  const CxCheck({super.key, required this.value, required this.onChanged, required this.label});
  final bool value;
  final ValueChanged<bool> onChanged;
  final String label;
  @override
  Widget build(BuildContext context) => Semantics(
        checked: value,
        label: label,
        excludeSemantics: true,
        onTap: () => onChanged(!value),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => onChanged(!value),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(
                width: 26,
                height: 26,
                margin: const EdgeInsets.only(top: 2),
                decoration: BoxDecoration(
                    color: value ? Cx.accent : Colors.white,
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: value ? Cx.accent : Cx.outlineC)),
                child: value ? const Icon(Icons.check, size: 20, color: Cx.ground) : null,
              ),
              const SizedBox(width: 12),
              Expanded(child: Text(label, style: Cx.body.copyWith(fontSize: 14))),
            ]),
          ),
        ),
      );
}

/// Numbered step row: state 'todo' (grey ring), 'now' (yellow ring), 'done' (yellow fill, tick).
class CxStep extends StatelessWidget {
  const CxStep(this.n, this.title, this.sub, {super.key, this.state = 'todo'});
  final int n;
  final String title;
  final String? sub;
  final String state;
  @override
  Widget build(BuildContext context) {
    final done = state == 'done', now = state == 'now';
    return Semantics(
      container: true,
      label: '${done ? 'Done. ' : ''}Step $n. $title${sub == null ? '' : '. $sub'}',
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Container(
            width: 34,
            height: 34,
            alignment: Alignment.center,
            decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: done ? Cx.accent : Colors.transparent,
                border: Border.all(color: done || now ? Cx.accent : Cx.outlineC, width: 1.5)),
            child: done
                ? const Icon(Icons.check, size: 18, color: Cx.ground)
                : Text('$n', style: TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, fontWeight: FontWeight.w700, color: now ? Cx.accent : Cx.faintC)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w600, color: Cx.text)),
              if (sub != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(sub!, style: Cx.small)),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// Pill used in the helper top bar: a yellow capsule or coral text link.
class CxPill extends StatelessWidget {
  const CxPill(this.label, {super.key, this.icon});
  final String label;
  final IconData? icon;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(color: Cx.accent, borderRadius: BorderRadius.circular(99)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 14, color: Cx.ground), const SizedBox(width: 6)],
          Text(label, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 13, fontWeight: FontWeight.w700, color: Cx.ground)),
        ]),
      );
}

class CxPager extends StatelessWidget {
  const CxPager({super.key, required this.step, this.of = 4});
  final int step;
  final int of;
  @override
  Widget build(BuildContext context) => Semantics(
        label: 'Step $step of $of',
        child: ExcludeSemantics(
          child: Row(children: [
            for (var i = 1; i <= of; i++)
              Container(
                margin: const EdgeInsets.only(right: 6),
                height: 6,
                width: i == step ? 28 : 8,
                decoration: BoxDecoration(
                    color: i == step ? Cx.accent : Cx.outlineC, borderRadius: BorderRadius.circular(3)),
              ),
          ]),
        ),
      );
}

/// Text link, 44px high touch target.
class CxLink extends StatelessWidget {
  const CxLink(this.label, {super.key, required this.onTap, this.semanticLabel});
  final String label;
  final String? semanticLabel;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: semanticLabel ?? label,
        excludeSemantics: true,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onTap,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44, minWidth: 44),
            child: Center(
                child: Text(label,
                    style: const TextStyle(
                        fontFamily: 'SpaceGrotesk',
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: Cx.text))),
          ),
        ),
      );
}

/// Extra space on top of the normal gap (the mockups' margin-top). The gap after it is skipped.
class CxSpace extends StatelessWidget {
  const CxSpace(this.h, {super.key});
  final double h;
  @override
  Widget build(BuildContext context) => SizedBox(height: h);
}

/// Section label above a list, e.g. ACCOUNT.
class CxSection extends StatelessWidget {
  const CxSection(this.text, {super.key, this.top = 6});
  final String text;
  final double top;
  @override
  Widget build(BuildContext context) => Padding(padding: EdgeInsets.only(left: 8, top: top), child: Semantics(header: true, child: Text(text.toUpperCase(), style: Cx.label)));
}

/// Slider drawn as in the mockups: 6px track, yellow fill, 26px thumb.
class CxSlider extends StatelessWidget {
  const CxSlider({super.key, required this.label, required this.value, required this.valueText, required this.onChanged, this.steps = 20});
  final String label;
  final double value; // 0..1
  final String valueText;
  final ValueChanged<double> onChanged;
  final int steps;
  @override
  Widget build(BuildContext context) => Semantics(
        slider: true,
        label: label,
        value: valueText,
        increasedValue: valueText,
        decreasedValue: valueText,
        onIncrease: () => onChanged((value + 1 / steps).clamp(0, 1)),
        onDecrease: () => onChanged((value - 1 / steps).clamp(0, 1)),
        excludeSemantics: true,
        child: LayoutBuilder(
          builder: (context, box) {
            final w = box.maxWidth;
            void at(double dx) => onChanged(((dx - 13) / (w - 26)).clamp(0, 1));
            return GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTapDown: (d) => at(d.localPosition.dx),
              onHorizontalDragUpdate: (d) => at(d.localPosition.dx),
              child: SizedBox(
                height: 44,
                child: Stack(alignment: Alignment.centerLeft, children: [
                  Container(height: 6, decoration: BoxDecoration(color: Cx.outlineC, borderRadius: BorderRadius.circular(3))),
                  Container(height: 6, width: 13 + value * (w - 26), decoration: BoxDecoration(color: Cx.accent, borderRadius: BorderRadius.circular(3))),
                  Positioned(left: value * (w - 26), child: Container(width: 26, height: 26, decoration: BoxDecoration(shape: BoxShape.circle, color: Cx.text, border: Border.all(color: Cx.accent, width: 3)))),
                ]),
              ),
            );
          },
        ),
      );
}

/// The grouped list from the mockups: surface card, rows with dividers.
class CxList extends StatelessWidget {
  const CxList({super.key, required this.children, this.padding = const EdgeInsets.symmetric(horizontal: 14, vertical: 4)});
  final List<Widget> children;
  final EdgeInsets padding;
  @override
  Widget build(BuildContext context) => Container(
        padding: padding,
        decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(Cx.tileRadius)),
        child: Column(children: [
          for (var i = 0; i < children.length; i++) ...[
            children[i],
            if (i < children.length - 1) Divider(color: Cx.lineC, height: 1, thickness: 1),
          ],
        ]),
      );
}

/// A dashed outline panel (privacy notes and waiting invites in the mockups).
class CxDashed extends StatelessWidget {
  const CxDashed({super.key, required this.child, this.padding = EdgeInsets.zero});
  final Widget child;
  final EdgeInsets padding;
  @override
  Widget build(BuildContext context) => CustomPaint(
        foregroundPainter: _DashPainter(),
        child: Padding(padding: padding, child: child),
      );
}

class _DashPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()..addRRect(RRect.fromRectAndRadius((Offset.zero & size).deflate(.75), const Radius.circular(Cx.tileRadius)));
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..color = Cx.outlineC;
    for (final m in path.computeMetrics()) {
      for (var d = 0.0; d < m.length; d += 9) {
        canvas.drawPath(m.extractPath(d, d + 5), paint);
      }
    }
  }

  @override
  bool shouldRepaint(_DashPainter old) => false;
}
