import 'dart:async';
import 'dart:convert';

import 'package:app_links/app_links.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:geolocator/geolocator.dart';
import 'package:local_auth/local_auth.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api.dart';
import 'push.dart';

/// Everything that touches the phone's hardware or OS sits behind one of these,
/// so screens can be tested with fakes and the real parts swapped in one place.

abstract class Speaker {
  Future<void> say(String text);
  Future<void> stop();
  void setRate(double rate); // 0.3 slow .. 0.7 fast
}

class TtsSpeaker implements Speaker {
  final FlutterTts _t = FlutterTts();
  @override
  Future<void> say(String text) async {
    try {
      await _t.stop();
      await _t.speak(text);
    } on Exception {
      // no speech engine: the text is still on screen
    }
  }

  @override
  Future<void> stop() async => _t.stop();
  @override
  void setRate(double rate) {
    _t.setSpeechRate(rate).catchError((_) => 0);
  }
}

abstract class LocationSource {
  /// Current position, or null when permission is off or location is unavailable.
  Future<Point?> current();
}

class GeoLocationSource implements LocationSource {
  @override
  Future<Point?> current() async {
    var p = await Geolocator.checkPermission();
    if (p == LocationPermission.denied) p = await Geolocator.requestPermission();
    if (p == LocationPermission.denied || p == LocationPermission.deniedForever) return null;
    try {
      final x = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 15)));
      return Point(x.latitude, x.longitude, x.accuracy, DateTime.now());
    } on Exception {
      return null;
    }
  }
}

enum OwnerResult { confirmed, declined, unavailable }

abstract class OwnerCheck {
  /// Face ID, fingerprint or passcode. [OwnerResult.unavailable] when the phone has none set up.
  Future<OwnerResult> confirm(String reason);
}

class DeviceOwnerCheck implements OwnerCheck {
  final _auth = LocalAuthentication();
  @override
  Future<OwnerResult> confirm(String reason) async {
    try {
      if (!await _auth.isDeviceSupported()) return OwnerResult.unavailable;
      return await _auth.authenticate(localizedReason: reason) ? OwnerResult.confirmed : OwnerResult.declined;
    } on LocalAuthException catch (e) {
      final c = e.code;
      if (c == LocalAuthExceptionCode.noBiometricsEnrolled || c == LocalAuthExceptionCode.noCredentialsSet || c == LocalAuthExceptionCode.noBiometricHardware || c == LocalAuthExceptionCode.biometricHardwareTemporarilyUnavailable) {
        return OwnerResult.unavailable;
      }
      return OwnerResult.declined;
    } on Exception {
      return OwnerResult.unavailable;
    }
  }
}

abstract class Opener {
  Future<void> open(Uri uri);
}

class UrlOpener implements Opener {
  @override
  Future<void> open(Uri uri) async {
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }
}

/// State of the cable to the pocket box, as the app sees it.
enum LinkState { cableOut, connectedOnline, connectedNoInternet }

/// The phone-to-box link over the USB-C cable (docs/architecture/PHONE-BOX-LINK.md).
/// [BoxLink] is the real one; [UnavailableLink] reports the cable as out (tests, web).
abstract class DeviceLink {
  Future<LinkState> state();
  Future<String?> boxCodeTail(); // last 4 characters of the box code, read back to the owner
  Future<List<int>?> boxPublicKey(); // DER public key the box makes for itself; the gateway pins it at claim
  Future<bool> pause(); // local command; obstacle warnings keep running
  Future<bool> resume();
  Future<bool> internetFromBox(); // can the box reach the gateway?
  Future<bool> handOver(Map<String, dynamic> claimReply, String claimCode); // the whole /claim reply, after the owner confirmed the box
  Future<bool> installUpdate(Map<String, dynamic> manifest); // hand the signed update to the box
  Future<bool> playTest(String kind); // 'sound' | 'vibrate' | 'voice' on the glasses
}

