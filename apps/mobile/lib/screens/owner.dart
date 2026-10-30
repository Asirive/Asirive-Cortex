import 'package:flutter/material.dart';

import '../api.dart';
import '../scope.dart';
import '../services.dart';
import '../session.dart';
import '../theme.dart';
import '../ui.dart';
import '../widgets.dart';
import 'setup.dart';
import 'settings.dart';

/// Owner Home: device status, connection, and the few things you do most.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  LinkState link = LinkState.cableOut;
  String? note;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = SessionScope.of(context);
    await s.refresh();
    final l = await s.services.link.state();
    if (mounted) setState(() => link = l);
  }

  String _status(Session s) {
    final d = s.devices.isEmpty ? null : s.devices.first;
    if (d == null) return 'No glasses are set up yet.';
    final b = d.battery == null ? '' : ' Battery ${d.battery} percent.';
    return '${d.label.isEmpty ? 'Your Cortex' : d.label} is ${d.online ? 'online' : 'offline'}.$b ${_linkText(link)}';
  }

  String _linkText(LinkState l) => switch (l) {
        LinkState.connectedOnline => 'The pocket box is connected and online.',
        LinkState.connectedNoInternet => 'The pocket box is connected but has no internet.',
        LinkState.cableOut => 'The pocket box is not plugged in to this phone.',
      };

  Future<void> _pause() async {
    final s = SessionScope.of(context);
    final ok = await confirmSheet(context,
        title: 'Pause the assistant?',
        body:
            'Cortex stops answering until you resume. Obstacle warnings keep running. The pocket box must be plugged in to this phone.',
        confirmLabel: 'Pause assistant');
    if (!ok) return;
    final done = await s.services.link.pause();
    if (mounted) setState(() => note = done ? 'Assistant paused. Obstacle warnings are still on.' : 'Could not reach the pocket box. Plug it in with the cable and try again.');
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final d = s.devices.isEmpty ? null : s.devices.first;
    return CxScreen(tab: true, children: [
      CxTop(back: false, trailing: _Profile(s)),
      const CxTitle('Home'),
      if (d == null)
        CxTile(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('GLASSES', style: Cx.label),
          const SizedBox(height: 8),
          Text('Set up your Cortex', style: Cx.strong.copyWith(fontSize: 20)),
          const SizedBox(height: 6),
          const CxText('A sighted helper sits next to you, and the app guides them through five short steps.'),
          const SizedBox(height: 14),
          CxButton('Set up with a helper', onTap: () => push(context, const SetupIntroScreen())),
        ]))
      else ...[
        CxTile(
            semanticLabel: _status(s),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text(d.label.isEmpty ? 'YOUR CORTEX' : d.label.toUpperCase(), style: Cx.label)),
                CxChip(d.online ? 'Online' : 'Offline', on: d.online),
              ]),
              const SizedBox(height: 14),
              Text(d.battery == null ? 'Battery unknown' : 'Battery ${d.battery}%', style: Cx.strong.copyWith(fontSize: 22)),
              const SizedBox(height: 10),
              _Bar(percent: d.battery ?? 0),
              const SizedBox(height: 14),
              Text(_linkText(link), style: Cx.small),
            ])),
        CxButton('Hear my status', onTap: () => s.services.speaker.say(_status(s))),
        CxTile(
            child: Column(children: [
          CxRow('Where I am', detail: 'See and share your location', onTap: () => push(context, const MyMapScreen())),
          const Divider(color: Cx.line, height: 1),
          CxRow('Share internet', detail: 'Give the pocket box a connection', onTap: () => push(context, const InternetScreen())),
          const Divider(color: Cx.line, height: 1),
          CxRow('Software update', detail: d.firmware.isEmpty ? null : 'Version ${d.firmware}', onTap: () => push(context, UpdateScreen(device: d))),
          const Divider(color: Cx.line, height: 1),
          CxRow('Pause the assistant', detail: 'Over the cable. Obstacle warnings stay on', onTap: _pause),
        ])),
        if (note != null) CxNotice(note!),
      ],
    ]);
  }
}

