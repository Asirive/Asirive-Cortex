import 'dart:convert';
import 'dart:io';

import 'package:cortex_app/box_link.dart';
import 'package:cortex_app/services.dart';
import 'package:cortex_app/session.dart';
import 'package:flutter_test/flutter_test.dart';

/// A tiny box that follows PHONE-BOX-LINK.md, so the app side is tested against the wire format.
class FakeBox {
  late HttpServer server;
  bool paired = false;
  List<int>? secret;
  int last = 0;
  final ops = <String>[];
  bool internet = true;

  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((req) async {
      final ws = await WebSocketTransformer.upgrade(req);
      const nonce = 'nonce-1';
      last = 0;
      ws.add(jsonEncode({'hello': {'v': 1, 'nonce': nonce, 'paired': paired, 'public_key': base64.encode([9, 8, 7]), 'box_tail': '4TXD'}}));
      ws.listen((raw) {
        final m = jsonDecode(raw as String) as Map<String, dynamic>;
        final id = m['id'] as int, op = m['op'] as String, args = Map<String, dynamic>.from(m['args'] as Map);
        Map<String, dynamic> out(Map<String, dynamic> b) => {'id': id, ...b};
        if (op == 'provision') {
          if (paired) return ws.add(jsonEncode(out({'ok': false, 'error': 'already paired'})));
          paired = true;
          secret = base64.decode(args['link_secret'] as String);
          ops.add('provision:${(args['reply'] as Map)['device_id']}:${args['gateway_ws_url']}');
          return ws.add(jsonEncode(out({'ok': true})));
        }
        if (!paired || m['mac'] != signRequest(secret!, nonce, id, op, args) || id <= last) {
          return ws.add(jsonEncode(out({'ok': false, 'error': 'bad signature'})));
        }
        last = id;
        ops.add(op);
        ws.add(jsonEncode(out(op == 'internet' || op == 'status' ? {'ok': true, 'internet': internet} : {'ok': true})));
      });
    });
  }

  BoxAddress get at => (address: InternetAddress.loopbackIPv4, port: server.port);
}

void main() {
  test('signatures match the box (same bytes as the Python test vectors)', () {
    final s = List<int>.filled(32, 's'.codeUnitAt(0));
    expect(signRequest(s, 'n', 2, 'pause', {'confirmed': true}), 'C0GUpVRfHtxaaR7wwcwbuAkTC2kYH4SEvCkmahdjKH8=');
    expect(
        signRequest(s, 'n', 3, 'install', {
          'manifest': {
            'b': [1, {'z': 'é"', 'a': null}],
            'a': 1.5
          }
        }),
        'y3iE7zQCJ7qkRBNjs+XilTXBAe89c26sTR9P1dhSP6s=');
  });

  group('against a box', () {
    late FakeBox box;
    late MemoryStore store;
    late BoxLink link;
    setUp(() async {
      box = FakeBox();
      await box.start();
      store = MemoryStore();
      link = BoxLink(store, find: () async => box.at, gatewayWsUrl: 'wss://gw.example:8443/ws/device');
    });
    tearDown(() => box.server.close(force: true));

    test('unpaired box: reads its key and code tail, hands over, then signs commands', () async {
      expect(await link.boxPublicKey(), [9, 8, 7]);
      expect(await link.boxCodeTail(), '4TXD');
      expect(await link.state(), LinkState.connectedOnline);
      expect(await link.pause(), isFalse); // nothing is signed before pairing
      expect(await link.handOver({'device_id': 'd1', 'device_token': 't'}), isTrue);
      expect(box.ops.single, 'provision:d1:wss://gw.example:8443/ws/device');
      expect(await store.read('box_link_secret'), isNotNull);
      expect(await link.pause(), isTrue);
      expect(await link.resume(), isTrue);
      expect(await link.playTest('sound'), isTrue);
      expect(await link.installUpdate({'release_id': 'r1'}), isTrue);
      expect(box.ops.skip(1), ['pause', 'resume', 'test', 'install']);
    });

    test('paired box reports internet or not', () async {
      await link.handOver({'device_id': 'd1'});
      expect(await link.state(), LinkState.connectedOnline);
      box.internet = false;
      expect(await link.state(), LinkState.connectedNoInternet);
      expect(await link.internetFromBox(), isFalse);
    });

    test('a phone without the secret is refused', () async {
      await link.handOver({'device_id': 'd1'});
      final other = BoxLink(MemoryStore(), find: () async => box.at);
      expect(await other.pause(), isFalse);
    });

    test('a second hand-over is refused and the first secret survives', () async {
      await link.handOver({'device_id': 'd1'});
      final first = await store.read('box_link_secret');
      expect(await link.handOver({'device_id': 'd2'}), isFalse);
      expect(await store.read('box_link_secret'), first);
    });
  });

  test('no box on the cable means cable out, and commands fail plainly', () async {
    final link = BoxLink(MemoryStore(), find: () async => null);
    expect(await link.state(), LinkState.cableOut);
    expect(await link.pause(), isFalse);
    expect(await link.boxPublicKey(), isNull);
  });

  test('a box that never answers times out instead of hanging', () async {
    final dead = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(dead.close);
    final link = BoxLink(MemoryStore(), find: () async => (address: InternetAddress.loopbackIPv4, port: dead.port), timeout: const Duration(milliseconds: 300));
    expect(await link.state(), LinkState.cableOut);
  });
}
