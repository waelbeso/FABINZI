from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.checkout.models import CheckoutSession, CustomerOrder, OrderItem
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.finance.models import FinanceAccount, FinancePolicy, LedgerEntry, PayoutProfile
from apps.finance.services import FinancePolicyUnavailable, account_balance, legacy_minimum_payout_default, mark_settlement_paid, mark_settlement_processing, recognize_order_finance, request_settlement, review_payout_profile, review_settlement
from apps.operations.models import FulfillmentRecord
from apps.organizations.models import Membership, Organization
from apps.storefront.models import ProductVariant, StoreProduct, Storefront, StudioProject

User = get_user_model()


def _grant(user, *codes): user.user_permissions.add(*Permission.objects.filter(codename__in=codes))


def _synthetic_policy():
    return FinancePolicy.objects.create(name=f"SYNTHETIC-STAGE8-{FinancePolicy.objects.count()}", code=f"FIN-POL-STAGE8-{FinancePolicy.objects.count()}", lifecycle_status=FinancePolicy.LifecycleStatus.ACTIVE, currency="EGP", fabinzi_rule_type=FinancePolicy.RuleType.PERCENTAGE, fabinzi_rule_value=Decimal("10.00"), garment_royalty_rule_type=FinancePolicy.RuleType.PERCENTAGE, garment_royalty_rule_value=Decimal("90.00"), artwork_royalty_rule_type=FinancePolicy.RuleType.FIXED, artwork_royalty_rule_value=Decimal("0.00"), manufacturer_include_unit_price=True, manufacturer_include_setup_fee=False, manufacturer_include_sample_fee=False, manufacturer_include_shipping_estimate=False, settlement_trigger=FinancePolicy.SettlementTrigger.DELIVERY, settlement_hold_days=0, v2_minimum_payout=Decimal("100.00"), validated_at=timezone.now(), activated_at=timezone.now())


def delivered_order():
    owner = User.objects.create_user(username=f"fin-owner-{User.objects.count()}", password="password123"); customer = User.objects.create_user(username=f"fin-customer-{User.objects.count()}", password="password123"); org = Organization.objects.create(kind="designer", display_name="Finance Brand", email=f"f{Organization.objects.count()}@x.test", verification_status="active", created_by=owner); Membership.objects.create(organization=org, user=owner, role="owner")
    gd = GarmentDesign.objects.create(organization=org, title="T", status="approved", created_by=owner); gv = GarmentDesignVersion.objects.create(design=gd, version_number=1, status="approved", created_by=owner); art = Artwork.objects.create(organization=org, title="A", status="approved", created_by=owner); av = ArtworkVersion.objects.create(artwork=art, version_number=1, status="approved", created_by=owner); dp = DesignedProduct.objects.create(organization=org, garment_version=gv, artwork_version=av, title="P", status="published", created_by=owner, garment_creator_organization=org, artwork_creator_organization=org, economic_attribution={"garment_creator_organization_id": org.pk, "artwork_creator_organization_id": org.pk})
    store = Storefront.objects.create(organization=org, slug=f"fin-{org.pk}", status="published", name_en="Fin"); product = StoreProduct.objects.create(storefront=store, designed_product=dp, slug="p", status="published", title_en="P", base_price=Decimal("500.00"), currency="EGP", fulfillment_mode="stock"); variant = ProductVariant.objects.create(product=product, sku=f"FIN-{org.pk}", stock_quantity=5); project = StudioProject.objects.create(customer=customer, product=product, variant=variant, status="ready", quantity=2); checkout = CheckoutSession.objects.create(customer=customer, studio_project=project, status="placed", subtotal=1000, total=1000, currency="EGP"); order = CustomerOrder.objects.create(checkout=checkout, customer=customer, designer_organization=org, status="confirmed", payment_method="cod", subtotal=1000, total=1000, currency="EGP", shipping_snapshot={}); OrderItem.objects.create(order=order, store_product=product, variant=variant, studio_project=project, sku=variant.sku, title="P", unit_price=500, quantity=2, line_total=1000, pricing_snapshot={"unit_customer_price": "500.00"}); FulfillmentRecord.objects.create(order=order, status="delivered", delivered_at=timezone.now()); return owner, org, order


def _legacy_settlement_fixture(prefix, *, kind, entry_type):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password123")
    organization = Organization.objects.create(kind=kind, display_name=f"{prefix} Org", email=f"{prefix}@example.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=organization, user=owner, role=Membership.Role.OWNER)
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=entry_type, amount=Decimal("500.00"), currency="EGP", available_at=timezone.now(), memo=f"{prefix} legacy compatibility balance")
    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder=f"{prefix} Owner", destination_hint="MANUAL-LEGACY-QA", status=PayoutProfile.Status.VERIFIED)
    return owner, organization, account


