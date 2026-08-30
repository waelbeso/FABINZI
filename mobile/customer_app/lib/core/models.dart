typedef JsonMap = Map<String, dynamic>;

JsonMap asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map)
    return value.map((key, val) => MapEntry(key.toString(), val));
  return <String, dynamic>{};
}

List<dynamic> asList(Object? value) =>
    value is List ? value : const <dynamic>[];
String asString(Object? value, [String fallback = '']) =>
    value?.toString() ?? fallback;
String? asNullableString(Object? value) {
  if (value == null) return null;
  final result = value.toString();
  return result.isEmpty ? null : result;
}

int asInt(Object? value, [int fallback = 0]) {
  if (value is int) return value;
  return int.tryParse(value?.toString() ?? '') ?? fallback;
}

bool asBool(Object? value, [bool fallback = false]) =>
    value is bool ? value : fallback;
DateTime? asDateTime(Object? value) =>
    DateTime.tryParse(value?.toString() ?? '');

class ApiProblem implements Exception {
  ApiProblem({
    required this.statusCode,
    required this.code,
    required this.message,
    this.fields = const {},
    this.requestId,
  });

  final int statusCode;
  final String code;
  final String message;
  final Map<String, List<String>> fields;
  final String? requestId;

  factory ApiProblem.fromPayload(int statusCode, Object? payload) {
    final error = asMap(asMap(payload)['error']);
    final rawFields = asMap(error['fields']);
    final fields = <String, List<String>>{};
    for (final entry in rawFields.entries) {
      fields[entry.key] = asList(entry.value)
          .map((item) => item.toString())
          .toList();
    }
    return ApiProblem(
      statusCode: statusCode,
      code: asString(error['code'], 'unknown_error'),
      message: asString(error['message'], 'Request failed.'),
      fields: fields,
      requestId: asNullableString(error['request_id']),
    );
  }

  bool get isAuthenticationFailure =>
      code == 'authentication_required' ||
      code == 'token_expired' ||
      code == 'invalid_token';

  @override
  String toString() => 'ApiProblem($statusCode, $code, requestId: $requestId)';
}

class Money {
  const Money({required this.amount, required this.currency});
  final String amount;
  final String? currency;

  factory Money.fromJson(Object? value) {
    final json = asMap(value);
    return Money(
      amount: asString(json['amount'], '0.00'),
      currency: asNullableString(json['currency']),
    );
  }

  String get display => currency == null ? amount : '$amount $currency';
}

class Paged<T> {
  const Paged({
    required this.count,
    required this.next,
    required this.previous,
    required this.results,
  });
  final int count;
  final String? next;
  final String? previous;
  final List<T> results;

  factory Paged.fromJson(Object? value, T Function(Object?) parse) {
    final json = asMap(value);
    return Paged<T>(
      count: asInt(json['count']),
      next: asNullableString(json['next']),
      previous: asNullableString(json['previous']),
      results: asList(json['results']).map(parse).toList(),
    );
  }
}

class BootstrapConfig {
  BootstrapConfig({
    required this.contract,
    required this.apiVersion,
    required this.backendVersion,
    required this.locales,
    required this.defaultLocale,
    required this.accessTokenSeconds,
    required this.refreshTokenSeconds,
    required this.refreshRotation,
    required this.refreshReuseRevoked,
    required this.accountCapabilities,
    required this.defaultPageSize,
    required this.maxPageSize,
    required this.uploadMaxBytes,
    required this.uploadMimeTypes,
    required this.privateUploads,
  });

  final String contract;
  final String apiVersion;
  final String backendVersion;
  final List<String> locales;
  final String defaultLocale;
  final int accessTokenSeconds;
  final int refreshTokenSeconds;
  final bool refreshRotation;
  final bool refreshReuseRevoked;
  final Map<String, bool> accountCapabilities;
  final int defaultPageSize;
  final int maxPageSize;
  final int uploadMaxBytes;
  final List<String> uploadMimeTypes;
  final bool privateUploads;

