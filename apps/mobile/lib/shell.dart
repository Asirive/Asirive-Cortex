import 'package:flutter/material.dart';

import 'api.dart';
import 'scope.dart';
import 'screens/calls.dart';
import 'screens/companion.dart';
import 'screens/owner.dart';
import 'screens/people.dart';
import 'screens/settings.dart';
import 'session.dart';
import 'shell_nav.dart';
export 'shell_nav.dart';
import 'theme.dart';
import 'ui.dart';

const _labels = {AppTab.home: 'Home', AppTab.people: 'My people', AppTab.following: 'Following', AppTab.settings: 'Settings'};
const _icons = {
  AppTab.home: Icons.home_outlined,
  AppTab.people: Icons.groups_outlined,
  AppTab.following: Icons.place_outlined,
  AppTab.settings: Icons.tune,
};

/// Tabs for the side the person is on (APP-PLAN 8): owner Home, My people, [Following], Settings;
/// companion Following, Settings.
List<AppTab> tabsFor(Session s) {
  if (s.side == Side.companion) return [AppTab.following, AppTab.settings];
  return [AppTab.home, AppTab.people, if (s.canCompanion) AppTab.following, AppTab.settings];
}

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> with Ticker<Shell> {
  AppTab? current;
  String? ringing; // call id already shown, so one call opens one screen

  @override
  void initState() {
    super.initState();
    tickEvery(const Duration(seconds: 4), _checkInbox);
    ShellNav.request.addListener(_onRequest);
  }

  void _onRequest() {
    final t = ShellNav.request.value;
    if (t == null) return;
    ShellNav.request.value = null;
    final s = SessionScope.of(context);
    if (t == AppTab.following && s.side != Side.companion && s.canCompanion) s.switchSide(Side.companion);
    if ((t == AppTab.home || t == AppTab.people) && s.side == Side.companion && s.canOwner) s.switchSide(Side.owner);
    setState(() => current = t);
  }

  @override
  void dispose() {
    ShellNav.request.removeListener(_onRequest);
    super.dispose();
  }

  Future<void> _checkInbox() async {
    final s = SessionScope.of(context);
    final t = s.token;
    if (t == null || !s.prefs.incomingCalls) return;
    try {
      final inbox = await s.api.inbox(t);
      final c = inbox.where((x) => x.state == 'ringing').toList();
      if (c.isNotEmpty && c.first.id != ringing && mounted) {
        ringing = c.first.id;
        push(context, IncomingCallScreen(call: c.first));
      }
    } on ApiException {
      // offline or signed out: the session handles the second case
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final tabs = tabsFor(s);
    if (current == null || !tabs.contains(current)) current = tabs.first;
    final tab = current!;
    final index = tabs.indexOf(tab);
    final page = switch (tab) {
      AppTab.home => const HomeScreen(),
      AppTab.people => const PeopleScreen(),
      AppTab.following => const FollowingScreen(),
      AppTab.settings => const SettingsScreen(),
    };
    return Scaffold(
      body: Stack(children: [
        Positioned.fill(child: KeyedSubtree(key: ValueKey(tab), child: page)),
        Positioned(
          left: Cx.margin,
          right: Cx.margin,
          bottom: 16,
          child: SafeArea(top: false, child: _Nav(tabs: tabs, index: index, onTap: (i) => setState(() => current = tabs[i]))),
        ),
      ]),
    );
  }
}

class _Nav extends StatelessWidget {
  const _Nav({required this.tabs, required this.index, required this.onTap});
  final List<AppTab> tabs;
  final int index;
  final ValueChanged<int> onTap;
  @override
  Widget build(BuildContext context) => Container(
        height: 64,
        padding: const EdgeInsets.all(6),
        decoration: BoxDecoration(
            color: Cx.surface, borderRadius: BorderRadius.circular(32), border: Border.all(color: Cx.line)),
        child: Row(children: [
          for (var i = 0; i < tabs.length; i++)
            Expanded(
              flex: i == index ? 23 : 10,
              child: Semantics(
                button: true,
                selected: i == index,
                label: '${_labels[tabs[i]]}${i == index ? ', current' : ''}',
                excludeSemantics: true,
                child: GestureDetector(
                  onTap: () => onTap(i),
                  child: Container(
                    height: 52,
                    margin: const EdgeInsets.symmetric(horizontal: 2),
                    decoration: BoxDecoration(
                        color: i == index ? Cx.accent : Colors.transparent, borderRadius: BorderRadius.circular(26)),
                    child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                      Icon(_icons[tabs[i]], size: 22, color: i == index ? Cx.ground : Cx.faint),
                      if (i == index) ...[
                        const SizedBox(width: 6),
                        Flexible(
                            child: Text(_labels[tabs[i]]!,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                    fontFamily: 'SpaceGrotesk', fontSize: 14, fontWeight: FontWeight.w700, color: Cx.ground))),
                      ],
                    ]),
                  ),
                ),
              ),
            ),
        ]),
      );
}
