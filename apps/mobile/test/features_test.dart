import 'package:cortex_app/api.dart';
import 'package:cortex_app/main.dart';
import 'package:cortex_app/scope.dart';
import 'package:cortex_app/screens/calls.dart';
import 'package:cortex_app/screens/invite.dart';
import 'package:cortex_app/services.dart';
import 'package:cortex_app/session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'fakes.dart';

Future<void> boot(WidgetTester t, Harness h, {bool signedIn = true}) async {
  phone(t);
  await h.store.write('intro_seen', '1');
  if (signedIn) await h.store.write('token', 'tok');
  await h.session.start();
  await t.pumpWidget(CortexApp(session: h.session));
  await t.pumpAndSettle();
}

Map<String, dynamic> dev({int battery = 82, bool online = true}) =>
    {'id': 'd1', 'label': 'My Cortex', 'online': online, 'battery_pct': battery, 'firmware': '1.2.0', 'tier': 'STABLE'};

Map<String, dynamic> person({String state = 'active', bool loc = false, bool call = false}) =>
    {'id': 'l1', 'companion': 'u2', 'label': 'Hui Min', 'state': state, 'grant_location': loc, 'grant_call': call};

void main() {
  setUpAll(loadFonts);
  group('helpers', () {
    test('invite codes from links and typed text', () {
      expect(inviteCodeFrom('https://app/companion?code=K7Q2XM9'), 'K7Q2XM9');
      expect(inviteCodeFrom('k7q2-xm9'), 'K7Q2XM9');
      expect(inviteCodeFrom('hello world!'), isNull);
      expect(inviteCodeFrom('ab'), isNull);
    });
    test('claim codes from the QR and typed text', () {
      expect(claimCodeFrom('asirive://claim?code=K7QM4TXD'), 'K7QM-4TXD');
      expect(claimCodeFrom('k7qm-4txd'), 'K7QM-4TXD');
      expect(claimCodeFrom('12'), isNull);
    });
  });

  group('owner', () {
    testWidgets('new account sees set-up on Home, with owner tabs only', (t) async {
      await boot(t, Harness());
      expect(find.text('Set up with a helper'), findsOneWidget);
      expect(find.bySemanticsLabel(RegExp('Home, current')), findsOneWidget);
      expect(find.bySemanticsLabel(RegExp('Following')), findsNothing);
    });

    testWidgets('Home shows battery and Hear my status speaks it', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      expect(find.text('Battery 82%'), findsOneWidget);
      await t.tap(find.text('Hear my status'));
      await t.pump();
      expect(h.speaker.said.last, contains('Battery 82 percent'));
      expect(h.speaker.said.last, contains('not plugged in'));
    });

    testWidgets('pause asks first, then reports when the cable is out', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.link.pauseOk = false;
      await boot(t, h);
      await t.tap(find.text('Pause the assistant'));
      await t.pumpAndSettle();
      expect(find.text('Pause the assistant?'), findsOneWidget);
      await t.tap(find.text('Cancel'));
      await t.pumpAndSettle();
      expect(h.link.paused, 0);
      await t.tap(find.text('Pause the assistant'));
      await t.pumpAndSettle();
      await t.tap(find.text('Pause assistant'));
      await t.pumpAndSettle();
      expect(h.link.paused, 1);
      expect(find.textContaining('Plug it in with the cable'), findsOneWidget);
    });

    testWidgets('where I am uploads the location', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.text('Where I am'));
      await t.pumpAndSettle();
      await t.tap(find.text('Find and share my location'));
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('PUT /v1/me/location'));
      expect(find.text('1.30000, 103.80000'), findsOneWidget);
    });

    testWidgets('where I am says so when location is off', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.location.at = null;
      await boot(t, h);
      await t.tap(find.text('Where I am'));
      await t.pumpAndSettle();
      await t.tap(find.text('Find and share my location'));
      await t.pumpAndSettle();
      expect(find.textContaining('Location is off'), findsOneWidget);
      expect(h.gw.calls.contains('PUT /v1/me/location'), isFalse);
    });

    testWidgets('update screen offers an install and confirms first', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.update = {'release_id': 'r1'};
      await boot(t, h);
      await t.tap(find.text('Software update'));
      await t.pumpAndSettle();
      expect(find.text('Install update'), findsOneWidget);
      await t.tap(find.text('Install update'));
      await t.pumpAndSettle();
      expect(find.text('Install the update?'), findsOneWidget);
    });

    testWidgets('up to date shows no install button', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.text('Software update'));
      await t.pumpAndSettle();
      expect(find.textContaining('You are up to date'), findsOneWidget);
      expect(find.text('Install update'), findsNothing);
    });

    testWidgets('share internet reports cable out, then success', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.text('Share internet'));
      await t.pumpAndSettle();
      await t.tap(find.text('Test the connection'));
      await t.pumpAndSettle();
      expect(find.textContaining('not plugged in'), findsOneWidget);
      h.link.st = LinkState.connectedNoInternet;
      await t.tap(find.text('Test the connection'));
      await t.pumpAndSettle();
      expect(find.textContaining('can reach the internet'), findsOneWidget);
    });
  });

  group('people', () {
    testWidgets('list shows grants and a pending invite', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.owned = [person(loc: true), {...person(state: 'pending'), 'id': 'l2', 'label': 'Uncle Ben'}];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('My people')));
      await t.pumpAndSettle();
      expect(find.text('Hui Min'), findsOneWidget);
      expect(find.text('Sees where you are'), findsOneWidget);
      expect(find.text('Waiting to accept'), findsOneWidget);
    });

    testWidgets('invite needs a name, then shows the code once', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('My people')));
      await t.pumpAndSettle();
      await t.tap(find.text('Invite someone'));
      await t.pumpAndSettle();
      await t.tap(find.text('Make the invite'));
      await t.pumpAndSettle();
      expect(find.textContaining('Add a name'), findsOneWidget);
      await t.enterText(find.byType(TextField), 'Hui Min');
      await t.tap(find.text('Make the invite'));
      await t.pumpAndSettle();
      expect(find.text('K7Q2-XM9'), findsOneWidget);
      expect(h.gw.bodies['POST /v1/companions'], {'label': 'Hui Min'});
    });

    testWidgets('grant switch sends both flags, and rolls back on error', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.owned = [person()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('My people')));
      await t.pumpAndSettle();
      await t.tap(find.text('Hui Min'));
      await t.pumpAndSettle();
      await t.tap(find.text('See where I am'));
      await t.pumpAndSettle();
      expect(h.gw.bodies['PUT /v1/companions/l1/grants'], {'location': true, 'call': false});
    });

    testWidgets('remove keeps them first, then removes after confirming', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.owned = [person()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('My people')));
      await t.pumpAndSettle();
      await t.tap(find.text('Hui Min'));
      await t.pumpAndSettle();
      await t.tap(find.text('Remove Hui Min'));
      await t.pumpAndSettle();
      expect(find.text('Keep Hui Min'), findsOneWidget);
      await t.tap(find.text('Keep Hui Min'));
      await t.pumpAndSettle();
      expect(h.gw.calls.contains('DELETE /v1/companions/l1'), isFalse);
      await t.tap(find.text('Remove Hui Min'));
      await t.pumpAndSettle();
      await t.tap(find.text('Remove').last);
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('DELETE /v1/companions/l1'));
    });
  });

  group('companion side', () {
    testWidgets('companion-only account gets two tabs and no owner screens', (t) async {
      final h = Harness();
      h.gw.watching = [
        {'link_id': 'l9', 'owner_id': 'o1', 'owner_email': 'hui@x.co', 'grants': {'location': true, 'call': false}}
      ];
      await boot(t, h);
      expect(find.text('FOLLOWING'), findsWidgets);
      expect(find.text('hui@x.co'), findsOneWidget);
      expect(find.bySemanticsLabel(RegExp('My people')), findsNothing);
      expect(find.text('Set up with a helper'), findsNothing);
    });

    testWidgets('where they are shows age; a call is disabled until allowed', (t) async {
      final h = Harness();
      h.gw.watching = [
        {'link_id': 'l9', 'owner_id': 'o1', 'owner_email': 'hui@x.co', 'grants': {'location': true, 'call': false}}
      ];
      await boot(t, h);
      await t.tap(find.text('hui@x.co'));
      await t.pumpAndSettle();
      expect(find.text('5 min ago'), findsOneWidget);
      expect(find.text('Calls not allowed yet'), findsOneWidget);
    });

    testWidgets('both sides: Following tab appears and Switch side works', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.watching = [
        {'link_id': 'l9', 'owner_id': 'o1', 'owner_email': 'hui@x.co', 'grants': {'location': true, 'call': true}}
      ];
      await boot(t, h);
      expect(h.session.hasBoth, isTrue);
      expect(find.bySemanticsLabel(RegExp('Following')), findsOneWidget);
      await h.session.switchSide(Side.companion);
      await t.pumpAndSettle();
      expect(find.text('hui@x.co'), findsOneWidget);
      expect(h.store.read('prefs'), isNotNull);
    });

    testWidgets('an invite scanned before sign-in is applied at sign-in', (t) async {
      final h = Harness();
      await boot(t, h, signedIn: false);
      await t.tap(find.text('Scan or enter invite code'));
      await t.pumpAndSettle();
      await t.tap(find.text('fake scan'));
      await t.pumpAndSettle();
      expect(find.text('YOU ARE\nINVITED'), findsOneWidget);
      await t.tap(find.text('I already have an account'));
      await t.pumpAndSettle();
      await t.enterText(find.byType(TextField).at(0), 'me@x.co');
      await t.enterText(find.byType(TextField).at(1), 'secret-password');
      await t.tap(find.text('Sign in').last);
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('POST /v1/companions/accept'));
      expect(h.session.side, Side.companion);
      expect(find.textContaining('You are now looking after hui@x.co'), findsOneWidget);
    });

    testWidgets('signed in: Accept joins right on the invite screen', (t) async {
      final h = Harness();
      phone(t);
      h.session.token = 'tok';
      await t.pumpWidget(SessionScope(session: h.session, child: const MaterialApp(home: AcceptScreen(code: 'K7Q2XM9'))));
      expect(find.text('Accept'), findsOneWidget);
      expect(find.text('Accept and create account'), findsNothing);
      await t.tap(find.text('Accept'));
      await t.pumpAndSettle();
      expect(h.gw.bodies['POST /v1/companions/accept'], {'code': 'K7Q2XM9'});
      expect(h.session.links.watching.single.ownerEmail, 'hui@x.co');
    });

    testWidgets('a wrong or expired code shows the server message and stays', (t) async {
      final h = Harness();
      phone(t);
      h.session.token = 'tok';
      await t.pumpWidget(SessionScope(session: h.session, child: const MaterialApp(home: AcceptScreen(code: 'BADCODE'))));
      await t.tap(find.text('Accept'));
      await t.pumpAndSettle();
      expect(find.textContaining('wrong or has expired'), findsOneWidget);
      expect(find.text('Accept'), findsOneWidget);
    });

    testWidgets('typed bad code is rejected on the screen itself', (t) async {
      final h = Harness();
      await boot(t, h, signedIn: false);
      await t.tap(find.text('Scan or enter invite code'));
      await t.pumpAndSettle();
      await t.tap(find.text('Enter the code instead'));
      await t.pumpAndSettle();
      await t.enterText(find.byType(TextField), '??');
      await t.tap(find.text('Continue'));
      await t.pumpAndSettle();
      expect(find.textContaining('That code did not work'), findsOneWidget);
    });
  });

  group('settings', () {
    testWidgets('assist settings are saved and speed is applied', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('Settings')));
      await t.pumpAndSettle();
      await t.tap(find.text('Voice, sound and text'));
      await t.pumpAndSettle();
      await t.tap(find.text('Larger'));
      await t.pumpAndSettle();
      expect(h.session.prefs.textScale, 1.6);
      expect(await h.store.read('prefs'), contains('"text":1.6'));
    });

    testWidgets('beta needs agreement before it can be joined', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('Settings')));
      await t.pumpAndSettle();
      await t.tap(find.text('Join the beta'));
      await t.pumpAndSettle();
      await t.tap(find.text('Join the beta').last);
      await t.pumpAndSettle();
      expect(h.gw.calls.contains('PUT /v1/me/beta'), isFalse);
      await t.tap(find.text('I have read and agree'));
      await t.pumpAndSettle();
      await t.tap(find.text('Join the beta').last);
      await t.pumpAndSettle();
      expect(h.gw.bodies['PUT /v1/me/beta'], {'enabled': true, 'consent_version': 'v1'});
      expect(find.text('Leave the beta'), findsOneWidget);
    });

    testWidgets('feedback sends text only', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('Settings')));
      await t.pumpAndSettle();
      await t.tap(find.text('Send feedback'));
      await t.pumpAndSettle();
      await t.enterText(find.byType(TextField), 'It works');
      await t.tap(find.text('Send'));
      await t.pumpAndSettle();
      expect(h.gw.bodies['POST /v1/feedback'], {'text': 'It works', 'app_version': '0.1.0'});
      expect(find.text('THANK YOU'), findsOneWidget);
    });

    testWidgets('delete account needs the password and a confirmation', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.override = (r) => r.method == 'DELETE' && r.url.path == '/v1/me'
          ? http.Response('{"result":"deleted"}', 200)
          : throw StateError('x');
      h.gw.override = null;
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('Settings')));
      await t.pumpAndSettle();
      await t.tap(find.text('Privacy and data'));
      await t.pumpAndSettle();
      await t.tap(find.text('Delete my account'));
      await t.pumpAndSettle();
      await t.tap(find.text('Delete my account').last);
      await t.pumpAndSettle();
      expect(find.text('Enter your password to confirm.'), findsOneWidget);
    });
  });

  group('setup with a helper', () {
    testWidgets('five steps, owner confirms the code and the hand back', (t) async {
      final h = Harness();
      await boot(t, h);
      await t.tap(find.text('Set up with a helper'));
      await t.pumpAndSettle();
      await t.tap(find.text('Hear this screen'));
      await t.pump();
      expect(h.speaker.said.last, contains('sighted helper'));
      await t.tap(find.text('Start with a helper'));
      await t.pumpAndSettle();
      expect(find.text('STEP 1 OF 5'), findsOneWidget);
      expect(find.text('Stop helper mode'), findsOneWidget);
      await t.tap(find.text('Next'));
      await t.pumpAndSettle();
      // pair: cable out first
      await t.enterText(find.byType(TextField), 'K7QM-4TXD');
      await t.tap(find.text('Pair the box'));
      await t.pumpAndSettle();
      expect(find.textContaining('not plugged in'), findsOneWidget);
      expect(h.gw.calls.contains('POST /v1/claim'), isFalse);
      h.link.st = LinkState.connectedOnline;
      await t.tap(find.text('Pair the box'));
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('POST /v1/claim'));
      expect(find.textContaining('ends in 4 T X D'), findsOneWidget);
      await t.tap(find.text('Yes, that is what I heard'));
      await t.pumpAndSettle();
      await t.tap(find.text('Next'));
      await t.pumpAndSettle();
      await t.tap(find.text('Next'));
      await t.pumpAndSettle();
      await t.tap(find.text('I heard Cortex answer'));
      await t.tap(find.text('I felt the touch'));
      await t.pumpAndSettle();
      await t.tap(find.text('Next'));
      await t.pumpAndSettle();
      expect(find.text('HAND\nBACK'), findsOneWidget);
      h.ownerCheck.ok = false;
      await t.tap(find.text('I have the phone back'));
      await t.pumpAndSettle();
      expect(find.textContaining('Not confirmed'), findsOneWidget);
      h.ownerCheck.ok = true;
      await t.tap(find.text('I have the phone back'));
      await t.pumpAndSettle();
      expect(find.text('HOME'), findsWidgets);
    });

    testWidgets('a failed hand-over is reported, not hidden', (t) async {
      final h = Harness();
      h.link.st = LinkState.connectedOnline;
      h.link.handOver = false;
      await boot(t, h);
      await t.tap(find.text('Set up with a helper'));
      await t.pumpAndSettle();
      await t.tap(find.text('Start with a helper'));
      await t.pumpAndSettle();
      await t.tap(find.text('Next'));
      await t.pumpAndSettle();
      await t.enterText(find.byType(TextField), 'K7QM-4TXD');
      await t.tap(find.text('Pair the box'));
      await t.pumpAndSettle();
      expect(find.textContaining('did not take it'), findsOneWidget);
    });

    testWidgets('stopping helper mode needs the owner to confirm', (t) async {
      final h = Harness();
      await boot(t, h);
      await t.tap(find.text('Set up with a helper'));
      await t.pumpAndSettle();
      await t.tap(find.text('Start with a helper'));
      await t.pumpAndSettle();
      h.ownerCheck.ok = false;
      await t.tap(find.text('Stop helper mode'));
      await t.pumpAndSettle();
      expect(find.text('STEP 1 OF 5'), findsOneWidget);
      h.ownerCheck.ok = true;
      await t.tap(find.text('Stop helper mode'));
      await t.pumpAndSettle();
      expect(find.text('STEP 1 OF 5'), findsNothing);
    });
  });

  group('calls', () {
    test('outgoing call rings, connects when answered, and ends when they hang up', () async {
      final h = Harness();
      h.session.token = 'tok';
      final c = CallController(h.session);
      await c.startOutgoing('u2');
      expect(c.phase, CallPhase.ringing);
      expect(h.gw.bodies['POST /v1/calls']!['to'], 'u2');
      expect(h.gw.calls, contains('POST /v1/calls/call1/ice')); // queued candidate flushed
      h.gw.callState = {'id': 'call1', 'state': 'active', 'answer': '{"sdp":"a","type":"answer"}', 'ice': ['{"candidate":"r1"}']};
      await Future<void>.delayed(const Duration(milliseconds: 1700));
      expect(c.phase, CallPhase.connected);
      expect(h.engine.answerSet, contains('answer'));
      expect(h.engine.candidates, ['{"candidate":"r1"}']);
      h.gw.callState = {'id': 'call1', 'state': 'ended'};
      await Future<void>.delayed(const Duration(milliseconds: 1700));
      expect(c.phase, CallPhase.ended);
      expect(h.engine.closed, isTrue);
      c.dispose();
    });

    test('declined call ends with a clear message', () async {
      final h = Harness();
      h.session.token = 'tok';
      final c = CallController(h.session);
      await c.startOutgoing('u2');
      h.gw.callState = {'id': 'call1', 'state': 'declined'};
      await Future<void>.delayed(const Duration(milliseconds: 1700));
      expect(c.phase, CallPhase.ended);
      expect(c.message, 'They declined.');
      c.dispose();
    });

    test('a call the other person has not allowed fails plainly', () async {
      final h = Harness();
      h.session.token = 'tok';
      h.gw.override = (r) => r.url.path == '/v1/calls' && r.method == 'POST'
          ? http.Response('{"error":"nope","error_code":"not_allowed"}', 403)
          : http.Response('{"ice_servers":[]}', 200);
      final c = CallController(h.session);
      await c.startOutgoing('u2');
      expect(c.phase, CallPhase.failed);
      expect(c.message, 'They have not allowed calls from you.');
      c.dispose();
    });

    test('answering an incoming call sends the answer', () async {
      final h = Harness();
      h.session.token = 'tok';
      h.gw.callState = {'id': 'call1', 'state': 'ringing', 'from': 'u2', 'to': 'me', 'offer': '{"sdp":"o","type":"offer"}', 'ice': []};
      final c = CallController(h.session);
      await c.answerIncoming(CallInfo(id: 'call1', from: 'u2', to: 'me', state: 'ringing'));
      expect(h.gw.bodies['POST /v1/calls/call1/answer'], isNotNull);
      expect(c.phase, CallPhase.ringing);
      c.toggleMute();
      expect(h.engine.muted, isTrue);
      await c.hangUp();
      expect(h.gw.calls, contains('POST /v1/calls/call1/end'));
      c.dispose();
    });

    testWidgets('a ringing call in the inbox opens the incoming screen, spoken, Answer first', (t) async {
      final h = Harness();
      h.gw.watching = [
        {'link_id': 'l9', 'owner_id': 'u2', 'owner_email': 'hui@x.co', 'grants': {'location': true, 'call': true}}
      ];
      h.gw.inbox = [
        {'id': 'call1', 'state': 'ringing', 'from': 'u2', 'to': 'me'}
      ];
      await boot(t, h);
      await t.pump(const Duration(seconds: 5));
      await t.pumpAndSettle();
      expect(find.text('Incoming call'), findsOneWidget);
      expect(find.text('Answer'), findsOneWidget);
      expect(h.speaker.said.last, 'Incoming call from hui@x.co.');
      await t.tap(find.text('Decline'));
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('POST /v1/calls/call1/end'));
    });
  });
}
