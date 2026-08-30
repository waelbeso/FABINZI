import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'config.dart';
import 'models.dart';
import 'secure_store.dart';

class NetworkProblem implements Exception {
  const NetworkProblem(this.kind, [this.message = '']);
  final String kind;
  final String message;
  @override
  String toString() =>
      'NetworkProblem($kind${message.isEmpty ? '' : ': $message'})';
}

class CustomerApiClient {
  CustomerApiClient({
    required this._config,
    required this._tokens,
    http.Client? httpClient,
    String Function()? language,
    this._timeout = const Duration(seconds: 20),
  }) : _http = httpClient ?? http.Client(),
       _language = language ?? (() => 'en');

  final AppConfig _config;
  final TokenStore _tokens;
  final http.Client _http;
  final String Function() _language;
  final Duration _timeout;
  Future<SessionTokens>? _refreshing;

  Future<BootstrapConfig> bootstrap() async =>
      BootstrapConfig.fromJson(await _json('GET', 'bootstrap/', auth: false));

  Future<UserProfile> login(String username, String password) async {
    final payload = asMap(
      await _json(
        'POST',
        'auth/login/',
        auth: false,
        body: {'username': username, 'password': password},
      ),
    );
    final access = asString(payload['access']);
    final refresh = asString(payload['refresh']);
    if (access.isEmpty || refresh.isEmpty) {
      throw const NetworkProblem(
        'invalid_response',
        'Login did not return both JWT credentials.',
      );
    }
    await _tokens.write(SessionTokens(access: access, refresh: refresh));
    return me();
  }

  Future<bool> restoreSession() async {
    final refresh = await _tokens.readRefresh();
    if (refresh == null || refresh.isEmpty) return false;
    try {
      await me();
      return true;
    } on ApiProblem catch (problem) {
      if (problem.isAuthenticationFailure ||
          problem.code == 'invalid_refresh_token') {
        await _tokens.clear();
        return false;
      }
      rethrow;
    }
  }

  Future<void> logout() async {
    var refresh = await _tokens.readRefresh();
    if (refresh == null || refresh.isEmpty) {
      await _tokens.clear();
      return;
    }
    try {
      try {
        await _json(
          'POST',
          'auth/logout/',
          body: {'refresh': refresh},
          retryAuth: false,
        );
      } on ApiProblem catch (problem) {
        if (!problem.isAuthenticationFailure) rethrow;
        await _refreshTokens();
        refresh = await _tokens.readRefresh();
        if (refresh != null && refresh.isNotEmpty) {
          await _json(
            'POST',
            'auth/logout/',
            body: {'refresh': refresh},
            retryAuth: false,
          );
        }
      }
    } finally {
      await _tokens.clear();
    }
  }

  Future<UserProfile> me() async =>
      UserProfile.fromJson(await _json('GET', 'me/'));

  Future<UserProfile> updateMe({String? language, String? theme}) async {
    final body = <String, Object?>{};
    if (language != null) body['language'] = language;
    if (theme != null) body['theme'] = theme;
    return UserProfile.fromJson(await _json('PATCH', 'me/', body: body));
  }

  Future<Paged<Storefront>> stores({String query = '', int page = 1}) async =>
      Paged<Storefront>.fromJson(
        await _json(
          'GET',
          'stores/',
          auth: false,
          query: {'q': query, 'page': '$page'},
        ),
        Storefront.fromJson,
      );

  Future<Storefront> store(String slug) async => Storefront.fromJson(
    await _json('GET', 'stores/${Uri.encodeComponent(slug)}/', auth: false),
  );

  Future<Paged<Product>> products({
    String query = '',
    String store = '',
    bool? customizable,
    int page = 1,
  }) async => Paged<Product>.fromJson(
    await _json(
      'GET',
      'products/',
      auth: false,
      query: {
        'q': query,
        'store': store,
        'customizable': customizable == null ? null : '$customizable',
        'page': '$page',
      },
    ),
    Product.fromJson,
  );

  Future<Product> product(
    String storeSlug,
    String productSlug,
  ) async => Product.fromJson(
    await _json(
      'GET',
      'stores/${Uri.encodeComponent(storeSlug)}/products/${Uri.encodeComponent(productSlug)}/',
      auth: false,
    ),
  );

  Future<Paged<Artwork>> artworks({
    String query = '',
    String method = '',
    int page = 1,
  }) async => Paged<Artwork>.fromJson(
    await _json(
      'GET',
      'artworks/',
      auth: false,
      query: {'q': query, 'method': method, 'page': '$page'},
    ),
    Artwork.fromJson,
  );

  Future<Artwork> artwork(int id) async =>
      Artwork.fromJson(await _json('GET', 'artworks/$id/', auth: false));

