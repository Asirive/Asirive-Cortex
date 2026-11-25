import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cortex_app/box_link.dart';
import 'package:cortex_app/location_stream.dart';
import 'package:cortex_app/session.dart';
import 'package:flutter_test/flutter_test.dart';

/// The box's checks on a `location` op (core/cortex_core/link/gps.py parse_fix), so a fix it would refuse fails here.
String? boxRefuses(Map<String, dynamic> a) {
  String? chk(String k, double lo, double hi, {bool required = true}) {
    final v = a[k];
    if (v == null) return required ? '$k missing' : null;
    if (v is! num || !v.isFinite) return '$k is not a number';
    return v < lo || v > hi ? '$k out of range' : null;
  }

  return chk('lat', -90, 90) ??
      chk('lon', -180, 180) ??
      chk('acc_m', 0, 10000) ??
      chk('speed', 0, 100, required: false) ??
      chk('course', 0, 360, required: false) ??
      chk('t', 0, 1e11, required: false);
}

/// A paired box that takes `location` ops on one connection, signed like PHONE-BOX-LINK.md says.
class LocationBox {
  late HttpServer server;
  final secret = List<int>.filled(32, 7);
  final fixes = <Map<String, dynamic>>[];
  int connections = 0;
  bool paired = true;
  WebSocket? open;

  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((req) async {
      final ws = await WebSocketTransformer.upgrade(req);
      open = ws;
      connections++;
      const nonce = 'n-loc';
      var last = 0;
      ws.add(jsonEncode({'hello': {'v': 1, 'nonce': nonce, 'paired': paired}}));
      void reply(Map<String, dynamic> m) {
        try {
          ws.add(jsonEncode(m));
        } on StateError {
          // the test closed this connection
        }
      }

      ws.listen((raw) {
        final m = jsonDecode(raw as String) as Map<String, dynamic>;
        final id = m['id'] as int, op = m['op'] as String, args = Map<String, dynamic>.from(m['args'] as Map);
        if (m['mac'] != signRequest(secret, nonce, id, op, args) || id <= last || op != 'location') {
          return reply({'id': id, 'ok': false, 'error': 'bad signature'});
        }
        last = id;
        final why = boxRefuses(args);
        if (why == null) fixes.add(args);
        reply({'id': id, 'ok': why == null, if (why != null) 'error': 'bad fix: $why'});
      });
    });
  }

  BoxAddress get at => (address: InternetAddress.loopbackIPv4, port: server.port);
}

Fix fix(double lat, {double acc = 5, double? speed, double? course, DateTime? at}) =>
    Fix(lat, 103.8, acc, at ?? DateTime.now(), speed: speed, course: course);

