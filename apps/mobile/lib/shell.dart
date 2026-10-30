import 'package:flutter/material.dart';

import 'api.dart';
import 'scope.dart';
import 'screens/calls.dart';
import 'screens/companion.dart';
import 'screens/owner.dart';
import 'screens/people.dart';
import 'screens/settings.dart';
import 'session.dart';
import 'theme.dart';
import 'ui.dart';

enum Tab { home, people, following, settings }

const _labels = {Tab.home: 'Home', Tab.people: 'My people', Tab.following: 'Following', Tab.settings: 'Settings'};
const _icons = {
  Tab.home: Icons.home_outlined,
  Tab.people: Icons.groups_outlined,
  Tab.following: Icons.favorite_border,
  Tab.settings: Icons.tune,
};

/// Tabs for the side the person is on (APP-PLAN 8): owner Home, My people, [Following], Settings;
/// companion Following, Settings.
List<Tab> tabsFor(Session s) {
  if (s.side == Side.companion) return [Tab.following, Tab.settings];
  return [Tab.home, Tab.people, if (s.canCompanion) Tab.following, Tab.settings];
}

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> with Ticker<Shell> {
  int index = 0;
  String? ringing; // call id already shown, so one call opens one screen

  @override
  void initState() {
    super.initState();
    tickEvery(const Duration(seconds: 4), _checkInbox);
  }

  Future<void> _checkInbox() async {
    final s = SessionScope.of(context);
    final t = s.token;
    if (t == null) return;
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
    if (index >= tabs.length) index = 0;
    final tab = tabs[index];
    final page = switch (tab) {
      Tab.home => const HomeScreen(),
      Tab.people => const PeopleScreen(),
      Tab.following => const FollowingScreen(),
      Tab.settings => const SettingsScreen(),
    };
    return Scaffold(
      body: Stack(children: [
        Positioned.fill(child: KeyedSubtree(key: ValueKey(tab), child: page)),
        Positioned(
          left: Cx.margin,
          right: Cx.margin,
          bottom: 16,
          child: SafeArea(top: false, child: _Nav(tabs: tabs, index: index, onTap: (i) => setState(() => index = i))),
        ),
      ]),
    );
  }
}

class _Nav extends StatelessWidget {
  const _Nav({required this.tabs, required this.index, required this.onTap});
  final List<Tab> tabs;
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