  Future<Paged<StudioProject>> studioProjects({int page = 1}) async =>
      Paged<StudioProject>.fromJson(
        await _json('GET', 'studio-projects/', query: {'page': '$page'}),
        StudioProject.fromJson,
      );

  Future<StudioProject> createStudio({
    required String storeSlug,
    required String productSlug,
    String? variantSku,
    int quantity = 1,
    String customerNotes = '',
  }) async => StudioProject.fromJson(
    await _json(
      'POST',
      'studio-projects/',
      body: {
        'store_slug': storeSlug,
        'product_slug': productSlug,
        'variant_sku': ?variantSku,
        'quantity': quantity,
        'customer_notes': customerNotes,
      },
    ),
  );

  Future<StudioProject> studioProject(int id) async =>
      StudioProject.fromJson(await _json('GET', 'studio-projects/$id/'));

  Future<StudioProject> updateStudio(
    int id, {
    String? variantSku,
    int? quantity,
    String? customerNotes,
  }) async {
    final body = <String, Object?>{};
    if (variantSku != null) body['variant_sku'] = variantSku;
    if (quantity != null) body['quantity'] = quantity;
    if (customerNotes != null) body['customer_notes'] = customerNotes;
    return StudioProject.fromJson(
      await _json('PATCH', 'studio-projects/$id/', body: body),
    );
  }

  Future<void> enableCustomization(int id) async =>
      _json('POST', 'studio-projects/$id/customization/');

  Future<StudioElement> addStudioElement(
    int projectId, {
    required String zone,
    required String kind,
    String text = '',
    int? mediaAssetId,
    int? artworkVersionId,
    required String productionMethod,
    required bool rightsConfirmed,
    StudioTransform transform = const StudioTransform(
      x: .5,
      y: .5,
      scale: .35,
      rotation: 0,
    ),
    JsonMap style = const {},
    int sortOrder = 0,
  }) async => StudioElement.fromJson(
    await _json(
      'POST',
      'studio-projects/$projectId/elements/',
      body: {
        'decoration_zone': zone,
        'kind': kind,
        'text': text,
        'media_asset_id': ?mediaAssetId,
        'artwork_version_id': ?artworkVersionId,
        'production_method': productionMethod,
        'rights_confirmed': rightsConfirmed,
        'transform': transform.toJson(),
        'style': style,
        'sort_order': sortOrder,
      },
    ),
  );

  Future<StudioElement> updateStudioElement(
    int projectId,
    int elementId, {
    StudioTransform? transform,
    String? productionMethod,
    String? text,
  }) async {
    final body = <String, Object?>{};
    if (transform != null) body['transform'] = transform.toJson();
    if (productionMethod != null) body['production_method'] = productionMethod;
    if (text != null) body['text'] = text;
    return StudioElement.fromJson(
      await _json(
        'PATCH',
        'studio-projects/$projectId/elements/$elementId/',
        body: body,
      ),
    );
  }

  Future<void> deleteStudioElement(int projectId, int elementId) async =>
      _json('DELETE', 'studio-projects/$projectId/elements/$elementId/');

  Future<StudioValidation> validateStudio(int id) async =>
      StudioValidation.fromJson(
        await _json('GET', 'studio-projects/$id/validation/'),
      );

  Future<StudioProject> markStudioReady(int id) async =>
      StudioProject.fromJson(await _json('POST', 'studio-projects/$id/ready/'));

  Future<Checkout> studioCheckout(int id) async =>
      Checkout.fromJson(await _json('POST', 'studio-projects/$id/checkout/'));

  Future<UploadAsset> uploadStudioImage(
    int projectId,
    Uint8List bytes,
    String filename,
  ) async {
    if (bytes.length > 10485760) {
      throw ApiProblem(
        statusCode: 413,
        code: 'upload_error',
        message: 'The image exceeds the 10 MiB Customer Studio limit.',
      );
    }
    Future<UploadAsset> send(bool retryAuth) async {
      final access = await _tokens.readAccess();
      final request = http.MultipartRequest(
        'POST',
        _config.customerUri('studio-projects/$projectId/uploads/'),
      );
      request.headers['Accept-Language'] = _language() == 'ar' ? 'ar' : 'en';
      if (access != null && access.isNotEmpty) {
        request.headers['Authorization'] = 'Bearer $access';
      }
      request.files.add(
        http.MultipartFile.fromBytes('file', bytes, filename: filename),
      );
      try {
        final streamed = await _http.send(request).timeout(_timeout);
        final response = await http.Response.fromStream(streamed);
        final payload = _decode(response.bodyBytes);
        if (response.statusCode >= 200 && response.statusCode < 300) {
          return UploadAsset.fromJson(payload);
        }
        final problem = ApiProblem.fromPayload(response.statusCode, payload);
        if (retryAuth && problem.isAuthenticationFailure) {
          await _refreshTokens();
          return await send(false);
        }
        throw problem;
      } on TimeoutException {
        throw const NetworkProblem('timeout');
      } on http.ClientException catch (error) {
        throw NetworkProblem('connection', error.message);
      }
    }

    return send(true);
  }

