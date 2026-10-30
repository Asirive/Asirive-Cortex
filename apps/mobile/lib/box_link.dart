import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';

import 'api.dart';
import 'services.dart';
import 'session.dart';

/// Where the box is on the tether network.
typedef BoxAddress = ({InternetAddress address, int port});

/// The box shouts "I am here" on UDP 8766 about every 2 seconds. No secrets in it.
Future<BoxAddress?> findBoxByBeacon({Duration wait = const Duration(seconds: 4), int beaconPort = 8766}) async {
  RawDatagramSocket? sock;
  try {
    sock = await RawDatagramSocket.bind(InternetAddress.anyIPv4, beaconPort, reuseAddress: true);
    final done = Completer<BoxAddress?>();
    final sub = sock.listen((e) {
      if (e != RawSocketEvent.read || done.isCompleted) return;
      final d = sock!.receive();
      if (d == null) return;
      try {
        final m = jsonDecode(utf8.decode(d.data)) as Map<String, dynamic>;
        if (m['cortex'] is int && m['port'] is int) done.complete((address: d.address, port: m['port'] as int));
      } on Object {
        // not ours
      }
    });
    final r = await done.future.timeout(wait, onTimeout: () => null);
    await sub.cancel();
    return r;
  } on Object {
    return null; // no network on the cable, or the OS refused the socket
  } finally {
    sock?.close();
  }
}

/// Same text the box builds: keys sorted, no spaces. Must match core/cortex_core/link/phone_link.py.
String canonicalJson(Object? v) {
  Object? sort(Object? x) => x is Map ? {for (final k in (x.keys.toList()..sort())) k: sort(x[k])} : (x is List ? x.map(sort).toList() : x);
  return jsonEncode(sort(v));
}

String signRequest(List<int> secret, String nonce, int id, String op, Map<String, dynamic> args) =>
    base64.encode(Hmac(sha256, secret).convert(utf8.encode('$nonce|$id|$op|${canonicalJson(args)}')).bytes);

/// The real phone-to-box link: WebSocket to the box over the USB tether network.
/// One short connection per action: hello, the request, close.
class BoxLink implements DeviceLink {
  BoxLink(this._store, {Future<BoxAddress?> Function()? find, String? gatewayWsUrl, this._timeout = const Duration(seconds: 8)})
      : _find = find ?? findBoxByBeacon,
        _wsUrl = gatewayWsUrl ?? deviceWsUrl;

  final Store _store;
  final Future<BoxAddress?> Function() _find;
  final String _wsUrl;
  final Duration _timeout;
  static const _secretKey = 'box_link_secret';

  Future<List<int>?> _secret() async {
    final s = await _store.read(_secretKey);
    return s == null ? null : base64.decode(s);
  }

  /// Opens a connection, reads hello, runs [body], always closes. Null when the box cannot be reached.
  Future<T?> _session<T>(Future<T> Function(Map<String, dynamic> hello, Future<Map<String, dynamic>> Function(String op, Map<String, dynamic> args, {bool signed,}) call) body) async {
    final at = await _find();
    if (at == null) return null;
    WebSocket? ws;
    try {
      ws = await WebSocket.connect('ws://${at.address.address}:${at.port}').timeout(_timeout);
      final frames = StreamIterator(ws.map((e) => e is String ? jsonDecode(e) as Map<String, dynamic> : <String, dynamic>{}));
      Future<Map<String, dynamic>> next() async {
        if (!await frames.moveNext().timeout(_timeout)) throw const SocketException('closed');
        return frames.current;
      }

      final hello = (await next())['hello'] as Map<String, dynamic>;
      final secret = await _secret();
      var id = 0;
      Future<Map<String, dynamic>> call(String op, Map<String, dynamic> args, {bool signed = true,}) async {
        id++;
        final req = <String, dynamic>{'id': id, 'op': op, 'args': args};
        if (signed && secret != null) req['mac'] = signRequest(secret, hello['nonce'] as String, id, op, args);
        ws!.add(jsonEncode(req));
        return next();
      }

      return await body(hello, call);
    } on Object {
      return null;
    } finally {
      await ws?.close();
    }
  }

  @override
  Future<LinkState> state() async {
    final r = await _session<LinkState>((hello, call) async {
      if (hello['paired'] != true) return LinkState.connectedOnline; // not paired yet: reachable is all we can say
      final s = await call('status', {});
      return s['ok'] == true && s['internet'] == true ? LinkState.connectedOnline : LinkState.connectedNoInternet;
    });
    return r ?? LinkState.cableOut;
  }

  @override
  Future<String?> boxCodeTail() => _session<String?>((h, _) async => h['box_tail'] as String?);

  @override
  Future<List<int>?> boxPublicKey() => _session<List<int>?>((h, _) async => h['public_key'] is String ? base64.decode(h['public_key'] as String) : null);

  Future<bool> _simple(String op, Map<String, dynamic> args) async => await _session<bool>((_, call) async => (await call(op, args))['ok'] == true) ?? false;

  @override
  Future<bool> pause() => _simple('pause', {'confirmed': true}); // the app asked the owner first
  @override
  Future<bool> resume() => _simple('resume', {});
  @override
  Future<bool> internetFromBox() async => await _session<bool>((_, call) async {
        final r = await call('internet', {});
        return r['ok'] == true && r['internet'] == true;
      }) ??
      false;
  @override
  Future<bool> installUpdate(Map<String, dynamic> manifest) => _simple('install', {'manifest': manifest});
  @override
  Future<bool> playTest(String kind) => _simple('test', {'kind': kind});

  @override
  Future<bool> handOver(Map<String, dynamic> claimReply) async {
    final rnd = Random.secure();
    final secret = List<int>.generate(32, (_) => rnd.nextInt(256));
    final ok = await _session<bool>((_, call) async {
          final r = await call('provision', {'reply': claimReply, 'link_secret': base64.encode(secret), 'gateway_ws_url': _wsUrl}, signed: false);
          return r['ok'] == true;
        }) ??
        false;
    if (ok) await _store.write(_secretKey, base64.encode(secret));
    return ok;
  }
}

/// Where the box dials the gateway (mTLS). Set with --dart-define=DEVICE_WS_URL if it is not the REST host.
String get deviceWsUrl {
  const set = String.fromEnvironment('DEVICE_WS_URL');
  return set.isNotEmpty ? set : '${gatewayUrl.replaceFirst('https://', 'wss://')}/ws/device';
}