  factory BootstrapConfig.fromJson(Object? value) {
    final json = asMap(value);
    final auth = asMap(json['authentication']);
    final pagination = asMap(json['pagination']);
    final uploads = asMap(json['uploads']);
    final capabilities = asMap(json['account_capabilities']);
    return BootstrapConfig(
      contract: asString(json['contract']),
      apiVersion: asString(json['api_version']),
      backendVersion: asString(json['backend_version']),
      locales: asList(json['locales']).map((v) => v.toString()).toList(),
      defaultLocale: asString(json['default_locale'], 'en'),
      accessTokenSeconds: asInt(auth['access_token_seconds'], 900),
      refreshTokenSeconds: asInt(auth['refresh_token_seconds'], 2592000),
      refreshRotation: asBool(auth['refresh_rotation']),
      refreshReuseRevoked: asBool(auth['refresh_reuse_revoked']),
      accountCapabilities: capabilities.map(
        (key, val) => MapEntry(key, asBool(val)),
      ),
      defaultPageSize: asInt(pagination['default_page_size'], 20),
      maxPageSize: asInt(pagination['max_page_size'], 50),
      uploadMaxBytes: asInt(uploads['max_bytes'], 10485760),
      uploadMimeTypes: asList(uploads['mime_types'])
          .map((v) => v.toString())
          .toList(),
      privateUploads: asBool(uploads['private_by_default'], true),
    );
  }
}

class UserProfile {
  UserProfile({
    required this.id,
    required this.username,
    required this.displayName,
    required this.email,
    required this.language,
    required this.theme,
    required this.accountState,
  });
  final int id;
  final String username;
  final String displayName;
  final String email;
  final String language;
  final String theme;
  final String accountState;

  factory UserProfile.fromJson(Object? value) {
    final json = asMap(value);
    return UserProfile(
      id: asInt(json['id']),
      username: asString(json['username']),
      displayName: asString(json['display_name']),
      email: asString(json['email']),
      language: asString(json['language'], 'en'),
      theme: asString(json['theme'], 'system'),
      accountState: asString(json['account_state'], 'unknown'),
    );
  }
}

class ApiImage {
  ApiImage({required this.url, this.width, this.height, this.alt});
  final String url;
  final int? width;
  final int? height;
  final String? alt;
  factory ApiImage.fromJson(Object? value) {
    final json = asMap(value);
    return ApiImage(
      url: asString(json['url']),
      width: json['width'] == null ? null : asInt(json['width']),
      height: json['height'] == null ? null : asInt(json['height']),
      alt: asNullableString(json['alt']),
    );
  }
}

class Storefront {
  Storefront({
    required this.slug,
    required this.name,
    required this.about,
    this.logo,
    this.publishedAt,
  });
  final String slug;
  final String name;
  final String about;
  final ApiImage? logo;
  final DateTime? publishedAt;
  factory Storefront.fromJson(Object? value) {
    final json = asMap(value);
    return Storefront(
      slug: asString(json['slug']),
      name: asString(json['name']),
      about: asString(json['about']),
      logo: json['logo'] == null ? null : ApiImage.fromJson(json['logo']),
      publishedAt: asDateTime(json['published_at']),
    );
  }
}

class ProductVariant {
  ProductVariant({
    required this.sku,
    required this.size,
    required this.colorName,
    required this.colorHex,
    required this.price,
    required this.available,
  });
  final String sku;
  final String size;
  final String colorName;
  final String colorHex;
  final Money price;
  final bool available;
  factory ProductVariant.fromJson(Object? value) {
    final json = asMap(value);
    return ProductVariant(
      sku: asString(json['sku']),
      size: asString(json['size']),
      colorName: asString(json['color_name']),
      colorHex: asString(json['color_hex']),
      price: Money.fromJson(json['price']),
      available: asBool(json['available']),
    );
  }
}

class ZonePlacement {
  ZonePlacement({
    required this.x,
    required this.y,
    required this.width,
    required this.height,
  });
  final double x;
  final double y;
  final double width;
  final double height;
  factory ZonePlacement.fromJson(Object? value) {
    final json = asMap(value);
    double number(String key, double fallback) =>
        double.tryParse(json[key]?.toString() ?? '') ?? fallback;
    return ZonePlacement(
      x: number('x', 0),
      y: number('y', 0),
      width: number('width', 1),
      height: number('height', 1),
    );
  }
}

