import 'dart:async';

import 'package:flutter/material.dart';

import 'scope.dart';
import 'theme.dart';
import 'widgets.dart';

void push(BuildContext context, Widget page) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => page));

String ago(DateTime t, [DateTime? now]) {
  final d = (now ?? DateTime.now()).difference(t);
  if (d.inSeconds < 60) return 'just now';
  if (d.inMinutes < 60) return '${d.inMinutes} min ago';
  if (d.inHours < 24) return '${d.inHours} h ago';
  return '${d.inDays} days ago';
}

/// A confirmation sheet (APP-PLAN 14.5): the safe choice first, the action second.
/// [onConfirm] runs when the action is tapped; return an error text to keep the sheet open.
Future<bool> confirmSheet(
  BuildContext context, {
  required String mono,
  required String title,
  required String confirmLabel,
  String? body,
  Widget? bodyWidget,
  String? small,
  String cancelLabel = 'Cancel',
  bool danger = true,
  Widget? extra,
  Future<String?> Function()? onConfirm,
  String? speak,
}) async {
  final session = SessionScope.of(context);
  if (session.prefs.spokenAlerts) session.services.speaker.say(speak ?? '$title. ${body ?? ''}');
  final r = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    barrierColor: const Color(0xA6000000),
    builder: (c) => _SheetBody(
      mono: mono,
      title: title,
      body: body,
      bodyWidget: bodyWidget,
      small: small,
      cancelLabel: cancelLabel,
      confirmLabel: confirmLabel,
      danger: danger,
      extra: extra,
      onConfirm: onConfirm,
    ),
  );
  return r ?? false;
}

class _SheetBody extends StatefulWidget {
  const _SheetBody({required this.mono, required this.title, required this.cancelLabel, required this.confirmLabel, required this.danger, this.body, this.bodyWidget, this.small, this.extra, this.onConfirm});
  final String mono, title, cancelLabel, confirmLabel;
  final String? body, small;
  final Widget? bodyWidget, extra;
  final bool danger;
  final Future<String?> Function()? onConfirm;
  @override
  State<_SheetBody> createState() => _SheetBodyState();
}

class _SheetBodyState extends State<_SheetBody> {
  bool busy = false;
  String? err;

  Future<void> _go() async {
    if (widget.onConfirm == null) {
      Navigator.pop(context, true);
      return;
    }
    setState(() {
      busy = true;
      err = null;
    });
    final e = await widget.onConfirm!();
    if (!mounted) return;
    if (e == null) {
      Navigator.pop(context, true);
    } else {
      setState(() {
        busy = false;
        err = e;
      });
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(8, 0, 8, 8 + MediaQuery.of(context).viewInsets.bottom + MediaQuery.of(context).padding.bottom),
        child: Container(
          padding: const EdgeInsets.fromLTRB(20, 14, 20, 22),
          decoration: BoxDecoration(color: Cx.surface, borderRadius: BorderRadius.circular(32), border: Border.all(color: Cx.line)),
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Center(child: ExcludeSemantics(child: Container(width: 44, height: 5, decoration: BoxDecoration(color: Cx.outline, borderRadius: BorderRadius.circular(3))))),
              const SizedBox(height: 16),
              Text(widget.mono.toUpperCase(), style: Cx.label),
              const SizedBox(height: 16),
              Semantics(header: true, child: Text(widget.title.toUpperCase(), style: Cx.display.copyWith(fontSize: 40, letterSpacing: 1.2))),
              if (widget.body != null) ...[const SizedBox(height: 16), Text(widget.body!, style: Cx.body.copyWith(fontSize: 16, color: const Color(0xFFD6DDD0)))],
              if (widget.bodyWidget != null) ...[const SizedBox(height: 16), widget.bodyWidget!],
              if (widget.small != null) ...[const SizedBox(height: 16), Text(widget.small!, style: Cx.small)],
              if (widget.extra != null) ...[const SizedBox(height: 14), widget.extra!],
              if (err != null) ...[const SizedBox(height: 12), CxNotice(err!, error: true)],
              const SizedBox(height: 16),
              CxButton(widget.cancelLabel, outline: true, onTap: busy ? null : () => Navigator.pop(context, false)),
              const SizedBox(height: 10),
              CxButton(widget.confirmLabel, outline: widget.danger, danger: widget.danger, busy: busy, onTap: _go),
            ]),
          ),
        ),
      );
}

/// Square yellow bullet used in short lists (mockup `.pt`).
class CxBullet extends StatelessWidget {
  const CxBullet(this.child, {super.key});
  final Widget child;
  @override
  Widget build(BuildContext context) => Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 6), child: Container(width: 10, height: 10, color: Cx.accent)),
        const SizedBox(width: 12),
        Expanded(child: DefaultTextStyle(style: const TextStyle(fontFamily: 'SpaceGrotesk', fontSize: 15, height: 1.4, color: Color(0xFFD6DDD0)), child: child)),
      ]);
}

