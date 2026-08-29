import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.checkout.models import CustomerOrder, PaymentAttempt
from apps.checkout.services import create_checkout, place_order, update_checkout_shipping
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.integrations.models import IntegrationConfig
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomizationElement
from apps.storefront.services import (
    add_customization_element,
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


def ready_project(stock=False, stock_quantity=None):
    owner = User.objects.create_user(username="owner", password="password123")
    customer = User.objects.create_user(username="customer", password="password123")
    org = Organization.objects.create(kind="designer", display_name="Brand", email="brand@x.test", verification_status="active", created_by=owner)
    Membership.objects.create(organization=org, user=owner, role="owner")
    gd = GarmentDesign.objects.create(organization=org, title="Tee", status="approved", created_by=owner)
    gv = GarmentDesignVersion.objects.create(design=gd, version_number=1, status="approved", created_by=owner)
    zone = DecorationZone.objects.create(version=gv, name="Front", method=DecorationZone.Method.BOTH, placement={"x": .5, "y": .5}, max_width_mm=240, max_height_mm=300)
    art = Artwork.objects.create(organization=org, title="Wave", status="approved", created_by=owner)
    av = ArtworkVersion.objects.create(artwork=art, version_number=1, status="approved", created_by=owner)
    dp = DesignedProduct.objects.create(organization=org, garment_version=gv, artwork_version=av, title="Wave Tee", status="published", created_by=owner)
    store = create_storefront(organization=org, actor=owner, slug="brand", name_en="Brand")
    publish_storefront(storefront=store, actor=owner)
    product = create_store_product(
        storefront=store,
        actor=owner,
        designed_product=dp,
        slug="wave",
        title_en="Wave Tee",
        base_price="500.00",
        fulfillment_mode="stock" if stock else "made_to_order",
        customization_enabled=True,
    )
    variant = add_variant(product=product, actor=owner, sku="WT-M", stock_quantity=stock_quantity)
    from apps.media.models import MediaAsset
    from apps.storefront.services import add_product_image
    image = MediaAsset.objects.create(provider="cloudflare_images", provider_asset_id="/static/brand/fabinzi-logo.svg", original_filename="x.png", mime_type="image/png", size_bytes=1, access="public", uploaded_by=owner)
    add_product_image(product=product, actor=owner, media_asset=image)
    publish_store_product(product=product, actor=owner)

    project = create_studio_project(customer=customer, product=product, variant=variant, quantity=2)
    customization = enable_customization(project=project, actor=customer)
    add_customization_element(
        customization=customization,
        actor=customer,
        decoration_zone=zone,
        kind=CustomizationElement.Kind.TEXT,
        text="Checkout fixture",
        production_method="print",
        transform={"x": .5, "y": .5, "scale": .25, "rotation": 0},
    )
    mark_project_ready(project=project, actor=customer)
    return customer, project, variant


def fill(session, customer):
    return update_checkout_shipping(session=session, actor=customer, shipping_name="Customer", shipping_phone="01000000000", shipping_address1="1 Main St", shipping_city="Cairo", shipping_country="EG")


@pytest.mark.django_db
def test_cod_places_confirms_and_reserves_stock():
    customer, project, variant = ready_project(stock=True, stock_quantity=5)
    session = fill(create_checkout(project=project, actor=customer), customer)
    order, attempt = place_order(session=session, actor=customer, payment_method="cod")
    variant.refresh_from_db()
    assert order.status == CustomerOrder.Status.CONFIRMED
    assert attempt.status == PaymentAttempt.Status.SUCCEEDED
    assert variant.stock_quantity == 3


@pytest.mark.django_db
def test_checkout_snapshot_and_price_are_server_calculated():
    customer, project, _ = ready_project()
    session = fill(create_checkout(project=project, actor=customer), customer)
    order, _ = place_order(session=session, actor=customer, payment_method="cod")
    assert order.total == 1000
    assert order.item.unit_price == 500
    assert order.shipping_snapshot["city"] == "Cairo"
    assert order.item.customization_snapshot["elements"][0]["production_method"] == "print"


@pytest.mark.django_db
def test_checkout_is_private_to_customer():
    customer, project, _ = ready_project()
    intruder = User.objects.create_user(username="intruder", password="password123")
    session = create_checkout(project=project, actor=customer)
    with pytest.raises(PermissionDenied):
        update_checkout_shipping(session=session, actor=intruder, shipping_name="X")


@pytest.mark.django_db
def test_missing_shipping_blocks_order():
    customer, project, _ = ready_project()
    session = create_checkout(project=project, actor=customer)
    with pytest.raises(ValidationError):
        place_order(session=session, actor=customer, payment_method="cod")


@pytest.mark.django_db
def test_disabled_online_provider_is_blocked():
    customer, project, _ = ready_project()
    session = fill(create_checkout(project=project, actor=customer), customer)
    cfg = IntegrationConfig.objects.get(provider="stripe")
    cfg.enabled = False
    cfg.save()
    with pytest.raises(ValidationError):
        place_order(session=session, actor=customer, payment_method="stripe")


@pytest.mark.django_db
def test_same_studio_project_cannot_create_second_final_order():
    customer, project, _ = ready_project()
    session = fill(create_checkout(project=project, actor=customer), customer)
    place_order(session=session, actor=customer, payment_method="cod")
    with pytest.raises(ValidationError):
        create_checkout(project=project, actor=customer)
