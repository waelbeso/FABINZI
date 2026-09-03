import json
import threading
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import RequestFactory
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkVersion
from apps.audit.models import AuditEvent
from apps.finance.maneg_v2_8 import payout_bank_proof
from apps.finance.models import FinanceAccount, FinancePolicy, FinanceRecognitionPending, LedgerEntry, OrderFinance, OrderFinanceComponent, PayoutProfile, SettlementRequest
from apps.finance.services import FinancePolicyUnavailable, account_balance, payout_iban, request_settlement, update_payout_profile
from apps.manufacturer_marketplace.services import submit_quote
from apps.media.models import MediaAsset
from apps.operations.models import FulfillmentRecord
from apps.operations.services import deliver_order
from apps.operations.v2_7 import CANONICAL_GARMENT, assign_customer_order_manufacturer, create_customer_order_routing
from apps.organizations.models import Organization
from tests.v2_7_helpers import manufacturer, media, order_line, org, user

pytestmark = pytest.mark.django_db


def _active_policy(prefix, *, manufacturer_unit=True, setup=False, sample=False, shipping=False, minimum="1.00"):
    now = timezone.now()
    return FinancePolicy.objects.create(
        name=f"SYNTHETIC V2-8 {prefix}",
        code=f"FIN-POL-{prefix.upper()}",
        lifecycle_status=FinancePolicy.LifecycleStatus.ACTIVE,
        currency="EGP",
        fabinzi_rule_type=FinancePolicy.RuleType.PERCENTAGE,
        fabinzi_rule_value=Decimal("7.50"),
        garment_royalty_rule_type=FinancePolicy.RuleType.PERCENTAGE,
        garment_royalty_rule_value=Decimal("10.00"),
        artwork_royalty_rule_type=FinancePolicy.RuleType.PERCENTAGE,
        artwork_royalty_rule_value=Decimal("5.00"),
        manufacturer_include_unit_price=manufacturer_unit,
        manufacturer_include_setup_fee=setup,
        manufacturer_include_sample_fee=sample,
        manufacturer_include_shipping_estimate=shipping,
        settlement_trigger=FinancePolicy.SettlementTrigger.DELIVERY,
        settlement_hold_days=0,
        v2_minimum_payout=Decimal(minimum),
        validated_at=now,
        activated_at=now,
        is_active=False,
    )


def _deliver(line):
    fulfillment = line["fulfillment"]
    fulfillment.status = FulfillmentRecord.Status.SHIPPED
    fulfillment.shipped_at = timezone.now()
    fulfillment.carrier = "SYNTHETIC-QA"
    fulfillment.tracking_number = f"V28-{line['order'].pk}"
    fulfillment.save()
    deliver_order(fulfillment=fulfillment, actor=line["designer"])
    return OrderFinance.objects.filter(order=line["order"]).first()


def _marketplace_artwork(prefix):
    owner = user(f"{prefix}-art-owner")
    organization = org(owner, kind=Organization.Kind.DESIGNER, name=f"{prefix} Artwork Designer")
    artwork = Artwork.objects.create(organization=organization, title=f"{prefix} Artwork", status=Artwork.Status.APPROVED, created_by=owner)
    version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, intended_methods=["dtf"], created_by=owner)
    return owner, organization, artwork, version


