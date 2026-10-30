import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import 'people.dart';
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

  String get _token {
    final t = session.token;
    if (t == null) throw ApiException(401, 'signed_out', 'You were signed out.');
    return t;
  }

  bool _ticking = false;

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
    if (_closed || _id == null || _ticking) return;
    _ticking = true;
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
      if (e.status == 404 || e.signedOut) await _finish('The call ended.', CallPhase.ended);
    } on Exception {
      // a bad candidate or a dropped request: the next tick tries again
    } finally {
      _ticking = false;
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
      if (_closed) return;
      _id = await session.api.startCall(_token, toAccountId, offer);
      if (_closed) {
        // the caller hung up while the call was being made
        session.api.endCall(_token, _id!).catchError((_) {});
        return;
      }
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
    } on Exception {
      // already ended
    } finally {
      await _finish('Declined.', CallPhase.ended);
    }
  }

  Future<void> hangUp({String message = 'The call ended.'}) async {
    final id = _id;
    try {
      if (id != null) await session.api.endCall(_token, id);
    } on Exception {
      // already ended, or signed out: still close the microphone below
    } finally {
      await _finish(message, CallPhase.ended);
    }
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

class _Rb extends StatelessWidget {
  const _Rb({required this.label, required this.icon, required this.onTap, this.on = false, this.color, this.size = 68, this.semantic});
  final String label;
  final IconData icon;
  final VoidCallback? onTap;
  final bool on;
  final Color? color;
  final double size;
  final String? semantic;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        toggled: color == null ? on : null,
        label: semantic ?? label,
        excludeSemantics: true,
        child: GestureDetector(
          onTap: onTap,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Container(
              width: size,
              height: size,
              decoration: BoxDecoration(shape: BoxShape.circle, color: color ?? (on ? Cx.accent : Cx.surface), border: color == null && !on ? Border.all(color: Cx.outline, width: 1.5) : null),
              child: Icon(icon, size: 30, color: color != null || on ? Cx.ground : Cx.text),
            ),
            const SizedBox(height: 10),
            Text(label, style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 14, fontWeight: FontWeight.w600, color: Cx.text)),
          ]),
        ),
      );
}

const _coral = Color(0xFFFF6B5E);

Widget _bigAvatar(String name, {bool halo = false}) => ExcludeSemantics(
      child: Container(
        width: 132,
        height: 132,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Cx.accent,
          boxShadow: halo
              ? const [BoxShadow(color: Cx.surface, spreadRadius: 14), BoxShadow(color: Cx.line, spreadRadius: 15), BoxShadow(color: Color(0xFF0F150F), spreadRadius: 32)]
              : null,
        ),
        child: Text(initials(name), style: const TextStyle(fontFamily: 'Anton', fontSize: 52, color: Cx.ground)),
      ),
    );

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
    if (t == null) return '00:00';
    final d = DateTime.now().difference(t);
    return '${d.inMinutes.toString().padLeft(2, '0')}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';
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
            CallPhase.connected => _dur(),
            _ => ctl.message ?? 'The call ended.',
          };
          final connected = ctl.phase == CallPhase.connected;
          return PopScope(
            canPop: over,
            child: CxScreen(children: [
              const SizedBox(height: 62),
              const Center(child: Text('VOICE CALL · NOT RECORDED', style: Cx.label)),
              const SizedBox(height: 12),
              Center(child: _bigAvatar(widget.name)),
              const SizedBox(height: 12),
              Center(child: Semantics(header: true, child: Text(widget.name.toUpperCase(), textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis, style: Cx.display.copyWith(fontSize: 52, color: Cx.text, letterSpacing: 1.5)))),
              Center(
                child: Semantics(
                  liveRegion: true,
                  label: connected ? 'Call time ${_dur()}' : status,
                  excludeSemantics: true,
                  child: Text(status, textAlign: TextAlign.center, style: connected ? const TextStyle(fontFamily: 'JetBrainsMono', fontSize: 24, letterSpacing: 1.4, color: Cx.accent) : Cx.body.copyWith(fontSize: 18, color: over && ctl.phase == CallPhase.failed ? Cx.danger : Cx.muted)),
                ),
              ),
            ], bottom: [
              if (!over) ...[
                Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  _Rb(label: 'Mute', icon: ctl.muted ? Icons.mic_off : Icons.mic_none, on: ctl.muted, onTap: ctl.toggleMute),
                  const SizedBox(width: 44),
                  _Rb(label: 'Speaker', icon: Icons.volume_up_outlined, on: ctl.speaker, onTap: ctl.toggleSpeaker),
                ]),
                const SizedBox(height: 30),
                Center(child: _Rb(label: 'End call', icon: Icons.call_end, color: _coral, size: 76, onTap: ctl.hangUp)),
                const SizedBox(height: 36),
              ] else
                CxButton('Back', onTap: () => Navigator.of(context).pop()),
            ]),
          );
        },
      );
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

  Future<void> _decline() async {
    final s = SessionScope.of(context);
    final nav = Navigator.of(context);
    try {
      await s.api.endCall(s.token!, widget.call.id);
    } on Exception {
      // already gone
    }
    if (nav.canPop()) nav.pop();
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final name = s.nameFor(widget.call.from);
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _decline();
      },
      child: CxScreen(children: [
        const SizedBox(height: 62),
        const Center(child: Text('CORTEX VOICE CALL', style: Cx.label)),
        const SizedBox(height: 26),
        Center(child: _bigAvatar(name, halo: true)),
        const SizedBox(height: 32),
        Center(child: Semantics(header: true, child: Text(name.toUpperCase(), textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis, style: Cx.display.copyWith(fontSize: 52, color: Cx.text, letterSpacing: 1.5)))),
        Center(child: Text('is calling you', style: Cx.body.copyWith(fontSize: 18))),
      ], bottom: [
        Row(textDirection: TextDirection.rtl, mainAxisAlignment: MainAxisAlignment.center, children: [
          _Rb(label: 'Answer', semantic: 'Answer call from $name', icon: Icons.call, color: Cx.accent, onTap: () => Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => CallScreen(name: name, incoming: widget.call)))),
          const SizedBox(width: 84),
          _Rb(label: 'Decline', icon: Icons.call_end, color: _coral, onTap: _decline),
        ]),
        const SizedBox(height: 40),
      ]),
    );
  }
}
