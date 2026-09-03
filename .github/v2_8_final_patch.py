from pathlib import Path


def replace_once(path, old, new, label):
    path = Path(path)
    text = path.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected exact anchor once, found {text.count(old)}")
    path.write_text(text.replace(old, new, 1))


# Finance: isolate legacy settlement policy resolution from V2 policy resolution.
replace_once(
    "apps/finance/services.py",
    "OPEN_SETTLEMENT = {SettlementRequest.Status.REQUESTED, SettlementRequest.Status.UNDER_REVIEW, SettlementRequest.Status.APPROVED, SettlementRequest.Status.PROCESSING}\n\n\nclass FinancePolicyUnavailable",
    "OPEN_SETTLEMENT = {SettlementRequest.Status.REQUESTED, SettlementRequest.Status.UNDER_REVIEW, SettlementRequest.Status.APPROVED, SettlementRequest.Status.PROCESSING}\nLEGACY_SETTLEMENT_EARNING_TYPES = {LedgerEntry.EntryType.DESIGNER_EARNING, LedgerEntry.EntryType.MANUFACTURER_EARNING}\nV2_SETTLEMENT_EARNING_TYPES = {LedgerEntry.EntryType.GARMENT_DESIGNER_ROYALTY, LedgerEntry.EntryType.ARTWORK_DESIGNER_ROYALTY, LedgerEntry.EntryType.MANUFACTURER_PAYABLE}\n\n\nclass FinancePolicyUnavailable",
    "finance provenance constants",
)

replace_once(
    "apps/finance/services.py",
    "def _idempotent_settlement(*, key, organization, amount, currency):\n    if not key: return None\n    existing = SettlementRequest.objects.filter(idempotency_key=key).first()\n    if not existing: return None\n    if existing.organization_id != organization.pk: raise PermissionDenied(\"Settlement idempotency key belongs to another organization.\")\n    if existing.currency.upper() != currency.upper() or _money(existing.amount) != _money(amount): raise ValidationError(\"Settlement idempotency key was already used with different amount/currency.\")\n    return existing\n\n\n@transaction.atomic\ndef request_settlement",
    "def _idempotent_settlement(*, key, organization, amount, currency):\n    if not key: return None\n    existing = SettlementRequest.objects.filter(idempotency_key=key).first()\n    if not existing: return None\n    if existing.organization_id != organization.pk: raise PermissionDenied(\"Settlement idempotency key belongs to another organization.\")\n    if existing.currency.upper() != currency.upper() or _money(existing.amount) != _money(amount): raise ValidationError(\"Settlement idempotency key was already used with different amount/currency.\")\n    return existing\n\n\ndef _settlement_policy_resolution(*, account, currency):\n    has_legacy = account.ledger_entries.filter(entry_type__in=LEGACY_SETTLEMENT_EARNING_TYPES, amount__gt=0).exists()\n    has_v2 = account.ledger_entries.filter(entry_type__in=V2_SETTLEMENT_EARNING_TYPES, amount__gt=0).exists()\n    if has_legacy and has_v2:\n        raise ValidationError(\"Mixed legacy/V2 finance provenance requires explicit payout allocation before settlement.\")\n    if has_legacy:\n        policy = FinancePolicy.objects.filter(is_active=True, lifecycle_status=FinancePolicy.LifecycleStatus.DRAFT).order_by(\"id\").first()\n        if not policy or policy.is_v2_complete:\n            raise ValidationError(\"Legacy settlement requires an explicitly configured legacy Finance Policy; V2 policy is not a fallback.\")\n        return {\"provenance\": \"legacy\", \"policy\": policy, \"minimum_payout\": _money(policy.minimum_payout)}\n    policy = active_policy(currency)\n    return {\"provenance\": \"v2\", \"policy\": policy, \"minimum_payout\": _money(policy.v2_minimum_payout)}\n\n\n@transaction.atomic\ndef request_settlement",
    "settlement provenance resolver",
)

replace_once(
    "apps/finance/services.py",
    "    policy = active_policy(currency)\n    if amount < policy.v2_minimum_payout: raise ValidationError(f\"Minimum settlement is {policy.v2_minimum_payout} {currency}.\")",
    "    resolution = _settlement_policy_resolution(account=account, currency=currency)\n    minimum_payout = resolution[\"minimum_payout\"]\n    if amount < minimum_payout: raise ValidationError(f\"Minimum settlement is {minimum_payout} {currency}.\")",
    "settlement minimum resolution",
)

