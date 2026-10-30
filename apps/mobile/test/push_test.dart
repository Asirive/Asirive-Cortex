import 'package:cortex_app/push.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fakes.dart';

void main() {
  test('signing in registers this phone for call alerts, signing out forgets it', () async {
    final h = Harness();
    await h.session.signIn('me@x.co', 'pw');
    await Future<void>.delayed(Duration.zero);
    expect(h.gw.pushed, [
      {'platform': 'android', 'token': 'fcm-1'}
    ]);
    await h.session.signOut();
    expect(h.gw.pushCleared, ['fcm-1']);
  });

  test('a refreshed address is registered again', () async {
    final h = Harness();
    await h.session.signIn('me@x.co', 'pw');
    await Future<void>.delayed(Duration.zero);
    h.push.refresh.add((platform: 'android', token: 'fcm-2'));
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);
    expect(h.gw.pushed.last['token'], 'fcm-2');
  });

  test('without push set up nothing is sent and sign-in still works', () async {
    final h = Harness();
    h.push.addr = null;
    await h.session.signIn('me@x.co', 'pw');
    await Future<void>.delayed(Duration.zero);
    expect(h.gw.pushed, isEmpty);
    expect(h.session.phase.name, 'signedIn');
    const NoPush();
  });
}
