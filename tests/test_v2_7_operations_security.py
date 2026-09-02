from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404

from apps.checkout.models import CustomerOrder, OrderItem
from apps.manufacturer_marketplace.services import submit_quote
from apps.media.manufacturer_views import _job_for_actor, _resolve_job_media
from apps.media.models import MediaAsset
from apps.operations.models import FulfillmentRecord, ProductionMilestone, QCInspection
from apps.operations.services import record_qc, request_qc, start_order_operations, start_production, update_milestone
from apps.operations.v2_7 import CANONICAL_GARMENT, assign_customer_order_manufacturer, create_customer_order_routing, release_customer_order_production
from apps.organizations.models import Membership
from .v2_7_helpers import manufacturer, media, order_line, user

pytestmark = pytest.mark.django_db


def _assigned(prefix, *, kind="plain", released=True):
    line = order_line(prefix, purchase_kind=kind, production_validated=True)
    required = [CANONICAL_GARMENT]
    if kind == "ready_designed": required.append("dtf")
    if kind == "studio": required.append("embroidery")
    owner, mfr, _ = manufacturer(prefix, required)
    staff = user(f"{prefix}-staff", staff=True)
    rfq = create_customer_order_routing(order_item=line["item"], actor=staff)
    quote = submit_quote(invitation=rfq.invitations.get(manufacturer=mfr), actor=owner, unit_price="100", production_lead_days=7)
    spec = assign_customer_order_manufacturer(quote=quote, actor=staff)
    if released:
        release_customer_order_production(job=line["job"], actor=staff)
    return line, owner, mfr, staff, spec


def test_ready_designed_and_studio_specifications_preserve_applicable_evidence():
    ready, _, _, _, ready_spec = _assigned("v27-ready-spec", kind="ready_designed")
    assert ready_spec.snapshot["ready_designed"]["artwork_version_id"] == ready["product"].designed_product.artwork_version_id
    assert ready_spec.snapshot["ready_designed"]["placements"][0]["production_method"] == "dtf"
    assert ready_spec.snapshot["ready_designed"]["source_assets"]

    studio, _, _, _, studio_spec = _assigned("v27-studio-spec", kind="studio")
    assert studio_spec.snapshot["studio"]["elements"][0]["production_method"] == "embroidery"
    assert studio_spec.snapshot["commerce"]["purchase_kind"] == "studio"


def test_operational_private_media_is_specification_bound_and_unrelated_asset_denied():
    line, owner, _, _, spec = _assigned("v27-media", kind="ready_designed")
    allowed_id = spec.authorized_media_asset_ids[0]
    asset = _resolve_job_media(line["job"], "spec", allowed_id)
    assert asset.pk == allowed_id
    unrelated = media(owner, "unrelated-private.pdf", access=MediaAsset.Access.PRIVATE)
    with pytest.raises(Http404):
        _resolve_job_media(line["job"], "spec", unrelated.pk)
    with pytest.raises(Http404):
        _resolve_job_media(line["job"], "design", line["version"].assets.filter(kind="tech_pack").get().pk)


def test_missing_customer_order_specification_fails_safe_instead_of_live_fallback():
    line = order_line("v27-missing-spec")
    owner, mfr, _ = manufacturer("v27-missing-spec", [CANONICAL_GARMENT])
    staff = user("v27-missing-spec-staff", staff=True)
    create_customer_order_routing(order_item=line["item"], actor=staff)
    line["job"].manufacturer = mfr
    line["job"].save(update_fields=["manufacturer", "updated_at"])
    live_design_asset = line["version"].assets.filter(kind="tech_pack").get()
    with pytest.raises(Http404):
        _resolve_job_media(line["job"], "design", live_design_asset.pk)
    line["job"].status = line["job"].Status.QUEUED
    line["job"].save(update_fields=["status", "updated_at"])
    with pytest.raises(ValidationError):
        start_production(job=line["job"], actor=owner)


def test_manufacturer_organization_isolation_for_production_access():
    line, _, _, _, _ = _assigned("v27-isolation")
    other_owner, _, _ = manufacturer("v27-isolation-other", [CANONICAL_GARMENT])
    with pytest.raises(Http404):
        _job_for_actor(other_owner, line["job"].pk)


def test_production_cannot_start_before_fabinzi_release_but_standard_lifecycle_remains_canonical():
    line, owner, _, staff, spec = _assigned("v27-lifecycle", released=False)
    with pytest.raises(ValidationError):
        start_production(job=line["job"], actor=owner)
    release_customer_order_production(job=line["job"], actor=staff)
    job = start_production(job=line["job"], actor=owner)
    assert job.status == job.Status.IN_PRODUCTION
    for milestone in job.milestones.all():
        update_milestone(milestone=milestone, actor=owner, status=ProductionMilestone.Status.COMPLETED)
    request_qc(job=job, actor=owner)
    inspection = record_qc(job=job, actor=owner, decision=QCInspection.Decision.PASSED, checklist={"reference": "actual inspection"})
    job.refresh_from_db(); line["fulfillment"].refresh_from_db()
    assert inspection.job_id == job.pk
    assert job.status == job.Status.READY
    assert line["fulfillment"].status == FulfillmentRecord.Status.READY_TO_PACK


def test_qc_role_authorization_remains_private_to_assigned_manufacturer():
    line, _, mfr, staff, _ = _assigned("v27-qc")
    production_owner = mfr.memberships.get(role=Membership.Role.OWNER).user
    job = start_production(job=line["job"], actor=production_owner)
    for milestone in job.milestones.all():
        update_milestone(milestone=milestone, actor=production_owner, status=ProductionMilestone.Status.COMPLETED)
    request_qc(job=job, actor=production_owner)
    outsider = user("v27-qc-outsider")
    with pytest.raises(PermissionDenied):
        record_qc(job=job, actor=outsider, decision=QCInspection.Decision.PASSED)


def test_child_fulfillment_progress_drives_parent_partial_state_without_parallel_fulfillment_model():
    first = order_line("v27-parent")
    second_order = CustomerOrder.objects.create(
        purchase=first["purchase"], customer=first["customer"], designer_organization=first["designer_org"],
        status=CustomerOrder.Status.CONFIRMED, payment_method=CustomerOrder.PaymentMethod.COD,
        subtotal=Decimal("500"), total=Decimal("500"), currency="EGP", shipping_snapshot=first["purchase"].shipping_snapshot,
    )
    second_item = OrderItem.objects.create(
        order=second_order, store_product=first["product"], variant=first["variant"], purchase_kind="plain",
        sku=first["variant"].sku, title=first["product"].title_en, size="M", color_name="Black",
        unit_price=Decimal("500"), quantity=1, line_total=Decimal("500"),
        pricing_snapshot=first["item"].pricing_snapshot, production_snapshot=first["item"].production_snapshot,
    )
    _, second_fulfillment = start_order_operations(order=second_order, actor=first["customer"])
    first["fulfillment"].status = FulfillmentRecord.Status.SHIPPED
    first["fulfillment"].save(update_fields=["status", "updated_at"])
    second_fulfillment.status = FulfillmentRecord.Status.WAITING_PRODUCTION
    second_fulfillment.save(update_fields=["status", "updated_at"])
    assert first["purchase"].child_orders.count() == 2
    assert first["purchase"].fulfillment_status == "partially_shipped"