class DecorationZone {
  DecorationZone({
    required this.name,
    required this.method,
    required this.placement,
    this.maxWidthMm,
    this.maxHeightMm,
  });
  final String name;
  final String method;
  final ZonePlacement placement;
  final String? maxWidthMm;
  final String? maxHeightMm;
  factory DecorationZone.fromJson(Object? value) {
    final json = asMap(value);
    return DecorationZone(
      name: asString(json['name']),
      method: asString(json['method']),
      placement: ZonePlacement.fromJson(json['placement']),
      maxWidthMm: asNullableString(json['max_width_mm']),
      maxHeightMm: asNullableString(json['max_height_mm']),
    );
  }

  List<String> get supportedMethods =>
      method == 'both' ? const ['print', 'embroidery'] : [method];
}

class Product {
  Product({
    required this.storeSlug,
    required this.storeName,
    required this.slug,
    required this.title,
    required this.description,
    required this.kind,
    required this.customizationEnabled,
    required this.featured,
    required this.fulfillmentMode,
    required this.basePrice,
    required this.variants,
    required this.images,
    required this.decorationZones,
    this.leadTimeDays,
    this.publishedAt,
  });
  final String storeSlug;
  final String storeName;
  final String slug;
  final String title;
  final String description;
  final String kind;
  final bool customizationEnabled;
  final bool featured;
  final String fulfillmentMode;
  final int? leadTimeDays;
  final Money basePrice;
  final List<ProductVariant> variants;
  final List<ApiImage> images;
  final List<DecorationZone> decorationZones;
  final DateTime? publishedAt;
  factory Product.fromJson(Object? value) {
    final json = asMap(value);
    final store = asMap(json['store']);
    return Product(
      storeSlug: asString(store['slug']),
      storeName: asString(store['name']),
      slug: asString(json['slug']),
      title: asString(json['title']),
      description: asString(json['description']),
      kind: asString(json['kind'], 'unknown'),
      customizationEnabled: asBool(json['customization_enabled']),
      featured: asBool(json['featured']),
      fulfillmentMode: asString(json['fulfillment_mode']),
      leadTimeDays: json['lead_time_days'] == null
          ? null
          : asInt(json['lead_time_days']),
      basePrice: Money.fromJson(json['base_price']),
      variants: asList(json['variants']).map(ProductVariant.fromJson).toList(),
      images: asList(json['images']).map(ApiImage.fromJson).toList(),
      decorationZones: asList(json['decoration_zones'])
          .map(DecorationZone.fromJson)
          .toList(),
      publishedAt: asDateTime(json['published_at']),
    );
  }
}

class Artwork {
  Artwork({
    required this.id,
    required this.title,
    required this.description,
    required this.tags,
    required this.creatorName,
    required this.approvedVersionId,
    required this.productionMethods,
    required this.productTypes,
    required this.suitability,
    this.preview,
    this.updatedAt,
  });
  final int id;
  final String title;
  final String description;
  final List<String> tags;
  final String creatorName;
  final int approvedVersionId;
  final ApiImage? preview;
  final List<String> productionMethods;
  final List<String> productTypes;
  final String suitability;
  final DateTime? updatedAt;
  factory Artwork.fromJson(Object? value) {
    final json = asMap(value);
    return Artwork(
      id: asInt(json['id']),
      title: asString(json['title']),
      description: asString(json['description']),
      tags: asList(json['tags']).map((v) => v.toString()).toList(),
      creatorName: asString(asMap(json['creator'])['name']),
      approvedVersionId: asInt(json['approved_version_id']),
      preview: json['preview'] == null
          ? null
          : ApiImage.fromJson(json['preview']),
      productionMethods: asList(json['production_methods'])
          .map((v) => v.toString())
          .toList(),
      productTypes: asList(json['product_types'])
          .map((v) => v.toString())
          .toList(),
      suitability: asString(json['suitability']),
      updatedAt: asDateTime(json['updated_at']),
    );
  }
}

class StudioTransform {
  const StudioTransform({
    required this.x,
    required this.y,
    required this.scale,
    required this.rotation,
  });
  final double x;
  final double y;
  final double scale;
  final double rotation;
  factory StudioTransform.fromJson(Object? value) {
    final json = asMap(value);
    double number(String key, double fallback) =>
        double.tryParse(json[key]?.toString() ?? '') ?? fallback;
    return StudioTransform(
      x: number('x', .5),
      y: number('y', .5),
      scale: number('scale', .35),
      rotation: number('rotation', 0),
    );
  }
  JsonMap toJson() => {'x': x, 'y': y, 'scale': scale, 'rotation': rotation};
  StudioTransform copyWith({
    double? x,
    double? y,
    double? scale,
    double? rotation,
  }) => StudioTransform(
    x: x ?? this.x,
    y: y ?? this.y,
    scale: scale ?? this.scale,
    rotation: rotation ?? this.rotation,
  );
}