Future<void> until(bool Function() ok, {Duration within = const Duration(seconds: 5)}) async {
  final end = DateTime.now().add(within);
  while (!ok()) {
    if (DateTime.now().isAfter(end)) throw TimeoutException('condition not met');
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

void main() {
  group('fixArgs is what the box accepts', () {
    test('seconds, not milliseconds; unknown speed and course left out', () {
      final at = DateTime.utc(2026, 11, 26, 1, 2, 3, 500);
      final a = fixArgs(fix(1.43, speed: -1, course: -1, at: at))!;
      expect(a['t'], 1795654923.5);
      expect(a.containsKey('speed'), isFalse);
      expect(a.containsKey('course'), isFalse);
      expect(boxRefuses(a), isNull);
      final b = fixArgs(fix(1.43, speed: 1.4, course: 359.5))!;
      expect(b['speed'], 1.4);
      expect(b['course'], 359.5);
      expect(boxRefuses(b), isNull);
    });

    test('NaN speed, huge accuracy, bad positions', () {
      final a = fixArgs(fix(1.43, speed: double.nan, acc: 25000))!;
      expect(a.containsKey('speed'), isFalse);
      expect(a['acc_m'], 10000.0);
      expect(boxRefuses(a), isNull);
      expect(fixArgs(fix(91)), isNull);
      expect(fixArgs(fix(double.nan)), isNull);
      expect(fixArgs(Fix(1.4, 200, 5, DateTime.now())), isNull);
      expect(fixArgs(fix(1.4, acc: -1)), isNull);
    });
  });

  group('streaming to a box', () {
    late LocationBox box;
    late BoxLink link;
    late MemoryStore store;
    setUp(() async {
      box = LocationBox();
      await box.start();
      store = MemoryStore();
      await store.write('box_link_secret', base64.encode(box.secret));
      link = BoxLink(store, find: () async => box.at, timeout: const Duration(seconds: 2));
    });
    tearDown(() => box.server.close(force: true));

    test('one connection carries every fix, at most one a second, newest first', () async {
      final gps = StreamController<Fix>();
      final s = LocationStreamer(link.locationSession, () => gps.stream, minGap: const Duration(milliseconds: 200));
      s.start();
      gps.add(fix(1.40));
      await until(() => box.fixes.length == 1);
      for (var i = 1; i <= 5; i++) {
        gps.add(fix(1.40 + i / 100)); // a burst: only the newest should go
      }
      await until(() => box.fixes.length == 2);
      await Future<void>.delayed(const Duration(milliseconds: 300));
      expect(box.fixes.length, 2);
      expect(box.fixes[1]['lat'], closeTo(1.45, 1e-9));
      expect(box.connections, 1);
      expect(s.sent, 2);
      await s.stop();
      await gps.close();
    });

    test('reconnects when the box drops the connection', () async {
      final gps = StreamController<Fix>();
      final s = LocationStreamer(link.locationSession, () => gps.stream,
          minGap: Duration.zero, retry: const Duration(milliseconds: 50));
      s.start();
      gps.add(fix(1.40));
      await until(() => box.fixes.length == 1);
      await box.open!.close(); // cable pulled / link service restarted
      await Future<void>.delayed(const Duration(milliseconds: 20));
      gps.add(fix(1.41)); // lost with the old connection, or sent on the new one
      await Future<void>.delayed(const Duration(milliseconds: 100));
      gps.add(fix(1.42));
      await until(() => box.fixes.any((f) => f['lat'] == 1.42));
      expect(box.connections, greaterThanOrEqualTo(2));
      expect(s.sessions, greaterThanOrEqualTo(2));
      await s.stop();
      await gps.close();
    });

    test('an unpaired box gets nothing, and the streamer keeps trying', () async {
      box.paired = false;
      final gps = StreamController<Fix>();
      final s = LocationStreamer(link.locationSession, () => gps.stream,
          minGap: Duration.zero, retry: const Duration(milliseconds: 30));
      s.start();
      gps.add(fix(1.4));
      await until(() => s.sessions >= 3);
      expect(box.fixes, isEmpty);
      await s.stop();
      await gps.close();
    });

    test('a refused fix is counted, the stream goes on', () async {
      final gps = StreamController<Fix>();
      final sentArgs = <Map<String, dynamic>>[];
      // a session that forwards a raw out-of-range value (as an older app would), then a good fix
      Future<bool> raw(Future<Map<String, dynamic>?> Function() next, void Function(bool) sent) =>
          link.locationSession(() async {
            final a = await next();
            if (a != null && sentArgs.isEmpty) a['speed'] = -1.0;
            if (a != null) sentArgs.add(a);
            return a;
          }, sent);
      final s = LocationStreamer(raw, () => gps.stream, minGap: Duration.zero);
      s.start();
      gps.add(fix(1.40));
      await until(() => s.refused == 1);
      gps.add(fix(1.41));
      await until(() => s.sent == 1);
      expect(box.fixes.single['lat'], 1.41);
      await s.stop();
      await gps.close();
    });

    test('stop ends the session cleanly', () async {
      final gps = StreamController<Fix>();
      final s = LocationStreamer(link.locationSession, () => gps.stream);
      s.start();
      await until(() => box.connections == 1);
      await s.stop();
      expect(s.running, isFalse);
      gps.add(fix(1.4));
      await Future<void>.delayed(const Duration(milliseconds: 100));
      expect(box.fixes, isEmpty);
      expect(s.sessions, 1);
      await gps.close();
    });
  });
}
