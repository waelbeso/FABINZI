import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

class AppPreferences {
  AppPreferences({this._preferences});

  SharedPreferences? _preferences;
  static const _localeKey = 'fabinzi.locale';
  static const _themeKey = 'fabinzi.theme';

  Future<SharedPreferences> get _prefs async =>
      _preferences ??= await SharedPreferences.getInstance();

  Future<String> readLocale() async =>
      (await _prefs).getString(_localeKey) ?? 'en';
  Future<String> readTheme() async =>
      (await _prefs).getString(_themeKey) ?? 'system';
  Future<void> writeLocale(String value) async =>
      (await _prefs).setString(_localeKey, value);
  Future<void> writeTheme(String value) async =>
      (await _prefs).setString(_themeKey, value);
}

abstract interface class PlacementKeyStore {
  Future<String> keyFor(int checkoutId, String provider);
  Future<void> clear(int checkoutId);
}

class PreferencesPlacementKeyStore implements PlacementKeyStore {
  PreferencesPlacementKeyStore({this._preferences});

  SharedPreferences? _preferences;
  final Uuid _uuid = const Uuid();

  Future<SharedPreferences> get _prefs async =>
      _preferences ??= await SharedPreferences.getInstance();

  String _key(int checkoutId, String provider) =>
      'fabinzi.placement.$checkoutId.$provider';

  @override
  Future<String> keyFor(int checkoutId, String provider) async {
    final prefs = await _prefs;
    final storageKey = _key(checkoutId, provider);
    final existing = prefs.getString(storageKey);
    if (existing != null && existing.length >= 8) return existing;
    final value = 'fcz:${_uuid.v4()}';
    await prefs.setString(storageKey, value);
    return value;
  }

  @override
  Future<void> clear(int checkoutId) async {
    final prefs = await _prefs;
    final prefix = 'fabinzi.placement.$checkoutId.';
    for (final key in prefs.getKeys().where(
      (value) => value.startsWith(prefix),
    )) {
      await prefs.remove(key);
    }
  }
}
