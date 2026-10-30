import 'package:flutter/material.dart';
import 'theme.dart';

/// Screen shell: 14px side margin, dark ground, safe area. [bottom] is pinned
/// to the foot of the screen when the content is short, and scrolls with it when not.
class CxScreen extends StatelessWidget {
  const CxScreen({super.key, required this.children, this.bottom = const [], this.tab = false});
  final List<Widget> children;
  final List<Widget> bottom;

  /// True on a main tab, which leaves room for the floating nav bar.
  final bool tab;

  List<Widget> _gap(List<Widget> l) => [for (final c in l) ...[c, const SizedBox(height: 14)]];

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: LayoutBuilder(
            builder: (context, box) => SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(Cx.margin, 8, Cx.margin, tab ? 100 : 20),
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: box.maxHeight - (tab ? 108 : 28)),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _gap(children)),
                    if (bottom.isNotEmpty)
                      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _gap(bottom)),
                  ],
                ),
              ),
            ),
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
        child: InkResponse(
          onTap: onTap ?? () => Navigator.of(context).maybePop(),
          child: Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Cx.line)),
            child: const ExcludeSemantics(child: Icon(Icons.chevron_left, color: Cx.text, size: 26)),
          ),
        ),
      );
}

/// Top row: optional back button, trailing widget on the right.
class CxTop extends StatelessWidget {
  const CxTop({super.key, this.back = true, this.onBack, this.title, this.trailing});
  final bool back;
  final VoidCallback? onBack;
  final String? title;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => SizedBox(
        height: 48,
        child: Row(children: [
          if (back) CxBack(onTap: onBack),
          if (title != null) ...[const SizedBox(width: 12), Text(title!.toUpperCase(), style: Cx.label)],
          const Spacer(),
          ?trailing,
        ]),
      );
}

class CxTitle extends StatelessWidget {
  const CxTitle(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) =>
      Semantics(header: true, child: Text(text.toUpperCase(), style: Cx.display));
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
  const CxButton(this.label, {super.key, required this.onTap, this.outline = false, this.busy = false, this.danger = false});
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
          height: 56,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: outline ? Colors.transparent : (onTap == null ? Cx.outline : Cx.accent),
            borderRadius: BorderRadius.circular(28),
            border: outline ? Border.all(color: danger ? Cx.danger : Cx.outline, width: 1.5) : null,
          ),
          child: busy
              ? SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2.5, color: fg))
              : Text(label,
                  style: TextStyle(
                      fontFamily: 'SpaceGrotesk', fontSize: 16, fontWeight: FontWeight.w700, color: fg)),
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
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: on ? Cx.accent : Colors.transparent,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: on ? Cx.accent : Cx.outline),
        ),
        child: Text(label,
            style: TextStyle(
                fontFamily: 'SpaceGrotesk',
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: on ? Cx.ground : Cx.text)),
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
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
          color: Cx.surface,
          borderRadius: BorderRadius.circular(Cx.tileRadius),
          border: Border.all(color: Cx.line)),
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
  });
  final int lines;
  final String label;
  final TextEditingController controller;
  final String? hint;
  final bool obscure;
  final TextInputType? keyboard;
  final String? error;
  final String? help;
  final Iterable<String>? autofill;
  final VoidCallback? onSubmit;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
              padding: const EdgeInsets.only(left: 8, bottom: 6),
              child: Text(label.toUpperCase(), style: Cx.label)),
          TextField(
            controller: controller,
            obscureText: obscure,
            keyboardType: lines > 1 ? TextInputType.multiline : keyboard,
            minLines: lines,
            maxLines: lines,
            autofillHints: autofill,
            onSubmitted: onSubmit == null ? null : (_) => onSubmit!(),
            style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 17, color: Cx.text),
            decoration: InputDecoration(
              hintText: hint,
              hintStyle: const TextStyle(color: Cx.faint),
              contentPadding: const EdgeInsets.symmetric(horizontal: 22, vertical: 18),
              filled: true,
              fillColor: Cx.surface,
              enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(30),
                  borderSide: BorderSide(color: error == null ? Cx.line : Cx.danger, width: 1.5)),
              focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(30),
                  borderSide: const BorderSide(color: Cx.accent, width: 2)),
            ),
          ),
          if (error != null)
            Padding(
                padding: const EdgeInsets.only(left: 8, top: 8),
                child: Semantics(
                    liveRegion: true, child: Text(error!, style: Cx.small.copyWith(color: Cx.danger)))),
          if (help != null && error == null)
            Padding(padding: const EdgeInsets.only(left: 8, top: 8), child: Text(help!, style: Cx.small)),
        ],
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
                    color: i == step ? Cx.accent : Cx.outline, borderRadius: BorderRadius.circular(3)),
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
