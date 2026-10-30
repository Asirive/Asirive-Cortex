import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

/// Gateway base URL. Set with --dart-define=GATEWAY_URL=https://your.host
const gatewayUrl =
    String.fromEnvironment('GATEWAY_URL', defaultValue: 'https://gateway.example');

/// An error the gateway sent, already worded for a person to read.
class ApiException implements Exception {
  ApiException(this.status, this.code, this.message);
  final int status;
  final String code;
  final String message;

  bool get signedOut => status == 401 && code == 'signed_out';
  bool get unverified => code == 'unverified';

  @override
  String toString() => 'ApiException($status, $code, $message)';
}

class Account {
  Account({required this.id, required this.email, this.beta = false, this.betaConsent = ''});
  final String id;
  final String email;
  final bool beta;
  final String betaConsent;

  factory Account.fromJson(Map<String, dynamic> j) => Account(
      id: j['id'] as String,
      email: j['email'] as String,
      beta: j['beta'] == true,
      betaConsent: (j['beta_consent_version'] as String?) ?? '');
}

class LoginResult {
  LoginResult(this.token, this.account);
  final String token;
  final Account account;
}

class Device {
  Device({required this.id, this.label = '', this.online = false, this.battery, this.firmware = '', this.tier = '', this.safety = ''});
  final String safety; // OK | DEGRADED | FAULT, from the heartbeat
  final String id;
  final String label;
  final bool online;
  final int? battery;
  final String firmware;
  final String tier;
  factory Device.fromJson(Map<String, dynamic> j) => Device(
      id: j['id'] as String,
      label: (j['label'] as String?) ?? '',
      online: j['online'] == true,
      battery: (j['battery_pct'] as num?)?.toInt(),
      firmware: (j['firmware'] as String?) ?? '',
      tier: (j['tier'] as String?) ?? '',
      safety: (j['safety'] as String?) ?? '');
}

/// A person the owner invited (owner side).
class Companion {
  Companion({required this.id, this.companionId = '', required this.label, required this.state, required this.location, required this.call});
  final String id;
  final String companionId; // account id once accepted
  final String label;
  final String state; // pending | active | revoked
  final bool location;
  final bool call;
  factory Companion.fromJson(Map<String, dynamic> j) => Companion(
      id: j['id'] as String,
      companionId: (j['companion'] as String?) ?? '',
      label: (j['label'] as String?) ?? '',
      state: (j['state'] as String?) ?? 'pending',
      location: j['grant_location'] == true,
      call: j['grant_call'] == true);
}

/// Someone I look after (companion side).
class Following {
  Following({required this.linkId, required this.ownerId, required this.ownerEmail, required this.location, required this.call});
  final String linkId;
  final String ownerId;
  final String ownerEmail;
  final bool location;
  final bool call;
  factory Following.fromJson(Map<String, dynamic> j) {
    final g = (j['grants'] as Map?)?.cast<String, dynamic>() ?? {};
    return Following(
        linkId: j['link_id'] as String,
        ownerId: j['owner_id'] as String,
        ownerEmail: (j['owner_email'] as String?) ?? '',
        location: g['location'] == true,
        call: g['call'] == true);
  }
}

class Links {
  Links(this.owned, this.watching);
  final List<Companion> owned;
  final List<Following> watching;
}

class Invite {
  Invite(this.code, this.link);
  final String code;
  final String link;
}

class Point {
  Point(this.lat, this.lon, this.accuracy, this.at);
  final double lat, lon, accuracy;
  final DateTime at;
  factory Point.fromJson(Map<String, dynamic> j) => Point(
      (j['lat'] as num).toDouble(),
      (j['lon'] as num).toDouble(),
      (j['accuracy_m'] as num?)?.toDouble() ?? 0,
      DateTime.fromMillisecondsSinceEpoch((j['ts_ms'] as num).toInt()));
}

class CallInfo {
  CallInfo({required this.id, required this.from, required this.to, required this.state, this.offer = '', this.answer = '', this.ice = const []});
  final String id, from, to, state, offer, answer;
  final List<String> ice;
  factory CallInfo.fromJson(Map<String, dynamic> j) => CallInfo(
      id: j['id'] as String,
      from: (j['from'] as String?) ?? '',
      to: (j['to'] as String?) ?? '',
      state: (j['state'] as String?) ?? '',
      offer: (j['offer'] as String?) ?? '',
      answer: (j['answer'] as String?) ?? '',
      ice: ((j['ice'] as List?) ?? const []).cast<String>());
}