# Focused proof: legacy-only works from configured legacy policy; V2 never falls back; mixed provenance fails closed.
replace_once(
    "tests/test_v2_8_finance_boundaries.py",
    "from apps.finance.services import account_balance, payout_iban, request_settlement, update_payout_profile\n",
    "from apps.finance.services import FinancePolicyUnavailable, account_balance, payout_iban, request_settlement, update_payout_profile\n",
    "finance test import",
)

test_path = Path("tests/test_v2_8_finance_boundaries.py")
test_text = test_path.read_text()
if "test_legacy_settlement_uses_only_configured_legacy_policy_without_v2_default" in test_text:
    raise SystemExit("provenance tests already present")
test_text += '''\n\n\ndef test_legacy_settlement_uses_only_configured_legacy_policy_without_v2_default():\n    owner = user("v28-legacy-settlement-owner")\n    organization = org(owner, kind=Organization.Kind.DESIGNER, name="V2-8 Legacy Settlement Org")\n    legacy = FinancePolicy.objects.create(name="SYNTHETIC LEGACY SETTLEMENT", minimum_payout=Decimal("100.00"), is_active=True)\n    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")\n    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.DESIGNER_EARNING, amount=Decimal("500.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC legacy earning")\n    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="Legacy Owner", destination_hint="MANUAL-LEGACY-QA", status=PayoutProfile.Status.VERIFIED)\n    assert not FinancePolicy.objects.filter(lifecycle_status=FinancePolicy.LifecycleStatus.ACTIVE).exists()\n    with pytest.raises(ValidationError):\n        request_settlement(organization=organization, actor=owner, amount="99.00", currency="EGP", idempotency_key="legacy-too-low")\n    settlement = request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="legacy-accepted")\n    assert settlement.amount == Decimal("100.00")\n    assert legacy.minimum_payout == Decimal("100.00")\n\n\ndef test_unconfigured_v2_obligation_never_falls_back_to_legacy_policy():\n    owner = user("v28-v2-no-fallback-owner")\n    organization = org(owner, kind=Organization.Kind.DESIGNER, name="V2-8 No Fallback Org")\n    FinancePolicy.objects.create(name="SYNTHETIC LEGACY NO FALLBACK", minimum_payout=Decimal("1.00"), is_active=True)\n    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")\n    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.GARMENT_DESIGNER_ROYALTY, amount=Decimal("500.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC unconfigured V2 obligation")\n    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="V2 Owner", destination_hint="MANUAL-V2-QA", status=PayoutProfile.Status.VERIFIED)\n    with pytest.raises(FinancePolicyUnavailable):\n        request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="v2-no-legacy-fallback")\n\n\ndef test_mixed_legacy_and_v2_settlement_provenance_fails_closed_without_allocation_rule():\n    owner = user("v28-mixed-provenance-owner")\n    organization = org(owner, kind=Organization.Kind.DESIGNER, name="V2-8 Mixed Provenance Org")\n    FinancePolicy.objects.create(name="SYNTHETIC LEGACY MIXED", minimum_payout=Decimal("1.00"), is_active=True)\n    _active_policy("MIXEDPROV", minimum="1.00")\n    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")\n    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.DESIGNER_EARNING, amount=Decimal("250.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC legacy portion")\n    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.GARMENT_DESIGNER_ROYALTY, amount=Decimal("250.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC V2 portion")\n    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="Mixed Owner", destination_hint="MANUAL-MIXED-QA", status=PayoutProfile.Status.VERIFIED)\n    with pytest.raises(ValidationError, match="Mixed legacy/V2 finance provenance"):\n        request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="mixed-provenance")\n'''
test_path.write_text(test_text)

