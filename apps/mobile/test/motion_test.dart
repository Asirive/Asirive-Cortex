import 'package:cortex_app/motion.dart';
import 'package:cortex_app/screens/intro.dart';
import 'package:cortex_app/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fakes.dart';

/// Wraps [child] like the app does, with the phone's "remove animations" setting on or off.
Widget host(Widget child, {bool still = false}) => MaterialApp(
      home: Builder(
        builder: (c) => MediaQuery(data: MediaQuery.of(c).copyWith(disableAnimations: still), child: child),
      ),
    );

double opacityOf(WidgetTester t, Finder f) {
  final fade = t.widget<FadeTransition>(find.ancestor(of: f, matching: find.byType(FadeTransition)).first);
  return fade.opacity.value;
}

void main() {
  setUpAll(loadFonts);

  group('Reveal', () {
    testWidgets('fades in, then settles fully visible', (t) async {
      await t.pumpWidget(host(const Scaffold(body: Reveal(child: Text('hello')))));
      expect(opacityOf(t, find.text('hello')), lessThan(1));
      await t.pumpAndSettle();
      expect(opacityOf(t, find.text('hello')), 1);
    });

    testWidgets('with "remove animations" on it is visible on the first frame', (t) async {
      await t.pumpWidget(host(const Scaffold(body: Reveal(index: 5, child: Text('hello'))), still: true));
      expect(opacityOf(t, find.text('hello')), 1);
      expect(t.binding.transientCallbackCount, 0); // nothing ticking
    });

    testWidgets('a screen reader can read it while it is still fading in', (t) async {
      final h = t.ensureSemantics();
      await t.pumpWidget(host(const Scaffold(body: Reveal(index: 3, child: Text('hello')))));
      expect(find.semantics.byLabel('hello'), findsOne);
      await t.pumpAndSettle();
      h.dispose();
    });

    testWidgets('later items start later', (t) async {
      await t.pumpWidget(host(const Scaffold(body: Column(children: [Reveal(child: Text('a')), Reveal(index: 4, child: Text('b'))]))));
      await t.pump(const Duration(milliseconds: 200));
      expect(opacityOf(t, find.text('a')), greaterThan(opacityOf(t, find.text('b'))));
      await t.pumpAndSettle();
    });
  });

  testWidgets('the animated logo builds itself and then stops', (t) async {
    await t.pumpWidget(host(const Center(child: CxLogo(size: 64, animate: true))));
    expect(t.binding.hasScheduledFrame, isTrue);
    await t.pumpAndSettle(); // finishes: nothing loops forever
    expect(find.byType(CxLogo), findsOne);
  });

  group('intro', () {
    Future<void> show(WidgetTester t, {bool still = false}) async {
      t.view.physicalSize = const Size(1170, 2532);
      t.view.devicePixelRatio = 3;
      addTearDown(t.view.reset);
      await t.pumpWidget(host(const IntroScreen(), still: still));
      await t.pumpAndSettle();
    }

    testWidgets('swiping left goes forward, swiping right goes back', (t) async {
      await show(t);
      await t.fling(find.text('GET THERE\nON YOUR OWN'), const Offset(-300, 0), 1000);
      await t.pumpAndSettle();
      expect(find.text('KNOW WHAT\nIS AHEAD'), findsOne);
      expect(find.text('GET THERE\nON YOUR OWN'), findsNothing);
      await t.fling(find.text('KNOW WHAT\nIS AHEAD'), const Offset(300, 0), 1000);
      await t.pumpAndSettle();
      expect(find.text('GET THERE\nON YOUR OWN'), findsOne);
      // no step before the first
      await t.fling(find.text('GET THERE\nON YOUR OWN'), const Offset(300, 0), 1000);
      await t.pumpAndSettle();
      expect(find.text('GET THERE\nON YOUR OWN'), findsOne);
    });

    testWidgets('while steps swap, the screen reader only hears the new one', (t) async {
      final h = t.ensureSemantics();
      await show(t);
      await t.tap(find.text('Next'));
      await t.pump(); // the first frame of the change: the new step is still fully transparent
      expect(find.semantics.byLabel('KNOW WHAT\nIS AHEAD'), findsOne);
      await t.pump(const Duration(milliseconds: 60)); // mid-transition: both steps are drawn
      expect(find.text('GET THERE\nON YOUR OWN'), findsOne);
      expect(find.semantics.byLabel('GET THERE\nON YOUR OWN'), findsNothing);
      expect(find.semantics.byLabel('KNOW WHAT\nIS AHEAD'), findsOne);
      await t.pumpAndSettle();
      h.dispose();
    });

    testWidgets('the question and the answer are both readable before the answer appears', (t) async {
      final h = t.ensureSemantics();
      await show(t);
      for (var i = 0; i < 2; i++) {
        await t.tap(find.text('Next'));
        await t.pumpAndSettle();
      }
      await t.tap(find.text('Next')); // to step 4 and back to 3 replays it
      await t.pumpAndSettle();
      await t.tap(find.bySemanticsLabel('Back'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 400)); // the answer is still behind the thinking dots
      // the tile reads as one block: the whole exchange, though the answer is not drawn yet
      expect(find.semantics.byPredicate((n) => n.label.contains('You say: "Hey Cortex, when is my bus?"') && n.label.contains('Cortex says: Bus 175 comes in 3 minutes.')), findsOne);
      await t.pumpAndSettle();
      h.dispose();
    });

    testWidgets('with "remove animations" on, Next shows the next step at once', (t) async {
      await show(t, still: true);
      await t.tap(find.text('Next'));
      await t.pump();
      await t.pump();
      expect(find.text('KNOW WHAT\nIS AHEAD'), findsOne);
      expect(find.text('GET THERE\nON YOUR OWN'), findsNothing);
      expect(t.binding.transientCallbackCount, 0);
    });
  });

  testWidgets('a button squishes a little while pressed', (t) async {
    await t.pumpWidget(host(Scaffold(body: Center(child: SizedBox(width: 200, child: CxButton('Go', onTap: () {}))))));
    double scale() => t.widget<AnimatedScale>(find.descendant(of: find.byType(CxButton), matching: find.byType(AnimatedScale))).scale;
    expect(scale(), 1);
    final g = await t.startGesture(t.getCenter(find.text('Go')));
    await t.pump();
    expect(scale(), lessThan(1));
    await g.up();
    await t.pumpAndSettle();
    expect(scale(), 1);
  });

  test('motion timings are short enough not to slow anyone down', () {
    expect(Motion.page.inMilliseconds, lessThanOrEqualTo(400));
    expect(Motion.base.inMilliseconds, lessThanOrEqualTo(400));
  });
}
