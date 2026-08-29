from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.artwork.models import ArtworkAsset
from apps.manufacturer_marketplace.models import ManufacturerQuote
from apps.manufacturer_marketplace.services import submit_quote
from apps.operations.models import FulfillmentRecord, ProductionJob, QCInspection
from apps.operations.services import pack_order, record_qc, ship_order, start_production
from apps.organizations.models import Membership
from apps.storefront.models import CustomerCustomization, CustomizationElement, StudioProject

from .test_manufacturer_portal_acceptance import (
    assigned_job,
    designer_product,
    invited_rfq,
    manufacturer,
    private_asset,
)

User = get_user_model()


@pytest.mark.django_db
def test_submitted_manufacturer_quote_is_immutable_under_existing_rules():
    actor, org, _, _ = manufacturer("quote-immutable", role=Membership.Role.PRODUCTION_MANAGER)
    _, _, _, _, invitation = invited_rfq(org, prefix="quote-immutable-rfq")
    quote = submit_quote(
        invitation=invitation,
        actor=actor,
        unit_price=Decimal("110.00"),
        production_lead_days=8,
        minimum_order_quantity=10,
    )
    assert quote.status == ManufacturerQuote.Status.SUBMITTED
    with pytest.raises(ValidationError):
        submit_quote(
            invitation=invitation,
            actor=actor,
            unit_price=Decimal("90.00"),
            production_lead_days=4,
        )
    quote.refresh_from_db()
    assert quote.unit_price == Decimal("110.00")
    assert quote.production_lead_days == 8


@pytest.mark.django_db
def test_unrelated_designer_source_and_unrelated_studio_upload_cannot_be_guessed(client):
    operator, org, _, _ = manufacturer("asset-edges", role=Membership.Role.OPERATOR)
    data = assigned_job(org, prefix="asset-edge-job")

    unrelated_owner, _, _, _, unrelated_artwork_version, _, unrelated_product, unrelated_variant = designer_product("unrelated-assets")
    unrelated_source_media = private_asset(unrelated_owner, "unrelated-source.pdf")
    unrelated_source = ArtworkAsset.objects.create(
        version=unrelated_artwork_version,
        kind=ArtworkAsset.Kind.SOURCE,
        media_asset=unrelated_source_media,
        label="Unrelated source",
    )

    other_project = StudioProject.objects.create(
        customer=data["customer"],
        product=data["store_product"],
        variant=data["variant"],
        status=StudioProject.Status.READY,
        quantity=1,
    )
    other_customization = CustomerCustomization.objects.create(project=other_project, enabled=True)
    other_image = private_asset(
        data["customer"],
        "other-project.png",
        payload=b"other-project-image",
        mime="image/png",
        metadata={"studio_private_upload": True},
    )
    other_element = CustomizationElement.objects.create(
        customization=other_customization,
        decoration_zone=data["zone"],
        kind=CustomizationElement.Kind.IMAGE,
        media_asset=other_image,
        production_method="print",
        rights_confirmed=True,
        transform={"x": 0.2, "y": 0.2, "scale": 0.1, "rotation": 0},
    )

    client.force_login(operator)
    assert client.get(
        reverse("manufacturer-production-media", args=[data["job"].id, "artwork", unrelated_source.id])
    ).status_code == 404
    assert client.get(
        reverse("manufacturer-production-media", args=[data["job"].id, "studio", other_element.id])
    ).status_code == 404


@pytest.mark.django_db
def test_foreign_manufacturer_cannot_mutate_production_or_packing():
    operator, org, _, _ = manufacturer("tenant-job-manufacturer", role=Membership.Role.PRODUCTION_MANAGER)
    data = assigned_job(org, prefix="tenant-job-design")
    foreign, _, _, _ = manufacturer("tenant-job-foreign", role=Membership.Role.PRODUCTION_MANAGER)
    with pytest.raises(PermissionDenied):
        start_production(job=data["job"], actor=foreign)
    data["fulfillment"].status = FulfillmentRecord.Status.READY_TO_PACK
    data["fulfillment"].save(update_fields=["status"])
    with pytest.raises(PermissionDenied):
        pack_order(fulfillment=data["fulfillment"], actor=foreign)


@pytest.mark.django_db
def test_operator_cannot_record_qc_and_foreign_job_is_rejected():
    operator, org, _, _ = manufacturer("qc-operator", role=Membership.Role.OPERATOR)
    data = assigned_job(org, prefix="qc-role-job")
    data["job"].status = ProductionJob.Status.QC_PENDING
    data["job"].save(update_fields=["status"])
    with pytest.raises(PermissionDenied):
        record_qc(
            job=data["job"],
            actor=operator,
            decision=QCInspection.Decision.PASSED,
            notes="Should not be accepted",
        )
    assert not data["job"].qc_inspections.exists()


@pytest.mark.django_db
def test_shipment_requires_real_carrier_and_tracking_values():
    actor, org, _, _ = manufacturer("shipment-validation", role=Membership.Role.PRODUCTION_MANAGER)
    data = assigned_job(org, prefix="shipment-validation-job")
    data["fulfillment"].status = FulfillmentRecord.Status.PACKED
    data["fulfillment"].save(update_fields=["status"])
    with pytest.raises(ValidationError):
        ship_order(
            fulfillment=data["fulfillment"],
            actor=actor,
            carrier="",
            tracking_number="",
            tracking_url="",
        )
    data["fulfillment"].refresh_from_db()
    assert data["fulfillment"].status == FulfillmentRecord.Status.PACKED
    assert data["fulfillment"].tracking_number == ""