class UnavailableLink implements DeviceLink {
  const UnavailableLink();
  @override
  Future<LinkState> state() async => LinkState.cableOut;
  @override
  Future<String?> boxCodeTail() async => null;
  @override
  Future<List<int>?> boxPublicKey() async => null;
  @override
  Future<bool> pause() async => false;
  @override
  Future<bool> resume() async => false;
  @override
  Future<bool> internetFromBox() async => false;
  @override
  Future<bool> handOver(Map<String, dynamic> claimReply, String claimCode) async => false;
  @override
  Future<bool> installUpdate(Map<String, dynamic> manifest) async => false;
  @override
  Future<bool> playTest(String kind) async => false;
}

/// Links that open the app: asirive://verify?token=, asirive://reset?token=, asirive://companion?code=.
abstract class LinkSource {
  Future<Uri?> initial();
  Stream<Uri> get stream;
}

class AppLinkSource implements LinkSource {
  final _l = AppLinks();
  @override
  Future<Uri?> initial() async {
    try {
      return await _l.getInitialLink();
    } on Exception {
      return null;
    }
  }

  @override
  Stream<Uri> get stream => _l.uriLinkStream;
}

/// Opens the phone's mail app.
Uri mailAppUri() => defaultTargetPlatform == TargetPlatform.iOS ? Uri.parse('message://') : Uri.parse('mailto:');

/// Camera view that reports each code it reads.
typedef ScanViewBuilder = Widget Function(BuildContext context, void Function(String code) onCode, ValueListenable<bool> torch);

Widget realScanView(BuildContext context, void Function(String code) onCode, ValueListenable<bool> torch) => _RealScan(onCode: onCode, torch: torch);

class _RealScan extends StatefulWidget {
  const _RealScan({required this.onCode, required this.torch});
  final void Function(String) onCode;
  final ValueListenable<bool> torch;
  @override
  State<_RealScan> createState() => _RealScanState();
}

class _RealScanState extends State<_RealScan> {
  final _c = MobileScannerController();
  bool _on = false;

  @override
  void initState() {
    super.initState();
    widget.torch.addListener(_t);
  }

  void _t() {
    if (widget.torch.value != _on) {
      _on = widget.torch.value;
      _c.toggleTorch();
    }
  }

  @override
  void dispose() {
    widget.torch.removeListener(_t);
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MobileScanner(
      controller: _c,
      onDetect: (capture) {
        for (final b in capture.barcodes) {
          final v = b.rawValue;
          if (v != null && v.isNotEmpty) {
            widget.onCode(v);
            return;
          }
        }
      },
    );
}

/// Pulls the invite code from a scanned value: the full link or a bare code.
String? inviteCodeFrom(String raw) {
  final s = raw.trim();
  final u = Uri.tryParse(s);
  final q = u?.queryParameters['code'];
  final c = (q ?? s).replaceAll('-', '').replaceAll(' ', '').toUpperCase();
  return RegExp(r'^[A-Z0-9]{6,16}$').hasMatch(c) ? c : null;
}

/// Pulls the box claim code from asirive://claim?code=XXXXXXXX or a typed code.
String? claimCodeFrom(String raw) {
  final s = raw.trim();
  final u = Uri.tryParse(s);
  final c = (u != null && u.scheme == 'asirive' ? u.queryParameters['code'] : s) ?? '';
  final t = c.toUpperCase().replaceAll(' ', '');
  return RegExp(r'^[A-Z0-9]{4}-?[A-Z0-9]{4}$').hasMatch(t)
      ? (t.contains('-') ? t : '${t.substring(0, 4)}-${t.substring(4)}')
      : null;
}

/// Voice call between two accounts. Signalling goes through the gateway (see [Api]).
abstract class CallEngine {
  Future<String> createOffer(List<Map<String, dynamic>> ice, void Function(String candidate) onCandidate);
  Future<String> acceptOffer(String offer, List<Map<String, dynamic>> ice, void Function(String candidate) onCandidate);
  Future<void> setAnswer(String answer);
  Future<void> addCandidate(String candidate);
  void setMuted(bool muted);
  Future<void> setSpeaker(bool on);
  Stream<bool> get connected;
  Future<void> close();
}

class WebRtcEngine implements CallEngine {
  RTCPeerConnection? _pc;
  MediaStream? _mic;
  final _conn = StreamController<bool>.broadcast();

