class AppConfig {
  AppConfig({String? serverBaseUrl})
      : serverBaseUrl = serverBaseUrl ??
            const String.fromEnvironment(
              'FABINZI_API_BASE_URL',
              defaultValue: 'http://localhost:8000',
            );

  final String serverBaseUrl;

  Uri get serverBaseUri {
    final value = serverBaseUrl.endsWith('/') ? serverBaseUrl : '$serverBaseUrl/';
    return Uri.parse(value);
  }

  Uri customerUri(String path, [Map<String, String?> query = const {}]) {
    final clean = path.startsWith('/') ? path.substring(1) : path;
    final uri = serverBaseUri.resolve('api/v1/customer/$clean');
    final filtered = <String, String>{};
    for (final entry in query.entries) {
      final value = entry.value;
      if (value != null && value.isNotEmpty) filtered[entry.key] = value;
    }
    return filtered.isEmpty ? uri : uri.replace(queryParameters: filtered);
  }

  Uri resolveApplicationUrl(String value) {
    final parsed = Uri.tryParse(value);
    if (parsed != null && parsed.hasScheme) return parsed;
    return serverBaseUri.resolve(value.startsWith('/') ? value.substring(1) : value);
  }
}
