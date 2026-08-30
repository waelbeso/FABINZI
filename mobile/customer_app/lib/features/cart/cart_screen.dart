import 'package:flutter/material.dart';
import 'package:flutter_stripe/flutter_stripe.dart' as stripe;
import 'package:url_launcher/url_launcher.dart';

import '../../core/app_controller.dart';
import '../../core/l10n.dart';
import '../../core/models.dart';
import '../../ui/common.dart';
import '../purchases/purchases_screen.dart';

class CartScreen extends StatefulWidget {
  const CartScreen({super.key, required this.controller});
  final AppController controller;

  @override
  State<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends State<CartScreen> {
  Cart? cart;
  bool loading = true;
  int? mutatingId;
  Object? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final value = await widget.controller.api.cart();
      if (mounted) setState(() => cart = value);
    } catch (value) {
      if (mounted) setState(() => error = value);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> quantity(CartItem item, int value) async {
    if (mutatingId != null || item.kind == 'studio' || value < 1) return;
    setState(() => mutatingId = item.id);
    try {
      final updated = await widget.controller.api.updateCartItem(
        item.id,
        value,
      );
      if (mounted) setState(() => cart = updated);
    } catch (value) {
      if (mounted) await showProblem(context, value);
    } finally {
      if (mounted) setState(() => mutatingId = null);
    }
  }

  Future<void> remove(CartItem item) async {
    if (mutatingId != null) return;
    setState(() => mutatingId = item.id);
    try {
      await widget.controller.api.removeCartItem(item.id);
      await load();
    } catch (value) {
      if (mounted) await showProblem(context, value);
    } finally {
      if (mounted) setState(() => mutatingId = null);
    }
  }

  Future<void> checkout() async {
    try {
      final value = await widget.controller.api.cartCheckout();
      if (mounted) {
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => CheckoutScreen(
              controller: widget.controller,
              initialCheckout: value,
            ),
          ),
        );
        load();
      }
    } catch (value) {
      if (mounted) await showProblem(context, value);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(L10n.t(context, 'cart'))),
    body: loading
        ? const BusyView()
        : error != null
        ? FailureView(error: error!, onRetry: load)
        : _body(context),
  );

  Widget _body(BuildContext context) {
    final value = cart!;
    if (value.items.isEmpty) {
      return EmptyView(
        icon: Icons.shopping_bag_outlined,
        title: L10n.t(context, 'emptyCart'),
      );
    }
    return Column(
      children: [
        Expanded(
          child: RefreshIndicator(
            onRefresh: load,
            child: ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(16),
              itemCount: value.items.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (context, index) {
                final item = value.items[index];
                final locked = mutatingId == item.id;
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Row(
                      children: [
                        CircleAvatar(
                          child: Icon(
                            item.kind == 'studio'
                                ? Icons.auto_fix_high
                                : Icons.checkroom_outlined,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                item.product.title,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                              if (item.variant != null)
                                Text(
                                  [item.variant!.size, item.variant!.colorName]
                                      .where((part) => part.isNotEmpty)
                                      .join(' · '),
                                ),
                              const SizedBox(height: 6),
                              MoneyText(item.lineTotal),
                              if (item.kind == 'studio')
                                Padding(
                                  padding: const EdgeInsets.only(top: 5),
                                  child: Text(
                                    L10n.t(context, 'studioQuantityHint'),
                                    style: Theme.of(context)
                                        .textTheme
                                        .bodySmall,
                                  ),
                                ),
                            ],
                          ),
                        ),
                        Column(
                          children: [
                            Row(
                              children: [
                                IconButton(
                                  onPressed:
                                      locked ||
                                          item.kind == 'studio' ||
                                          item.quantity <= 1
                                      ? null
                                      : () => quantity(item, item.quantity - 1),
                                  icon: const Icon(Icons.remove_circle_outline),
                                ),
                                Text(
                                  '${item.quantity}',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                IconButton(
                                  onPressed: locked || item.kind == 'studio'
                                      ? null
                                      : () => quantity(item, item.quantity + 1),
                                  icon: const Icon(Icons.add_circle_outline),
                                ),
                              ],
                            ),
                            TextButton.icon(
                              onPressed: locked ? null : () => remove(item),
                              icon: const Icon(Icons.delete_outline),
                              label: Text(L10n.t(context, 'remove')),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ),
        SafeArea(
          top: false,
          child: Material(
            elevation: 10,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(18, 14, 18, 16),
              child: Column(
                children: [
                  _amountRow(
                    context,
                    L10n.t(context, 'subtotal'),
                    value.subtotal,
                  ),
                  _amountRow(
                    context,
                    L10n.t(context, 'shipping'),
                    value.shippingAmount,
                  ),
                  _amountRow(
                    context,
                    L10n.t(context, 'discount'),
                    value.discountAmount,
                  ),
                  const Divider(height: 22),
                  _amountRow(
                    context,
                    L10n.t(context, 'total'),
                    value.total,
                    strong: true,
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: checkout,
                      icon: const Icon(Icons.arrow_forward_rounded),
                      label: Text(L10n.t(context, 'reviewCheckout')),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

Widget _amountRow(
  BuildContext context,
  String label,
  Money money, {
  bool strong = false,
}) => Padding(
  padding: const EdgeInsets.symmetric(vertical: 3),
  child: Row(
    children: [
      Expanded(
        child: Text(
          label,
          style: strong ? const TextStyle(fontWeight: FontWeight.w900) : null,
        ),
      ),
      MoneyText(
        money,
        style: strong
            ? Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.w900)
            : Theme.of(context).textTheme.bodyLarge,
      ),
    ],
  ),
);

class CheckoutScreen extends StatefulWidget {
  const CheckoutScreen({
    super.key,
    required this.controller,
    required this.initialCheckout,
  });
  final AppController controller;
  final Checkout initialCheckout;

  @override
  State<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends State<CheckoutScreen> {
  late Checkout checkout = widget.initialCheckout;
  final formKey = GlobalKey<FormState>();
  late final Map<String, TextEditingController> fields;
  List<PaymentOption> options = [];
  String? provider;
  bool loadingOptions = true;
  bool saving = false;
  bool placing = false;

  @override
  void initState() {
    super.initState();
    final shipping = checkout.shipping;
    fields = {
      'name': TextEditingController(text: shipping.name),
      'phone': TextEditingController(text: shipping.phone),
      'email': TextEditingController(text: shipping.email),
      'address1': TextEditingController(text: shipping.address1),
      'address2': TextEditingController(text: shipping.address2),
      'city': TextEditingController(text: shipping.city),
      'region': TextEditingController(text: shipping.region),
      'country': TextEditingController(text: shipping.country),
      'postalCode': TextEditingController(text: shipping.postalCode),
    };
    loadOptions();
  }

  @override
  void dispose() {
    for (final controller in fields.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> loadOptions() async {
    try {
      final value = await widget.controller.api.paymentOptions();
      if (mounted) {
        setState(() {
          options = value;
          provider = value.isEmpty ? null : value.first.provider;
        });
      }
    } catch (error) {
      if (mounted) await showProblem(context, error);
    } finally {
      if (mounted) setState(() => loadingOptions = false);
    }
  }

  ShippingDetails shipping() => ShippingDetails(
    name: fields['name']!.text.trim(),
    phone: fields['phone']!.text.trim(),
    email: fields['email']!.text.trim(),
    address1: fields['address1']!.text.trim(),
    address2: fields['address2']!.text.trim(),
    city: fields['city']!.text.trim(),
    region: fields['region']!.text.trim(),
    country: fields['country']!.text.trim().toUpperCase(),
    postalCode: fields['postalCode']!.text.trim(),
  );

  Future<bool> saveShipping({bool manageBusyState = true}) async {
    if (!(formKey.currentState?.validate() ?? false)) return false;
    if (manageBusyState) setState(() => saving = true);
    try {
      checkout = await widget.controller.api.updateCheckout(
        checkout.id,
        shipping(),
      );
      if (mounted) setState(() {});
      return true;
    } catch (error) {
      if (mounted) await showProblem(context, error);
      return false;
    } finally {
      if (mounted && manageBusyState) setState(() => saving = false);
    }
  }

  Future<void> place() async {
    final selected = provider;
    if (placing || selected == null) return;
    if (!(formKey.currentState?.validate() ?? false)) return;
    if (!widget.controller.checkoutSubmissions.tryAcquire(checkout.id)) return;
    setState(() => placing = true);
    try {
      if (!await saveShipping(manageBusyState: false)) return;
      final key = await widget.controller.placementKeys.keyFor(
        checkout.id,
        selected,
      );
      final result = await widget.controller.api.placeCheckout(
        checkout.id,
        selected,
        key,
      );
      if (!mounted) return;
      await _continuePayment(result);
      if (!mounted) return;
      await widget.controller.placementKeys.clear(checkout.id);
      if (!mounted) return;
      await Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => PurchaseDetailScreen(
            controller: widget.controller,
            reference: result.purchase.reference,
            initial: result.purchase,
          ),
        ),
      );
    } on ApiProblem catch (problem) {
      if (problem.code == 'conflict') {
        try {
          checkout = await widget.controller.api.checkout(checkout.id);
          if (mounted) setState(() {});
        } catch (_) {
          // The conflict remains authoritative even if refresh also fails.
        }
        if (mounted) {
          await showDialog<void>(
            context: context,
            builder: (context) => AlertDialog(
              title: Text(L10n.t(context, 'unavailable')),
              content: Text(L10n.t(context, 'conflictRefresh')),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: Text(L10n.t(context, 'close')),
                ),
              ],
            ),
          );
        }
      } else if (mounted) {
        await showProblem(context, problem);
      }
    } catch (error) {
      if (mounted) await showProblem(context, error);
    } finally {
      widget.controller.checkoutSubmissions.release(checkout.id);
      if (mounted) setState(() => placing = false);
    }
  }

  Future<void> _continuePayment(PlacementResult result) async {
    if (result.payment.provider == 'cod') return;
    if (result.payment.provider == 'paymob') {
      final redirect = result.payment.redirectUrl;
      if (redirect != null && redirect.isNotEmpty) {
        await launchUrl(
          Uri.parse(redirect),
          mode: LaunchMode.externalApplication,
        );
      } else if (mounted) {
        await _paymentUnavailable();
      }
      return;
    }
    if (result.payment.provider == 'stripe') {
      final secret = result.payment.clientSecret;
      if (secret == null ||
          secret.isEmpty ||
          widget.controller.config.stripePublishableKey.isEmpty) {
        if (mounted) await _paymentUnavailable();
        return;
      }
      try {
        await stripe.Stripe.instance.initPaymentSheet(
          paymentSheetParameters: stripe.SetupPaymentSheetParameters(
            paymentIntentClientSecret: secret,
            merchantDisplayName: 'FABINZI',
          ),
        );
        await stripe.Stripe.instance.presentPaymentSheet();
      } on stripe.StripeException catch (error) {
        if (error.error.code == stripe.FailureCode.Canceled) return;
        rethrow;
      }
    }
  }

  Future<void> _paymentUnavailable() => showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(L10n.t(context, 'unavailable')),
      content: Text(L10n.t(context, 'paymentContinuationUnavailable')),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(L10n.t(context, 'close')),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(L10n.t(context, 'reviewCheckout'))),
    body: Form(
      key: formKey,
      child: ListView(
        padding: const EdgeInsets.all(18),
        children: [
          _summaryCard(context),
          const SizedBox(height: 18),
          Text(
            L10n.t(context, 'shipping'),
            style: Theme.of(context).textTheme.titleLarge
                ?.copyWith(fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 12),
          _field('name', 'name', required: true),
          _field(
            'phone',
            'phone',
            required: true,
            keyboard: TextInputType.phone,
          ),
          _field('email', 'email', keyboard: TextInputType.emailAddress),
          _field('address1', 'address1', required: true),
          _field('address2', 'address2'),
          _field('city', 'city', required: true),
          _field('region', 'region'),
          Row(
            children: [
              Expanded(child: _field('country', 'country', required: true)),
              const SizedBox(width: 10),
              Expanded(child: _field('postalCode', 'postalCode')),
            ],
          ),
          const SizedBox(height: 18),
          Text(
            L10n.t(context, 'paymentMethod'),
            style: Theme.of(context).textTheme.titleLarge
                ?.copyWith(fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 8),
          if (loadingOptions)
            const Center(child: CircularProgressIndicator())
          else if (options.isEmpty)
            Text(L10n.t(context, 'paymentOptionsUnavailable'))
          else
            RadioGroup<String>(
              groupValue: provider,
              onChanged: (value) {
                if (!placing && value != null) {
                  setState(() => provider = value);
                }
              },
              child: Column(
                children: [
                  for (final option in options)
                    RadioListTile<String>(
                      value: option.provider,
                      enabled: !placing,
                      title: Text(option.label),
                    ),
                ],
              ),
            ),
          const SizedBox(height: 18),
          FilledButton.icon(
            onPressed: placing || saving || provider == null ? null : place,
            icon: placing
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.lock_outline),
            label: Text(
              placing
                  ? L10n.t(context, 'placingOrder')
                  : L10n.t(context, 'placeOrder'),
            ),
          ),
          const SizedBox(height: 10),
          Text(
            L10n.t(context, 'paymentPending'),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    ),
  );

  Widget _field(
    String key,
    String label, {
    bool required = false,
    TextInputType? keyboard,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextFormField(
      controller: fields[key],
      keyboardType: keyboard,
      validator: required
          ? (value) => (value == null || value.trim().isEmpty)
                ? L10n.t(context, 'requiredField')
                : null
          : null,
      decoration: InputDecoration(labelText: L10n.t(context, label)),
    ),
  );

  Widget _summaryCard(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          _amountRow(context, L10n.t(context, 'subtotal'), checkout.subtotal),
          _amountRow(
            context,
            L10n.t(context, 'shipping'),
            checkout.shippingAmount,
          ),
          _amountRow(
            context,
            L10n.t(context, 'discount'),
            checkout.discountAmount,
          ),
          const Divider(),
          _amountRow(
            context,
            L10n.t(context, 'total'),
            checkout.total,
            strong: true,
          ),
        ],
      ),
    ),
  );
}