  Future<Uint8List> protectedMedia(String accessUrl) async {
    Future<Uint8List> send(bool retryAuth) async {
      final access = await _tokens.readAccess();
      final request = http.Request(
        'GET',
        _config.resolveApplicationUrl(accessUrl),
      )..followRedirects = false;
      request.headers['Accept-Language'] = _language() == 'ar' ? 'ar' : 'en';
      if (access != null && access.isNotEmpty) {
        request.headers['Authorization'] = 'Bearer $access';
      }
      try {
        final streamed = await _http.send(request).timeout(_timeout);
        final response = await http.Response.fromStream(streamed);
        if (response.statusCode >= 300 && response.statusCode < 400) {
          final location = response.headers['location'];
          if (location == null || location.isEmpty) {
            throw const NetworkProblem(
              'invalid_response',
              'Private media redirect omitted Location.',
            );
          }
          final signed = await _http.get(Uri.parse(location)).timeout(_timeout);
          if (signed.statusCode >= 200 && signed.statusCode < 300) {
            return signed.bodyBytes;
          }
          throw const NetworkProblem('media_unavailable');
        }
        if (response.statusCode >= 200 && response.statusCode < 300) {
          return response.bodyBytes;
        }
        final problem = ApiProblem.fromPayload(
          response.statusCode,
          _decode(response.bodyBytes),
        );
        if (retryAuth && problem.isAuthenticationFailure) {
          await _refreshTokens();
          return await send(false);
        }
        throw problem;
      } on TimeoutException {
        throw const NetworkProblem('timeout');
      } on http.ClientException catch (error) {
        throw NetworkProblem('connection', error.message);
      }
    }

    return send(true);
  }

  Future<Cart> cart() async => Cart.fromJson(await _json('GET', 'cart/'));

  Future<Cart> addCartItem({
    required String kind,
    String? storeSlug,
    String? productSlug,
    String? variantSku,
    int? studioProjectId,
    int quantity = 1,
  }) async => Cart.fromJson(
    await _json(
      'POST',
      'cart/items/',
      body: {
        'kind': kind,
        'store_slug': ?storeSlug,
        'product_slug': ?productSlug,
        'variant_sku': ?variantSku,
        'studio_project_id': ?studioProjectId,
        'quantity': quantity,
      },
    ),
  );

  Future<Cart> updateCartItem(int id, int quantity) async => Cart.fromJson(
    await _json('PATCH', 'cart/items/$id/', body: {'quantity': quantity}),
  );

  Future<void> removeCartItem(int id) async =>
      _json('DELETE', 'cart/items/$id/');

  Future<Checkout> cartCheckout() async =>
      Checkout.fromJson(await _json('POST', 'cart/checkout/'));
  Future<Checkout> checkout(int id) async =>
      Checkout.fromJson(await _json('GET', 'checkouts/$id/'));
  Future<Checkout> updateCheckout(int id, ShippingDetails shipping) async =>
      Checkout.fromJson(
        await _json('PATCH', 'checkouts/$id/', body: shipping.toPatchJson()),
      );

  Future<List<PaymentOption>> paymentOptions() async {
    final payload = asMap(await _json('GET', 'payment-options/'));
    return asList(payload['results']).map(PaymentOption.fromJson).toList();
  }

  Future<PlacementResult> placeCheckout(
    int id,
    String provider,
    String idempotencyKey,
  ) async => PlacementResult.fromJson(
    await _json(
      'POST',
      'checkouts/$id/place/',
      body: {'payment_method': provider},
      headers: {'Idempotency-Key': idempotencyKey},
    ),
  );

  Future<Paged<Purchase>> purchases({int page = 1}) async =>
      Paged<Purchase>.fromJson(
        await _json('GET', 'purchases/', query: {'page': '$page'}),
        Purchase.fromJson,
      );

  Future<Purchase> purchase(String reference) async => Purchase.fromJson(
    await _json('GET', 'purchases/${Uri.encodeComponent(reference)}/'),
  );

  Future<Paged<NotificationItem>> notifications({int page = 1}) async =>
      Paged<NotificationItem>.fromJson(
        await _json('GET', 'notifications/', query: {'page': '$page'}),
        NotificationItem.fromJson,
      );

  Future<NotificationItem> markNotificationRead(int id) async =>
      NotificationItem.fromJson(await _json('POST', 'notifications/$id/read/'));
  Future<int> markAllNotificationsRead() async =>
      asInt(asMap(await _json('POST', 'notifications/read-all/'))['updated']);

