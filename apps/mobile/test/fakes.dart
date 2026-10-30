import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cortex_app/api.dart';
import 'package:cortex_app/prefs.dart';
import 'package:cortex_app/push.dart';
import 'package:cortex_app/services.dart';
import 'package:cortex_app/session.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeSpeaker implements Speaker {
  final said = <String>[];
  @override
  Future<void> say(String text) async => said.add(text);
  @override
  Future<void> stop() async {}
  @override
  void setRate(double rate) {}
}

class FakeLocation implements LocationSource {
  Point? at = Point(1.30, 103.80, 12, DateTime.now());
  @override
  Future<Point?> current() async => at;
}

class FakeOwnerCheck implements OwnerCheck {
  bool ok = true;
  bool unavailable = false;
  @override
  Future<OwnerResult> confirm(String reason) async => unavailable ? OwnerResult.unavailable : (ok ? OwnerResult.confirmed : OwnerResult.declined);
}

class FakeOpener implements Opener {
  final opened = <Uri>[];
  @override
  Future<void> open(Uri uri) async => opened.add(uri);
}

class FakeLinks implements LinkSource {
  final controller = StreamController<Uri>.broadcast();
  Uri? first;
  @override
  Future<Uri?> initial() async => first;
  @override
  Stream<Uri> get stream => controller.stream;
}

class FakeLink implements DeviceLink {
  LinkState st = LinkState.cableOut;
  bool pauseOk = true, internetOk = true, handOverOk = true, installOk = true;
  int paused = 0;
  @override
  Future<LinkState> state() async => st;
  @override
  Future<String?> boxCodeTail() async => null;
  @override
  Future<List<int>?> boxPublicKey() async => [1, 2, 3];
  @override
  Future<bool> pause() async {
    paused++;
    return pauseOk;
  }

  @override
  Future<bool> resume() async => true;
  @override
  Future<bool> internetFromBox() async => internetOk;
  @override
  Future<bool> handOver(Map<String, dynamic> claimReply) async => handOverOk;
  @override
  Future<bool> installUpdate(Map<String, dynamic> manifest) async => installOk;
  final tested = <String>[];
  @override
  Future<bool> playTest(String kind) async {
    tested.add(kind);
    return true;
  }
}

class FakeEngine implements CallEngine {
  final candidates = <String>[];
  String? answerSet;
  bool closed = false;
  bool muted = false;
  final _c = StreamController<bool>.broadcast();
  void emitConnected(bool v) => _c.add(v);
  @override
  Future<String> createOffer(List<Map<String, dynamic>> ice, void Function(String) onCandidate) async {
    onCandidate('{"candidate":"c1"}');
    return '{"sdp":"offer","type":"offer"}';
  }

  @override
  Future<String> acceptOffer(String offer, List<Map<String, dynamic>> ice, void Function(String) onCandidate) async =>
      '{"sdp":"answer","type":"answer"}';
  @override
  Future<void> setAnswer(String answer) async => answerSet = answer;
  @override
  Future<void> addCandidate(String candidate) async => candidates.add(candidate);
  @override
  void setMuted(bool m) => muted = m;
  @override
  Future<void> setSpeaker(bool on) async {}
  @override
  Stream<bool> get connected => _c.stream;
  @override
  Future<void> close() async => closed = true;
}

/// An in-memory gateway for the endpoints the app uses.
class FakeGateway {
  List<Map<String, dynamic>> devices = [];
  List<Map<String, dynamic>> owned = [];
  List<Map<String, dynamic>> watching = [];
  final calls = <String>[]; // "METHOD path"
  final bodies = <String, Map<String, dynamic>>{};
  Map<String, dynamic>? update;
  final pushed = <Map>[];
  final pushCleared = <String>[];
  Map<String, dynamic> account = {'id': 'me', 'email': 'me@x.co', 'beta': false, 'beta_consent_version': 'v1'};
  bool loginOk = true;
  http.Response Function(http.Request)? override;
  Map<String, dynamic> callState = {'id': 'call1', 'state': 'ringing', 'from': 'me', 'to': 'u2'};
  List<Map<String, dynamic>> inbox = [];

  http.Response _j(int code, Object body) => http.Response(jsonEncode(body), code, headers: {'content-type': 'application/json'});

