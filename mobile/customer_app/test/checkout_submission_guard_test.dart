import 'package:fabinzi_customer_app/core/checkout_submission_guard.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'checkout submission guard allows only one active placement per checkout',
    () {
      final guard = CheckoutSubmissionGuard();

      expect(guard.tryAcquire(6001), isTrue);
      expect(guard.isActive(6001), isTrue);
      expect(guard.tryAcquire(6001), isFalse);
      expect(guard.tryAcquire(6002), isTrue);

      guard.release(6001);
      expect(guard.isActive(6001), isFalse);
      expect(guard.tryAcquire(6001), isTrue);
    },
  );
}
