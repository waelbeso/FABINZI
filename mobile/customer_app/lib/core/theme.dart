import 'package:flutter/material.dart';

class FabinziTheme {
  const FabinziTheme._();

  static const purple = Color(0xFF7C5CFF);
  static const deepPurple = Color(0xFF5A36E6);
  static const ink = Color(0xFF111827);
  static const mint = Color(0xFF21D3AE);

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(seedColor: purple, brightness: Brightness.light);
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme.copyWith(primary: deepPurple, secondary: mint),
      scaffoldBackgroundColor: const Color(0xFFF7F7FB),
      cardTheme: const CardThemeData(margin: EdgeInsets.zero),
      inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
      visualDensity: VisualDensity.standard,
    );
  }

  static ThemeData dark() {
    final scheme = ColorScheme.fromSeed(seedColor: purple, brightness: Brightness.dark);
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme.copyWith(primary: purple, secondary: mint, surface: const Color(0xFF151A24)),
      scaffoldBackgroundColor: const Color(0xFF0D1118),
      cardTheme: const CardThemeData(margin: EdgeInsets.zero),
      inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
      visualDensity: VisualDensity.standard,
    );
  }
}