class StudioElement {
  StudioElement({
    required this.id,
    required this.kind,
    required this.decorationZone,
    required this.text,
    required this.productionMethod,
    required this.transform,
    required this.style,
    this.mediaAssetId,
    this.artworkVersionId,
    this.sourceUrl,
  });
  final int id;
  final String kind;
  final DecorationZone decorationZone;
  final String text;
  final int? mediaAssetId;
  final int? artworkVersionId;
  final String productionMethod;
  final StudioTransform transform;
  final JsonMap style;
  final String? sourceUrl;
  factory StudioElement.fromJson(Object? value) {
    final json = asMap(value);
    return StudioElement(
      id: asInt(json['id']),
      kind: asString(json['kind']),
      decorationZone: DecorationZone.fromJson(json['decoration_zone']),
      text: asString(json['text']),
      mediaAssetId: json['media_asset_id'] == null
          ? null
          : asInt(json['media_asset_id']),
      artworkVersionId: json['artwork_version_id'] == null
          ? null
          : asInt(json['artwork_version_id']),
      productionMethod: asString(json['production_method']),
      transform: StudioTransform.fromJson(json['transform']),
      style: asMap(json['style']),
      sourceUrl: asNullableString(json['source_url']),
    );
  }
  StudioElement copyWith({
    StudioTransform? transform,
    String? text,
    String? productionMethod,
  }) => StudioElement(
    id: id,
    kind: kind,
    decorationZone: decorationZone,
    text: text ?? this.text,
    mediaAssetId: mediaAssetId,
    artworkVersionId: artworkVersionId,
    productionMethod: productionMethod ?? this.productionMethod,
    transform: transform ?? this.transform,
    style: style,
    sourceUrl: sourceUrl,
  );
}

class StudioProductRef {
  StudioProductRef({
    required this.storeSlug,
    required this.productSlug,
    required this.title,
    required this.customizationEnabled,
  });
  final String storeSlug;
  final String productSlug;
  final String title;
  final bool customizationEnabled;
  factory StudioProductRef.fromJson(Object? value) {
    final json = asMap(value);
    return StudioProductRef(
      storeSlug: asString(json['store_slug']),
      productSlug: asString(json['product_slug']),
      title: asString(json['title']),
      customizationEnabled: asBool(json['customization_enabled']),
    );
  }
}

class StudioProject {
  StudioProject({
    required this.id,
    required this.status,
    required this.product,
    required this.quantity,
    required this.customerNotes,
    required this.unitPrice,
    required this.decorationZones,
    required this.elements,
    this.variant,
    this.createdAt,
    this.updatedAt,
    this.readyAt,
  });
  final int id;
  final String status;
  final StudioProductRef product;
  final ProductVariant? variant;
  final int quantity;
  final String customerNotes;
  final Money unitPrice;
  final List<DecorationZone> decorationZones;
  final List<StudioElement> elements;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final DateTime? readyAt;
  bool get isDraft => status == 'draft';
  bool get isReady => status == 'ready';
  factory StudioProject.fromJson(Object? value) {
    final json = asMap(value);
    return StudioProject(
      id: asInt(json['id']),
      status: asString(json['status']),
      product: StudioProductRef.fromJson(json['product']),
      variant: json['variant'] == null
          ? null
          : ProductVariant.fromJson(json['variant']),
      quantity: asInt(json['quantity'], 1),
      customerNotes: asString(json['customer_notes']),
      unitPrice: Money.fromJson(json['unit_price']),
      decorationZones: asList(json['decoration_zones'])
          .map(DecorationZone.fromJson)
          .toList(),
      elements: asList(json['elements']).map(StudioElement.fromJson).toList(),
      createdAt: asDateTime(json['created_at']),
      updatedAt: asDateTime(json['updated_at']),
      readyAt: asDateTime(json['ready_at']),
    );
  }
}

