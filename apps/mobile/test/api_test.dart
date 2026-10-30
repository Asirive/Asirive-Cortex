import 'dart:convert';

import 'package:cortex_app/api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Api apiWith(Future<http.Response> Function(http.Request) h) =>
    Api(client: MockClient(h), baseUrl: 'https://gw.test');

http.Response json(int code, Object body) =>
    http.Response(jsonEncode(body), code, headers: {'content-type': 'application/json'});

void main() {
  test('login returns token and account', () async {
    final api = apiWith((r) async {
      expect(r.url.toString(), 'https://gw.test/v1/auth/login');
      expect(jsonDecode(r.body), {'email': 'a@b.co', 'password': 'pw'});
      return json(200, {
        'token': 't1',
        'account': {'id': 'x', 'email': 'a@b.co', 'beta': false}
      });
    });
    final r = await api.login('a@b.co', 'pw');
    expect(r.token, 't1');
    expect(r.account.email, 'a@b.co');
  });

  test('server errors keep their wording and code', () async {
    final api = apiWith((r) async =>
        json(403, {'error': 'Confirm your email first.', 'error_code': 'unverified'}));
    try {
      await api.login('a@b.co', 'pw');
      fail('should throw');
    } on ApiException catch (e) {
      expect(e.unverified, isTrue);
      expect(e.message, 'Confirm your email first.');
    }
  });

  test('authenticated call sends bearer and reports signed_out', () async {
    var called = false;
    final api = apiWith((r) async {
      expect(r.headers['authorization'], 'Bearer tok');
      return json(401, {'error': 'Please sign in again.', 'error_code': 'signed_out'});
    })
      ..onSignedOut = () => called = true;
    await expectLater(api.me('tok'), throwsA(isA<ApiException>()));
    expect(called, isTrue);
  });

  test('bad login 401 is not treated as a session ending', () async {
    var called = false;
    final api = apiWith((r) async =>
        json(401, {'error': 'Email or password is wrong.', 'error_code': 'bad_credentials'}))
      ..onSignedOut = () => called = true;
    await expectLater(api.login('a@b.co', 'x'), throwsA(isA<ApiException>()));
    expect(called, isFalse);
  });

  test('no network gives a plain offline error', () async {
    final api = apiWith((r) async => throw http.ClientException('down'));
    try {
      await api.register('a@b.co', 'longenoughpw');
      fail('should throw');
    } on ApiException catch (e) {
      expect(e.status, 0);
      expect(e.code, 'offline');
    }
  });
}
