import 'package:flutter/material.dart';
import 'package:flutter_stripe/flutter_stripe.dart';

import 'app.dart';
import 'core/config.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final config = AppConfig();
  if (config.stripePublishableKey.isNotEmpty) {
    Stripe.publishableKey = config.stripePublishableKey;
    await Stripe.instance.applySettings();
  }
  runApp(const FabinziCustomerApp());
}