class UploadAsset {
  UploadAsset({
    required this.id,
    required this.mimeType,
    required this.sizeBytes,
    required this.accessUrl,
    this.width,
    this.height,
  });
  final int id;
  final String mimeType;
  final int sizeBytes;
  final int? width;
  final int? height;
  final String accessUrl;
  factory UploadAsset.fromJson(Object? value) {
    final json = asMap(value);
    return UploadAsset(
      id: asInt(json['id']),
      mimeType: asString(json['mime_type']),
      sizeBytes: asInt(json['size_bytes']),
      width: json['width'] == null ? null : asInt(json['width']),
      height: json['height'] == null ? null : asInt(json['height']),
      accessUrl: asString(json['access_url']),
    );
  }
}

class StudioValidation {
  StudioValidation({
    required this.valid,
    required this.errors,
    required this.unitPrice,
  });
  final bool valid;
  final List<String> errors;
  final Money unitPrice;
  factory StudioValidation.fromJson(Object? value) {
    final json = asMap(value);
    return StudioValidation(
      valid: asBool(json['valid']),
      errors: asList(json['errors']).map((v) => v.toString()).toList(),
      unitPrice: Money.fromJson(json['unit_price']),
    );
  }
}

class CartProductRef {
  CartProductRef({
    required this.storeSlug,
    required this.productSlug,
    required this.title,
  });
  final String storeSlug;
  final String productSlug;
  final String title;
  factory CartProductRef.fromJson(Object? value) {
    final json = asMap(value);
    return CartProductRef(
      storeSlug: asString(json['store_slug']),
      productSlug: asString(json['product_slug']),
      title: asString(json['title']),
    );
  }
}

class CartItem {
  CartItem({
    required this.id,
    required this.kind,
    required this.product,
    required this.quantity,
    required this.unitPrice,
    required this.lineTotal,
    this.variant,
    this.studioProjectId,
  });
  final int id;
  final String kind;
  final CartProductRef product;
  final ProductVariant? variant;
  final int? studioProjectId;
  final int quantity;
  final Money unitPrice;
  final Money lineTotal;
  factory CartItem.fromJson(Object? value) {
    final json = asMap(value);
    return CartItem(
      id: asInt(json['id']),
      kind: asString(json['kind']),
      product: CartProductRef.fromJson(json['product']),
      variant: json['variant'] == null
          ? null
          : ProductVariant.fromJson(json['variant']),
      studioProjectId: json['studio_project_id'] == null
          ? null
          : asInt(json['studio_project_id']),
      quantity: asInt(json['quantity'], 1),
      unitPrice: Money.fromJson(json['unit_price']),
      lineTotal: Money.fromJson(json['line_total']),
    );
  }
}

class Cart {
  Cart({
    required this.id,
    required this.status,
    required this.items,
    required this.itemCount,
    required this.subtotal,
    required this.shippingAmount,
    required this.discountAmount,
    required this.total,
  });
  final int id;
  final String status;
  final List<CartItem> items;
  final int itemCount;
  final Money subtotal;
  final Money shippingAmount;
  final Money discountAmount;
  final Money total;
  factory Cart.fromJson(Object? value) {
    final json = asMap(value);
    return Cart(
      id: asInt(json['id']),
      status: asString(json['status']),
      items: asList(json['items']).map(CartItem.fromJson).toList(),
      itemCount: asInt(json['item_count']),
      subtotal: Money.fromJson(json['subtotal']),
      shippingAmount: Money.fromJson(json['shipping_amount']),
      discountAmount: Money.fromJson(json['discount_amount']),
      total: Money.fromJson(json['total']),
    );
  }
}

class ShippingDetails {
  ShippingDetails({
    required this.name,
    required this.phone,
    required this.email,
    required this.address1,
    required this.address2,
    required this.city,
    required this.region,
    required this.country,
    required this.postalCode,
  });
  final String name;
  final String phone;
  final String email;
  final String address1;
  final String address2;
  final String city;
  final String region;
  final String country;
  final String postalCode;
  factory ShippingDetails.fromJson(Object? value) {
    final json = asMap(value);
    return ShippingDetails(
      name: asString(json['name']),
      phone: asString(json['phone']),
      email: asString(json['email']),
      address1: asString(json['address1']),
      address2: asString(json['address2']),
      city: asString(json['city']),
      region: asString(json['region']),
      country: asString(json['country']),
      postalCode: asString(json['postal_code']),
    );
  }
  JsonMap toPatchJson() => {
    'shipping_name': name,
    'shipping_phone': phone,
    'shipping_email': email,
    'shipping_address1': address1,
    'shipping_address2': address2,
    'shipping_city': city,
    'shipping_region': region,
    'shipping_country': country,
    'postal_code': postalCode,
  };
}

