import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cortex_app/box_link.dart';
import 'package:cortex_app/location_stream.dart';
import 'package:cortex_app/session.dart';
import 'package:flutter_test/flutter_test.dart';

/// Run by core/tests/test_phone_gps_cross.py against the REAL Python phone link (not a fake box).
/// It sets CORTEX_BOX_PORT and CORTEX_BOX_SECRET (base64); without them this test is skipped.
void main() {
  final env = Platform.environment;
  final port = int.tryParse(env['CORTEX_BOX_PORT'] ?? '');
  final secret = env['CORTEX_BOX_SECRET'];

  test('the app streams fixes the real box accepts', () async {
    final store = MemoryStore();
    await store.write('box_link_secret', secret!);
    final link = BoxLink(store, find: () async => (address: InternetAddress.loopbackIPv4, port: port!));
    final gps = StreamController<Fix>();
    final s = LocationStreamer(link.locationSession, () => gps.stream, minGap: const Duration(milliseconds: 50));
    s.start();
    final t0 = DateTime.utc(2026, 11, 26, 2, 0, 0);
    // what phones really send: unknown speed/course as -1, a NaN, a fractional timestamp
    final fixes = [
      Fix(1.4295, 103.8355, 6, t0, speed: -1, course: -1),
      Fix(1.4296, 103.8356, 5.5, t0.add(const Duration(milliseconds: 1500)), speed: 1.3, course: 90),
      Fix(1.4297, 103.8357, 4, t0.add(const Duration(seconds: 3)), speed: double.nan, course: 359.9),
    ];
    for (final f in fixes) {
      gps.add(f);
      final want = s.sent + 1;
      final end = DateTime.now().add(const Duration(seconds: 5));
      while (s.sent < want && s.refused == 0) {
        if (DateTime.now().isAfter(end)) fail('box did not take the fix (sent ${s.sent}, refused ${s.refused})');
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
    }
    expect(s.refused, 0);
    expect(s.sent, 3);
    await s.stop();
    await gps.close();
    stdout.writeln('CROSS-OK ${jsonEncode({'sent': s.sent, 'sessions': s.sessions})}');
  }, skip: port == null || secret == null ? 'run from core/tests/test_phone_gps_cross.py' : false);
}
