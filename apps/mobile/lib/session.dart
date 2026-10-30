import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api.dart';

/// Where the sign-in token and small flags live. Secure storage on the phone,
/// memory in tests.
abstract class Store {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

class SecureStore implements Store {
  const SecureStore();
  static const _s = FlutterSecureStorage();
  @override
  Future<String?> read(String key) => _s.read(key: key);
  @override
  Future<void> write(String key, String value) => _s.write(key: key, value: value);
  @override
  Future<void> delete(String key) => _s.delete(key: key);
}

class MemoryStore implements Store {
  final Map<String, String> _m = {};
  @override
  Future<String?> read(String key) async => _m[key];
  @override
  Future<void> write(String key, String value) async => _m[key] = value;
  @override
  Future<void> delete(String key) async => _m.remove(key);
}

enum Phase { loading, signedOut, signedIn }

class Session extends ChangeNotifier {
  Session(this.api, this.store) {
    api.onSignedOut = expire;
  }

  final Api api;
  final Store store;

  Phase phase = Phase.loading;
  Account? account;
  String? token;
  bool introSeen = false;

  /// True after the server ended the session, so we can say so once.
  bool expired = false;

  static const _kToken = 'token';
  static const _kIntro = 'intro_seen';

  Future<void> start() async {
    introSeen = (await store.read(_kIntro)) == '1';
    final t = await store.read(_kToken);
    if (t == null) {
      phase = Phase.signedOut;
      notifyListeners();
      return;
    }
    try {
      account = await api.me(t);
      token = t;
      phase = Phase.signedIn;
    } on ApiException catch (e) {
      if (e.status == 0) {
        // Offline at launch: keep the token and let the person in; the next call re-checks it.
        token = t;
        account = Account(id: '', email: '');
        phase = Phase.signedIn;
      } else {
        await store.delete(_kToken);
        phase = Phase.signedOut;
      }
    }
    notifyListeners();
  }

  Future<void> markIntroSeen() async {
    introSeen = true;
    await store.write(_kIntro, '1');
    notifyListeners();
  }

  Future<void> signIn(String email, String password) async {
    final r = await api.login(email.trim(), password);
    token = r.token;
    account = r.account;
    expired = false;
    phase = Phase.signedIn;
    await store.write(_kToken, r.token);
    notifyListeners();
  }

  Future<void> signOut() async {
    final t = token;
    token = null;
    account = null;
    phase = Phase.signedOut;
    await store.delete(_kToken);
    notifyListeners();
    if (t != null) {
      try {
        await api.logout(t);
      } on ApiException {
        // Already signed out on the server, or offline. The token is gone locally either way.
      }
    }
  }

  void expire() {
    if (phase != Phase.signedIn) return;
    token = null;
    account = null;
    expired = true;
    phase = Phase.signedOut;
    store.delete(_kToken);
    notifyListeners();
  }
}
