import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api.dart';
import 'prefs.dart';
import 'services.dart';

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

enum Side { owner, companion }

class Session extends ChangeNotifier {
  Session(this.api, this.store, {Services? services, Prefs? prefs})
      : services = services ?? Services(),
        prefs = prefs ?? Prefs(store) {
    api.onSignedOut = expire;
  }

  final Api api;
  final Store store;
  final Services services;
  final Prefs prefs;

  List<Device> devices = [];
  Links links = Links([], []);
  Side side = Side.owner;
  String? pendingInvite;
  String? inviteNote; // shown once on Following after an invite was applied or failed

  /// Has glasses or has invited people.
  bool get canOwner => devices.isNotEmpty || links.owned.isNotEmpty;
  bool get canCompanion => links.watching.isNotEmpty;
  bool get hasBoth => canOwner && canCompanion;

  Phase phase = Phase.loading;
  Account? account;
  String? token;
  bool introSeen = false;

  /// True after the server ended the session, so we can say so once.
  bool expired = false;

  static const _kToken = 'token';
  static const _kIntro = 'intro_seen';

  Future<void> start() async {
    try {
      introSeen = (await store.read(_kIntro)) == '1';
      await prefs.load();
      services.speaker.setRate(prefs.speechRate);
    } on Exception {
      // unreadable storage: carry on with defaults, the person can still sign in
    }
    String? t;
    try {
      t = await store.read(_kToken);
    } on Exception {
      t = null;
    }
    if (t == null) {
      phase = Phase.signedOut;
      notifyListeners();
      return;
    }
    try {
      account = await api.me(t);
      token = t;
      await refresh();
      phase = Phase.signedIn;
    } on ApiException catch (e) {
      if (e.status == 401) {
        await _forget();
        phase = Phase.signedOut;
      } else {
        // Offline or the server is busy: keep the token and let the person in. The next call re-checks it.
        token = t;
        account = Account(id: '', email: '');
        phase = Phase.signedIn;
      }
    }
    notifyListeners();
  }

  Future<void> _forget() async {
    token = null;
    account = null;
    devices = [];
    links = Links([], []);
    pendingInvite = null;
    inviteNote = null;
    side = Side.owner;
    try {
      await store.delete(_kToken);
    } on Exception {
      // nothing more to do
    }
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
    await applyPendingInvite();
    await refresh();
    notifyListeners();
  }

  /// Joins whoever's invite was scanned before sign-in. Failure is kept as a note, not thrown.
  Future<void> applyPendingInvite() async {
    final code = pendingInvite;
    final t = token;
    if (code == null || t == null) return;
    pendingInvite = null;
    try {
      final f = await api.acceptInvite(t, code);
      inviteNote = 'You are now looking after ${f.ownerEmail}. They choose what you can see.';
    } on ApiException catch (e) {
      inviteNote = e.message;
    }
  }

  /// Reloads devices and people, then picks the side.
  Future<void> refresh() async {
    final t = token;
    if (t == null) return;
    try {
      final d = await api.devices(t);
      final l = await api.links(t);
      if (token != t) return; // signed out or switched account while we waited
      devices = d;
      links = l;
    } on ApiException {
      return; // keep what we had; the caller sees offline/session errors on its own calls
    }
    if (canCompanion && !canOwner) {
      side = Side.companion;
    } else if (canOwner && !canCompanion) {
      side = Side.owner;
    } else if (hasBoth) {
      side = prefs.side == 'companion' ? Side.companion : Side.owner;
    } else {
      side = prefs.side == 'companion' && canCompanion ? Side.companion : Side.owner;
    }
    notifyListeners();
  }

  void setAccount(Account a) {
    account = a;
    notifyListeners();
  }

  /// A readable name for an account id on a call.
  String nameFor(String accountId) {
    for (final f in links.watching) {
      if (f.ownerId == accountId) return f.ownerEmail;
    }
    for (final c in links.owned) {
      if (c.companionId == accountId) return c.label;
    }
    return 'Someone';
  }

  Future<void> switchSide(Side s) async {
    side = s;
    await prefs.update(side: s == Side.companion ? 'companion' : 'owner');
    notifyListeners();
  }

  Future<void> signOut() async {
    final t = token;
    await _forget();
    expired = false;
    phase = Phase.signedOut;
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
    expired = true;
    phase = Phase.signedOut;
    _forget();
    notifyListeners();
  }
}
