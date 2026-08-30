class CheckoutSubmissionGuard {
  final Set<int> _activeCheckoutIds = <int>{};

  bool tryAcquire(int checkoutId) => _activeCheckoutIds.add(checkoutId);

  void release(int checkoutId) {
    _activeCheckoutIds.remove(checkoutId);
  }

  bool isActive(int checkoutId) => _activeCheckoutIds.contains(checkoutId);
}
