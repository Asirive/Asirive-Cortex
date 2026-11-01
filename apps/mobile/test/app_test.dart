import 'package:cortex_app/push.dart';
import 'dart:convert';

import 'package:cortex_app/api.dart';
import 'package:cortex_app/main.dart';
import 'package:cortex_app/prefs.dart';
import 'package:cortex_app/services.dart';
import 'package:cortex_app/session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'fakes.dart';

http.Response json(int code, Object body) =>
    http.Response(jsonEncode(body), code, headers: {'content-type': 'application/json'});

Session makeSession(Future<http.Response> Function(http.Request) h, [MemoryStore? store]) {
  final st = store ?? MemoryStore();
  return Session(Api(client: MockClient(h), baseUrl: 'https://gw.test'), st,
      services: Services(speaker: FakeSpeaker(), link: FakeLink(), links: FakeLinks(), push: const NoPush()), prefs: Prefs(st));
}

Future<void> boot(WidgetTester t, Session s) async {
  t.view.physicalSize = const Size(1170, 2532);
  t.view.devicePixelRatio = 3;
  addTearDown(t.view.reset);
  await s.start();
  await t.pumpWidget(CortexApp(session: s));
  await t.pumpAndSettle();
}

void main() {
  setUpAll(loadFonts);
  testWidgets('fresh install shows intro 1, Next walks to the end, Get started opens Welcome',
      (t) async {
    await boot(t, makeSession((r) async => json(500, {})));
    expect(find.text('GET THERE\nON YOUR OWN'), findsOneWidget);
    for (var i = 0; i < 3; i++) {
      await t.tap(find.text('Next'));
      await t.pumpAndSettle();
    }
    expect(find.text('FAMILY\nCLOSE BY'), findsOneWidget);
    await t.tap(find.text('Get started'));
    await t.pumpAndSettle();
    expect(find.text("LET'S GET\nYOU STARTED"), findsOneWidget);
    expect(find.text('Scan or enter invite code'), findsOneWidget);
  });

  testWidgets('Skip goes to Welcome and the intro stays seen', (t) async {
    final store = MemoryStore();
    await boot(t, makeSession((r) async => json(500, {}), store));
    await t.tap(find.text('Skip'));
    await t.pumpAndSettle();
    expect(find.text("LET'S GET\nYOU STARTED"), findsOneWidget);
    expect(await store.read('intro_seen'), '1');
  });

  testWidgets('sign in with good details lands on Home and stores the token', (t) async {
    final store = MemoryStore();
    await store.write('intro_seen', '1');
    final s = makeSession((r) async {
      if (r.url.path == '/v1/auth/login') {
        return json(200, {
          'token': 'tok',
          'account': {'id': '1', 'email': 'a@b.co', 'beta': false}
        });
      }
      return json(200, {'result': 'signed_out'});
    }, store);
    await boot(t, s);
    await t.tap(find.text('Sign in'));
    await t.pumpAndSettle();
    await t.enterText(find.byType(TextField).at(0), 'a@b.co');
    await t.enterText(find.byType(TextField).at(1), 'secret-password');
    await t.tap(find.text('Sign in').last);
    await t.pumpAndSettle();
    expect(find.text('WELCOME'), findsWidgets);
    expect(await store.read('token'), 'tok');
    await t.tap(find.bySemanticsLabel(RegExp('Settings')));
    await t.pumpAndSettle();
    await t.tap(find.text('Sign out'));
    await t.pumpAndSettle();
    expect(await store.read('token'), isNull);
    expect(find.text("LET'S GET\nYOU STARTED"), findsOneWidget);
  });

  testWidgets('wrong password shows the server wording and stays put', (t) async {
    final store = MemoryStore();
    await store.write('intro_seen', '1');
    await boot(
        t,
        makeSession(
            (r) async =>
                json(401, {'error': 'Email or password is wrong.', 'error_code': 'bad_credentials'}),
            store));
    await t.tap(find.text('Sign in'));
    await t.pumpAndSettle();
    await t.enterText(find.byType(TextField).at(0), 'a@b.co');
    await t.enterText(find.byType(TextField).at(1), 'nope');
    await t.tap(find.text('Sign in').last);
    await t.pumpAndSettle();
    expect(find.text('Email or password is wrong.'), findsOneWidget);
    expect(find.text('SIGN\nIN'), findsOneWidget);
  });

  testWidgets('create account checks the password length before calling the server', (t) async {
    final store = MemoryStore();
    await store.write('intro_seen', '1');
    var calls = 0;
    await boot(t, makeSession((r) async {
      calls++;
      return json(200, {'result': 'check_email'});
    }, store));
    await t.tap(find.text('Create an account'));
    await t.pumpAndSettle();
    await t.enterText(find.byType(TextField).at(0), 'a@b.co');
    await t.enterText(find.byType(TextField).at(1), 'short');
    await t.tap(find.text('Create account'));
    await t.pumpAndSettle();
    expect(find.text('Use at least 10 characters.'), findsOneWidget);
    expect(calls, 0);
    await t.enterText(find.byType(TextField).at(1), 'long-enough-password');
    await t.tap(find.text('Create account'));
    await t.pumpAndSettle();
    expect(calls, 0); // the terms box is not ticked yet
    expect(find.textContaining('agree to the Terms'), findsWidgets);
    await t.tap(find.textContaining('I agree to the Terms'));
    await t.tap(find.text('Create account'));
    await t.pumpAndSettle();
    expect(calls, 1);
    expect(find.text('CHECK\nYOUR EMAIL'), findsOneWidget);
  });

  testWidgets('a stored token that the server rejects returns to Welcome', (t) async {
    final store = MemoryStore();
    await store.write('intro_seen', '1');
    await store.write('token', 'old');
    await boot(
        t,
        makeSession(
            (r) async => json(401, {'error': 'Please sign in again.', 'error_code': 'signed_out'}),
            store));
    expect(find.text("LET'S GET\nYOU STARTED"), findsOneWidget);
    expect(await store.read('token'), isNull);
  });

  testWidgets('session ending while signed in shows the signed-out screen', (t) async {
    final store = MemoryStore();
    await store.write('intro_seen', '1');
    await store.write('token', 'good');
    var dead = false;
    final s = makeSession((r) async {
      if (dead) return json(401, {'error': 'Please sign in again.', 'error_code': 'signed_out'});
      if (r.url.path == '/v1/me') return json(200, {'id': '1', 'email': 'a@b.co', 'beta': false});
      return json(200, <Object>[]);
    }, store);
    await boot(t, s);
    expect(find.text('WELCOME'), findsWidgets);
    dead = true;
    await expectLater(s.api.me('good'), throwsA(isA<ApiException>()));
    await t.pumpAndSettle();
    expect(find.text('YOU WERE\nSIGNED OUT'), findsOneWidget);
  });
}

