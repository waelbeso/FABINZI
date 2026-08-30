from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "mobile" / "customer_app"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"expected edit anchor not found in {path}")
    path.write_text(text.replace(old, new, 1))


# Checkout: process-wide per-checkout placement locking, persistent idempotency key
# reuse after ambiguous transport failures, and clean conflict refresh.
(APP / "lib" / "core" / "checkout_submission_guard.dart").write_text(
    """class CheckoutSubmissionGuard {
  final Set<int> _activeCheckoutIds = <int>{};

  bool tryAcquire(int checkoutId) => _activeCheckoutIds.add(checkoutId);

  void release(int checkoutId) {
    _activeCheckoutIds.remove(checkoutId);
  }

  bool isActive(int checkoutId) => _activeCheckoutIds.contains(checkoutId);
}
"""
)

app_controller = APP / "lib" / "core" / "app_controller.dart"
replace_once(
    app_controller,
    "import 'api_client.dart';\n",
    "import 'api_client.dart';\nimport 'checkout_submission_guard.dart';\n",
)
replace_once(
    app_controller,
    """    PlacementKeyStore? placementKeys,
    CustomerApiClient? api,
  })  : config = config ?? AppConfig(),
        tokens = tokens ?? SessionAwareTokenStore(SecureTokenStore()),
        preferences = preferences ?? AppPreferences(),
        placementKeys = placementKeys ?? PreferencesPlacementKeyStore() {""",
    """    PlacementKeyStore? placementKeys,
    CheckoutSubmissionGuard? checkoutSubmissions,
    CustomerApiClient? api,
  })  : config = config ?? AppConfig(),
        tokens = tokens ?? SessionAwareTokenStore(SecureTokenStore()),
        preferences = preferences ?? AppPreferences(),
        placementKeys = placementKeys ?? PreferencesPlacementKeyStore(),
        checkoutSubmissions = checkoutSubmissions ?? CheckoutSubmissionGuard() {""",
)
replace_once(
    app_controller,
    """  final AppPreferences preferences;
  final PlacementKeyStore placementKeys;
  late final CustomerApiClient api;""",
    """  final AppPreferences preferences;
  final PlacementKeyStore placementKeys;
  final CheckoutSubmissionGuard checkoutSubmissions;
  late final CustomerApiClient api;""",
)

cart = APP / "lib" / "features" / "cart" / "cart_screen.dart"
replace_once(
    cart,
    """  Future<bool> saveShipping() async {
    if (!(formKey.currentState?.validate() ?? false)) return false;
    setState(() => saving = true);
    try {
      checkout = await widget.controller.api.updateCheckout(checkout.id, shipping());
      if (mounted) setState(() {});
      return true;
    } catch (error) { if (mounted) await showProblem(context, error); return false; }
    finally { if (mounted) setState(() => saving = false); }
  }

  Future<void> place() async {
    final selected = provider;
    if (placing || selected == null || !await saveShipping()) return;
    setState(() => placing = true);
    try {
      final key = await widget.controller.placementKeys.keyFor(checkout.id, selected);
      final result = await widget.controller.api.placeCheckout(checkout.id, selected, key);
      await widget.controller.placementKeys.clear(checkout.id);
      if (!mounted) return;
      await _continuePayment(result);
      if (!mounted) return;
      await Navigator.of(context).pushReplacement(MaterialPageRoute<void>(builder: (_) => PurchaseDetailScreen(controller: widget.controller, reference: result.purchase.reference, initial: result.purchase)));
    } on ApiProblem catch (problem) {
      if (problem.code == 'conflict') {
        await showDialog<void>(context: context, builder: (context) => AlertDialog(title: Text(L10n.t(context, 'unavailable')), content: Text(L10n.t(context, 'conflictRefresh')), actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(L10n.t(context, 'close')))]));
      } else if (mounted) {
        await showProblem(context, problem);
      }
    } catch (error) { if (mounted) await showProblem(context, error); }
    finally { if (mounted) setState(() => placing = false); }
  }
""",
    """  Future<bool> saveShipping({bool manageBusyState = true}) async {
    if (!(formKey.currentState?.validate() ?? false)) return false;
    if (manageBusyState) setState(() => saving = true);
    try {
      checkout = await widget.controller.api.updateCheckout(checkout.id, shipping());
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
      final key = await widget.controller.placementKeys.keyFor(checkout.id, selected);
      final result = await widget.controller.api.placeCheckout(checkout.id, selected, key);
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
""",
)