@pytest.mark.django_db
def test_delivered_order_recognized_once_with_explicit_v2_policy_snapshot():
    owner, org, order = delivered_order(); policy = _synthetic_policy(); result = recognize_order_finance(order=order, actor=owner); again = recognize_order_finance(order=order, actor=owner); assert result.pk == again.pk; assert result.finance_policy_id == policy.pk; assert result.gross_amount == Decimal("1000.00"); assert result.fabinzi_component == Decimal("100.00"); assert result.garment_designer_royalty == Decimal("900.00"); assert result.policy_snapshot["code"] == policy.code


@pytest.mark.django_db
def test_balance_is_ledger_derived():
    owner, org, order = delivered_order(); _synthetic_policy(); result = recognize_order_finance(order=order, actor=owner); balance = account_balance(result.garment_designer_account); assert balance["available"] == Decimal("900.00"); assert balance["withdrawable"] == Decimal("900.00")


@pytest.mark.django_db
def test_settlement_requires_verified_profile_and_reserves_balance_owner_only():
    owner, org, order = delivered_order(); staff = User.objects.create_user(username="stage8-staff", password="password123", is_staff=True); _grant(staff, "change_payoutprofile", "change_settlementrequest", "execute_finance_payout"); _synthetic_policy(); result = recognize_order_finance(order=order, actor=owner)
    with pytest.raises(ValidationError): request_settlement(organization=org, actor=owner, amount=200, currency="EGP")
    profile = PayoutProfile.objects.create(organization=org, method="manual", account_holder="Owner", destination_hint="MANUAL-QA", status="pending"); review_payout_profile(profile=profile, reviewer=staff, decision="verified"); settlement = request_settlement(organization=org, actor=owner, amount=200, currency="EGP", idempotency_key="stage8-reserve"); assert settlement.status == "requested"; assert account_balance(result.garment_designer_account)["reserved"] == Decimal("200.00")


@pytest.mark.django_db
def test_paid_settlement_requires_processing_and_posts_single_debit():
    owner, org, order = delivered_order(); staff = User.objects.create_user(username="stage8-staff2", password="password123", is_staff=True); _grant(staff, "change_payoutprofile", "change_settlementrequest", "execute_finance_payout"); _synthetic_policy(); result = recognize_order_finance(order=order, actor=owner); profile = PayoutProfile.objects.create(organization=org, method="manual", account_holder="Owner", destination_hint="MANUAL-QA", status="pending"); review_payout_profile(profile=profile, reviewer=staff, decision="verified"); settlement = request_settlement(organization=org, actor=owner, amount=300, currency="EGP", idempotency_key="stage8-paid"); review_settlement(settlement=settlement, reviewer=staff, decision="under_review"); review_settlement(settlement=settlement, reviewer=staff, decision="approved")
    with pytest.raises(ValidationError): mark_settlement_paid(settlement=settlement, reviewer=staff, external_reference="BANK-1")
    mark_settlement_processing(settlement=settlement, reviewer=staff, execution_evidence="SYNTHETIC-QA-EXECUTION"); mark_settlement_paid(settlement=settlement, reviewer=staff, external_reference="SYNTHETIC-QA-BANK-1"); assert LedgerEntry.objects.filter(settlement=settlement, entry_type="settlement", amount=Decimal("-300.00")).count() == 1


@pytest.mark.django_db
def test_accountant_cannot_request_payout():
    owner, org, order = delivered_order(); accountant = User.objects.create_user(username="stage8-accountant", password="password123"); Membership.objects.create(organization=org, user=accountant, role=Membership.Role.ACCOUNTANT); _synthetic_policy(); recognize_order_finance(order=order, actor=owner); PayoutProfile.objects.create(organization=org, method="manual", account_holder="Owner", destination_hint="MANUAL-QA", status="verified")
    with pytest.raises(PermissionDenied): request_settlement(organization=org, actor=accountant, amount=100, currency="EGP")


@pytest.mark.django_db
def test_legacy_designer_no_policy_uses_declared_model_default_without_creating_policy():
    assert FinancePolicy.objects.count() == 0
    declared_default = FinancePolicy._meta.get_field("minimum_payout").get_default()
    assert legacy_minimum_payout_default() == Decimal("100.00")
    assert legacy_minimum_payout_default() == Decimal(declared_default).quantize(Decimal("0.01"))
    owner, organization, _ = _legacy_settlement_fixture("legacy-designer-no-row", kind=Organization.Kind.DESIGNER, entry_type=LedgerEntry.EntryType.DESIGNER_EARNING)
    with pytest.raises(ValidationError, match="Minimum settlement"):
        request_settlement(organization=organization, actor=owner, amount="99.00", currency="EGP", idempotency_key="legacy-designer-below-default")
    settlement = request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="legacy-designer-default")
    assert settlement.amount == Decimal("100.00")
    assert FinancePolicy.objects.count() == 0