def test_ready_designed_studio_marketplace_and_private_customer_artwork_attribution_boundaries():
    _active_policy("ATTR")

    ready = order_line("v28-ready-fin", purchase_kind="ready_designed")
    _, ready_art_org, ready_art, ready_art_version = _marketplace_artwork("v28-ready-fin")
    ready_snapshot = dict(ready["item"].production_snapshot)
    ready_snapshot.update({
        "garment_creator_organization_id": ready["designer_org"].pk,
        "artwork_id": ready_art.pk,
        "artwork_version_id": ready_art_version.pk,
        "artwork_creator_organization_id": ready_art_org.pk,
    })
    ready["item"].production_snapshot = ready_snapshot
    ready["item"].save(update_fields=["production_snapshot"])
    ready_finance = _deliver(ready)
    assert ready_finance.artwork_designer_account.organization_id == ready_art_org.pk
    assert ready_finance.artwork_designer_royalty == Decimal("25.00")
    assert ready_finance.source_snapshot["artwork_creator_organization_ids"] == [ready_art_org.pk]

    studio = order_line("v28-studio-market", purchase_kind="studio")
    _, studio_art_org, _, studio_art_version = _marketplace_artwork("v28-studio-market")
    studio_customization = {
        "enabled": True,
        "elements": [{
            "kind": "artwork",
            "artwork_version_id": studio_art_version.pk,
            "artwork_id": studio_art_version.artwork_id,
            "media_asset_id": None,
            "production_method": "dtf",
            "transform": {"x": 0.2, "y": 0.2, "scale": 0.3, "rotation": 0},
        }],
    }
    studio["item"].customization_snapshot = studio_customization
    studio["item"].save(update_fields=["customization_snapshot"])
    studio_finance = _deliver(studio)
    assert studio_finance.artwork_designer_account.organization_id == studio_art_org.pk
    assert studio_finance.artwork_designer_royalty == Decimal("25.00")
    assert studio_finance.source_snapshot["artwork_creator_organization_ids"] == [studio_art_org.pk]

    private_studio = order_line("v28-studio-private", purchase_kind="studio")
    private_asset = media(private_studio["customer"], "private-customer-art.png", access=MediaAsset.Access.PRIVATE, mime="image/png", marker="v28-private-art")
    private_studio["item"].customization_snapshot = {
        "enabled": True,
        "elements": [{
            "kind": "image",
            "media_asset_id": private_asset.pk,
            "artwork_version_id": None,
            "artwork_id": None,
            "production_method": "dtf",
            "transform": {"x": 0.2, "y": 0.2, "scale": 0.3, "rotation": 0},
        }],
    }
    private_studio["item"].save(update_fields=["customization_snapshot"])
    private_finance = _deliver(private_studio)
    assert private_finance.artwork_designer_account_id is None
    assert private_finance.artwork_designer_royalty == Decimal("0.00")
    assert private_finance.source_snapshot["artwork_creator_organization_ids"] == []
    assert not private_finance.components.filter(component_type=OrderFinanceComponent.ComponentType.ARTWORK_ROYALTY).exists()

    plain = order_line("v28-plain-no-art", purchase_kind="plain")
    designed = plain["product"].designed_product
    designed.artwork_creator_organization = plain["designer_org"]
    designed.save(update_fields=["artwork_creator_organization", "updated_at"])
    plain_finance = _deliver(plain)
    assert plain_finance.artwork_designer_account_id is None
    assert plain_finance.artwork_designer_royalty == Decimal("0.00")


def test_multiple_studio_marketplace_artwork_beneficiaries_remain_durably_blocked_without_invented_split():
    _active_policy("MULTIART")
    line = order_line("v28-studio-multi", purchase_kind="studio")
    _, org_a, _, version_a = _marketplace_artwork("v28-studio-multi-a")
    _, org_b, _, version_b = _marketplace_artwork("v28-studio-multi-b")
    line["item"].customization_snapshot = {
        "enabled": True,
        "elements": [
            {"kind": "artwork", "artwork_version_id": version_a.pk, "artwork_id": version_a.artwork_id, "production_method": "dtf", "transform": {"x": 0.1}},
            {"kind": "artwork", "artwork_version_id": version_b.pk, "artwork_id": version_b.artwork_id, "production_method": "dtf", "transform": {"x": 0.5}},
        ],
    }
    line["item"].save(update_fields=["customization_snapshot"])
    assert _deliver(line) is None
    pending = FinanceRecognitionPending.objects.get(order=line["order"])
    assert pending.status == FinanceRecognitionPending.Status.BLOCKED
    assert pending.source_snapshot["artwork_creator_organization_ids"] == sorted([org_a.pk, org_b.pk])
    assert "split-royalty policy" in pending.block_reason
    assert not OrderFinance.objects.filter(order=line["order"]).exists()


def test_manufacturer_quote_components_follow_bound_policy_exactly():
    line = order_line("v28-mfr-components")
    mfr_owner, mfr_org, _ = manufacturer("v28-mfr-components", [CANONICAL_GARMENT])
    staff = user("v28-mfr-components-staff", staff=True)
    rfq = create_customer_order_routing(order_item=line["item"], actor=staff)
    quote = submit_quote(
        invitation=rfq.invitations.get(manufacturer=mfr_org),
        actor=mfr_owner,
        unit_price="100.00",
        production_lead_days=7,
        setup_fee="3.50",
        sample_fee="2.25",
        shipping_estimate="11.75",
        currency="EGP",
        minimum_order_quantity=1,
    )
    assign_customer_order_manufacturer(quote=quote, actor=staff)
    policy = _active_policy("MFRCOMP", manufacturer_unit=True, setup=True, sample=True, shipping=True)
    finance = _deliver(line)
    assert finance.finance_policy_id == policy.pk
    assert finance.manufacturer_account.organization_id == mfr_org.pk
    assert finance.manufacturer_payable == Decimal("117.50")
    assert finance.source_snapshot["manufacturer_quote"] == {
        "quote_id": quote.pk,
        "manufacturer_id": mfr_org.pk,
        "currency": "EGP",
        "unit_price": "100.00",
        "setup_fee": "3.50",
        "sample_fee": "2.25",
        "shipping_estimate": "11.75",
    }
    component = finance.components.get(component_type=OrderFinanceComponent.ComponentType.MANUFACTURER_PAYABLE)
    assert component.amount == Decimal("117.50")
    assert component.beneficiary_organization_id == mfr_org.pk