# Studio quantity: use only the already-frozen PATCH quantity field and keep
# the canonical server StudioProject as source of truth.
studio = APP / "lib" / "features" / "studio" / "studio_screen.dart"
replace_once(
    studio,
    "  Future<void> validateAndReady() async {\n",
    """  Future<void> changeQuantity(int nextQuantity) async {
    if (saving || !project.isDraft || nextQuantity < 1) return;
    setState(() => saving = true);
    try {
      final updated = await widget.controller.api.updateStudio(
        project.id,
        quantity: nextQuantity,
      );
      if (!mounted) return;
      setState(() {
        project = updated;
        elements = [...updated.elements];
      });
    } catch (error) {
      if (mounted) await showProblem(context, error);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  Future<void> validateAndReady() async {
""",
)
replace_once(
    studio,
    """        const SizedBox(height: 12),
        if (project.isDraft) ...[
""",
    """        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: Text(
                L10n.t(context, 'quantity'),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
            IconButton(
              onPressed: project.isDraft && !saving && project.quantity > 1
                  ? () => changeQuantity(project.quantity - 1)
                  : null,
              icon: const Icon(Icons.remove_circle_outline),
            ),
            Text(
              '${project.quantity}',
              style: const TextStyle(fontWeight: FontWeight.w900),
            ),
            IconButton(
              onPressed: project.isDraft && !saving
                  ? () => changeQuantity(project.quantity + 1)
                  : null,
              icon: const Icon(Icons.add_circle_outline),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (project.isDraft) ...[
""",
)

# Targeted hardening tests.
preferences_test = APP / "test" / "preferences_test.dart"
replace_once(
    preferences_test,
    """    expect(a.length, greaterThanOrEqualTo(8));
  });
""",
    """    expect(a.length, greaterThanOrEqualTo(8));

    await store.clear(42);
    final afterConfirmedCompletion = await store.keyFor(42, 'cod');
    expect(afterConfirmedCompletion, isNot(a));
  });
""",
)
(APP / "test" / "checkout_submission_guard_test.dart").write_text(
    """import 'package:fabinzi_customer_app/core/checkout_submission_guard.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('checkout submission guard allows only one active placement per checkout', () {
    final guard = CheckoutSubmissionGuard();

    expect(guard.tryAcquire(6001), isTrue);
    expect(guard.isActive(6001), isTrue);
    expect(guard.tryAcquire(6001), isFalse);
    expect(guard.tryAcquire(6002), isTrue);

    guard.release(6001);
    expect(guard.isActive(6001), isFalse);
    expect(guard.tryAcquire(6001), isTrue);
  });
}
"""
)

api_test = APP / "test" / "api_client_test.dart"
replace_once(api_test, "import 'dart:convert';\n", "import 'dart:convert';\nimport 'dart:io';\n")
replace_once(
    api_test,
    """Map<String, dynamic> mePayload() => {'id': 1, 'username': 'customer', 'display_name': 'Customer', 'email': 'c@example.test', 'language': 'en', 'theme': 'system', 'account_state': 'active'};
""",
    """Map<String, dynamic> mePayload() => {'id': 1, 'username': 'customer', 'display_name': 'Customer', 'email': 'c@example.test', 'language': 'en', 'theme': 'system', 'account_state': 'active'};

Map<String, dynamic> contractFixtures() =>
    jsonDecode(
      File('../../contracts/customer-api-v1-fixtures.json').readAsStringSync(),
    ) as Map<String, dynamic>;
""",
)
replace_once(
    api_test,
    "  test('oversized Studio upload is rejected client-side before network', () async {\n",
    """  test('Studio quantity update uses the frozen PATCH quantity field', () async {
    final store = MemoryTokenStore()..access = 'access'..refresh = 'refresh';
    final fixture = Map<String, dynamic>.from(contractFixtures()['studio'] as Map<String, dynamic>)..['quantity'] = 3;
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      httpClient: MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(request.url.path, '/api/v1/customer/studio-projects/3001/');
        expect(jsonDecode(request.body), {'quantity': 3});
        return jsonResponse(fixture, 200);
      }),
    );

    final updated = await client.updateStudio(3001, quantity: 3);
    expect(updated.quantity, 3);
  });

  test('checkout placement sends the persisted Idempotency-Key unchanged', () async {
    final store = MemoryTokenStore()..access = 'access'..refresh = 'refresh';
    final fixtures = contractFixtures();
    final client = CustomerApiClient(
      config: AppConfig(serverBaseUrl: 'https://api.example.test'),
      tokens: store,
      httpClient: MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/customer/checkouts/6001/place/');
        expect(request.headers['idempotency-key'], 'fcz:test-replay-key');
        expect(jsonDecode(request.body), {'payment_method': 'cod'});
        return jsonResponse({
          'idempotent_replay': false,
          'purchase': fixtures['purchase'],
          'payment': {
            'provider': 'cod',
            'status': 'succeeded',
            'redirect_url': null,
            'client_secret': null,
          },
        }, 201);
      }),
    );

    final result = await client.placeCheckout(6001, 'cod', 'fcz:test-replay-key');
    expect(result.purchase.reference, '11111111-1111-4111-8111-111111111111');
  });

  test('oversized Studio upload is rejected client-side before network', () async {
""",
)