  Future<NotificationPreferences> notificationPreferences() async =>
      NotificationPreferences.fromJson(
        await _json('GET', 'notifications/preferences/'),
      );

  Future<NotificationPreferences> updateNotificationPreferences({
    bool? emailEnabled,
    bool? smsEnabled,
    String? phoneE164,
  }) async {
    final body = <String, Object?>{};
    if (emailEnabled != null) body['email_enabled'] = emailEnabled;
    if (smsEnabled != null) body['sms_enabled'] = smsEnabled;
    if (phoneE164 != null) body['phone_e164'] = phoneE164;
    return NotificationPreferences.fromJson(
      await _json('PATCH', 'notifications/preferences/', body: body),
    );
  }

  Future<Object?> _json(
    String method,
    String path, {
    bool auth = true,
    JsonMap? body,
    Map<String, String?> query = const {},
    Map<String, String> headers = const {},
    bool retryAuth = true,
  }) async {
    Future<Object?> send(bool canRefresh) async {
      final access = auth ? await _tokens.readAccess() : null;
      final allHeaders = <String, String>{
        'Accept': 'application/json',
        'Accept-Language': _language() == 'ar' ? 'ar' : 'en',
        if (body != null) 'Content-Type': 'application/json',
        if (access != null && access.isNotEmpty)
          'Authorization': 'Bearer $access',
        ...headers,
      };
      try {
        final request = http.Request(method, _config.customerUri(path, query))
          ..headers.addAll(allHeaders);
        if (body != null) request.body = jsonEncode(body);
        final streamed = await _http.send(request).timeout(_timeout);
        final response = await http.Response.fromStream(streamed);
        final payload = response.bodyBytes.isEmpty
            ? null
            : _decode(response.bodyBytes);
        if (response.statusCode >= 200 && response.statusCode < 300) {
          return payload;
        }
        final problem = ApiProblem.fromPayload(response.statusCode, payload);
        if (auth &&
            canRefresh &&
            retryAuth &&
            problem.isAuthenticationFailure) {
          await _refreshTokens();
          return await send(false);
        }
        throw problem;
      } on TimeoutException {
        throw const NetworkProblem('timeout');
      } on http.ClientException catch (error) {
        throw NetworkProblem('connection', error.message);
      }
    }

    return send(true);
  }

  Object? _decode(Uint8List bytes) {
    if (bytes.isEmpty) return null;
    try {
      return jsonDecode(utf8.decode(bytes));
    } on FormatException {
      throw const NetworkProblem(
        'invalid_response',
        'Server response was not valid JSON.',
      );
    }
  }

  Future<SessionTokens> _refreshTokens() {
    final active = _refreshing;
    if (active != null) return active;
    final next = _performRefresh();
    _refreshing = next;
    next.whenComplete(() {
      if (identical(_refreshing, next)) _refreshing = null;
    });
    return next;
  }

  Future<SessionTokens> _performRefresh() async {
    final refresh = await _tokens.readRefresh();
    if (refresh == null || refresh.isEmpty) {
      await _tokens.clear();
      throw ApiProblem(
        statusCode: 401,
        code: 'invalid_refresh_token',
        message: 'No refresh credential is available.',
      );
    }
    try {
      final request = http.Request('POST', _config.customerUri('auth/refresh/'))
        ..headers.addAll({
          'Accept': 'application/json',
          'Accept-Language': _language() == 'ar' ? 'ar' : 'en',
          'Content-Type': 'application/json',
        })
        ..body = jsonEncode({'refresh': refresh});
      final streamed = await _http.send(request).timeout(_timeout);
      final response = await http.Response.fromStream(streamed);
      final payload = response.bodyBytes.isEmpty
          ? null
          : _decode(response.bodyBytes);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final problem = ApiProblem.fromPayload(response.statusCode, payload);
        if (problem.code == 'invalid_refresh_token' ||
            problem.isAuthenticationFailure) {
          await _tokens.clear();
        }
        throw problem;
      }
      final json = asMap(payload);
      final access = asString(json['access']);
      final rotated = asString(json['refresh']);
      if (access.isEmpty || rotated.isEmpty) {
        await _tokens.clear();
        throw const NetworkProblem(
          'invalid_response',
          'Rotating refresh response did not return new credentials.',
        );
      }
      final tokens = SessionTokens(access: access, refresh: rotated);
      await _tokens.write(tokens);
      return tokens;
    } on TimeoutException {
      throw const NetworkProblem('timeout');
    } on http.ClientException catch (error) {
      throw NetworkProblem('connection', error.message);
    }
  }

  void close() => _http.close();
}