  Future<RTCPeerConnection> _open(List<Map<String, dynamic>> ice, void Function(String) onCandidate) async {
    final pc = await createPeerConnection({'iceServers': ice});
    _pc = pc;
    _mic = await navigator.mediaDevices.getUserMedia({'audio': true, 'video': false});
    for (final t in _mic!.getAudioTracks()) {
      await pc.addTrack(t, _mic!);
    }
    pc.onIceCandidate = (c) {
      if (c.candidate == null) return;
      onCandidate(jsonEncode({'candidate': c.candidate, 'sdpMid': c.sdpMid, 'sdpMLineIndex': c.sdpMLineIndex}));
    };
    pc.onConnectionState = (s) {
      if (s == RTCPeerConnectionState.RTCPeerConnectionStateConnected) _conn.add(true);
      if (s == RTCPeerConnectionState.RTCPeerConnectionStateFailed ||
          s == RTCPeerConnectionState.RTCPeerConnectionStateClosed ||
          s == RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
        _conn.add(false);
      }
    };
    return pc;
  }

  @override
  Future<String> createOffer(List<Map<String, dynamic>> ice, void Function(String) onCandidate) async {
    final pc = await _open(ice, onCandidate);
    final o = await pc.createOffer({'offerToReceiveAudio': true});
    await pc.setLocalDescription(o);
    return jsonEncode({'sdp': o.sdp, 'type': o.type});
  }

  @override
  Future<String> acceptOffer(String offer, List<Map<String, dynamic>> ice, void Function(String) onCandidate) async {
    final pc = await _open(ice, onCandidate);
    final m = jsonDecode(offer) as Map<String, dynamic>;
    await pc.setRemoteDescription(RTCSessionDescription(m['sdp'] as String, m['type'] as String));
    final a = await pc.createAnswer();
    await pc.setLocalDescription(a);
    return jsonEncode({'sdp': a.sdp, 'type': a.type});
  }

  @override
  Future<void> setAnswer(String answer) async {
    final m = jsonDecode(answer) as Map<String, dynamic>;
    await _pc?.setRemoteDescription(RTCSessionDescription(m['sdp'] as String, m['type'] as String));
  }

  @override
  Future<void> addCandidate(String candidate) async {
    final m = jsonDecode(candidate) as Map<String, dynamic>;
    await _pc?.addCandidate(RTCIceCandidate(m['candidate'] as String?, m['sdpMid'] as String?, m['sdpMLineIndex'] as int?));
  }

  @override
  void setMuted(bool muted) {
    for (final t in _mic?.getAudioTracks() ?? <MediaStreamTrack>[]) {
      t.enabled = !muted;
    }
  }

  @override
  Future<void> setSpeaker(bool on) => Helper.setSpeakerphoneOn(on);

  @override
  Stream<bool> get connected => _conn.stream;

  @override
  Future<void> close() async {
    for (final t in _mic?.getTracks() ?? <MediaStreamTrack>[]) {
      await t.stop();
    }
    await _mic?.dispose();
    await _pc?.close();
    _pc = null;
    _mic = null;
  }
}

class Services {
  Services({
    Speaker? speaker,
    LocationSource? location,
    OwnerCheck? ownerCheck,
    Opener? opener,
    DeviceLink? link,
    ScanViewBuilder? scanView,
    CallEngine Function()? callEngine,
    LinkSource? links,
    PushService? push,
  })  : speaker = speaker ?? TtsSpeaker(),
        location = location ?? GeoLocationSource(),
        ownerCheck = ownerCheck ?? DeviceOwnerCheck(),
        opener = opener ?? UrlOpener(),
        link = link ?? const UnavailableLink(),
        scanView = scanView ?? realScanView,
        callEngine = callEngine ?? WebRtcEngine.new,
        links = links ?? AppLinkSource(),
        push = push ?? FirebasePush();

  final Speaker speaker;
  final LocationSource location;
  final OwnerCheck ownerCheck;
  final Opener opener;
  final DeviceLink link;
  final ScanViewBuilder scanView;
  final CallEngine Function() callEngine;
  final LinkSource links;
  final PushService push;
}
