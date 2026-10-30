import 'dart:async';
import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

/// The phone's push address, as the gateway wants it: platform 'ios' + APNs token,
/// or 'android' + FCM token. The gateway sends a plain "Incoming call" alert; tapping it opens
/// the app, which then finds the ringing call.
typedef PushAddress = ({String platform, String token});

abstract class PushService {
  /// Asks permission and returns the address, or null when push is not set up or not allowed.
  Future<PushAddress?> address();
  /// Fires when the phone gets a new address; register it again.
  Stream<PushAddress> get refreshed;
}

class NoPush implements PushService {
  const NoPush();
  @override
  Future<PushAddress?> address() async => null;
  @override
  Stream<PushAddress> get refreshed => const Stream.empty();
}

/// Firebase for Android, and for the raw APNs token on iOS. Needs google-services.json
/// and GoogleService-Info.plist; without them [address] is null and the app falls back to polling.
class FirebasePush implements PushService {
  FirebaseMessaging? _m;

  Future<FirebaseMessaging?> _ready() async {
    if (_m != null) return _m;
    try {
      if (Firebase.apps.isEmpty) await Firebase.initializeApp();
      return _m = FirebaseMessaging.instance;
    } on Object {
      return null; // no Firebase config in this build
    }
  }

  @override
  Future<PushAddress?> address() async {
    final m = await _ready();
    if (m == null) return null;
    try {
      final p = await m.requestPermission(alert: true, badge: false, sound: true);
      if (p.authorizationStatus == AuthorizationStatus.denied) return null;
      if (Platform.isIOS) {
        for (var i = 0; i < 5; i++) {
          final t = await m.getAPNSToken();
          if (t != null) return (platform: 'ios', token: t);
          await Future<void>.delayed(const Duration(seconds: 1));
        }
        return null;
      }
      // ignore: deprecated_member_use
      final t = await m.getToken(); // the registration token the gateway's FCM v1 call expects
      return t == null ? null : (platform: 'android', token: t);
    } on Object {
      return null;
    }
  }

  @override
  Stream<PushAddress> get refreshed async* {
    final m = await _ready();
    if (m == null) return;
    // ignore: deprecated_member_use
    await for (final _ in m.onTokenRefresh) {
      final a = await address();
      if (a != null) yield a;
    }
  }
}
