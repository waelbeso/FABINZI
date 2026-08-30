from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Expected source block not found: {label}")
    return text.replace(old, new)


cart_path = ROOT / "lib/features/cart/cart_screen.dart"
cart = cart_path.read_text()
for old, new in {
    "import 'package:flutter_stripe/flutter_stripe.dart';": "import 'package:flutter_stripe/flutter_stripe.dart' as stripe;",
    "Stripe.instance": "stripe.Stripe.instance",
    "SetupPaymentSheetParameters(": "stripe.SetupPaymentSheetParameters(",
    "on StripeException catch": "on stripe.StripeException catch",
    "FailureCode.Canceled": "stripe.FailureCode.Canceled",
}.items():
    cart = replace_required(cart, old, new, old)

old_payment = """          else
            ...options.map(
              (option) => RadioListTile<String>(
                value: option.provider,
                groupValue: provider,
                onChanged: placing
                    ? null
                    : (value) => setState(() => provider = value),
                title: Text(option.label),
              ),
            ),
"""
new_payment = """          else
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
"""
cart = replace_required(cart, old_payment, new_payment, "checkout payment radio group")
cart_path.write_text(cart)

account_path = ROOT / "lib/features/account/account_screen.dart"
account = account_path.read_text()
old_language = """      RadioListTile<String>(
        value: 'en',
        groupValue: controller.locale.languageCode,
        onChanged: (value) {
          if (value != null) controller.setLocale(value);
        },
        title: Text(L10n.t(context, 'english')),
      ),
      RadioListTile<String>(
        value: 'ar',
        groupValue: controller.locale.languageCode,
        onChanged: (value) {
          if (value != null) controller.setLocale(value);
        },
        title: Text(L10n.t(context, 'arabic')),
      ),
"""
new_language = """      RadioGroup<String>(
        groupValue: controller.locale.languageCode,
        onChanged: (value) {
          if (value != null) {
            controller.setLocale(value);
          }
        },
        child: Column(
          children: [
            RadioListTile<String>(
              value: 'en',
              title: Text(L10n.t(context, 'english')),
            ),
            RadioListTile<String>(
              value: 'ar',
              title: Text(L10n.t(context, 'arabic')),
            ),
          ],
        ),
      ),
"""
account = replace_required(account, old_language, new_language, "language radio group")
old_theme = """      RadioListTile<ThemeMode>(
        value: ThemeMode.system,
        groupValue: controller.themeMode,
        onChanged: (value) {
          if (value != null) controller.setThemeMode(value);
        },
        title: Text(L10n.t(context, 'system')),
      ),
      RadioListTile<ThemeMode>(
        value: ThemeMode.light,
        groupValue: controller.themeMode,
        onChanged: (value) {
          if (value != null) controller.setThemeMode(value);
        },
        title: Text(L10n.t(context, 'light')),
      ),
      RadioListTile<ThemeMode>(
        value: ThemeMode.dark,
        groupValue: controller.themeMode,
        onChanged: (value) {
          if (value != null) controller.setThemeMode(value);
        },
        title: Text(L10n.t(context, 'dark')),
      ),
"""
new_theme = """      RadioGroup<ThemeMode>(
        groupValue: controller.themeMode,
        onChanged: (value) {
          if (value != null) {
            controller.setThemeMode(value);
          }
        },
        child: Column(
          children: [
            RadioListTile<ThemeMode>(
              value: ThemeMode.system,
              title: Text(L10n.t(context, 'system')),
            ),
            RadioListTile<ThemeMode>(
              value: ThemeMode.light,
              title: Text(L10n.t(context, 'light')),
            ),
            RadioListTile<ThemeMode>(
              value: ThemeMode.dark,
              title: Text(L10n.t(context, 'dark')),
            ),
          ],
        ),
      ),
"""
account = replace_required(account, old_theme, new_theme, "theme radio group")
account_path.write_text(account)

api_path = ROOT / "lib/core/api_client.dart"
api = api_path.read_text()
retry_count = api.count("return send(false);")
if retry_count != 3:
    raise SystemExit(f"Expected exactly three auth retry returns, found {retry_count}")
api_path.write_text(api.replace("return send(false);", "return await send(false);"))
