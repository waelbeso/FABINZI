import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fabinzi_customer_app/core/l10n.dart';
import 'package:fabinzi_customer_app/core/theme.dart';

void main() {
  test(
    'Arabic and English string catalogs have exact key parity',
    () => expect(L10n.hasParity, isTrue),
  );

  testWidgets('English resolves LTR', (tester) async {
    TextDirection? direction;
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        supportedLocales: L10n.supportedLocales,
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: Builder(
          builder: (context) {
            direction = Directionality.of(context);
            return Text(L10n.t(context, 'discover'));
          },
        ),
      ),
    );
    expect(direction, TextDirection.ltr);
    expect(find.text('Discover'), findsOneWidget);
  });

  testWidgets('Arabic resolves RTL with Arabic copy', (tester) async {
    TextDirection? direction;
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ar'),
        supportedLocales: L10n.supportedLocales,
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: Builder(
          builder: (context) {
            direction = Directionality.of(context);
            return Text(L10n.t(context, 'discover'));
          },
        ),
      ),
    );
    expect(direction, TextDirection.rtl);
    expect(find.text('اكتشف'), findsOneWidget);
  });

  test('light and dark themes preserve approved FABINZI brand colors', () {
    expect(FabinziTheme.purple, const Color(0xFF7C5CFF));
    expect(FabinziTheme.deepPurple, const Color(0xFF5A36E6));
    expect(FabinziTheme.ink, const Color(0xFF111827));
    expect(FabinziTheme.mint, const Color(0xFF21D3AE));
    expect(FabinziTheme.light().brightness, Brightness.light);
    expect(FabinziTheme.dark().brightness, Brightness.dark);
  });
}
