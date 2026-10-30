import 'package:flutter/material.dart';

import '../widgets.dart';

/// Placeholder for screens that are drawn but not built yet.
class SoonScreen extends StatelessWidget {
  const SoonScreen({super.key, required this.title, required this.body});
  final String title;
  final String body;
  @override
  Widget build(BuildContext context) => CxScreen(children: [
        const CxTop(),
        CxTitle(title),
        CxText(body),
      ]);
}
