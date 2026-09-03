from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.checkout.models import CheckoutSession, CustomerOrder, OrderItem
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.finance.models import FinancePolicy, LedgerEntry, PayoutProfile
from apps.finance.services import account_balance, mark_settlement_paid, mark_settlement_processing, recognize_order_finance, request_settlement, review_payout_profile, review_settlement
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
