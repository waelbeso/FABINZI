import threading

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections

from apps.manufacturer_marketplace.models import ManufacturerQuote
from apps.manufacturer_marketplace.services import save_quote_draft, submit_quote
from apps.operations.models import ProductionSpecification
from apps.operations.v2_7 import (
    CANONICAL_GARMENT,
    assign_customer_order_manufacturer,
    create_customer_order_routing,
    release_customer_order_production,
    snapshot_sha256,
)
from apps.subscriptions.models import ManufacturerOfferUsage
from .v2_7_helpers import manufacturer, order_line, user

pytestmark = pytest.mark.django_db


def _opportunity(prefix, *, production_validated=True):
    line = order_line(prefix, production_validated=production_validated)
    owner, mfr, _ = manufacturer(prefix, [CANONICAL_GARMENT])
    staff = user(f"{prefix}-staff", staff=True)
    rfq = create_customer_order_routing(order_item=line["item"], actor=staff)
    invitation = rfq.invitations.get(manufacturer=mfr)
    return line, owner, mfr, staff, rfq, invitation


def test_draft_offer_consumes_no_quota_and_first_submit_consumes_exactly_once():
    _, owner, _, _, _, invitation = _opportunity("v27-offer")
    draft = save_quote_draft(invitation=invitation, actor=owner, unit_price="100", production_lead_days=7)
    assert draft.status == ManufacturerQuote.Status.DRAFT
    assert not ManufacturerOfferUsage.objects.filter(quote=draft).exists()
    submitted = submit_quote(
        invitation=invitation,
        actor=owner,
        unit_price="100",
        production_lead_days=7,
        setup_fee="3.50",
        sample_fee="2.25",
        shipping_estimate="11.75",
        currency="EGP",
        minimum_order_quantity=2,
        sample_lead_days=3,
        valid_until="2026-10-01",
        notes="Frozen offer",
    )
    assert submitted.pk == draft.pk
    assert submitted.status == ManufacturerQuote.Status.SUBMITTED
    submitted_at = submitted.submitted_at
    assert ManufacturerOfferUsage.objects.filter(quote=submitted).count() == 1
    retry = submit_quote(
        invitation=invitation,
        actor=owner,
        unit_price="100.00",
        production_lead_days=7,
        setup_fee="3.50",
        sample_fee="2.25",
        shipping_estimate="11.75",
        currency="egp",
        minimum_order_quantity=2,
        sample_lead_days=3,
        valid_until="2026-10-01",
        notes="Frozen offer",
    )
    assert retry.pk == submitted.pk
    retry.refresh_from_db()
    assert retry.submitted_at == submitted_at
    assert ManufacturerOfferUsage.objects.filter(quote=submitted).count() == 1


def test_submitted_offer_conflicting_retry_is_rejected_without_mutation_or_quota():
    _, owner, _, _, rfq, invitation = _opportunity("v27-offer-conflict")
    quote = submit_quote(
        invitation=invitation,
        actor=owner,
        unit_price="100",
        production_lead_days=7,
        setup_fee="3.50",
        sample_fee="2.25",
        shipping_estimate="11.75",
        currency="EGP",
        minimum_order_quantity=2,
        sample_lead_days=3,
        valid_until="2026-10-01",
        notes="Frozen offer",
    )
    frozen = {
        field: getattr(quote, field)
        for field in (
            "unit_price",
            "production_lead_days",
            "setup_fee",
            "sample_fee",
            "shipping_estimate",
            "currency",
            "minimum_order_quantity",
            "sample_lead_days",
            "valid_until",
            "notes",
            "submitted_at",
        )
    }
    invitation.refresh_from_db()
    rfq.refresh_from_db()
    invitation_state = (invitation.status, invitation.responded_at)
    rfq_status = rfq.status
    usage_id = ManufacturerOfferUsage.objects.get(quote=quote).pk

    with pytest.raises(ValidationError):
        submit_quote(
            invitation=invitation,
            actor=owner,
            unit_price="100",
            production_lead_days=7,
            setup_fee="3.50",
            sample_fee="2.25",
            shipping_estimate="11.75",
            currency="EGP",
            minimum_order_quantity=2,
            sample_lead_days=3,
            valid_until="2026-10-01",
            notes="Changed after submission",
        )

    quote.refresh_from_db()
    invitation.refresh_from_db()
    rfq.refresh_from_db()
    assert {field: getattr(quote, field) for field in frozen} == frozen
    assert (invitation.status, invitation.responded_at) == invitation_state
    assert rfq.status == rfq_status
    assert ManufacturerOfferUsage.objects.get(quote=quote).pk == usage_id
    assert ManufacturerOfferUsage.objects.filter(quote=quote).count() == 1


