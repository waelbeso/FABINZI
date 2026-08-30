import 'dart:convert';
import 'dart:io';

import 'package:fabinzi_customer_app/core/models.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> fixtures() => jsonDecode(
  File('../../contracts/customer-api-v1-fixtures.json').readAsStringSync(),
) as Map<String, dynamic>;

void main() {
  late Map<String, dynamic> data;
  setUpAll(() => data = fixtures());

  test('authoritative money remains a decimal string plus currency', () {
    final product = Product.fromJson(data['product']);
    expect(product.basePrice.amount, '500.00');
    expect(product.basePrice.currency, 'EGP');
    expect(product.variants.single.price.amount, '525.00');
  });

  test('pagination contract parses count next previous results', () {
    final page = Paged<Object?>.fromJson(data['pagination'], (value) => value);
    expect(page.count, 25);
    expect(page.next, contains('page=2'));
    expect(page.previous, isNull);
    expect(page.results, isEmpty);
  });

  test(
    'product and Artwork fixtures parse without invented marketplace fields',
    () {
      final product = Product.fromJson(data['product']);
      final art = Artwork.fromJson(data['artwork']);
      expect(product.storeSlug, 'example-store');
      expect(product.decorationZones.single.supportedMethods, [
        'print',
        'embroidery',
      ]);
      expect(art.approvedVersionId, 2101);
      expect(art.productionMethods, ['print']);
    },
  );

  test(
    'Studio canonical transform round-trips normalized coordinates and degrees',
    () {
      final studio = StudioProject.fromJson(data['studio']);
      final transform = studio.elements.single.transform;
      expect(transform.x, .5);
      expect(transform.y, .5);
      expect(transform.scale, .3);
      expect(transform.rotation, 0);
      expect(
        StudioTransform.fromJson(transform.copyWith(rotation: 45).toJson())
            .rotation,
        45,
      );
    },
  );

  test('private upload exposes only Customer access URL metadata', () {
    final upload = UploadAsset.fromJson(data['private_upload']);
    expect(upload.mimeType, 'image/png');
    expect(upload.sizeBytes, 123456);
    expect(upload.accessUrl, '/api/v1/customer/media/4001/');
  });

  test('Cart and Checkout preserve server-authoritative totals and shipping patch names', () {
    final cart = Cart.fromJson(data['cart']);
    final checkout = Checkout.fromJson(data['checkout']);
    expect(cart.total.amount, '1050.00');
    expect(cart.items.single.quantity, 2);
    expect(checkout.total.amount, '1050.00');
    final patch = checkout.shipping.toPatchJson();
    expect(patch['shipping_address1'], '1 Example Street');
    expect(patch['shipping_country'], 'EG');
  });

  test(
    'Parent CustomerPurchase parses aggregate and child fulfillment truthfully',
    () {
      final purchase = Purchase.fromJson(data['purchase']);
      expect(purchase.reference, '11111111-1111-4111-8111-111111111111');
      expect(purchase.itemCount, 1);
      expect(purchase.items.single.fulfillment.status, 'processing');
      expect(purchase.items.single.fulfillment.trackingNumber, isNull);
    },
  );

  test('notification purchase deep link parses from frozen target shape', () {
    final notification = NotificationItem.fromJson(data['notification']);
    expect(notification.isRead, isFalse);
    expect(notification.targetResource, 'purchase');
    expect(
      notification.targetReference,
      '11111111-1111-4111-8111-111111111111',
    );
  });

  test('error envelope preserves code fields and request id', () {
    final problem = ApiProblem.fromPayload(
      400,
      (data['errors'] as Map<String, dynamic>)['validation_error'],
    );
    expect(problem.code, 'validation_error');
    expect(problem.fields['quantity'], ['Quantity must be at least 1.']);
    expect(problem.requestId, 'fixture-request-id-validation');
  });
}
