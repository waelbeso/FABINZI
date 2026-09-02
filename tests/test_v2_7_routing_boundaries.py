import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing, RFQ
from apps.manufacturer_marketplace.services import create_rfq, open_rfq
from apps.organizations.models import OnboardingApplication, Organization
from apps.public_profiles.models import ManufacturerCapabilityVerification
from apps.operations.v2_7 import (
    CANONICAL_GARMENT,
    create_customer_order_routing,
    eligible_manufacturers,
    required_canonical_capabilities,
)
from .v2_7_helpers import manufacturer, order_line, user

pytestmark = pytest.mark.django_db


def test_private_operational_routing_does_not_require_public_marketplace_visibility_or_accepts_rfq():
    line = order_line("v27-hidden")
    _, mfr, listing = manufacturer("v27-hidden", [CANONICAL_GARMENT], listing_status=ManufacturerListing.Status.DRAFT)
    assert listing.accepts_rfq is False
    assert list(eligible_manufacturers(line["item"])) == [mfr]
    staff = user("v27-hidden-staff", staff=True)
    rfq = create_customer_order_routing(order_item=line["item"], actor=staff)
    assert rfq.source == RFQ.Source.CUSTOMER_ORDER
    assert rfq.invitations.get().manufacturer == mfr
    assert rfq.routing_snapshot["public_marketplace_visibility_required"] is False
    assert rfq.routing_snapshot["remaining_offer_quota_required_for_routing"] is False


def test_legacy_capability_names_do_not_infer_canonical_truth():
    line = order_line("v27-no-infer")
    owner, mfr, listing = manufacturer("v27-no-infer", [])
    ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.CUT_SEW, name="Legacy cut sew", is_active=True)
    ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.EMBROIDERY, name="Legacy embroidery", is_active=True)
    ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.PRINT, name="Legacy print", is_active=True)
    assert mfr not in eligible_manufacturers(line["item"])


def test_revoked_or_absent_verification_rejected():
    line = order_line("v27-revoked")
    _, mfr, listing = manufacturer("v27-revoked", [])
    cap = ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.OTHER, name="Explicit garment", is_active=True)
    ManufacturerCapabilityVerification.objects.create(capability=cap, canonical_code=CANONICAL_GARMENT, status=ManufacturerCapabilityVerification.Status.REVOKED)
    assert mfr not in eligible_manufacturers(line["item"])


def test_inactive_suspended_and_unapproved_manufacturers_rejected():
    line = order_line("v27-org-state")
    _, active, _ = manufacturer("v27-active", [CANONICAL_GARMENT])
    _, suspended, _ = manufacturer("v27-suspended", [CANONICAL_GARMENT], status=Organization.VerificationStatus.SUSPENDED)
    _, unapproved, _ = manufacturer("v27-unapproved", [CANONICAL_GARMENT], approved=False)
    eligible = eligible_manufacturers(line["item"])
    assert active in eligible
    assert suspended not in eligible
    assert unapproved not in eligible


def test_routing_does_not_consult_remaining_offer_quota(monkeypatch):
    line = order_line("v27-no-quota-route")
    _, mfr, _ = manufacturer("v27-no-quota-route", [CANONICAL_GARMENT])
    import apps.subscriptions.services as subscriptions
    monkeypatch.setattr(subscriptions, "entitlement_summary", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("routing consulted quota")))
    assert mfr in eligible_manufacturers(line["item"])


def test_plain_ready_designed_and_studio_capability_boundaries_are_explicit():
    plain = order_line("v27-plain", purchase_kind="plain")["item"]
    ready = order_line("v27-ready", purchase_kind="ready_designed")["item"]
    studio = order_line("v27-studio", purchase_kind="studio")["item"]
    assert required_canonical_capabilities(plain) == ["garment_manufacturing"]
    assert required_canonical_capabilities(ready) == ["dtf", "garment_manufacturing"]
    assert required_canonical_capabilities(studio) == ["embroidery", "garment_manufacturing"]


def test_generic_print_order_evidence_fails_instead_of_dtf_dtg_inference():
    line = order_line("v27-generic-print", purchase_kind="studio")
    line["item"].customization_snapshot["elements"][0]["production_method"] = "print"
    line["item"].save(update_fields=["customization_snapshot"])
    with pytest.raises(ValidationError):
        required_canonical_capabilities(line["item"])


def test_legacy_designer_sourcing_keeps_published_listing_and_accepts_rfq_gate():
    line = order_line("v27-legacy")
    owner, mfr, listing = manufacturer("v27-legacy-mfr", [CANONICAL_GARMENT], listing_status=ManufacturerListing.Status.DRAFT)
    designer = line["designer"]
    product = line["product"].designed_product
    rfq = create_rfq(designer_organization=line["designer_org"], actor=designer, designed_product=product, title="Legacy sourcing", quantity=1)
    assert rfq.source == RFQ.Source.DESIGNER_SOURCING
    with pytest.raises(ValidationError):
        open_rfq(rfq=rfq, actor=designer, manufacturer_ids=[mfr.pk])


def test_customer_order_routing_requires_staff_control():
    line = order_line("v27-staff-route")
    with pytest.raises(PermissionDenied):
        create_customer_order_routing(order_item=line["item"], actor=line["designer"])