  Future<http.Response> handle(http.Request r) async {
    final key = '${r.method} ${r.url.path}';
    calls.add(key);
    if (r.body.isNotEmpty) bodies[key] = jsonDecode(r.body) as Map<String, dynamic>;
    if (override != null) return override!(r);
    switch (key) {
      case 'POST /v1/auth/login':
        return loginOk
            ? _j(200, {'token': 'tok', 'account': account})
            : _j(401, {'error': 'Email or password is wrong.', 'error_code': 'bad_credentials'});
      case 'POST /v1/auth/register':
        return _j(200, {'result': 'check_email'});
      case 'POST /v1/auth/verify':
        return _j(200, {'result': 'verified'});
      case 'POST /v1/auth/reset':
        return _j(200, {'result': 'reset'});
      case 'POST /v1/auth/logout':
        return _j(200, {'result': 'signed_out'});
      case 'GET /v1/me':
        return _j(200, account);
      case 'GET /v1/me/devices':
        return _j(200, devices);
      case 'GET /v1/companions':
        return _j(200, {'companions': owned, 'looking_after': watching});
      case 'POST /v1/companions':
        return _j(200, {'invite_code': 'K7Q2-XM9', 'invite_link': 'https://app/companion?code=K7Q2XM9'});
      case 'POST /v1/companions/accept':
        if (r.body.contains('BADCODE')) return _j(422, {'error': 'That invite code is wrong or has expired. Ask for a new one.', 'error_code': 'invalid_or_expired'});
        watching = [
          {'link_id': 'l9', 'owner_id': 'o1', 'owner_email': 'hui@x.co', 'grants': {'location': false, 'call': false}}
        ];
        return _j(200, watching.first);
      case 'PUT /v1/me/location':
      case 'DELETE /v1/me/location':
        return _j(200, {'result': 'ok'});
      case 'PUT /v1/me/push':
        pushed.add(jsonDecode(r.body) as Map);
        return _j(200, {'result': 'ok'});
      case 'DELETE /v1/me/push':
        pushCleared.add((jsonDecode(r.body) as Map)['token'] as String);
        return _j(200, {'result': 'ok'});
      case 'POST /v1/feedback':
        return _j(200, {'result': 'received'});
      case 'PUT /v1/me/beta':
        account = {...account, 'beta': (jsonDecode(r.body) as Map)['enabled'] == true};
        return _j(200, {'beta': account['beta']});
      case 'POST /v1/claim':
        return _j(200, {'device_id': 'd1', 'device_token': 'dt'});
      case 'GET /v1/calls/ice-servers':
        return _j(200, {'ice_servers': []});
      case 'POST /v1/calls':
        return _j(200, {'call_id': 'call1'});
      case 'GET /v1/calls/call1':
        return _j(200, callState);
      case 'POST /v1/calls/call1/end':
      case 'POST /v1/calls/call1/ice':
      case 'POST /v1/calls/call1/answer':
        return _j(200, {'result': 'ok'});
      case 'GET /v1/calls/inbox':
        return _j(200, inbox);
    }
    if (r.url.path.endsWith('/grants') || r.method == 'DELETE' && r.url.path.startsWith('/v1/companions/')) {
      return _j(200, {'result': 'ok'});
    }
    if (r.url.path.startsWith('/v1/companion/users/')) {
      return _j(200, {'lat': 1.3, 'lon': 103.8, 'accuracy_m': 10, 'ts_ms': DateTime.now().subtract(const Duration(minutes: 5)).millisecondsSinceEpoch});
    }
    if (r.url.path.endsWith('/update')) {
      return update == null ? http.Response('', 204) : _j(200, update!);
    }
    return _j(404, {'error': 'Not found.', 'error_code': 'not_found'});
  }
}

class FakePush implements PushService {
  PushAddress? addr = (platform: 'android', token: 'fcm-1');
  final refresh = StreamController<PushAddress>.broadcast();
  @override
  Future<PushAddress?> address() async => addr;
  @override
  Stream<PushAddress> get refreshed => refresh.stream;
}

class Harness {
  Harness({FakeGateway? gw, MemoryStore? store})
      : gw = gw ?? FakeGateway(),
        store = store ?? MemoryStore() {
    session = Session(Api(client: MockClient(this.gw.handle), baseUrl: 'https://gw.test'), this.store,
        services: Services(
            speaker: speaker,
            location: location,
            ownerCheck: ownerCheck,
            opener: opener,
            link: link,
            scanView: (c, onCode, torch) => TextButton(onPressed: () => onCode('https://app/companion?code=K7Q2XM9'), child: const Text('fake scan')),
            callEngine: () => engine,
            links: linkSource,
            push: push),
        prefs: Prefs(this.store));
  }
  final FakeGateway gw;
  final MemoryStore store;
  final speaker = FakeSpeaker();
  final location = FakeLocation();
  final ownerCheck = FakeOwnerCheck();
  final opener = FakeOpener();
  final link = FakeLink();
  final engine = FakeEngine();
  final linkSource = FakeLinks();
  final push = FakePush();
  late final Session session;
}

bool _fonts = false;

/// Real fonts, so text wraps as it does on a phone (the default test font is far wider).
Future<void> loadFonts() async {
  if (_fonts) return;
  _fonts = true;
  for (final e in {
    'Anton': 'assets/fonts/Anton-Regular.ttf',
    'SpaceGrotesk': 'assets/fonts/SpaceGrotesk.ttf',
    'JetBrainsMono': 'assets/fonts/JetBrainsMono.ttf',
  }.entries) {
    final l = FontLoader(e.key)..addFont(Future.value(ByteData.view(File(e.value).readAsBytesSync().buffer)));
    await l.load();
  }
  final icons = File('/opt/flutter/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf');
  if (icons.existsSync()) {
    final l = FontLoader('MaterialIcons')..addFont(Future.value(ByteData.view(icons.readAsBytesSync().buffer)));
    await l.load();
  }
}

void phone(WidgetTester t) {
  t.view.physicalSize = const Size(1170, 2532);
  t.view.devicePixelRatio = 3;
  addTearDown(t.view.reset);
}