class _Bar extends StatelessWidget {
  const _Bar({required this.percent});
  final int percent;
  @override
  Widget build(BuildContext context) => ExcludeSemantics(
        child: Container(
          height: 10,
          decoration: BoxDecoration(color: Cx.line, borderRadius: BorderRadius.circular(5)),
          alignment: Alignment.centerLeft,
          child: FractionallySizedBox(
              widthFactor: (percent.clamp(0, 100)) / 100,
              child: Container(decoration: BoxDecoration(color: Cx.accent, borderRadius: BorderRadius.circular(5)))),
        ),
      );
}

class _Profile extends StatelessWidget {
  const _Profile(this.s);
  final Session s;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: s.hasBoth ? 'Profile. Switch side' : 'Profile. Open settings',
        excludeSemantics: true,
        child: GestureDetector(
          onTap: () => push(context, s.hasBoth ? const SwitchSideScreen() : const AccountScreen()),
          child: Container(
            width: 44,
            height: 44,
            alignment: Alignment.center,
            decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Cx.outline, width: 1.5)),
            child: Text((s.account?.email ?? '?').substring(0, 1).toUpperCase(), style: Cx.strong),
          ),
        ),
      );
}

/// Where I am: reads the phone's position, shows it and can share it with people the owner allowed.
class MyMapScreen extends StatefulWidget {
  const MyMapScreen({super.key});
  @override
  State<MyMapScreen> createState() => _MyMapScreenState();
}

class _MyMapScreenState extends State<MyMapScreen> {
  Point? p;
  String? msg;
  bool busy = false;

  Future<void> _locate() async {
    setState(() {
      busy = true;
      msg = null;
    });
    final s = SessionScope.of(context);
    final got = await s.services.location.current();
    if (!mounted) return;
    if (got == null) {
      setState(() {
        busy = false;
        msg = 'Location is off or not allowed. Turn it on in your phone settings, then try again.';
      });
      return;
    }
    try {
      await s.api.putLocation(s.token!, got.lat, got.lon, got.accuracy);
      if (mounted) setState(() => msg = 'Shared with the people you allowed.');
    } on ApiException catch (e) {
      if (mounted) msg = e.message;
    }
    if (mounted) setState(() {
      p = got;
      busy = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return CxScreen(children: [
      const CxTop(title: 'Where I am'),
      const CxTitle('My\nlocation'),
      const CxText('Only people you allowed in My people can see this. History is kept for 30 days.'),
      CxTile(
          semanticLabel: p == null ? 'No position yet' : 'Position found. Accurate to ${p!.accuracy.round()} metres.',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('POSITION', style: Cx.label),
            const SizedBox(height: 8),
            Text(p == null ? 'Not found yet' : '${p!.lat.toStringAsFixed(5)}, ${p!.lon.toStringAsFixed(5)}', style: Cx.strong.copyWith(fontSize: 20)),
            if (p != null) Text('Accurate to about ${p!.accuracy.round()} m', style: Cx.small),
          ])),
      if (msg != null) CxNotice(msg!),
    ], bottom: [
      CxButton(p == null ? 'Find and share my location' : 'Update and share', onTap: _locate, busy: busy),
      CxButton('Say where I am',
          outline: true,
          onTap: () => s.services.speaker.say(p == null
              ? 'I have not found your position yet. Press Find and share my location first.'
              : 'Your position is found, accurate to about ${p!.accuracy.round()} metres. Open in Maps to hear the street name.')),
      if (p != null)
        CxButton('Open in Maps',
            outline: true, onTap: () => s.services.opener.open(Uri.parse('https://maps.google.com/?q=${p!.lat},${p!.lon}'))),
    ]);
  }
}

/// Help to give the pocket box internet over the cable, with a test.
class InternetScreen extends StatefulWidget {
  const InternetScreen({super.key, this.helper = false});
  final bool helper;
  @override
  State<InternetScreen> createState() => _InternetScreenState();
}