@pytest.mark.django_db
def test_legacy_manufacturer_no_policy_can_request_150_without_creating_policy():
    assert FinancePolicy.objects.count() == 0
    owner, organization, _ = _legacy_settlement_fixture("legacy-manufacturer-no-row", kind=Organization.Kind.MANUFACTURER, entry_type=LedgerEntry.EntryType.MANUFACTURER_EARNING)
    settlement = request_settlement(organization=organization, actor=owner, amount="150.00", currency="EGP", idempotency_key="legacy-manufacturer-150")
    assert settlement.amount == Decimal("150.00")
    assert FinancePolicy.objects.count() == 0


@pytest.mark.django_db
def test_v2_settlement_uses_explicit_v2_minimum_and_never_legacy_minimum_field():
    owner = User.objects.create_user(username="v2-minimum-isolation-owner", password="password123")
    organization = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="V2 Minimum Isolation", email="v2-minimum-isolation@example.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=organization, user=owner, role=Membership.Role.OWNER)
    policy = FinancePolicy.objects.create(
        name="SYNTHETIC V2 MINIMUM ISOLATION",
        minimum_payout=Decimal("999.00"),
        code="FIN-POL-V2-MINIMUM-ISOLATION",
        lifecycle_status=FinancePolicy.LifecycleStatus.ACTIVE,
        currency="EGP",
        fabinzi_rule_type=FinancePolicy.RuleType.FIXED,
        fabinzi_rule_value=Decimal("0.00"),
        garment_royalty_rule_type=FinancePolicy.RuleType.FIXED,
        garment_royalty_rule_value=Decimal("0.00"),
        artwork_royalty_rule_type=FinancePolicy.RuleType.FIXED,
        artwork_royalty_rule_value=Decimal("0.00"),
        manufacturer_include_unit_price=False,
        manufacturer_include_setup_fee=False,
        manufacturer_include_sample_fee=False,
        manufacturer_include_shipping_estimate=False,
        settlement_trigger=FinancePolicy.SettlementTrigger.DELIVERY,
        settlement_hold_days=0,
        v2_minimum_payout=Decimal("25.00"),
        validated_at=timezone.now(),
        activated_at=timezone.now(),
        is_active=False,
    )
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.GARMENT_DESIGNER_ROYALTY, amount=Decimal("500.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC V2 minimum-isolation balance")
    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="V2 Owner", destination_hint="MANUAL-V2-QA", status=PayoutProfile.Status.VERIFIED)
    with pytest.raises(ValidationError, match="Minimum settlement"):
        request_settlement(organization=organization, actor=owner, amount="24.00", currency="EGP", idempotency_key="v2-below-explicit-minimum")
    settlement = request_settlement(organization=organization, actor=owner, amount="25.00", currency="EGP", idempotency_key="v2-explicit-minimum")
    assert settlement.amount == Decimal("25.00")
    assert policy.v2_minimum_payout == Decimal("25.00")
    assert policy.minimum_payout == Decimal("999.00")


@pytest.mark.django_db
def test_multiple_explicit_legacy_policies_fail_closed_as_ambiguous():
    owner, organization, _ = _legacy_settlement_fixture("legacy-ambiguous", kind=Organization.Kind.DESIGNER, entry_type=LedgerEntry.EntryType.DESIGNER_EARNING)
    FinancePolicy.objects.create(name="SYNTHETIC LEGACY AMBIGUOUS A", minimum_payout=Decimal("100.00"), is_active=True)
    FinancePolicy.objects.create(name="SYNTHETIC LEGACY AMBIGUOUS B", minimum_payout=Decimal("120.00"), is_active=True)
    with pytest.raises(ValidationError, match="ambiguous"):
        request_settlement(organization=organization, actor=owner, amount="150.00", currency="EGP", idempotency_key="legacy-ambiguous")


@pytest.mark.django_db
def test_v2_only_without_complete_active_policy_still_fails_closed():
    owner = User.objects.create_user(username="v2-no-policy-owner", password="password123")
    organization = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="V2 No Policy", email="v2-no-policy@example.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=organization, user=owner, role=Membership.Role.OWNER)
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.GARMENT_DESIGNER_ROYALTY, amount=Decimal("500.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC V2 unconfigured balance")
    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="V2 Owner", destination_hint="MANUAL-V2-QA", status=PayoutProfile.Status.VERIFIED)
    with pytest.raises(FinancePolicyUnavailable):
        request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="v2-no-policy")