def test_withdrawal_resubmission_and_expiration_never_restore_consumed_quota():
    _, owner, _, _, _, invitation = _opportunity("v27-resubmit")
    quote = submit_quote(invitation=invitation, actor=owner, unit_price="100", production_lead_days=7)
    usage_id = ManufacturerOfferUsage.objects.get(quote=quote).pk
    quote.status = ManufacturerQuote.Status.WITHDRAWN
    quote.save(update_fields=["status", "updated_at"])
    resubmitted = submit_quote(invitation=invitation, actor=owner, unit_price="101", production_lead_days=8)
    assert ManufacturerOfferUsage.objects.get(quote=resubmitted).pk == usage_id
    resubmitted.status = ManufacturerQuote.Status.EXPIRED
    resubmitted.save(update_fields=["status", "updated_at"])
    assert ManufacturerOfferUsage.objects.filter(quote=resubmitted).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_submission_consumes_once():
    _, owner, _, _, _, invitation = _opportunity("v27-concurrent")
    barrier = threading.Barrier(2)
    results, errors = [], []

    def worker():
        close_old_connections()
        try:
            from django.contrib.auth import get_user_model
            from apps.manufacturer_marketplace.models import RFQInvitation
            local_owner = get_user_model().objects.get(pk=owner.pk)
            local_invitation = RFQInvitation.objects.get(pk=invitation.pk)
            barrier.wait()
            quote = submit_quote(invitation=local_invitation, actor=local_owner, unit_price="100", production_lead_days=7)
            results.append(quote.pk)
        except Exception as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert errors == []
    assert len(set(results)) == 1
    assert ManufacturerOfferUsage.objects.filter(quote_id=results[0]).count() == 1


def test_assignment_is_fabinzi_controlled_and_creates_immutable_complete_specification():
    line, owner, mfr, staff, _, invitation = _opportunity("v27-spec")
    quote = submit_quote(invitation=invitation, actor=owner, unit_price="100", production_lead_days=7)
    with pytest.raises(PermissionDenied):
        assign_customer_order_manufacturer(quote=quote, actor=line["designer"])
    spec = assign_customer_order_manufacturer(quote=quote, actor=staff)
    assert spec.job == line["job"]
    assert spec.manufacturer == mfr
    assert spec.accepted_quote_id == quote.pk
    assert spec.snapshot_sha256 == snapshot_sha256(spec.snapshot)
    assert spec.snapshot["lineage"]["customer_purchase_id"] == line["purchase"].pk
    assert spec.snapshot["lineage"]["customer_order_id"] == line["order"].pk
    assert spec.snapshot["lineage"]["order_item_id"] == line["item"].pk
    assert spec.snapshot["commerce"]["store_product_id"] == line["product"].pk
    assert spec.snapshot["commerce"]["product_variant_id"] == line["variant"].pk
    garment = spec.snapshot["garment_design"]
    assert garment["garment_design_version_id"] == line["version"].pk
    assert garment["technical_schema_version"] == "2.4"
    assert garment["ordered_size_measurements"]
    assert garment["ordered_size_pom"]
    assert garment["selected_size_patterns"]
    assert garment["materials_bom"]
    assert garment["technical_assets"]
    assert garment["qc_requirements"]
    assert spec.snapshot["manufacturing_offer"]["quote_id"] == quote.pk
    assert spec.snapshot["assignment"]["manufacturer_id"] == mfr.pk
    assert spec.snapshot["assignment"]["verified_canonical_capabilities"]
    assert spec.authorized_media_asset_ids

    frozen = spec.snapshot
    line["version"].construction_notes = "MUTATED AFTER ASSIGNMENT"
    line["version"].save(update_fields=["construction_notes"])
    spec.refresh_from_db()
    assert spec.snapshot == frozen
    spec.snapshot = {"tampered": True}
    with pytest.raises(ValidationError):
        spec.save()


def test_production_release_requires_canonical_production_eligibility_and_validation():
    line, owner, _, staff, _, invitation = _opportunity("v27-release-block", production_validated=False)
    quote = submit_quote(invitation=invitation, actor=owner, unit_price="100", production_lead_days=7)
    spec = assign_customer_order_manufacturer(quote=quote, actor=staff)
    with pytest.raises(ValidationError):
        release_customer_order_production(job=line["job"], actor=staff)
    spec.refresh_from_db()
    assert spec.released_at is None
    assert spec.release_block_reason


def test_production_release_succeeds_when_canonical_gdv_is_production_eligible():
    line, owner, _, staff, _, invitation = _opportunity("v27-release-pass", production_validated=True)
    quote = submit_quote(invitation=invitation, actor=owner, unit_price="100", production_lead_days=7)
    assign_customer_order_manufacturer(quote=quote, actor=staff)
    released = release_customer_order_production(job=line["job"], actor=staff)
    assert released.released_at is not None
    assert released.released_by == staff


def test_competing_assignment_cannot_replace_first_assignment():
    line = order_line("v27-compete")
    owner1, mfr1, _ = manufacturer("v27-compete-a", [CANONICAL_GARMENT])
    owner2, mfr2, _ = manufacturer("v27-compete-b", [CANONICAL_GARMENT])
    staff = user("v27-compete-staff", staff=True)
    rfq = create_customer_order_routing(order_item=line["item"], actor=staff)
    q1 = submit_quote(invitation=rfq.invitations.get(manufacturer=mfr1), actor=owner1, unit_price="100", production_lead_days=7)
    q2 = submit_quote(invitation=rfq.invitations.get(manufacturer=mfr2), actor=owner2, unit_price="101", production_lead_days=8)
    first = assign_customer_order_manufacturer(quote=q1, actor=staff)
    with pytest.raises(ValidationError):
        assign_customer_order_manufacturer(quote=q2, actor=staff)
    first.refresh_from_db()
    assert first.manufacturer == mfr1
    assert ProductionSpecification.objects.filter(job=line["job"]).count() == 1
