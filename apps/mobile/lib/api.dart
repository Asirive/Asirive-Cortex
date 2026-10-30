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
  Account({required this.id, required this.email, this.beta = false});
  final String id;
  final String email;
  final bool beta;

  factory Account.fromJson(Map<String, dynamic> j) =>
      Account(id: j['id'] as String, email: j['email'] as String, beta: j['beta'] == true);
}

class LoginResult {
  LoginResult(this.token, this.account);
  final String token;
  final Account account;
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
}
