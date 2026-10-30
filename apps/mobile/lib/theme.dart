import 'package:flutter/material.dart';

/// Colours and type from docs/architecture/APP-PLAN.md section 10.
class Cx {
  static const ground = Color(0xFF0A0A08);
  static const surface = Color(0xFF131A14);
  static const line = Color(0xFF223024);
  static const outline = Color(0xFF5C6F5F);
  static const text = Color(0xFFF4F4EC);
  static const muted = Color(0xFFB6BFB0);
  static const faint = Color(0xFF9AA394);
  static const accent = Color(0xFFEAFF00);
  static const danger = Color(0xFFFF8A7D);

  static const margin = 14.0;
  static const tileRadius = 22.0;

  static const display = TextStyle(
      fontFamily: 'Anton', fontSize: 44, height: 1, color: accent, letterSpacing: 1.3);
  static const chipFill = Color(0xFF26342A);
  static const dangerLine = Color(0xFF5A2F2A);
  static const body = TextStyle(
      fontFamily: 'SpaceGrotesk', fontSize: 15, height: 1.45, color: muted);
  static const small = TextStyle(
      fontFamily: 'SpaceGrotesk', fontSize: 13, height: 1.35, color: faint);
  static const strong = TextStyle(
      fontFamily: 'SpaceGrotesk', fontSize: 17, fontWeight: FontWeight.w700, color: text);
  static const label = TextStyle(
      fontFamily: 'JetBrainsMono', fontSize: 12, letterSpacing: 1.7, color: faint);

  static ThemeData theme() => ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: ground,
        colorScheme: const ColorScheme.dark(
            primary: accent, onPrimary: ground, surface: surface, error: danger),
        fontFamily: 'SpaceGrotesk',
        useMaterial3: true,
      );
}
