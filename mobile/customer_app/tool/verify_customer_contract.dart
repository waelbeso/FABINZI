import 'dart:convert';
import 'dart:io';

Never _fail(String message) => throw StateError(message);

void main() {
  final root = Directory('../../');
  final manifest = jsonDecode(
    File('${root.path}/contracts/customer-api-v1-manifest.json')
        .readAsStringSync(),
  ) as Map<String, dynamic>;
  final openapi = jsonDecode(
    File('${root.path}/docs/api/fabinzi-customer-api-v1.openapi.json')
        .readAsStringSync(),
  ) as Map<String, dynamic>;
  final fixtures = jsonDecode(
    File('${root.path}/contracts/customer-api-v1-fixtures.json')
        .readAsStringSync(),
  ) as Map<String, dynamic>;
  final deferred = File('${root.path}/docs/DEFERRED_LIVE_E2E.md')
      .readAsStringSync();

  if (manifest['contract'] != 'FABINZI Customer API v1') {
    _fail('Unexpected Customer contract identity.');
  }
  if (manifest['api_version'] != 'v1') {
    _fail('Unexpected Customer API version.');
  }
  final auth = manifest['auth'] as Map<String, dynamic>;
  if (auth['scheme'] != 'Bearer JWT' ||
      auth['access_seconds'] != 900 ||
      auth['refresh_seconds'] != 2592000 ||
      auth['rotate_refresh'] != true ||
      auth['blacklist_after_rotation'] != true) {
    _fail('Frozen JWT lifecycle drifted.');
  }
  final pagination = manifest['pagination'] as Map<String, dynamic>;
  if (pagination['default_page_size'] != 20 ||
      pagination['max_page_size'] != 50) {
    _fail('Frozen pagination drifted.');
  }
  final uploads = manifest['uploads'] as Map<String, dynamic>;
  if (uploads['max_bytes'] != 10485760 ||
      uploads['private_by_default'] != true) {
    _fail('Frozen private upload policy drifted.');
  }
  final mimeTypes = (uploads['mime_types'] as List)
      .map((value) => value.toString())
      .toSet();
  if (!mimeTypes.containsAll({'image/png', 'image/jpeg', 'image/webp'}) ||
      mimeTypes.length != 3) {
    _fail('Frozen upload MIME set drifted.');
  }

  final paths = openapi['paths'] as Map<String, dynamic>;
  if (paths.keys.any((path) => !path.startsWith('/api/v1/customer/'))) {
    _fail('Non-Customer path entered frozen OpenAPI.');
  }
  const methods = {'get', 'post', 'patch', 'delete'};
  var operations = 0;
  for (final value in paths.values) {
    final item = value as Map<String, dynamic>;
    operations += item.keys.where(methods.contains).length;
  }
  if (operations != manifest['operation_count'] || operations != 41) {
    _fail('OpenAPI operation count mismatch: $operations.');
  }

  const forbidden = [
    '/Maneg/',
    '/designer/',
    '/manufacturer/',
    '/finance/',
    '/operations/',
    '/webhook/',
  ];
  for (final path in paths.keys) {
    if (forbidden.any(path.contains)) {
      _fail('Forbidden internal route in Customer OpenAPI: $path');
    }
  }

  final metadata = fixtures['metadata'] as Map<String, dynamic>;
  if (metadata['synthetic_only'] != true) {
    _fail('Customer fixtures must remain synthetic.');
  }
  final encodedFixtures = jsonEncode(fixtures).toLowerCase();
  for (final forbiddenKey in [
    'secret_key',
    'access_key_id',
    'secret_access_key',
    'provider_asset_id',
    'manufacturer_cost',
    'payout_amount',
  ]) {
    if (encodedFixtures.contains(forbiddenKey)) {
      _fail('Sensitive/internal fixture field detected: $forbiddenKey');
    }
  }

  if (!deferred.contains('UNRESOLVED')) {
    _fail('Deferred Global Live E2E must remain UNRESOLVED.');
  }
  stdout.writeln(
    'FABINZI Customer API v1 compatibility: PASS ($operations operations).',
  );
}
