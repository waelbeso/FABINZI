import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

class FabinziCustomerApp extends StatelessWidget {
  const FabinziCustomerApp({super.key});

  static const brandPurple = Color(0xFF7C5CFF);
  static const brandInk = Color(0xFF111827);
  static const brandMint = Color(0xFF21D3AE);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'FABINZI',
      supportedLocales: const [Locale('en'), Locale('ar')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: brandPurple),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: brandPurple,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const _BootstrapScaffold(),
    );
  }
}

class _BootstrapScaffold extends StatelessWidget {
  const _BootstrapScaffold();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Semantics(
          label: 'FABINZI',
          child: Text(
            'FABINZI',
            style: TextStyle(fontSize: 34, fontWeight: FontWeight.w900),
          ),
        ),
      ),
    );
  }
}