def _payout_fixture(prefix, *, balance="500.00"):
    owner = user(f"{prefix}-owner")
    organization = org(owner, kind=Organization.Kind.DESIGNER, name=f"{prefix} Payout Org")
    _active_policy(prefix, minimum="1.00")
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.ADJUSTMENT, event_key=f"{prefix}-credit", amount=Decimal(balance), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC QA credit", created_by=owner)
    profile = PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="Synthetic Owner", destination_hint="MANUAL-QA", status=PayoutProfile.Status.VERIFIED)
    return owner, organization, account, profile


def test_bank_profile_encrypts_full_iban_masks_snapshots_and_requires_private_proof():
    owner = user("v28-bank-owner")
    organization = org(owner, kind=Organization.Kind.DESIGNER, name="V2-8 Bank Org")
    private_proof = media(owner, "synthetic-bank-proof.pdf", access=MediaAsset.Access.PRIVATE, marker="v28-bank")
    full_iban = "EG00SYNTHETICFABINZI000123"
    profile = update_payout_profile(organization=organization, actor=owner, method=PayoutProfile.Method.BANK, account_holder="Synthetic Owner", bank_name="Synthetic QA Bank", iban=full_iban, country="EG", currency="EGP", bank_proof=private_proof, submit=True)
    profile.refresh_from_db()
    assert profile.iban_encrypted
    assert profile.iban_encrypted != full_iban
    assert full_iban not in profile.iban_encrypted
    assert payout_iban(profile) == full_iban
    assert profile.iban_last4 == full_iban[-4:]
    assert profile.destination_hint == f"IBAN •••• {full_iban[-4:]}"
    assert profile.bank_proof.access == MediaAsset.Access.PRIVATE
    event = AuditEvent.objects.filter(action="finance.payout_profile.submitted", object_id=str(profile.pk)).latest("created_at")
    assert full_iban not in json.dumps(event.metadata, sort_keys=True)
    assert "iban_encrypted" not in event.metadata

    public_proof = media(owner, "public-bank-proof.pdf", access=MediaAsset.Access.PUBLIC, marker="v28-bank-public")
    with pytest.raises(ValidationError):
        update_payout_profile(organization=organization, actor=owner, method=PayoutProfile.Method.BANK, account_holder="Synthetic Owner", bank_name="Synthetic QA Bank", iban=full_iban, country="EG", currency="EGP", bank_proof=public_proof, submit=True)

    profile.status = PayoutProfile.Status.VERIFIED
    profile.save(update_fields=["status"])
    _active_policy("BANKPAYOUT")
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.ADJUSTMENT, event_key="v28-bank-credit", amount=Decimal("200.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC QA", created_by=owner)
    settlement = request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="v28-bank-payout")
    payload = json.dumps(settlement.payout_snapshot, sort_keys=True)
    assert full_iban not in payload
    assert profile.iban_encrypted not in payload
    assert settlement.payout_snapshot["iban_last4"] == full_iban[-4:]

    unauthorized_staff = user("v28-bank-no-perm", staff=True)
    request = RequestFactory().get(f"/Maneg/finance-payouts/profile/{profile.pk}/bank-proof/")
    request.user = unauthorized_staff
    with pytest.raises(PermissionDenied): payout_bank_proof(request, profile.pk)


@pytest.mark.django_db(transaction=True)
def test_payout_same_key_is_concurrently_idempotent_and_conflicting_retry_is_rejected():
    owner, organization, account, _ = _payout_fixture("v28-payout-idem")
    barrier = threading.Barrier(2)
    results, errors = [], []

    def worker():
        close_old_connections()
        try:
            from django.contrib.auth import get_user_model
            local_owner = get_user_model().objects.get(pk=owner.pk)
            local_org = Organization.objects.get(pk=organization.pk)
            barrier.wait()
            results.append(request_settlement(organization=local_org, actor=local_owner, amount="200.00", currency="EGP", idempotency_key="v28-same-key").pk)
        except Exception as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert errors == []
    assert len(set(results)) == 1
    assert SettlementRequest.objects.filter(idempotency_key="v28-same-key").count() == 1
    assert account_balance(account)["reserved"] == Decimal("200.00")
    with pytest.raises(ValidationError): request_settlement(organization=organization, actor=owner, amount="201.00", currency="EGP", idempotency_key="v28-same-key")


