import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:fabinzi_customer_app/core/preferences.dart';

void main() {
  test('placement key is stable per checkout/provider and distinct across providers', () async {
    SharedPreferences.setMockInitialValues({});
    final store = PreferencesPlacementKeyStore();
    final a = await store.keyFor(42, 'cod');
    final replay = await store.keyFor(42, 'cod');
    final otherProvider = await store.keyFor(42, 'stripe');
    expect(a, replay);
    expect(a, isNot(otherProvider));
    expect(a.length, greaterThanOrEqualTo(8));
  });

  test('locale and theme preferences never contain authentication credentials', () async {
    SharedPreferences.setMockInitialValues({});
    final preferences = AppPreferences();
    await preferences.writeLocale('ar');
    await preferences.writeTheme('dark');
    final raw = await SharedPreferences.getInstance();
    expect(raw.getString('fabinzi.locale'), 'ar');
    expect(raw.getString('fabinzi.theme'), 'dark');
    expect(raw.getKeys().where((key) => key.contains('token') || key.contains('access') || key.contains('refresh')), isEmpty);
  });
}