/// Thin client for the account endpoints in infra/gateway/internal/server/app.go.
class Api {
  Api({http.Client? client, String? baseUrl})
      : _http = client ?? http.Client(),
        _base = baseUrl ?? gatewayUrl;

  final http.Client _http;
  final String _base;

  /// Called when an authenticated request comes back 401 signed_out.
  void Function()? onSignedOut;

  Future<Map<String, dynamic>> _call(String method, String path,
      {Map<String, Object?>? body, String? token}) async {
    final uri = Uri.parse('$_base/v1$path');
    final headers = {
      'content-type': 'application/json',
      if (token != null) 'authorization': 'Bearer $token',
    };
    http.Response res;
    try {
      final req = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) req.body = jsonEncode(body);
      res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(seconds: 20)));
    } on SocketException {
      throw ApiException(0, 'offline', "Can't reach Cortex. Check your internet and try again.");
    } on http.ClientException {
      throw ApiException(0, 'offline', "Can't reach Cortex. Check your internet and try again.");
    } on Exception {
      throw ApiException(0, 'offline', "Can't reach Cortex. Check your internet and try again.");
    }
    Map<String, dynamic> data = {};
    try {
      final d = jsonDecode(utf8.decode(res.bodyBytes));
      if (d is Map<String, dynamic>) data = d;
    } on FormatException {
      // fall through with an empty body
    }
    if (res.statusCode >= 400) {
      final e = ApiException(res.statusCode, (data['error_code'] as String?) ?? 'error',
          (data['error'] as String?) ?? 'Something went wrong. Try again.');
      if (token != null && e.signedOut) onSignedOut?.call();
      throw e;
    }
    return data;
  }

  Future<void> register(String email, String password) =>
      _call('POST', '/auth/register', body: {'email': email, 'password': password});

  Future<void> verify(String token) => _call('POST', '/auth/verify', body: {'token': token});

  Future<void> resend(String email) => _call('POST', '/auth/resend', body: {'email': email});

  Future<LoginResult> login(String email, String password) async {
    final d = await _call('POST', '/auth/login', body: {'email': email, 'password': password});
    return LoginResult(d['token'] as String, Account.fromJson(d['account'] as Map<String, dynamic>));
  }

  Future<void> logout(String token) => _call('POST', '/auth/logout', token: token);

  Future<void> resetRequest(String email) =>
      _call('POST', '/auth/reset-request', body: {'email': email});

  Future<void> reset(String token, String password) =>
      _call('POST', '/auth/reset', body: {'token': token, 'password': password});

  Future<Account> me(String token) async =>
      Account.fromJson(await _call('GET', '/me', token: token));

  Future<List<dynamic>> _list(String path, String token) async {
    // List endpoints return a bare JSON array, which _call (map-only) would drop.
    final uri = Uri.parse('$_base/v1$path');
    http.Response res;
    try {
      res = await _http.get(uri, headers: {'authorization': 'Bearer $token'}).timeout(const Duration(seconds: 20));
    } on Exception {
      throw ApiException(0, 'offline', "Can't reach Cortex. Check your internet and try again.");
    }
    if (res.statusCode >= 400) {
      Map<String, dynamic> data = {};
      try {
        final d = jsonDecode(utf8.decode(res.bodyBytes));
        if (d is Map<String, dynamic>) data = d;
      } on FormatException {
        // keep empty
      }
      final e = ApiException(res.statusCode, (data['error_code'] as String?) ?? 'error',
          (data['error'] as String?) ?? 'Something went wrong. Try again.');
      if (e.signedOut) onSignedOut?.call();
      throw e;
    }
    final d = jsonDecode(utf8.decode(res.bodyBytes));
    return d is List ? d : <dynamic>[];
  }

  Future<List<Device>> devices(String token) async =>
      [for (final d in await _list('/me/devices', token)) Device.fromJson(d as Map<String, dynamic>)];

  Future<Links> links(String token) async {
    final d = await _call('GET', '/companions', token: token);
    return Links(
        [for (final c in (d['companions'] as List?) ?? const []) Companion.fromJson(c as Map<String, dynamic>)],
        [for (final c in (d['looking_after'] as List?) ?? const []) Following.fromJson(c as Map<String, dynamic>)]);
  }

  Future<Invite> invite(String token, String label) async {
    final d = await _call('POST', '/companions', body: {'label': label}, token: token);
    return Invite(d['invite_code'] as String, d['invite_link'] as String);
  }

  Future<Following> acceptInvite(String token, String code) async {
    final d = await _call('POST', '/companions/accept', body: {'code': code}, token: token);
    return Following.fromJson(d);
  }

  Future<void> setGrants(String token, String linkId, {required bool location, required bool call}) =>
      _call('PUT', '/companions/$linkId/grants', body: {'location': location, 'call': call}, token: token);

  Future<void> revoke(String token, String linkId) => _call('DELETE', '/companions/$linkId', token: token);

  Future<void> putLocation(String token, double lat, double lon, double acc) =>
      _call('PUT', '/me/location', body: {'lat': lat, 'lon': lon, 'accuracy_m': acc}, token: token);

  Future<void> clearLocation(String token) => _call('DELETE', '/me/location', token: token);

  Future<Point> locationOf(String token, String ownerId) async =>
      Point.fromJson(await _call('GET', '/companion/users/$ownerId/location', token: token));

  Future<void> setBeta(String token, bool enabled, String consent) =>
      _call('PUT', '/me/beta', body: {'enabled': enabled, 'consent_version': consent}, token: token);

  Future<void> feedback(String token, String text, String appVersion) => _call('POST', '/feedback',
      body: {'text': text, 'app_version': appVersion}, token: token);

  Future<void> deleteAccount(String token, String password) =>
      _call('DELETE', '/me', body: {'password': password}, token: token);

  Future<void> registerPush(String token, String platform, String pushToken) =>
      _call('PUT', '/me/push', body: {'platform': platform, 'token': pushToken}, token: token);

  Future<Map<String, dynamic>> claim(String token, String code, {List<int>? boxKey}) =>
      _call('POST', '/claim', body: {'claim_code': code, if (boxKey != null) 'device_public_key': base64Encode(boxKey)}, token: token);

  /// The update the box should install, or null when it is up to date (204).
  Future<Map<String, dynamic>?> updateOffer(String token, String deviceId) async {
    final uri = Uri.parse('$_base/v1/me/devices/$deviceId/update');
    http.Response res;
    try {
      res = await _http.get(uri, headers: {'authorization': 'Bearer $token'}).timeout(const Duration(seconds: 20));
    } on Exception {
      throw ApiException(0, 'offline', "Can't reach Cortex. Check your internet and try again.");
    }
    if (res.statusCode == 204) return null;
    if (res.statusCode >= 400) {
      throw ApiException(res.statusCode, 'error', 'Could not check for updates. Try again.');
    }
    final d = jsonDecode(utf8.decode(res.bodyBytes));
    return d is Map<String, dynamic> ? d : null;
  }

  Future<void> reportUpdate(String token, String deviceId, String releaseId, String outcome) =>
      _call('POST', '/me/devices/$deviceId/update',
          body: {'release_id': releaseId, 'outcome': outcome}, token: token);

  // Calls
  Future<String> startCall(String token, String to, String offer) async =>
      (await _call('POST', '/calls', body: {'to': to, 'offer': offer}, token: token))['call_id'] as String;

  Future<List<CallInfo>> inbox(String token) async =>
      [for (final c in await _list('/calls/inbox', token)) CallInfo.fromJson(c as Map<String, dynamic>)];

  Future<CallInfo> getCall(String token, String id) async =>
      CallInfo.fromJson(await _call('GET', '/calls/$id', token: token));

  Future<void> answerCall(String token, String id, String answer) =>
      _call('POST', '/calls/$id/answer', body: {'answer': answer}, token: token);

  Future<void> sendIce(String token, String id, String candidate) =>
      _call('POST', '/calls/$id/ice', body: {'candidate': candidate}, token: token);

  Future<void> endCall(String token, String id) => _call('POST', '/calls/$id/end', token: token);

  Future<List<Map<String, dynamic>>> iceServers(String token) async {
    final d = await _call('GET', '/calls/ice-servers', token: token);
    return ((d['ice_servers'] as List?) ?? const []).cast<Map<String, dynamic>>();
  }
}
