import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:fabinzi_customer_app/core/api_client.dart';
import 'package:fabinzi_customer_app/core/config.dart';
import 'package:fabinzi_customer_app/core/models.dart';
import 'package:fabinzi_customer_app/core/secure_store.dart';

class MemoryTokenStore implements TokenStore {
  String? access;
  String? refresh;
  int writes = 0;
  int clears = 0;

  @override
  Future<String?> readAccess() async => access;
  @override
  Future<String?> readRefresh() async => refresh;
  @override
  Future<void> write(SessionTokens tokens) async { access = tokens.access; refresh = tokens.refresh; writes++; }
  @override
  Future<void> clear() async { access = null; refresh = null; clears++; }
}

http.Response jsonResponse(Object value, int status) => http.Response(jsonEncode(value), status, headers: {'content-type': 'application/json'});
Map<String, dynamic> error(String code) => {'error': {'code': code, 'message': code, 'fields': <String, dynamic>{}, 'request_id': 'test-request'}};
Map<String, dynamic> mePayload() => {'id': 1, 'username': 'customer', 'display_name': 'Customer', 'email': 'c@example.test', 'language': 'en', 'theme': 'system', 'account_state': 'active'};

void main() {
  test('login stores returned JWTs only after successful response', () async {
    final store = MemoryTokenStore();
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/auth/login/')) return jsonResponse({'access': 'access-1', 'refresh': 'refresh-1'}, 200);
        if (request.url.path.endsWith('/me/')) {
          expect(request.headers['authorization'], 'Bearer access-1');
          return jsonResponse(mePayload(), 200);
        }
        return jsonResponse(error('not_found'), 404);
      }),
    );
    final profile = await client.login('customer', 'password');
    expect(profile.username, 'customer');
    expect(store.access, 'access-1');
    expect(store.refresh, 'refresh-1');
    expect(store.writes, 1);
  });

  test('concurrent expired requests share one refresh rotation and use rotated refresh', () async {
    final store = MemoryTokenStore()..access = 'expired-access'..refresh = 'refresh-old';
    var refreshCalls = 0;
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/me/')) {
          if (request.headers['authorization'] == 'Bearer expired-access') return jsonResponse(error('token_expired'), 401);
          expect(request.headers['authorization'], 'Bearer access-new');
          return jsonResponse(mePayload(), 200);
        }
        if (request.url.path.endsWith('/auth/refresh/')) {
          refreshCalls++;
          expect(jsonDecode(request.body)['refresh'], 'refresh-old');
          await Future<void>.delayed(const Duration(milliseconds: 20));
          return jsonResponse({'access': 'access-new', 'refresh': 'refresh-new'}, 200);
        }
        return jsonResponse(error('not_found'), 404);
      }),
    );
    final profiles = await Future.wait([client.me(), client.me()]);
    expect(profiles.map((value) => value.username), everyElement('customer'));
    expect(refreshCalls, 1);
    expect(store.access, 'access-new');
    expect(store.refresh, 'refresh-new');
  });

  test('invalid refresh clears local session', () async {
    final store = MemoryTokenStore()..access = 'expired'..refresh = 'bad-refresh';
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/me/')) return jsonResponse(error('token_expired'), 401);
        if (request.url.path.endsWith('/auth/refresh/')) return jsonResponse(error('invalid_refresh_token'), 401);
        return jsonResponse(error('not_found'), 404);
      }),
    );
    await expectLater(client.me(), throwsA(isA<ApiProblem>()));
    expect(store.access, isNull);
    expect(store.refresh, isNull);
    expect(store.clears, greaterThan(0));
  });

  test('logout revokes active refresh and clears device tokens', () async {
    final store = MemoryTokenStore()..access = 'access'..refresh = 'refresh';
    var logoutCalls = 0;
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/auth/logout/')) {
          logoutCalls++;
          expect(request.headers['authorization'], 'Bearer access');
          expect(jsonDecode(request.body)['refresh'], 'refresh');
          return http.Response('', 204);
        }
        return jsonResponse(error('not_found'), 404);
      }),
    );
    await client.logout();
    expect(logoutCalls, 1);
    expect(store.access, isNull);
    expect(store.refresh, isNull);
  });

  test('Accept-Language is sent without altering frozen path', () async {
    final store = MemoryTokenStore();
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      language: () => 'ar',
      httpClient: MockClient((request) async {
        expect(request.url.path, '/api/v1/customer/products/');
        expect(request.headers['accept-language'], 'ar');
        return jsonResponse({'count': 0, 'next': null, 'previous': null, 'results': []}, 200);
      }),
    );
    final products = await client.products();
    expect(products.count, 0);
  });

  test('oversized Studio upload is rejected client-side before network', () async {
    final store = MemoryTokenStore()..access = 'access'..refresh = 'refresh';
    var calls = 0;
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      httpClient: MockClient((request) async { calls++; return jsonResponse({}, 200); }),
    );
    await expectLater(client.uploadStudioImage(1, Uint8List(10485761), 'too-large.png'), throwsA(isA<ApiProblem>().having((value) => value.statusCode, 'status', 413)));
    expect(calls, 0);
  });

  test('private media redirect does not forward Bearer token to signed storage host', () async {
    final store = MemoryTokenStore()..access = 'access'..refresh = 'refresh';
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      httpClient: MockClient((request) async {
        if (request.url.host == 'api.example.test') {
          expect(request.headers['authorization'], 'Bearer access');
          return http.Response('', 302, headers: {'location': 'https://signed-storage.example/object'});
        }
        expect(request.url.host, 'signed-storage.example');
        expect(request.headers.containsKey('authorization'), isFalse);
        return http.Response.bytes([1, 2, 3], 200);
      }),
    );
    expect(await client.protectedMedia('/api/v1/customer/media/7/'), [1, 2, 3]);
  });
}
