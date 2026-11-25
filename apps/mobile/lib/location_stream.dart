import 'dart:async';

import 'package:geolocator/geolocator.dart';

/// One phone GPS fix.
class Fix {
  const Fix(this.lat, this.lon, this.accM, this.at, {this.speed, this.course});
  final double lat, lon, accM;
  final DateTime at;
  final double? speed; // m/s; phones report -1 (or NaN) when they don't know
  final double? course; // degrees from north; same

  factory Fix.fromPosition(Position p) =>
      Fix(p.latitude, p.longitude, p.accuracy, p.timestamp, speed: p.speed, course: p.heading);
}

/// The box's signed `location` op arguments. Must match parse_fix in core/cortex_core/link/gps.py:
/// lat/lon in range, acc_m 0..10000, t in SECONDS (milliseconds are refused), speed 0..100 and course
/// 0..360 only when known (the box refuses the whole fix for an out-of-range value, so unknown = left out).
/// Null when the fix itself is unusable.
Map<String, dynamic>? fixArgs(Fix f) {
  bool ok(double? v, double lo, double hi) => v != null && v.isFinite && v >= lo && v <= hi;
  if (!ok(f.lat, -90, 90) || !ok(f.lon, -180, 180) || !f.accM.isFinite || f.accM < 0) return null;
  return {
    'lat': f.lat,
    'lon': f.lon,
    'acc_m': f.accM > 10000 ? 10000.0 : f.accM,
    't': f.at.millisecondsSinceEpoch / 1000.0,
    if (ok(f.speed, 0, 100)) 'speed': f.speed,
    if (ok(f.course, 0, 360)) 'course': f.course,
  };
}

/// What the streamer needs from the link: hold one session, send each fix [next] gives until it gives null.
/// Returns true when [next] ended it, false when the box could not be reached or the connection broke.
typedef LocationSession = Future<bool> Function(Future<Map<String, dynamic>?> Function() next, void Function(bool accepted) sent);

/// Phone GPS -> the glasses at most once per [minGap], newest fix first (a fix that waited is
/// stale; it is replaced, never queued). Reconnects after [retry] when the cable or box goes away.
class LocationStreamer {
  LocationStreamer(this._session, this._positions,
      {this.minGap = const Duration(seconds: 1), this.retry = const Duration(seconds: 3)});

  final LocationSession _session;
  final Stream<Fix> Function() _positions;
  final Duration minGap, retry;

  StreamSubscription<Fix>? _sub;
  Map<String, dynamic>? _latest;
  Completer<void>? _wake;
  DateTime _lastSent = DateTime.fromMillisecondsSinceEpoch(0);
  bool _running = false;
  int sent = 0, refused = 0, sessions = 0;

  bool get running => _running;

  void start() {
    if (_running) return;
    _running = true;
    _sub = _positions().listen((f) {
      final a = fixArgs(f);
      if (a == null) return;
      _latest = a;
      _poke();
    }, onError: (_) {}); // a GPS error is not a reason to stop; the next fix may come
    unawaited(_loop());
  }

  Future<void> stop() async {
    _running = false;
    _poke();
    await _sub?.cancel();
    _sub = null;
  }

  void _poke() {
    final w = _wake;
    if (w != null && !w.isCompleted) w.complete();
  }

  Future<Map<String, dynamic>?> _next() async {
    while (_running) {
      if (_latest != null) {
        final wait = minGap - DateTime.now().difference(_lastSent);
        if (wait > Duration.zero) {
          await Future<void>.delayed(wait);
          continue;
        }
        final a = _latest;
        _latest = null;
        _lastSent = DateTime.now();
        return a;
      }
      _wake = Completer<void>();
      await _wake!.future;
    }
    return null;
  }

  Future<void> _loop() async {
    while (_running) {
      sessions++;
      final ended = await _session(_next, (ok) => ok ? sent++ : refused++);
      if (ended || !_running) break;
      await Future<void>.delayed(retry);
    }
  }
}

/// The phone's position stream for navigation: best accuracy, every update. Empty when permission is off.
Stream<Fix> phonePositions() async* {
  var p = await Geolocator.checkPermission();
  if (p == LocationPermission.denied) p = await Geolocator.requestPermission();
  if (p == LocationPermission.denied || p == LocationPermission.deniedForever) return;
  yield* Geolocator.getPositionStream(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.bestForNavigation, distanceFilter: 0))
      .map(Fix.fromPosition);
}
