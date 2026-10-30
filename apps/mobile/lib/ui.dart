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

/// A confirmation sheet. The safe choice comes first and is the default focus.
Future<bool> confirmSheet(
  BuildContext context, {
  required String title,
  required String body,
  required String confirmLabel,
  String cancelLabel = 'Cancel',
  bool danger = false,
  Widget? extra,
}) async {
  final session = SessionScope.of(context);
  if (session.prefs.spokenAlerts) session.services.speaker.say('$title. $body');
  final r = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Cx.surface,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(32))),
    builder: (c) => Padding(
      padding: EdgeInsets.fromLTRB(Cx.margin + 6, 24, Cx.margin + 6, 20 + MediaQuery.of(c).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Semantics(header: true, child: Text(title, style: Cx.strong.copyWith(fontSize: 22))),
          const SizedBox(height: 10),
          Text(body, style: Cx.body),
          if (extra != null) ...[const SizedBox(height: 14), extra],
          const SizedBox(height: 18),
          CxButton(cancelLabel, onTap: () => Navigator.pop(c, false)),
          const SizedBox(height: 10),
          CxButton(confirmLabel, outline: true, danger: danger, onTap: () => Navigator.pop(c, true)),
        ]),
      ),
    ),
  );
  return r ?? false;
}

/// A row in a list tile: label, optional detail, chevron.
class CxRow extends StatelessWidget {
  const CxRow(this.label, {super.key, this.detail, this.onTap, this.trailing});
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
            constraints: const BoxConstraints(minHeight: 56),
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                  Text(label, style: Cx.strong.copyWith(fontSize: 16, fontWeight: FontWeight.w600)),
                  if (detail != null) Text(detail!, style: Cx.small),
                ]),
              ),
              ?trailing,
              if (onTap != null && trailing == null) const Icon(Icons.chevron_right, color: Cx.faint),
            ]),
          ),
        ),
      );
}

class CxSwitch extends StatelessWidget {
  const CxSwitch({super.key, required this.label, this.detail, required this.value, required this.onChanged});
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
            constraints: const BoxConstraints(minHeight: 56),
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
                height: 30,
                padding: const EdgeInsets.all(3),
                alignment: value ? Alignment.centerRight : Alignment.centerLeft,
                decoration: BoxDecoration(
                    color: value ? Cx.accent : Colors.transparent,
                    borderRadius: BorderRadius.circular(15),
                    border: Border.all(color: value ? Cx.accent : Cx.outline, width: 1.5)),
                child: Container(
                    width: 22, height: 22, decoration: BoxDecoration(shape: BoxShape.circle, color: value ? Cx.ground : Cx.outline)),
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
