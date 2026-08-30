import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fabinzi_customer_app/core/app_controller.dart';
import 'package:fabinzi_customer_app/core/config.dart';
import 'package:fabinzi_customer_app/core/secure_store.dart';
import 'package:fabinzi_customer_app/features/auth/login_screen.dart';

class EmptyStore implements TokenStore {
  @override Future<void> clear() async {}
  @override Future<String?> readAccess() async => null;
  @override Future<String?> readRefresh() async => null;
  @override Future<void> write(SessionTokens tokens) async {}
}

void main() {
  testWidgets('login screen exposes supported login only and no fabricated reset/signup actions', (tester) async {
    final controller = AppController(config: AppConfig(serverBaseUrl: 'https://api.example.test'), tokens: EmptyStore());
    await tester.pumpWidget(MaterialApp(home: LoginScreen(controller: controller)));
    expect(find.text('Sign in'), findsWidgets);
    expect(find.textContaining('Password reset'), findsOneWidget);
    expect(find.widgetWithText(TextButton, 'Reset password'), findsNothing);
    expect(find.widgetWithText(TextButton, 'Sign up'), findsNothing);
    controller.dispose();
  });

  testWidgets('touch controls satisfy a minimum 48 logical pixel tap target', (tester) async {
    final button = FilledButton(onPressed: () {}, child: const Text('Action'));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: Center(child: button))));
    final size = tester.getSize(find.byType(FilledButton));
    expect(size.height, greaterThanOrEqualTo(48));
  });
}