class Checkout {
  Checkout({
    required this.id,
    required this.status,
    required this.source,
    required this.subtotal,
    required this.shippingAmount,
    required this.discountAmount,
    required this.total,
    required this.shipping,
    this.createdAt,
    this.updatedAt,
    this.placedAt,
  });
  final int id;
  final String status;
  final String source;
  final Money subtotal;
  final Money shippingAmount;
  final Money discountAmount;
  final Money total;
  final ShippingDetails shipping;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final DateTime? placedAt;
  factory Checkout.fromJson(Object? value) {
    final json = asMap(value);
    return Checkout(
      id: asInt(json['id']),
      status: asString(json['status']),
      source: asString(json['source']),
      subtotal: Money.fromJson(json['subtotal']),
      shippingAmount: Money.fromJson(json['shipping_amount']),
      discountAmount: Money.fromJson(json['discount_amount']),
      total: Money.fromJson(json['total']),
      shipping: ShippingDetails.fromJson(json['shipping']),
      createdAt: asDateTime(json['created_at']),
      updatedAt: asDateTime(json['updated_at']),
      placedAt: asDateTime(json['placed_at']),
    );
  }
}

class PaymentOption {
  PaymentOption({required this.provider, required this.label});
  final String provider;
  final String label;
  factory PaymentOption.fromJson(Object? value) {
    final json = asMap(value);
    return PaymentOption(
      provider: asString(json['provider']),
      label: asString(json['label']),
    );
  }
}

class Fulfillment {
  Fulfillment({
    required this.status,
    required this.label,
    this.carrier,
    this.trackingNumber,
    this.trackingUrl,
    this.packedAt,
    this.shippedAt,
    this.deliveredAt,
  });
  final String status;
  final String label;
  final String? carrier;
  final String? trackingNumber;
  final String? trackingUrl;
  final DateTime? packedAt;
  final DateTime? shippedAt;
  final DateTime? deliveredAt;
  factory Fulfillment.fromJson(Object? value) {
    final json = asMap(value);
    return Fulfillment(
      status: asString(json['status'], 'processing'),
      label: asString(json['label']),
      carrier: asNullableString(json['carrier']),
      trackingNumber: asNullableString(json['tracking_number']),
      trackingUrl: asNullableString(json['tracking_url']),
      packedAt: asDateTime(json['packed_at']),
      shippedAt: asDateTime(json['shipped_at']),
      deliveredAt: asDateTime(json['delivered_at']),
    );
  }
}

class PurchaseItem {
  PurchaseItem({
    required this.reference,
    required this.title,
    required this.sku,
    required this.size,
    required this.colorName,
    required this.quantity,
    required this.unitPrice,
    required this.lineTotal,
    required this.status,
    required this.statusLabel,
    required this.customized,
    required this.fulfillment,
    this.studioProjectId,
  });
  final String reference;
  final String title;
  final String sku;
  final String size;
  final String colorName;
  final int quantity;
  final Money unitPrice;
  final Money lineTotal;
  final String status;
  final String statusLabel;
  final bool customized;
  final int? studioProjectId;
  final Fulfillment fulfillment;
  factory PurchaseItem.fromJson(Object? value) {
    final json = asMap(value);
    return PurchaseItem(
      reference: asString(json['reference']),
      title: asString(json['title']),
      sku: asString(json['sku']),
      size: asString(json['size']),
      colorName: asString(json['color_name']),
      quantity: asInt(json['quantity']),
      unitPrice: Money.fromJson(json['unit_price']),
      lineTotal: Money.fromJson(json['line_total']),
      status: asString(json['status']),
      statusLabel: asString(json['status_label']),
      customized: asBool(json['customized']),
      studioProjectId: json['studio_project_id'] == null
          ? null
          : asInt(json['studio_project_id']),
      fulfillment: Fulfillment.fromJson(json['fulfillment']),
    );
  }
}

