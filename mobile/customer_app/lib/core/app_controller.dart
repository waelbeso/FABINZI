import 'package:flutter/material.dart';

import 'api_client.dart';
import 'config.dart';
import 'models.dart';
import 'preferences.dart';
import 'secure_store.dart';

class AppController extends ChangeNotifier {
  AppController({
    AppConfig? config,
    TokenStore? tokens,
    AppPreferences? preferences,
    PlacementKeyStore? placementKeys,
    CustomerApiClient? api,
  })  : config = config ?? AppConfig(),
        tokens = tokens ?? SecureTokenStore(),
        preferences = preferences ?? AppPreferences(),
        placementKeys = placementKeys ?? PreferencesPlacementKeyStore() {
    this.api = api ?? CustomerApiClient(
      config: this.config,
      tokens: this.tokens,
      language: () => locale.languageCode,
    );
  }

  final AppConfig config;
  final TokenStore tokens;
  final AppPreferences preferences;
  final PlacementKeyStore placementKeys;
  late final CustomerApiClient api;

  BootstrapConfig? bootstrap;
  UserProfile? profile;
  Locale locale = const Locale('en');
  ThemeMode themeMode = ThemeMode.system;
  bool initialized = false;
  bool initializing = false;
  Object? initializationError;

  bool get isAuthenticated => profile != null;

  Future<void> initialize() async {
    if (initializing || initialized) return;
    initializing = true;
    initializationError = null;
    notifyListeners();
    try {
      final localeValue = await preferences.readLocale();
      final themeValue = await preferences.readTheme();
      locale = Locale(localeValue == 'ar' ? 'ar' : 'en');
      themeMode = _themeFromValue(themeValue);
      bootstrap = await api.bootstrap();
      if (await api.restoreSession()) {
        profile = await api.me();
        await _adoptServerPreferences(profile!);
      }
      initialized = true;
    } catch (error) {
      initializationError = error;
    } finally {
      initializing = false;
      notifyListeners();
    }
  }

  Future<void> retryInitialize() async {
    initializationError = null;
    initialized = false;
    await initialize();
  }

  Future<void> login(String username, String password) async {
    profile = await api.login(username, password);
    await _adoptServerPreferences(profile!);
    notifyListeners();
  }

  Future<void> logout() async {
    try {
      await api.logout();
    } finally {
      profile = null;
      notifyListeners();
    }
  }

  Future<void> expireSession() async {
    await tokens.clear();
    profile = null;
    notifyListeners();
  }

  Future<void> setLocale(String code) async {
    final clean = code == 'ar' ? 'ar' : 'en';
    locale = Locale(clean);
    await preferences.writeLocale(clean);
    notifyListeners();
    if (profile != null) {
      try {
        profile = await api.updateMe(language: clean);
      } on ApiProblem catch (problem) {
        await handleApiProblem(problem);
        rethrow;
      }
      notifyListeners();
    }
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    themeMode = mode;
    final value = switch (mode) {
      ThemeMode.light => 'light',
      ThemeMode.dark => 'dark',
      ThemeMode.system => 'system',
    };
    await preferences.writeTheme(value);
    notifyListeners();
    if (profile != null) {
      try {
        profile = await api.updateMe(theme: value);
      } on ApiProblem catch (problem) {
        await handleApiProblem(problem);
        rethrow;
      }
      notifyListeners();
    }
  }

  Future<void> refreshProfile() async {
    if (!isAuthenticated) return;
    try {
      profile = await api.me();
      await _adoptServerPreferences(profile!);
      notifyListeners();
    } on ApiProblem catch (problem) {
      await handleApiProblem(problem);
      rethrow;
    }
  }

  Future<void> handleApiProblem(ApiProblem problem) async {
    if (problem.code == 'invalid_refresh_token' ||
        problem.code == 'authentication_required' ||
        problem.code == 'invalid_token') {
      await expireSession();
    }
  }

  Future<void> _adoptServerPreferences(UserProfile value) async {
    locale = Locale(value.language == 'ar' ? 'ar' : 'en');
    themeMode = _themeFromValue(value.theme);
    await preferences.writeLocale(locale.languageCode);
    await preferences.writeTheme(value.theme);
  }

  ThemeMode _themeFromValue(String value) => switch (value) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };

  @override
  void dispose() {
    api.close();
    super.dispose();
  }
}
