# FABINZI Flutter Customer App

Status: **Flutter Customer App Productization checkpoint — repository implementation and verification only.**

The Customer mobile product lives in this monorepo at `mobile/customer_app/` and consumes the frozen FABINZI Customer API v1 under `/api/v1/customer/`. Designer, Manufacturer and `/Maneg/` mobile products are out of scope.

## Integration baseline

The Flutter branch was created from `feature/web-productization` after the accepted Customer API freeze was integrated. The immutable Flutter integration baseline is:

`101b62220222f6372b11dfd5c76bd71aee1ab420`

The frozen contract sources remain authoritative:

- `docs/api/fabinzi-customer-api-v1.openapi.json`
- `docs/API_V1_CUSTOMER_CONTRACT.md`
- `docs/FLUTTER_API_HANDOFF.md`
- `docs/CUSTOMER_API_V1_ENDPOINT_INVENTORY.md`
- `contracts/customer-api-v1-manifest.json`
- `contracts/customer-api-v1-fixtures.json`

## Toolchain

- Flutter `3.47.0` stable
- Dart `3.13.x`
- Android/iOS host projects are generated from that pinned Flutter SDK with `tool/bootstrap_platforms.sh` / `flutter create`.
- `pubspec.lock` is generated and must be committed for the accepted candidate.

## Local setup

From `mobile/customer_app/`:

```bash
./tool/bootstrap_platforms.sh
flutter pub get
flutter analyze
flutter test
flutter run --dart-define=FABINZI_API_BASE_URL=https://your-qa-host.example
```

Use HTTPS for non-local environments. The app has no embedded backend credential.

For an enabled Stripe mobile flow, configure the matching **publishable** key only:

```bash
flutter run \
  --dart-define=FABINZI_API_BASE_URL=https://your-qa-host.example \
  --dart-define=FABINZI_STRIPE_PUBLISHABLE_KEY=pk_...
```

The publishable key is not a server secret. Stripe secret/API keys and all Paymob credentials remain backend-only.

## Architecture

`lib/core/` owns configuration, frozen contract models, networking, secure session storage, local non-secret preferences, theme and localization. `lib/features/` owns Customer product journeys. `lib/ui/` contains reusable product-state widgets.

The API client implements the frozen envelope and lifecycle rather than duplicating backend business rules. Server responses remain authoritative for pricing, variants, availability, currency, permissions, Studio validation, purchase/payment state and fulfillment.

## Authentication and secure storage

Flutter uses Bearer JWT separately from Django browser session authentication. Access lifetime is 15 minutes; refresh lifetime is 30 days; refresh rotation and blacklist/revocation are enabled. The client coalesces concurrent refresh attempts to prevent refresh storms and replaces both credentials only after a successful rotation.

Access and refresh credentials are stored through `flutter_secure_storage`, backed by Android Keystore-supported secure storage and iOS Keychain. Shared preferences contain only non-secret language/theme preferences and checkout idempotency keys. Passwords and JWT values are never logged.

Logout sends the active refresh credential to the frozen logout operation and clears local secure credentials. Invalid/revoked refresh state clears the authenticated shell state.

## Customer API semantics

- Errors: `error.code`, `error.message`, `error.fields`, `error.request_id`.
- Pagination: `count`, `next`, `previous`, `results`; default 20, maximum 50.
- Money: authoritative decimal string plus currency; Flutter never treats binary floating point as monetary authority.
- Datetime: timezone-aware ISO-8601 parsed into `DateTime`.
- Localization: `Accept-Language: en|ar`, English fallback.
- Checkout placement: `Idempotency-Key` required. The app persists a stable key per checkout/provider and locks the submission UI.

## Visual Studio

The mobile Studio persists the backend `StudioProject`; it has no mobile-only canonical schema. It renders the product and real decoration-zone geometry, and supports backend-defined text, approved Artwork and private image elements.

Transforms use the frozen normalized `{x, y, scale, rotation}` representation. Rotation is degrees, scale is normalized, and the server performs final containment/eligibility validation. The app supports drag, pinch and rotation for UX while retaining the backend as authority.

Private images are client-checked for PNG/JPEG/WebP and the 10 MiB limit, then uploaded to the Customer private-media endpoint. Private media is fetched through the authorized Customer endpoint; Bearer credentials are not forwarded to redirected signed-storage URLs.

## Commerce and payments

Customer UI stays Parent `CustomerPurchase`-first. Cart lines remain distinct operational children; Manufacturer/Production internals are not promoted into mobile Customer architecture.

Checkout uses server totals and server-returned payment options only. Placement uses persistent idempotency and duplicate-tap locking. COD has no fabricated provider step. Paymob opens only the server-returned redirect. Stripe uses the server-returned PaymentIntent client secret with the separately configured publishable key. Webhook confirmation remains server-authoritative; the Purchase screen refreshes on app resume.

## Localization, direction and theme

English/LTR and Arabic/RTL are first-class. Visible product copy is keyed in both languages and the catalogs have parity tests. Layouts rely on Flutter directionality rather than hard-coded left/right assumptions where semantic direction matters. Light, Dark and System theme modes use the approved FABINZI purple/deep-purple/ink/mint identity.

## CI

`.github/workflows/flutter-customer.yml` is independent of the existing Django/Web `CI` workflow. It pins Flutter 3.47.0 and verifies formatting, static analysis, unit/widget tests, frozen-contract compatibility, localization/direction/theme behavior, Android debug build and iOS debug build with `--no-codesign`.

The final job assembles the non-secret `flutter-customer-app-checkpoint` artifact containing exact source SHA, toolchain evidence, dependency lock evidence, test inventory/result, analyze result, Android/iOS build evidence, API compatibility, localization/theme evidence, known limitations and changed-file inventory.

## Release boundary

This checkpoint does not sign an Android or iOS release, publish either store, deploy Render production, touch `main`, or resume `docs/DEFERRED_LIVE_E2E.md`. Those steps require later explicit release instructions.
