import 'package:flutter/widgets.dart';

enum AppTab { home, people, following, settings }

/// Lets a pushed screen or a Home tile switch the main tab.
class ShellNav {
  static final ValueNotifier<AppTab?> request = ValueNotifier<AppTab?>(null);

  /// Pops back to the shell, then asks it to show [tab].
  static void go(AppTab tab, BuildContext context) {
    Navigator.of(context).popUntil((r) => r.isFirst);
    request.value = tab;
  }
}
