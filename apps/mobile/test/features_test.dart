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
      expect(find.text('SET UP GLASSES'), findsOneWidget);
      expect(find.bySemanticsLabel(RegExp('Home, current')), findsOneWidget);
      expect(find.bySemanticsLabel(RegExp('Following')), findsNothing);
    });

    testWidgets('Home shows battery and Hear my status speaks it', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      expect(find.bySemanticsLabel(RegExp('Battery 82 percent')), findsOneWidget);
      await t.tap(find.bySemanticsLabel('Hear my status'));
      await t.pump();
      expect(h.speaker.said.last, contains('Battery 82 percent'));
      expect(h.speaker.said.last, contains('not plugged in'));
    });

    testWidgets('pause asks first, then reports when the cable is out', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.link.pauseOk = false;
      await boot(t, h);
      await t.tap(find.bySemanticsLabel('Pause the assistant'));
      await t.pumpAndSettle();
      expect(find.text('PAUSE THE ASSISTANT?'), findsOneWidget);
      await t.tap(find.text('Keep it running'));
      await t.pumpAndSettle();
      expect(h.link.paused, 0);
      await t.tap(find.bySemanticsLabel('Pause the assistant'));
      await t.pumpAndSettle();
      await t.tap(find.text('Pause the assistant'));
      await t.pumpAndSettle();
      expect(h.link.paused, 1);
      expect(find.textContaining('Plug it in with the cable'), findsOneWidget);
    });

    testWidgets('where I am uploads the location', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.text('My location'));
      await t.pumpAndSettle();
      await t.tap(find.text('Find and share my location'));
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('PUT /v1/me/location'));
      expect(find.text('1.3000, 103.8000'), findsOneWidget);
    });

    testWidgets('where I am says so when location is off', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.location.at = null;
      await boot(t, h);
      await t.tap(find.text('My location'));
      await t.pumpAndSettle();
      await t.tap(find.text('Find and share my location'));
      await t.pumpAndSettle();
      expect(find.textContaining('Location is off'), findsOneWidget);
      expect(h.gw.calls.contains('PUT /v1/me/location'), isFalse);
    });

    testWidgets('an update offer shows a tile and confirms first', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.update = {'release_id': 'r1'};
      await boot(t, h);
      await t.tap(find.text('UPDATE READY'));
      await t.pumpAndSettle();
      expect(find.text('INSTALL THE UPDATE?'), findsOneWidget);
      expect(find.text('Not now'), findsOneWidget);
    });

    testWidgets('up to date shows no update tile', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      expect(find.text('UPDATE READY'), findsNothing);
    });

    testWidgets('share internet reports cable out, then success', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.link.st = LinkState.connectedNoInternet;
      await boot(t, h);
      await t.tap(find.text('GLASSES ARE OFFLINE'));
      await t.pumpAndSettle();
      h.link.st = LinkState.cableOut;
      await t.tap(find.text('Test now'));
      await t.pumpAndSettle();
      expect(find.text('Not reachable yet'), findsOneWidget);
      h.link.st = LinkState.connectedOnline;
      await t.tap(find.text('Test now'));
      await t.pumpAndSettle();
      expect(find.text('Reachable'), findsOneWidget);
    });
  });

  group('people', () {
    testWidgets('list shows grants and a pending invite', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.owned = [person(loc: true), {...person(state: 'pending'), 'id': 'l2', 'label': 'Uncle Ben'}];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel('My people'));
      await t.pumpAndSettle();
      expect(find.text('Hui Min'), findsOneWidget);
      expect(find.text('Location'), findsOneWidget);
      expect(find.text('Invite sent to Uncle Ben'), findsOneWidget);
    });

    testWidgets('invite needs a name, then shows the code once', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel('My people'));
      await t.pumpAndSettle();
      await t.tap(find.text('Invite someone'));
      await t.pumpAndSettle();
      await t.tap(find.text('Copy link'));
      await t.pumpAndSettle();
      expect(find.textContaining('Add a name'), findsOneWidget);
      await t.enterText(find.byType(TextField), 'Hui Min');
      await t.tap(find.text('Copy link'));
      await t.pumpAndSettle();
      expect(find.text('K7Q2-XM9'), findsOneWidget);
      expect(h.gw.bodies['POST /v1/companions'], {'label': 'Hui Min'});
    });

    testWidgets('grant switch sends both flags, and rolls back on error', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.owned = [person()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel('My people'));
      await t.pumpAndSettle();
      await t.tap(find.text('Hui Min'));
      await t.pumpAndSettle();
      await t.tap(find.text('See my location'));
      await t.pumpAndSettle();
      expect(h.gw.bodies['PUT /v1/companions/l1/grants'], {'location': true, 'call': false});
    });

    testWidgets('remove keeps them first, then removes after confirming', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.owned = [person()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel('My people'));
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
      await t.tap(find.text('Remove Hui Min').last);
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
      expect(find.bySemanticsLabel('My people'), findsNothing);
      expect(find.text('Set up with a helper'), findsNothing);
    });

    testWidgets('where they are shows age; a call is disabled until allowed', (t) async {
      final h = Harness();
      h.gw.watching = [
        {'link_id': 'l9', 'owner_id': 'o1', 'owner_email': 'hui@x.co', 'grants': {'location': true, 'call': false}}
      ];
      await boot(t, h);
      await t.tap(find.text('Where'));
      await t.pumpAndSettle();
      expect(find.textContaining('Updated 5 min ago'), findsOneWidget);
      expect(find.text('Calls off'), findsOneWidget);
    });

    testWidgets('both sides: Following tab appears and Switch side works', (t) async {
      final h = Harness()..gw.devices = [dev()];
      h.gw.watching = [
        {'link_id': 'l9', 'owner_id': 'o1', 'owner_email': 'hui@x.co', 'grants': {'location': true, 'call': true}}
      ];
      await boot(t, h);
      expect(h.session.hasBoth, isTrue);
      expect(find.bySemanticsLabel('Following'), findsOneWidget);
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
      await t.tap(find.text('Extra contrast'));
      await t.pumpAndSettle();
      expect(h.session.prefs.highContrast, isTrue);
      expect(await h.store.read('prefs'), contains('"contrast":true'));
    });

    testWidgets('beta needs agreement before it can be joined', (t) async {
      final h = Harness()..gw.devices = [dev()];
      await boot(t, h);
      await t.tap(find.bySemanticsLabel(RegExp('Settings')));
      await t.pumpAndSettle();
      await t.tap(find.text('Join the beta'));
      await t.pumpAndSettle();
      expect(find.text('JOIN THE BETA?'), findsOneWidget);
      await t.tap(find.text('Not now'));
      await t.pumpAndSettle();
      expect(h.gw.calls.contains('PUT /v1/me/beta'), isFalse);
      await t.tap(find.text('Join the beta'));
      await t.pumpAndSettle();
      await t.tap(find.text('I agree, join the beta'));
      await t.pumpAndSettle();
      expect(h.gw.bodies['PUT /v1/me/beta'], {'enabled': true, 'consent_version': 'v1'});
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
      await t.tap(find.text('Delete account'));
      await t.pumpAndSettle();
      await t.tap(find.text('Delete my account').last);
      await t.pumpAndSettle();
      expect(find.text('Enter your password to confirm.'), findsOneWidget);
    });
  });

  group('setup with a helper', () {
    Future<void> toPair(WidgetTester t) async {
      await t.tap(find.text('SET UP GLASSES'));
      await t.pumpAndSettle();
      await t.tap(find.text('Start with my helper'));
      await t.pumpAndSettle();
      await t.tap(find.text('Start step 1'));
      await t.pumpAndSettle();
    }

    testWidgets('five steps, owner confirms the code and the hand back', (t) async {
      final h = Harness();
      await boot(t, h);
      await t.tap(find.text('SET UP GLASSES'));
      await t.pumpAndSettle();
      await t.tap(find.text('Hear this screen'));
      await t.pump();
      expect(h.speaker.said.last, contains('A few steps need eyes'));
      await t.tap(find.text('Start with my helper'));
      await t.pumpAndSettle();
      expect(find.text('Stop helper mode'), findsOneWidget);
      await t.tap(find.text('Start step 1'));
      await t.pumpAndSettle();
      // pair: cable out first
      await t.enterText(find.byType(TextField), 'K7QM-4TXD');
      await t.tap(find.text('Pair glasses'));
      await t.pumpAndSettle();
      expect(find.textContaining('not plugged in'), findsOneWidget);
      expect(h.gw.calls.contains('POST /v1/claim'), isFalse);
      h.link.st = LinkState.connectedOnline;
      await t.tap(find.text('Pair glasses'));
      await t.pumpAndSettle();
      expect(find.textContaining('ends in 4 T X D'), findsOneWidget);
      expect(h.gw.calls.contains('POST /v1/claim'), isFalse);
      await t.tap(find.text('Yes, that is my box'));
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('POST /v1/claim'));
      expect(h.gw.bodies['POST /v1/claim']!['device_public_key'], 'AQID');
      await t.tap(find.text('Setting up? Continue to step 4'));
      await t.pumpAndSettle();
      await t.tap(find.text('Play a sound'));
      await t.tap(find.text('Make the glasses vibrate'));
      await t.tap(find.text('Say a word'));
      await t.pumpAndSettle();
      await t.tap(find.text('Yes, all good'));
      await t.pumpAndSettle();
      expect(find.text('HAND THE\nPHONE BACK'), findsOneWidget);
      h.ownerCheck.ok = false;
      await t.tap(find.text("Owner: I'm ready"));
      await t.pumpAndSettle();
      expect(find.textContaining('Not confirmed'), findsOneWidget);
      h.ownerCheck.ok = true;
      await t.tap(find.text("Owner: I'm ready"));
      await t.pumpAndSettle();
      expect(find.text('WELCOME'), findsWidgets);
    });

    testWidgets('a failed hand-over is reported, not hidden', (t) async {
      final h = Harness();
      h.link.st = LinkState.connectedOnline;
      h.link.handOverOk = false;
      await boot(t, h);
      await toPair(t);
      await t.enterText(find.byType(TextField), 'K7QM-4TXD');
      await t.tap(find.text('Pair glasses'));
      await t.pumpAndSettle();
      await t.tap(find.text('Yes, that is my box'));
      await t.pumpAndSettle();
      expect(find.textContaining('did not take it'), findsOneWidget);
    });

    testWidgets('stopping helper mode needs the owner to confirm', (t) async {
      final h = Harness();
      await boot(t, h);
      await t.tap(find.text('SET UP GLASSES'));
      await t.pumpAndSettle();
      await t.tap(find.text('Start with my helper'));
      await t.pumpAndSettle();
      h.ownerCheck.ok = false;
      await t.tap(find.text('Stop helper mode'));
      await t.pumpAndSettle();
      expect(find.text('Stop helper mode'), findsOneWidget);
      h.ownerCheck.ok = true;
      await t.tap(find.text('Stop helper mode'));
      await t.pumpAndSettle();
      expect(find.text('Stop helper mode'), findsNothing);
    });
  });

  group('links and expiry', () {
    testWidgets('an email verify link confirms the email', (t) async {
      final h = Harness();
      await boot(t, h, signedIn: false);
      h.linkSource.controller.add(Uri.parse('asirive://verify?token=abc'));
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('POST /v1/auth/verify'));
      expect(find.text('EMAIL\nCONFIRMED'), findsOneWidget);
    });

    testWidgets('a reset link asks for a new password and checks its length', (t) async {
      final h = Harness();
      await boot(t, h, signedIn: false);
      h.linkSource.controller.add(Uri.parse('asirive://reset?token=abc'));
      await t.pumpAndSettle();
      await t.enterText(find.byType(TextField), 'short');
      await t.tap(find.text('Save and sign in'));
      await t.pumpAndSettle();
      expect(find.text('Use at least 10 characters.'), findsOneWidget);
      await t.enterText(find.byType(TextField), 'a-long-new-password');
      await t.tap(find.text('Save and sign in'));
      await t.pumpAndSettle();
      expect(h.gw.bodies['POST /v1/auth/reset'], {'token': 'abc', 'password': 'a-long-new-password'});
    });

    testWidgets('an invite link opens the accept screen', (t) async {
      final h = Harness();
      await boot(t, h);
      h.linkSource.controller.add(Uri.parse('asirive://companion?code=K7Q2XM9'));
      await t.pumpAndSettle();
      expect(find.text('Accept'), findsOneWidget);
    });

    test('signing out in the middle of a call ends it instead of crashing', () async {
      final h = Harness();
      h.session.token = 'tok';
      final c = CallController(h.session);
      await c.startOutgoing('u2');
      h.session.token = null;
      await Future<void>.delayed(const Duration(milliseconds: 1700));
      expect(c.phase, isNot(CallPhase.ringing));
      c.dispose();
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
      expect(find.text('is calling you'), findsOneWidget);
      expect(find.text('Answer'), findsOneWidget);
      expect(h.speaker.said.last, 'Incoming call from hui@x.co.');
      await t.tap(find.text('Decline'));
      await t.pumpAndSettle();
      expect(h.gw.calls, contains('POST /v1/calls/call1/end'));
    });
  });
}
