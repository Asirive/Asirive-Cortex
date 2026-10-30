import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../services.dart';
import '../session.dart';
import '../scope.dart';
import '../theme.dart';
import '../widgets.dart';

enum CallPhase { starting, ringing, connected, ended, failed }

/// Runs one call: signalling through the gateway, media through [CallEngine].
class CallController extends ChangeNotifier {
  CallController(this.session);
  final Session session;

  CallPhase phase = CallPhase.starting;
  String? message;
  bool muted = false;
  bool speaker = false;
  DateTime? connectedAt;

  CallEngine? _engine;
  String? _id;
  Timer? _poll;
  Timer? _giveUp;
  StreamSubscription<bool>? _sub;
  final List<String> _queued = [];
  int _iceSeen = 0;
  bool _answerSet = false;
  bool _closed = false;

  String get _token => session.token!;

  Future<List<Map<String, dynamic>>> _ice() => session.api.iceServers(_token);

  void _onCandidate(String c) {
    if (_id == null) {
      _queued.add(c);
    } else {
      session.api.sendIce(_token, _id!, c).catchError((_) {});
    }
  }

  Future<void> _flush() async {
    for (final c in _queued) {
      await session.api.sendIce(_token, _id!, c).catchError((_) {});
    }
    _queued.clear();
  }

  void _watch() {
    _sub = _engine!.connected.listen((up) {
      if (up && phase != CallPhase.connected) {
        phase = CallPhase.connected;
        connectedAt = DateTime.now();
        _giveUp?.cancel();
        notifyListeners();
      }
    });
    _poll = Timer.periodic(const Duration(milliseconds: 1500), (_) => _tick());
  }

  Future<void> _tick() async {
    if (_closed || _id == null) return;
    try {
      final c = await session.api.getCall(_token, _id!);
      if (c.answer.isNotEmpty && !_answerSet) {
        _answerSet = true;
        await _engine!.setAnswer(c.answer);
      }
      while (_iceSeen < c.ice.length) {
        await _engine!.addCandidate(c.ice[_iceSeen++]);
      }
      if (c.state == 'active' && phase == CallPhase.ringing) {
        phase = CallPhase.connected;
        connectedAt ??= DateTime.now();
        notifyListeners();
      }
      if (c.state == 'ended' || c.state == 'declined' || c.state == 'missed') {
        await _finish(c.state == 'declined' ? 'They declined.' : c.state == 'missed' ? 'No answer.' : 'The call ended.', CallPhase.ended);
      }
    } on ApiException catch (e) {
      if (e.status == 404) await _finish('The call ended.', CallPhase.ended);
    }
  }

  Future<void> _finish(String msg, CallPhase p) async {
    if (_closed) return;
    _closed = true;
    _poll?.cancel();
    _giveUp?.cancel();
    await _sub?.cancel();
    await _engine?.close();
    phase = p;
    message = msg;
    notifyListeners();
  }

  Future<void> startOutgoing(String toAccountId) async {
    try {
      _engine = session.services.callEngine();
      final ice = await _ice();
      final offer = await _engine!.createOffer(ice, _onCandidate);
      _id = await session.api.startCall(_token, toAccountId, offer);
      await _flush();
      phase = CallPhase.ringing;
      notifyListeners();
      _watch();
      _giveUp = Timer(const Duration(seconds: 45), () async {
        await hangUp(message: 'No answer.');
      });
    } on ApiException catch (e) {
      await _finish(e.code == 'not_allowed' ? 'They have not allowed calls from you.' : e.message, CallPhase.failed);
    } on Exception {
      await _finish('The call could not start. Check the microphone is allowed for Cortex.', CallPhase.failed);
    }
  }

  Future<void> answerIncoming(CallInfo call) async {
    try {
      _id = call.id;
      _engine = session.services.callEngine();
      final full = await session.api.getCall(_token, call.id);
      final ice = await _ice();
      final answer = await _engine!.acceptOffer(full.offer, ice, _onCandidate);
      await session.api.answerCall(_token, call.id, answer);
      await _flush();
      phase = CallPhase.ringing;
      _answerSet = true;
      notifyListeners();
      _watch();
    } on ApiException catch (e) {
      await _finish(e.message, CallPhase.failed);
    } on Exception {
      await _finish('Could not join the call. Check the microphone is allowed for Cortex.', CallPhase.failed);
    }
  }

  Future<void> decline(String id) async {
    try {
      await session.api.endCall(_token, id);
    } on ApiException {
      // already ended
    }
    await _finish('Declined.', CallPhase.ended);
  }

  Future<void> hangUp({String message = 'The call ended.'}) async {
    final id = _id;
    if (id != null) {
      try {
        await session.api.endCall(_token, id);
      } on ApiException {
        // already ended
      }
    }
    await _finish(message, CallPhase.ended);
  }

  void toggleMute() {
    muted = !muted;
    _engine?.setMuted(muted);
    notifyListeners();
  }

  Future<void> toggleSpeaker() async {
    speaker = !speaker;
    await _engine?.setSpeaker(speaker);
    notifyListeners();
  }