# Pin the direct Stripe package; pubspec.lock will freeze the whole graph.
pubspec = APP / "pubspec.yaml"
replace_once(pubspec, "  flutter_stripe: ^14.0.0\n", "  flutter_stripe: 14.0.0\n")

# Final strict workflow. No source-writing permissions remain after this one-shot
# preparation commit is created.
(ROOT / ".github" / "workflows" / "flutter-customer.yml").write_text(r'''name: Flutter Customer

on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: flutter-customer-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

env:
  FLUTTER_VERSION: "3.47.0"
  FLUTTER_INTEGRATION_BASE_SHA: 101b62220222f6372b11dfd5c76bd71aee1ab420

jobs:
  quality-android:
    name: Flutter quality + Android
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
      - name: Verify exact source checkout
        shell: bash
        run: |
          expected="${{ github.event.pull_request.head.sha || github.sha }}"
          actual="$(git rev-parse HEAD)"
          test "$actual" = "$expected"
          echo "FABINZI_SOURCE_SHA=$actual" >> "$GITHUB_ENV"
      - uses: subosito/flutter-action@1a449444c387b1966244ae4d4f8c696479add0b2 # v2
        with:
          flutter-version: "3.47.0"
          channel: stable
          cache: true
      - name: Verify pinned Flutter and Dart toolchain
        shell: bash
        run: |
          mkdir -p mobile/customer_app/build-evidence
          flutter --version --machine | tee mobile/customer_app/build-evidence/flutter-version.json
          dart --version 2>&1 | tee mobile/customer_app/build-evidence/dart-version.txt
          python - <<'PY'
          import json
          from pathlib import Path
          data = json.loads(Path('mobile/customer_app/build-evidence/flutter-version.json').read_text())
          assert data['frameworkVersion'] == '3.47.0', data
          assert data['dartSdkVersion'].startswith('3.13.'), data
          PY
      - name: Generate standard Android and iOS hosts
        working-directory: mobile/customer_app
        run: flutter create --no-pub --platforms=android,ios --org com.fabinzi --project-name fabinzi_customer_app .
      - name: Verify committed locked dependencies
        working-directory: mobile/customer_app
        shell: bash
        run: |
          set -euo pipefail
          test -s pubspec.lock
          flutter pub get --enforce-lockfile
          cp pubspec.lock build-evidence/pubspec.lock
          sha256sum pubspec.lock > build-evidence/dependency-lock-sha256.txt
          flutter pub deps --style=compact > build-evidence/resolved-dependencies.txt
          grep -A7 -E '^  (flutter_stripe|stripe_ios|stripe_android|stripe_platform_interface):' pubspec.lock > build-evidence/stripe-resolution.txt
      - name: Verify frozen Customer API has no drift
        shell: bash
        run: |
          git diff --exit-code "$FLUTTER_INTEGRATION_BASE_SHA"...HEAD -- \
            docs/api/fabinzi-customer-api-v1.openapi.json \
            docs/API_V1_CUSTOMER_CONTRACT.md \
            docs/FLUTTER_API_HANDOFF.md \
            docs/CUSTOMER_API_V1_ENDPOINT_INVENTORY.md \
            docs/API_V1_CUSTOMER_REPRODUCIBILITY.md \
            contracts/customer-api-v1-manifest.json \
            contracts/customer-api-v1-fixtures.json
      - name: Formatting
        working-directory: mobile/customer_app
        shell: bash
        run: |
          set -o pipefail
          dart format --output=none --set-exit-if-changed lib test tool/verify_customer_contract.dart 2>&1 | tee build-evidence/format.log
          printf 'PASS\n' > build-evidence/format-result.txt
      - name: Static analysis
        working-directory: mobile/customer_app
        shell: bash
        run: |
          set -o pipefail
          flutter analyze 2>&1 | tee build-evidence/analyze.log
          printf 'PASS\n' > build-evidence/analyze-result.txt
      - name: Flutter unit and widget tests
        working-directory: mobile/customer_app
        shell: bash
        run: |
          set -o pipefail
          find test -type f -name '*_test.dart' -print | sort > build-evidence/test-inventory.txt
          flutter test --reporter expanded 2>&1 | tee build-evidence/tests.log
          printf 'PASS\n' > build-evidence/test-result.txt
      - name: Arabic English RTL LTR and theme evidence
        working-directory: mobile/customer_app
        shell: bash
        run: |
          set -o pipefail
          flutter test test/localization_theme_test.dart --reporter expanded 2>&1 | tee build-evidence/localization-theme.log
          printf 'PASS — English/LTR, Arabic/RTL, Light/Dark/System contract covered\n' > build-evidence/localization-theme-result.txt
      - name: Frozen Customer contract compatibility
        working-directory: mobile/customer_app
        shell: bash
        run: |
          set -o pipefail
          dart run tool/verify_customer_contract.dart 2>&1 | tee build-evidence/contract.log
          printf 'PASS — 41 frozen Customer operations; no contract drift\n' > build-evidence/contract-result.txt
      - name: Android debug build
        working-directory: mobile/customer_app
        shell: bash
        run: |
          set -o pipefail
          flutter build apk --debug 2>&1 | tee build-evidence/android-build.log
          apk=build/app/outputs/flutter-apk/app-debug.apk
          test -s "$apk"
          printf 'PASS\n' > build-evidence/android-build-result.txt
          sha256sum "$apk" > build-evidence/android-build-sha256.txt
      - name: Changed-file inventory
        shell: bash
        run: git diff --name-status "$FLUTTER_INTEGRATION_BASE_SHA"...HEAD > mobile/customer_app/build-evidence/changed-files.txt
      - name: Upload Flutter quality evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: flutter-customer-quality
          path: mobile/customer_app/build-evidence
          if-no-files-found: error
          retention-days: 30

  ios:
    name: Flutter iOS no-code-sign build
    runs-on: macos-15
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
      - name: Verify exact source checkout
        shell: bash
        run: |
          expected="${{ github.event.pull_request.head.sha || github.sha }}"
          actual="$(git rev-parse HEAD)"
          test "$actual" = "$expected"
      - uses: subosito/flutter-action@1a449444c387b1966244ae4d4f8c696479add0b2 # v2
        with:
          flutter-version: "3.47.0"
          channel: stable
          cache: true
      - name: Select Xcode 26.3 for Stripe iOS 26.3
        working-directory: mobile/customer_app
        shell: bash
        run: |
          mkdir -p build-evidence-ios
          sudo xcode-select -s /Applications/Xcode_26.3.app/Contents/Developer
          xcodebuild -version | tee build-evidence-ios/xcode-version.txt
      - name: Generate standard hosts and restore locked dependencies
        working-directory: mobile/customer_app
        run: |
          flutter create --no-pub --platforms=android,ios --org com.fabinzi --project-name fabinzi_customer_app .
          flutter pub get --enforce-lockfile
      - name: iOS debug build without code signing
        working-directory: mobile/customer_app
        shell: bash
        run: |
          set -o pipefail
          flutter build ios --debug --no-codesign 2>&1 | tee build-evidence-ios/ios-build.log
          test -d build/ios/iphoneos/Runner.app
          printf 'PASS — flutter build ios --debug --no-codesign\n' > build-evidence-ios/ios-build-result.txt
      - name: Upload iOS evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: flutter-customer-ios
          path: mobile/customer_app/build-evidence-ios
          if-no-files-found: error
          retention-days: 30

  checkpoint-evidence:
    name: Flutter checkpoint evidence
    runs-on: ubuntu-latest
    needs: [quality-android, ios]
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
      - uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4
        with:
          name: flutter-customer-quality
          path: evidence/quality
      - uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4
        with:
          name: flutter-customer-ios
          path: evidence/ios
      - name: Assemble deterministic checkpoint evidence
        shell: bash
        run: |
          set -euo pipefail
          out=artifacts/flutter-customer-app-checkpoint
          mkdir -p "$out"
          printf '%s\n' "$(git rev-parse HEAD)" > "$out/source-sha.txt"
          printf '%s\n' "$FLUTTER_INTEGRATION_BASE_SHA" > "$out/integration-baseline-sha.txt"
          cmp mobile/customer_app/pubspec.lock evidence/quality/pubspec.lock
          cp evidence/quality/flutter-version.json "$out/"
          cp evidence/quality/dart-version.txt "$out/"
          cp evidence/quality/pubspec.lock "$out/"
          cp evidence/quality/dependency-lock-sha256.txt "$out/"
          cp evidence/quality/resolved-dependencies.txt "$out/"
          cp evidence/quality/stripe-resolution.txt "$out/"
          cp evidence/quality/format-result.txt "$out/"
          cp evidence/quality/analyze-result.txt "$out/"
          cp evidence/quality/test-result.txt "$out/"
          cp evidence/quality/test-inventory.txt "$out/"
          cp evidence/quality/localization-theme-result.txt "$out/"
          cp evidence/quality/contract-result.txt "$out/"
          cp evidence/quality/android-build-result.txt "$out/"
          cp evidence/quality/android-build-sha256.txt "$out/"
          cp evidence/ios/xcode-version.txt "$out/"
          cp evidence/ios/ios-build-result.txt "$out/"
          cp mobile/customer_app/KNOWN_LIMITATIONS.md "$out/"
          git diff --name-status "$FLUTTER_INTEGRATION_BASE_SHA"...HEAD > "$out/changed-files.txt"
          sha256sum \
            docs/api/fabinzi-customer-api-v1.openapi.json \
            docs/API_V1_CUSTOMER_CONTRACT.md \
            docs/FLUTTER_API_HANDOFF.md \
            contracts/customer-api-v1-manifest.json \
            contracts/customer-api-v1-fixtures.json \
            > "$out/frozen-contract-sha256.txt"
          python - <<'PY'
          import json
          import subprocess
          from pathlib import Path
          out = Path('artifacts/flutter-customer-app-checkpoint')
          flutter = json.loads((out / 'flutter-version.json').read_text())
          payload = {
              'checkpoint': 'FABINZI — Flutter Customer App Productization',
              'source_sha': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
              'integration_baseline_sha': '101b62220222f6372b11dfd5c76bd71aee1ab420',
              'flutter_version': flutter['frameworkVersion'],
              'dart_version': flutter['dartSdkVersion'],
              'flutter_framework_revision': flutter.get('frameworkRevision'),
              'stripe_flutter_version': '14.0.0',
              'stripe_ios_native_version': '26.3.0',
              'ios_xcode': (out / 'xcode-version.txt').read_text().strip(),
              'format': 'PASS',
              'analyze': 'PASS',
              'flutter_tests': 'PASS',
              'android_build': 'PASS',
              'ios_no_codesign_build': 'PASS',
              'customer_api_compatibility': 'PASS',
              'localization': {'en_ltr': 'PASS', 'ar_rtl': 'PASS'},
              'themes': {'light': 'PASS', 'dark': 'PASS', 'system': 'PASS'},
              'deferred_global_live_e2e': 'UNRESOLVED',
          }
          (out / 'checkpoint-manifest.json').write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
          PY
      - name: Upload final Flutter checkpoint artifact
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: flutter-customer-app-checkpoint
          path: artifacts/flutter-customer-app-checkpoint
          if-no-files-found: error
          retention-days: 30
''')

# The preparation script is intentionally absent from the final tree.
Path(__file__).unlink()