@pytest.mark.django_db(transaction=True)
def test_concurrent_distinct_payouts_cannot_overreserve_same_available_balance():
    owner, organization, account, _ = _payout_fixture("v28-payout-race", balance="500.00")
    barrier = threading.Barrier(2)
    results, errors = [], []

    def worker(key):
        close_old_connections()
        try:
            from django.contrib.auth import get_user_model
            local_owner = get_user_model().objects.get(pk=owner.pk)
            local_org = Organization.objects.get(pk=organization.pk)
            barrier.wait()
            results.append(request_settlement(organization=local_org, actor=local_owner, amount="400.00", currency="EGP", idempotency_key=key).pk)
        except Exception as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker, args=("v28-race-a",)), threading.Thread(target=worker, args=("v28-race-b",))]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)
    assert SettlementRequest.objects.filter(organization=organization).count() == 1
    assert account_balance(account)["reserved"] == Decimal("400.00")
    assert account_balance(account)["withdrawable"] == Decimal("100.00")



def test_legacy_settlement_uses_only_configured_legacy_policy_without_v2_default():
    owner = user("v28-legacy-settlement-owner")
    organization = org(owner, kind=Organization.Kind.DESIGNER, name="V2-8 Legacy Settlement Org")
    legacy = FinancePolicy.objects.create(name="SYNTHETIC LEGACY SETTLEMENT", minimum_payout=Decimal("100.00"), is_active=True)
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.DESIGNER_EARNING, amount=Decimal("500.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC legacy earning")
    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="Legacy Owner", destination_hint="MANUAL-LEGACY-QA", status=PayoutProfile.Status.VERIFIED)
    assert not FinancePolicy.objects.filter(lifecycle_status=FinancePolicy.LifecycleStatus.ACTIVE).exists()
    with pytest.raises(ValidationError):
        request_settlement(organization=organization, actor=owner, amount="99.00", currency="EGP", idempotency_key="legacy-too-low")
    settlement = request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="legacy-accepted")
    assert settlement.amount == Decimal("100.00")
    assert legacy.minimum_payout == Decimal("100.00")


def test_unconfigured_v2_obligation_never_falls_back_to_legacy_policy():
    owner = user("v28-v2-no-fallback-owner")
    organization = org(owner, kind=Organization.Kind.DESIGNER, name="V2-8 No Fallback Org")
    FinancePolicy.objects.create(name="SYNTHETIC LEGACY NO FALLBACK", minimum_payout=Decimal("1.00"), is_active=True)
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.GARMENT_DESIGNER_ROYALTY, amount=Decimal("500.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC unconfigured V2 obligation")
    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="V2 Owner", destination_hint="MANUAL-V2-QA", status=PayoutProfile.Status.VERIFIED)
    with pytest.raises(FinancePolicyUnavailable):
        request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="v2-no-legacy-fallback")


def test_mixed_legacy_and_v2_settlement_provenance_fails_closed_without_allocation_rule():
    owner = user("v28-mixed-provenance-owner")
    organization = org(owner, kind=Organization.Kind.DESIGNER, name="V2-8 Mixed Provenance Org")
    FinancePolicy.objects.create(name="SYNTHETIC LEGACY MIXED", minimum_payout=Decimal("1.00"), is_active=True)
    _active_policy("MIXEDPROV", minimum="1.00")
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.DESIGNER_EARNING, amount=Decimal("250.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC legacy portion")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.GARMENT_DESIGNER_ROYALTY, amount=Decimal("250.00"), currency="EGP", available_at=timezone.now(), memo="SYNTHETIC V2 portion")
    PayoutProfile.objects.create(organization=organization, method=PayoutProfile.Method.MANUAL, account_holder="Mixed Owner", destination_hint="MANUAL-MIXED-QA", status=PayoutProfile.Status.VERIFIED)
    with pytest.raises(ValidationError, match="Mixed legacy/V2 finance provenance"):
        request_settlement(organization=organization, actor=owner, amount="100.00", currency="EGP", idempotency_key="mixed-provenance")