# /Maneg/: retain V2 governance page while restoring accepted pending review controls.
replace_once(
    "templates/maneg/finance.html",
    '<article class="subcard"><strong>{{ p.organization.display_name }}</strong><span>{{ p.get_status_display }} · {{ p.account_holder }} · {{ p.destination_hint }}</span></article>',
    '<article class="subcard"><div class="section-head"><div><strong>{{ p.organization.display_name }}</strong><span>{{ p.method|maneg_label:maneg_language }} · {{ p.account_holder }} · {{ p.destination_hint }}</span></div><span class="status status--{{ p.status|maneg_tone }}">{{ p.status|maneg_label:maneg_language }}</span></div>{% if p.status == \'pending\' and request.user|has_perm_name:\'finance.change_payoutprofile\' %}<form method="post" class="action-row">{% csrf_token %}<input type="hidden" name="profile_id" value="{{ p.pk }}"><button class="button button--sm" name="action" value="verify_payout">{% if maneg_is_ar %}توثيق{% else %}Verify{% endif %}</button><button class="button button--danger button--sm" name="action" value="reject_payout">{% if maneg_is_ar %}رفض{% else %}Reject{% endif %}</button></form>{% endif %}</article>',
    "Maneg payout controls",
)
replace_once(
    "templates/maneg/finance.html",
    '<article class="subcard"><strong>{{ s.organization.display_name }} · {{ s.amount }} {{ s.currency }}</strong><span>{{ s.get_status_display }} · {{ s.requested_at }}</span></article>',
    '<article class="subcard"><div class="section-head"><div><strong>{{ s.organization.display_name }} · {{ s.amount }} {{ s.currency }}</strong><span>{{ s.requested_at }}</span></div><span class="status status--{{ s.status|maneg_tone }}">{{ s.status|maneg_label:maneg_language }}</span></div>{% if request.user|has_perm_name:\'finance.change_settlementrequest\' and s.status == \'requested\' %}<form method="post" class="action-row">{% csrf_token %}<input type="hidden" name="settlement_id" value="{{ s.pk }}"><button class="button button--sm" name="action" value="approve_settlement">{% if maneg_is_ar %}اعتماد{% else %}Approve{% endif %}</button><button class="button button--danger button--sm" name="action" value="reject_settlement">{% if maneg_is_ar %}رفض{% else %}Reject{% endif %}</button></form>{% endif %}</article>',
    "Maneg settlement controls",
)

# Flutter: deterministic dedicated guard execution; no Flutter source or behavior change.
replace_once(
    ".github/workflows/flutter-customer.yml",
    "      - name: Checkpoint behavior evidence\n        working-directory: mobile/customer_app\n        shell: bash\n        run: |\n          set -euo pipefail\n          grep -F 'checkout submission guard allows only one active placement per checkout' build-evidence/tests.log\n          grep -F 'placement key is stable per checkout/provider and distinct across providers' build-evidence/preferences-tests.log\n          grep -F 'checkout placement sends the persisted Idempotency-Key unchanged' build-evidence/api-client-tests.log\n          grep -F 'Studio quantity update uses the frozen PATCH quantity field' build-evidence/api-client-tests.log\n          printf 'PASS — submission guard + persisted Idempotency-Key replay behavior\\n' > build-evidence/checkout-idempotency-result.txt\n          printf 'PASS — Studio quantity serialized via frozen PATCH quantity and canonical response\\n' > build-evidence/studio-quantity-result.txt\n",
    "      - name: Checkout submission guard evidence\n        working-directory: mobile/customer_app\n        shell: bash\n        run: |\n          set -euo pipefail\n          set -o pipefail\n          test -f test/checkout_submission_guard_test.dart\n          grep -Fx 'test/checkout_submission_guard_test.dart' build-evidence/test-inventory.txt\n          flutter test test/checkout_submission_guard_test.dart --reporter expanded 2>&1 | tee build-evidence/checkout-submission-guard-tests.log\n          grep -F 'checkout submission guard allows only one active placement per checkout' build-evidence/checkout-submission-guard-tests.log\n          printf 'PASS — explicit checkout_submission_guard_test.dart execution proved single active placement per checkout\\n' > build-evidence/checkout-submission-guard-test-result.txt\n      - name: Checkpoint behavior evidence\n        working-directory: mobile/customer_app\n        shell: bash\n        run: |\n          set -euo pipefail\n          grep -F 'checkout submission guard allows only one active placement per checkout' build-evidence/checkout-submission-guard-tests.log\n          grep -F 'placement key is stable per checkout/provider and distinct across providers' build-evidence/preferences-tests.log\n          grep -F 'checkout placement sends the persisted Idempotency-Key unchanged' build-evidence/api-client-tests.log\n          grep -F 'Studio quantity update uses the frozen PATCH quantity field' build-evidence/api-client-tests.log\n          printf 'PASS — submission guard + persisted Idempotency-Key replay behavior\\n' > build-evidence/checkout-idempotency-result.txt\n          printf 'PASS — Studio quantity serialized via frozen PATCH quantity and canonical response\\n' > build-evidence/studio-quantity-result.txt\n",
    "Flutter guard evidence",
)
replace_once(
    ".github/workflows/flutter-customer.yml",
    '          cp evidence/quality/preferences-test-result.txt "$out/"\n          cp evidence/quality/preferences-tests.log "$out/"\n          cp evidence/quality/localization-theme-result.txt "$out/"\n',
    '          cp evidence/quality/preferences-test-result.txt "$out/"\n          cp evidence/quality/preferences-tests.log "$out/"\n          cp evidence/quality/checkout-submission-guard-test-result.txt "$out/"\n          cp evidence/quality/checkout-submission-guard-tests.log "$out/"\n          cp evidence/quality/localization-theme-result.txt "$out/"\n',
    "Flutter evidence assembly",
)
