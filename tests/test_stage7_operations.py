import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.checkout.services import create_checkout, place_order, update_checkout_shipping
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerQuote, ManufacturerSelection, RFQ, RFQInvitation
from apps.media.models import MediaAsset
from apps.operations.models import FulfillmentRecord, ProductionJob, ProductionMilestone, QCInspection
from apps.operations.services import assign_manufacturer, deliver_order, pack_order, record_qc, request_qc, ship_order, start_production, update_milestone
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomizationElement
from apps.storefront.services import (
    add_customization_element,
    add_product_image,
    add_variant,
    create_store_product,
    create_storefront,
    create_studio_project,
    enable_customization,
    mark_project_ready,
    publish_store_product,
    publish_storefront,
)

User = get_user_model()


def confirmed_order(stock=False):
    owner = User.objects.create_user(username="owner", password="password123")
    customer = User.objects.create_user(username="customer", password="password123")
    org = Organization.objects.create(kind="designer", display_name="Brand", email="brand@x.test", verification_status="active", created_by=owner)
    Membership.objects.create(organization=org, user=owner, role="owner")
    gd = GarmentDesign.objects.create(organization=org, title="Tee", status="approved", created_by=owner)
    gv = GarmentDesignVersion.objects.create(design=gd, version_number=1, status="approved", created_by=owner)
    zone = DecorationZone.objects.create(version=gv, name="Front", method=DecorationZone.Method.BOTH, placement={"x": .5, "y": .5}, max_width_mm=220, max_height_mm=280)
    art = Artwork.objects.create(organization=org, title="Wave", status="approved", created_by=owner)
    av = ArtworkVersion.objects.create(artwork=art, version_number=1, status="approved", created_by=owner)
    dp = DesignedProduct.objects.create(organization=org, garment_version=gv, artwork_version=av, title="Wave Tee", status="published", created_by=owner)
    store = create_storefront(organization=org, actor=owner, slug="brand", name_en="Brand")
    publish_storefront(storefront=store, actor=owner)
    p = create_store_product(
        storefront=store,
        actor=owner,
        designed_product=dp,
        slug="wave",
        title_en="Wave Tee",
        base_price="500",
        fulfillment_mode="stock" if stock else "made_to_order",
        customization_enabled=True,
    )
    v = add_variant(product=p, actor=owner, sku="WT-M", stock_quantity=10 if stock else None)
    image = MediaAsset.objects.create(provider="cloudflare_images", provider_asset_id="/static/brand/fabinzi-logo.svg", original_filename="x.png", mime_type="image/png", size_bytes=1, access="public", uploaded_by=owner)
    add_product_image(product=p, actor=owner, media_asset=image)
    publish_store_product(product=p, actor=owner)

    project = create_studio_project(customer=customer, product=p, variant=v, quantity=2)
    customization = enable_customization(project=project, actor=customer)
    add_customization_element(
        customization=customization,
        actor=customer,
        decoration_zone=zone,
        kind=CustomizationElement.Kind.TEXT,
        text="Operations fixture",
        production_method="print",
        transform={"x": .5, "y": .5, "scale": .25, "rotation": 0},
    )
    mark_project_ready(project=project, actor=customer)
    s = create_checkout(project=project, actor=customer)
    update_checkout_shipping(session=s, actor=customer, shipping_name="Customer", shipping_phone="010", shipping_address1="1 Main", shipping_city="Cairo", shipping_country="EG")
    order, _ = place_order(session=s, actor=customer, payment_method="cod")
    return owner, customer, org, dp, order


def selection_for(owner, designer, dp):
    muser = User.objects.create_user(username="mfr", password="password123")
    m = Organization.objects.create(kind="manufacturer", display_name="Factory", email="f@x.test", verification_status="active", created_by=muser)
    Membership.objects.create(organization=m, user=muser, role="production_manager")
    rfq = RFQ.objects.create(designer_organization=designer, designed_product=dp, title="Production", quantity=100, status="selected", created_by=owner)
    inv = RFQInvitation.objects.create(rfq=rfq, manufacturer=m, status="quoted")
    q = ManufacturerQuote.objects.create(invitation=inv, status="accepted", unit_price=100, production_lead_days=7, created_by=muser)
    sel = ManufacturerSelection.objects.create(rfq=rfq, quote=q, manufacturer=m, selected_by=owner)
    return muser, m, sel


@pytest.mark.django_db
def test_made_to_order_confirmation_initializes_operations_without_manufacturer_selection():
    _, _, _, _, order = confirmed_order(False)
    assert ProductionJob.objects.filter(order=order, status="awaiting_assignment").exists()
    assert order.production_job.manufacturer_id is None
    assert order.fulfillment.status == FulfillmentRecord.Status.WAITING_PRODUCTION
    assert order.production_job.milestones.count() == 5


@pytest.mark.django_db
def test_stock_order_bypasses_manufacturing():
    _, _, _, _, order = confirmed_order(True)
    assert not ProductionJob.objects.filter(order=order).exists()
    assert order.fulfillment.status == FulfillmentRecord.Status.READY_TO_PACK


@pytest.mark.django_db
def test_assignment_production_qc_and_fulfillment_lifecycle():
    owner, _, designer, dp, order = confirmed_order(False)
    muser, _, sel = selection_for(owner, designer, dp)
    job = assign_manufacturer(job=order.production_job, selection=sel, actor=owner)
    start_production(job=job, actor=muser)
    for milestone in job.milestones.all():
        update_milestone(milestone=milestone, actor=muser, status=ProductionMilestone.Status.COMPLETED)
    request_qc(job=job, actor=muser)
    q = record_qc(job=job, actor=muser, decision=QCInspection.Decision.PASSED)
    order.fulfillment.refresh_from_db()
    assert q.decision == "passed"
    assert order.fulfillment.status == FulfillmentRecord.Status.READY_TO_PACK
    f = pack_order(fulfillment=order.fulfillment, actor=muser)
    f = ship_order(fulfillment=f, actor=muser, carrier="DHL", tracking_number="ABC123")
    f = deliver_order(fulfillment=f, actor=muser)
    assert f.status == FulfillmentRecord.Status.DELIVERED
    assert f.events.count() >= 4


@pytest.mark.django_db
def test_cross_manufacturer_cannot_update_job():
    owner, _, designer, dp, order = confirmed_order(False)
    muser, _, sel = selection_for(owner, designer, dp)
    job = assign_manufacturer(job=order.production_job, selection=sel, actor=owner)
    outsider = User.objects.create_user(username="outsider", password="password123")
    with pytest.raises(PermissionDenied):
        start_production(job=job, actor=outsider)


@pytest.mark.django_db
def test_qc_requires_all_milestones_complete():
    owner, _, designer, dp, order = confirmed_order(False)
    muser, _, sel = selection_for(owner, designer, dp)
    job = assign_manufacturer(job=order.production_job, selection=sel, actor=owner)
    start_production(job=job, actor=muser)
    with pytest.raises(ValidationError):
        request_qc(job=job, actor=muser)
