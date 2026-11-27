import 'package:flutter/material.dart';

/// Motion for the whole app. Rules (see apps/AGENTS.md):
/// - Every animation ends on its own. Nothing loops forever: it costs battery, and a screen reader user gains nothing.
/// - The phone's "remove animations" setting (MediaQuery.disableAnimations) turns all of it off: content is simply
///   there, at once.
/// - Animating never hides content from a screen reader: fades keep their semantics.
class Motion {
  static const fast = Duration(milliseconds: 160);
  static const base = Duration(milliseconds: 320);
  static const page = Duration(milliseconds: 360);
  static const stagger = Duration(milliseconds: 55);

  /// Material 3 "emphasized decelerate": quick start, long soft landing.
  static const enter = Cubic(0.05, 0.7, 0.1, 1.0);
  static const exit = Cubic(0.3, 0.0, 0.8, 0.15);
  static const move = Curves.easeInOutCubicEmphasized;

  static bool off(BuildContext context) => MediaQuery.maybeDisableAnimationsOf(context) ?? false;

  /// [d], or zero when animations are off.
  static Duration of(BuildContext context, Duration d) => off(context) ? Duration.zero : d;
}

/// Fades its child in while rising [rise] pixels. [index] staggers a list: item k starts k * [Motion.stagger] later.
/// Plays once, when it first appears.
class Reveal extends StatefulWidget {
  const Reveal({super.key, required this.child, this.index = 0, this.rise = 14, this.delay = Duration.zero, this.duration = Motion.base});
  final Widget child;
  final int index;
  final double rise;
  final Duration delay;
  final Duration duration;
  @override
  State<Reveal> createState() => _RevealState();
}

class _RevealState extends State<Reveal> with SingleTickerProviderStateMixin {
  AnimationController? _c;
  late Animation<double> _t;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_c != null) return;
    // capped, so a long screen has finished arriving in well under a second
    final wait = widget.delay + Motion.stagger * widget.index.clamp(0, 8);
    final total = wait + widget.duration;
    // one controller covering the wait too (no Timer): the animation is running from the first frame, so tests and
    // the framework see it as in progress until it has landed
    _c = AnimationController(vsync: this, duration: total);
    final start = total.inMicroseconds == 0 ? 0.0 : wait.inMicroseconds / total.inMicroseconds;
    _t = CurvedAnimation(parent: _c!, curve: Interval(start, 1, curve: Motion.enter));
    if (Motion.off(context)) {
      _c!.value = 1;
    } else {
      _c!.forward();
    }
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
        opacity: _t,
        alwaysIncludeSemantics: true,
        child: AnimatedBuilder(
          animation: _t,
          builder: (context, child) => Transform.translate(offset: Offset(0, (1 - _t.value) * widget.rise), child: child),
          child: widget.child,
        ),
      );
}

/// Pops its child in from [from] scale with a small overshoot, after [delay]. Plays once.
class PopIn extends StatefulWidget {
  const PopIn({super.key, required this.child, this.delay = Duration.zero, this.from = 0.6});
  final Widget child;
  final Duration delay;
  final double from;
  @override
  State<PopIn> createState() => _PopInState();
}

class _PopInState extends State<PopIn> with SingleTickerProviderStateMixin {
  AnimationController? _c;
  late Animation<double> _t;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_c != null) return;
    final total = widget.delay + const Duration(milliseconds: 420);
    _c = AnimationController(vsync: this, duration: total);
    final start = widget.delay.inMicroseconds / total.inMicroseconds;
    _t = CurvedAnimation(parent: _c!, curve: Interval(start, 1, curve: Curves.easeOutBack));
    if (Motion.off(context)) {
      _c!.value = 1;
    } else {
      _c!.forward();
    }
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _t,
        builder: (context, child) => Opacity(
          opacity: _t.value.clamp(0.0, 1.0),
          alwaysIncludeSemantics: true,
          child: Transform.scale(scale: widget.from + (1 - widget.from) * _t.value, child: child),
        ),
        child: widget.child,
      );
}

/// Page change: the new page rises a little and fades in; the page underneath dims and drifts up behind it.
/// Android and others only. iOS keeps its own transition, because that is what gives the swipe-from-the-edge back.
class CxPageTransitions extends PageTransitionsBuilder {
  const CxPageTransitions();

  @override
  Duration get transitionDuration => Motion.page;

  @override
  Widget buildTransitions<T>(PageRoute<T> route, BuildContext context, Animation<double> animation,
      Animation<double> secondaryAnimation, Widget child) {
    if (Motion.off(context)) return child;
    final inT = CurvedAnimation(parent: animation, curve: Motion.enter, reverseCurve: Motion.exit);
    final outT = CurvedAnimation(parent: secondaryAnimation, curve: Motion.move);
    return AnimatedBuilder(
      animation: Listenable.merge([inT, outT]),
      builder: (context, child) => Transform.translate(offset: Offset(0, 36 * (1 - inT.value) - 12 * outT.value), child: child),
      child: FadeTransition(
        opacity: inT,
        child: FadeTransition(opacity: Tween(begin: 1.0, end: 0.4).animate(outT), child: child),
      ),
    );
  }
}
