import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'session.dart';

/// Voice, sound and text settings (APP-PLAN 10.7). Kept on the phone for now;
/// the server has no preferences endpoint yet (listed in APP-PLAN 16).
class Prefs extends ChangeNotifier {
  Prefs(this._store);
  final Store _store;

  double speechRate = 0.5; // slow 0.3 .. fast 0.7
  int haptic = 1; // 0 low, 1 medium, 2 high
  bool spokenAlerts = true;
  double textScale = 1.0; // 1.0 .. 2.0
  bool highContrast = false; // extra contrast
  bool readStatusOnOpen = true;
  bool incomingCalls = true;
  bool glassesAlerts = true;
  String side = ''; // 'owner' | 'companion' | '' (not chosen yet)

  static const _k = 'prefs';

  Future<void> load() async {
    final raw = await _store.read(_k);
    if (raw == null) return;
    try {
      final m = jsonDecode(raw) as Map<String, dynamic>;
      speechRate = (m['rate'] as num?)?.toDouble() ?? speechRate;
      haptic = (m['haptic'] as num?)?.toInt() ?? haptic;
      spokenAlerts = m['alerts'] as bool? ?? spokenAlerts;
      textScale = (m['text'] as num?)?.toDouble() ?? textScale;
      highContrast = m['contrast'] as bool? ?? highContrast;
      readStatusOnOpen = m['readOpen'] as bool? ?? readStatusOnOpen;
      incomingCalls = m['calls'] as bool? ?? incomingCalls;
      glassesAlerts = m['alerts2'] as bool? ?? glassesAlerts;
      side = (m['side'] as String?) ?? side;
    } on Exception {
      // bad file: keep defaults
    }
    notifyListeners();
  }

  Future<void> update({double? speechRate, int? haptic, bool? spokenAlerts, double? textScale, bool? highContrast, String? side, bool? readStatusOnOpen, bool? incomingCalls, bool? glassesAlerts}) async {
    this.speechRate = speechRate ?? this.speechRate;
    this.haptic = haptic ?? this.haptic;
    this.spokenAlerts = spokenAlerts ?? this.spokenAlerts;
    this.textScale = textScale ?? this.textScale;
    this.highContrast = highContrast ?? this.highContrast;
    this.side = side ?? this.side;
    this.readStatusOnOpen = readStatusOnOpen ?? this.readStatusOnOpen;
    this.incomingCalls = incomingCalls ?? this.incomingCalls;
    this.glassesAlerts = glassesAlerts ?? this.glassesAlerts;
    notifyListeners();
    await _store.write(
        _k,
        jsonEncode({
          'rate': this.speechRate,
          'haptic': this.haptic,
          'alerts': this.spokenAlerts,
          'text': this.textScale,
          'contrast': this.highContrast,
          'side': this.side,
          'readOpen': this.readStatusOnOpen,
          'calls': this.incomingCalls,
          'alerts2': this.glassesAlerts,
        }));
  }
}