  @override
  void dispose() {
    _closed = true;
    _poll?.cancel();
    _giveUp?.cancel();
    _sub?.cancel();
    _engine?.close();
    super.dispose();
  }
}

class _Round extends StatelessWidget {
  const _Round({required this.label, required this.icon, required this.on, required this.onTap});
  final String label;
  final IconData icon;
  final bool on;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        toggled: on,
        label: label,
        excludeSemantics: true,
        child: GestureDetector(
          onTap: onTap,
          child: Column(children: [
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(shape: BoxShape.circle, color: on ? Cx.accent : Colors.transparent, border: Border.all(color: on ? Cx.accent : Cx.outline, width: 1.5)),
              child: Icon(icon, size: 30, color: on ? Cx.ground : Cx.text),
            ),
            const SizedBox(height: 8),
            Text(label, style: Cx.small),
          ]),
        ),
      );
}

/// The call itself. Used for both outgoing and answered calls.
class CallScreen extends StatefulWidget {
  const CallScreen({super.key, required this.name, this.toAccountId, this.incoming});
  final String name;
  final String? toAccountId; // outgoing
  final CallInfo? incoming; // answered
  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  CallController? c;
  Timer? clock;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (c != null) return;
    final s = SessionScope.of(context);
    c = CallController(s);
    if (widget.incoming != null) {
      c!.answerIncoming(widget.incoming!);
    } else {
      c!.startOutgoing(widget.toAccountId!);
    }
    clock = Timer.periodic(const Duration(seconds: 1), (_) => mounted ? setState(() {}) : null);
  }

  @override
  void dispose() {
    clock?.cancel();
    c?.dispose();
    super.dispose();
  }

  String _dur() {
    final t = c!.connectedAt;
    if (t == null) return '';
    final d = DateTime.now().difference(t);
    return '${d.inMinutes}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: c!,
        builder: (context, _) {
          final ctl = c!;
          final over = ctl.phase == CallPhase.ended || ctl.phase == CallPhase.failed;
          final status = switch (ctl.phase) {
            CallPhase.starting => 'Starting the call',
            CallPhase.ringing => widget.incoming != null ? 'Connecting' : 'Ringing',
            CallPhase.connected => 'On a call ${_dur()}',
            _ => ctl.message ?? 'The call ended.',
          };
          return PopScope(
            canPop: over,
            child: CxScreen(children: [
              const CxTop(back: false, trailing: CxLogo()),
              const SizedBox(height: 24),
              Center(child: ExcludeSemantics(child: CircleAvatar(radius: 56, backgroundColor: Cx.accent, child: Text(initialsOf(widget.name), style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w700, color: Cx.ground))))),
              Center(child: Text(widget.name, style: Cx.strong.copyWith(fontSize: 24))),
              Center(child: Semantics(liveRegion: true, child: Text(status, style: Cx.body))),
              if (!over)
                Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  _Round(label: 'Mute', icon: ctl.muted ? Icons.mic_off : Icons.mic, on: ctl.muted, onTap: ctl.toggleMute),
                  const SizedBox(width: 32),
                  _Round(label: 'Speaker', icon: Icons.volume_up, on: ctl.speaker, onTap: ctl.toggleSpeaker),
                ]),
            ], bottom: [
              if (over) CxButton('Back', onTap: () => Navigator.of(context).pop()) else CxButton('End call', outline: true, danger: true, onTap: ctl.hangUp),
            ]),
          );
        },
      );
}

String initialsOf(String s) {
  final t = s.trim();
  return t.isEmpty ? '?' : t.substring(0, 1).toUpperCase();
}

/// Opened by the inbox poll in the shell, or by a push. Answer comes first.
class IncomingCallScreen extends StatefulWidget {
  const IncomingCallScreen({super.key, required this.call});
  final CallInfo call;
  @override
  State<IncomingCallScreen> createState() => _IncomingCallScreenState();
}

class _IncomingCallScreenState extends State<IncomingCallScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final s = SessionScope.of(context);
      if (s.prefs.spokenAlerts) s.services.speaker.say('Incoming call from ${s.nameFor(widget.call.from)}.');
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final name = s.nameFor(widget.call.from);
    return CxScreen(children: [
      const CxTop(back: false, trailing: CxLogo()),
      const SizedBox(height: 24),
      Center(child: ExcludeSemantics(child: CircleAvatar(radius: 56, backgroundColor: Cx.accent, child: Text(initialsOf(name), style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w700, color: Cx.ground))))),
      Center(child: Text(name, style: Cx.strong.copyWith(fontSize: 24))),
      const Center(child: CxText('Incoming call')),
    ], bottom: [
      CxButton('Answer', onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => CallScreen(name: name, incoming: widget.call)))),
      CxButton('Decline', outline: true, danger: true, onTap: () async {
        final nav = Navigator.of(context);
        try {
          await s.api.endCall(s.token!, widget.call.id);
        } on ApiException {
          // already gone
        }
        nav.pop();
      }),
    ]);
  }
}