/// A row in a list tile: label, optional detail, chevron.
class CxRow extends StatelessWidget {
  const CxRow(this.label, {super.key, this.detail, this.onTap, this.trailing, this.color, this.chevron = true});
  final Color? color;
  final bool chevron;
  final String label;
  final String? detail;
  final VoidCallback? onTap;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Semantics(
        button: onTap != null,
        label: detail == null ? label : '$label, $detail',
        excludeSemantics: true,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 60),
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                  Text(label, style: Cx.strong.copyWith(fontSize: 16, fontWeight: FontWeight.w600, color: color ?? Cx.text)),
                  if (detail != null) Text(detail!, style: Cx.small),
                ]),
              ),
              ?trailing,
              if (onTap != null && trailing == null && chevron) const Icon(Icons.chevron_right, color: Cx.faint),
            ]),
          ),
        ),
      );
}

class CxSwitch extends StatelessWidget {
  const CxSwitch({super.key, required this.label, this.detail, required this.value, required this.onChanged, this.tall = false});
  final bool tall;
  final String label;
  final String? detail;
  final bool value;
  final ValueChanged<bool>? onChanged;
  @override
  Widget build(BuildContext context) => Semantics(
        toggled: value,
        label: detail == null ? label : '$label. $detail',
        excludeSemantics: true,
        onTap: onChanged == null ? null : () => onChanged!(!value),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onChanged == null ? null : () => onChanged!(!value),
          child: Container(
            constraints: BoxConstraints(minHeight: tall ? 76 : 60),
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(label, style: Cx.strong.copyWith(fontSize: 16, fontWeight: FontWeight.w600)),
                  if (detail != null) Text(detail!, style: Cx.small),
                ]),
              ),
              const SizedBox(width: 12),
              AnimatedContainer(
                duration: const Duration(milliseconds: 120),
                width: 52,
                height: 32,
                padding: const EdgeInsets.all(4),
                alignment: value ? Alignment.centerRight : Alignment.centerLeft,
                decoration: BoxDecoration(color: value ? Cx.accent : Cx.outline, borderRadius: BorderRadius.circular(16)),
                child: Container(width: 24, height: 24, decoration: BoxDecoration(shape: BoxShape.circle, color: value ? Cx.ground : Cx.text)),
              ),
            ]),
          ),
        ),
      );
}

/// One-of-N choice shown as pills. The current one is marked for screen readers.
class CxChoice<T> extends StatelessWidget {
  const CxChoice({super.key, required this.label, required this.options, required this.value, required this.onChanged});
  final String label;
  final Map<T, String> options;
  final T value;
  final ValueChanged<T> onChanged;
  @override
  Widget build(BuildContext context) => SizedBox(width: double.infinity, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(left: 4, bottom: 8), child: Text(label.toUpperCase(), style: Cx.label)),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final e in options.entries)
            Semantics(
              button: true,
              selected: e.key == value,
              label: '${e.value}${e.key == value ? ', current' : ''}',
              excludeSemantics: true,
              child: GestureDetector(
                onTap: () => onChanged(e.key),
                child: Container(
                  constraints: const BoxConstraints(minHeight: 44, minWidth: 64),
                  padding: const EdgeInsets.symmetric(horizontal: 18),
                  decoration: BoxDecoration(
                      color: e.key == value ? Cx.accent : Colors.transparent,
                      borderRadius: BorderRadius.circular(22),
                      border: Border.all(color: e.key == value ? Cx.accent : Cx.outline, width: 1.5)),
                  child: Center(
                    widthFactor: 1,
                    child: Text(e.value,
                        style: TextStyle(
                            fontFamily: 'SpaceGrotesk',
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: e.key == value ? Cx.ground : Cx.text)),
                  ),
                ),
              ),
            ),
        ]),
      ]));
}

/// Shows an error line that screen readers announce.
class CxNotice extends StatelessWidget {
  const CxNotice(this.text, {super.key, this.error = false});
  final String text;
  final bool error;
  @override
  Widget build(BuildContext context) =>
      Semantics(liveRegion: true, child: Text(text, style: Cx.body.copyWith(color: error ? Cx.danger : Cx.text)));
}

/// Runs [fn] every [every] while mounted.
mixin Ticker<T extends StatefulWidget> on State<T> {
  Timer? _t;
  void tickEvery(Duration every, FutureOr<void> Function() fn) {
    _t?.cancel();
    _t = Timer.periodic(every, (_) => fn());
  }

  void stopTicking() => _t?.cancel();

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }
}
