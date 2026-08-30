from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"Expected {label} block was not found")


cart_path = Path("mobile/customer_app/lib/features/cart/cart_screen.dart")
cart = cart_path.read_text()
if "import 'package:flutter_stripe/flutter_stripe.dart';" in cart:
    cart = cart.replace(
        "import 'package:flutter_stripe/flutter_stripe.dart';",
        "import 'package:flutter_stripe/flutter_stripe.dart' as stripe;",
        1,
    )
for old, new in (
    ("Stripe.instance", "stripe.Stripe.instance"),
    ("SetupPaymentSheetParameters(", "stripe.SetupPaymentSheetParameters("),
    ("on StripeException catch", "on stripe.StripeException catch"),
    ("FailureCode.Canceled", "stripe.FailureCode.Canceled"),
):
    if old in cart:
        cart = cart.replace(old, new)

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
cart = replace_once(cart, old_payment, new_payment, "checkout payment RadioGroup")
cart_path.write_text(cart)

account_path = Path("mobile/customer_app/lib/features/account/account_screen.dart")
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
account = replace_once(account, old_language, new_language, "account language RadioGroup")
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
account = replace_once(account, old_theme, new_theme, "account theme RadioGroup")
account_path.write_text(account)

api_path = Path("mobile/customer_app/lib/core/api_client.dart")
api = api_path.read_text()
plain = api.count("return send(false);")
awaited = api.count("return await send(false);")
if plain == 3:
    api = api.replace("return send(false);", "return await send(false);")
elif plain != 0 or awaited != 3:
    raise SystemExit(
        f"Unexpected auth retry shape: plain={plain}, awaited={awaited}; expected 3 retries"
    )
api_path.write_text(api)