class Purchase {
  Purchase({
    required this.reference,
    required this.status,
    required this.statusLabel,
    required this.fulfillmentStatus,
    required this.fulfillmentStatusLabel,
    required this.paymentMethod,
    required this.paymentStatus,
    required this.subtotal,
    required this.shippingAmount,
    required this.discountAmount,
    required this.total,
    required this.itemCount,
    required this.items,
    this.shipping = const {},
    this.createdAt,
    this.confirmedAt,
  });
  final String reference;
  final String status;
  final String statusLabel;
  final String fulfillmentStatus;
  final String fulfillmentStatusLabel;
  final String paymentMethod;
  final String? paymentStatus;
  final Money subtotal;
  final Money shippingAmount;
  final Money discountAmount;
  final Money total;
  final int itemCount;
  final JsonMap shipping;
  final List<PurchaseItem> items;
  final DateTime? createdAt;
  final DateTime? confirmedAt;
  factory Purchase.fromJson(Object? value) {
    final json = asMap(value);
    final payment = asMap(json['payment']);
    return Purchase(
      reference: asString(json['reference']),
      status: asString(json['status']),
      statusLabel: asString(json['status_label']),
      fulfillmentStatus: asString(json['fulfillment_status']),
      fulfillmentStatusLabel: asString(json['fulfillment_status_label']),
      paymentMethod: asString(payment['method']),
      paymentStatus: asNullableString(payment['status']),
      subtotal: Money.fromJson(json['subtotal']),
      shippingAmount: Money.fromJson(json['shipping_amount']),
      discountAmount: Money.fromJson(json['discount_amount']),
      total: Money.fromJson(json['total']),
      itemCount: asInt(json['item_count']),
      shipping: asMap(json['shipping']),
      items: asList(json['items']).map(PurchaseItem.fromJson).toList(),
      createdAt: asDateTime(json['created_at']),
      confirmedAt: asDateTime(json['confirmed_at']),
    );
  }
}

class PaymentContinuation {
  PaymentContinuation({
    required this.provider,
    required this.status,
    this.redirectUrl,
    this.clientSecret,
  });
  final String provider;
  final String status;
  final String? redirectUrl;
  final String? clientSecret;
  factory PaymentContinuation.fromJson(Object? value) {
    final json = asMap(value);
    return PaymentContinuation(
      provider: asString(json['provider']),
      status: asString(json['status']),
      redirectUrl: asNullableString(json['redirect_url']),
      clientSecret: asNullableString(json['client_secret']),
    );
  }
}

class PlacementResult {
  PlacementResult({
    required this.idempotentReplay,
    required this.purchase,
    required this.payment,
  });
  final bool idempotentReplay;
  final Purchase purchase;
  final PaymentContinuation payment;
  factory PlacementResult.fromJson(Object? value) {
    final json = asMap(value);
    return PlacementResult(
      idempotentReplay: asBool(json['idempotent_replay']),
      purchase: Purchase.fromJson(json['purchase']),
      payment: PaymentContinuation.fromJson(json['payment']),
    );
  }
}

class NotificationItem {
  NotificationItem({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    required this.isRead,
    this.createdAt,
    this.readAt,
    this.targetResource,
    this.targetReference,
  });
  final int id;
  final String type;
  final String title;
  final String body;
  final bool isRead;
  final DateTime? createdAt;
  final DateTime? readAt;
  final String? targetResource;
  final String? targetReference;
  factory NotificationItem.fromJson(Object? value) {
    final json = asMap(value);
    final target = asMap(json['target']);
    return NotificationItem(
      id: asInt(json['id']),
      type: asString(json['type']),
      title: asString(json['title']),
      body: asString(json['body']),
      isRead: asBool(json['is_read']),
      createdAt: asDateTime(json['created_at']),
      readAt: asDateTime(json['read_at']),
      targetResource: asNullableString(target['resource']),
      targetReference: asNullableString(target['reference']),
    );
  }
}

class NotificationPreferences {
  NotificationPreferences({
    required this.emailEnabled,
    required this.smsEnabled,
    required this.phoneE164,
  });
  final bool emailEnabled;
  final bool smsEnabled;
  final String phoneE164;
  factory NotificationPreferences.fromJson(Object? value) {
    final json = asMap(value);
    return NotificationPreferences(
      emailEnabled: asBool(json['email_enabled']),
      smsEnabled: asBool(json['sms_enabled']),
      phoneE164: asString(json['phone_e164']),
    );
  }
}