class _InternetScreenState extends State<InternetScreen> {
  bool android = false;
  String? result;
  bool busy = false;

  Future<void> _test() async {
    setState(() {
      busy = true;
      result = null;
    });
    final link = SessionScope.of(context).services.link;
    final st = await link.state();
    String r;
    if (st == LinkState.cableOut) {
      r = 'The pocket box is not plugged in. Connect the cable and try again.';
    } else {
      r = (await link.internetFromBox()) ? 'The pocket box can reach the internet.' : 'The pocket box is connected but cannot reach the internet yet. Check the steps above.';
    }
    if (mounted) setState(() {
      result = r;
      busy = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final steps = android
        ? ['Plug the pocket box into your phone with the cable.', 'Open Settings, then Network, then Hotspot and tethering.', 'Turn on USB tethering.']
        : ['Plug the pocket box into your iPhone with the cable.', 'Open Settings, then Personal Hotspot.', 'Turn on Allow Others to Join. Tap Trust if asked.'];
    return CxScreen(children: [
      const CxTop(title: 'Share internet'),
      const CxTitle('Share your\ninternet'),
      const CxText('The pocket box has no SIM. It uses your phone\'s internet over the cable.'),
      CxChoice<bool>(label: 'My phone', options: const {false: 'iPhone', true: 'Android'}, value: android, onChanged: (v) => setState(() => android = v)),
      CxTile(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (var i = 0; i < steps.length; i++)
          Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                ExcludeSemantics(
                    child: CircleAvatar(radius: 14, backgroundColor: Cx.accent, child: Text('${i + 1}', style: const TextStyle(color: Cx.ground, fontWeight: FontWeight.w700)))),
                const SizedBox(width: 12),
                Expanded(child: Text('Step ${i + 1}. ${steps[i]}', style: Cx.body.copyWith(color: Cx.text))),
              ])),
      ])),
      const CxText('It uses your mobile data and a little extra battery on this phone.', small: true),
      if (result != null) CxNotice(result!),
    ], bottom: [
      CxButton('Test the connection', onTap: _test, busy: busy),
    ]);
  }
}

class UpdateScreen extends StatefulWidget {
  const UpdateScreen({super.key, required this.device});
  final Device device;
  @override
  State<UpdateScreen> createState() => _UpdateScreenState();
}

class _UpdateScreenState extends State<UpdateScreen> {
  bool loading = true;
  Map<String, dynamic>? offer;
  String? msg;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _check());
  }

  Future<void> _check() async {
    final s = SessionScope.of(context);
    try {
      final o = await s.api.updateOffer(s.token!, widget.device.id);
      if (mounted) setState(() {
        offer = o;
        loading = false;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() {
        msg = e.message;
        loading = false;
      });
    }
  }

  Future<void> _install() async {
    final ok = await confirmSheet(context,
        title: 'Install the update?',
        body: 'The pocket box restarts. Keep it plugged in to this phone and do not unplug it until it is done.',
        confirmLabel: 'Install');
    if (!ok || !mounted) return;
    final s = SessionScope.of(context);
    setState(() => busy = true);
    final done = await s.services.link.installUpdate(offer!);
    if (!mounted) return;
    setState(() {
      busy = false;
      msg = done ? 'Sent to the pocket box. It will restart on its own.' : 'Could not reach the pocket box. Plug it in with the cable and try again.';
    });
  }

  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(title: 'Software'),
        const CxTitle('Software\nupdate'),
        if (loading)
          const CxText('Checking for updates')
        else if (offer == null && msg == null)
          CxText('You are up to date${widget.device.firmware.isEmpty ? '' : ' on version ${widget.device.firmware}'}.')
        else if (offer != null)
          const CxText('A new version is ready for your pocket box.'),
        if (msg != null) CxNotice(msg!),
      ], bottom: [
        if (offer != null) CxButton('Install update', onTap: _install, busy: busy),
      ]);
}
