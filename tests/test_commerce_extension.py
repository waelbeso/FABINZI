import importlib
import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.checkout.models import CartItem, CheckoutSession, CustomerOrder, CustomerPurchase, OrderItem, PaymentAttempt
from apps.checkout.services import add_cart_item, create_cart_checkout, create_checkout, get_active_cart, place_cart_purchase, place_order, process_webhook, update_cart_item, update_checkout_shipping
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.integrations.models import IntegrationConfig
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomizationElement, StudioProject
from apps.storefront.services import add_customization_element, add_product_image, add_variant, create_store_product, create_storefront, create_studio_project, enable_customization, mark_project_ready, publish_store_product, publish_storefront

User = get_user_model()


def make_catalog(prefix, *, customization=False):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password12345")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name=f"{prefix} Brand", email=f"{prefix}@brand.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    design = GarmentDesign.objects.create(organization=org, title=f"{prefix} Tee", status=GarmentDesign.Status.APPROVED, created_by=owner)
    version = GarmentDesignVersion.objects.create(design=design, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    if customization:
        DecorationZone.objects.create(version=version, name="Front", method=DecorationZone.Method.BOTH, placement={"x": .2, "y": .2, "width": .6, "height": .6}, max_width_mm=240, max_height_mm=300)
    artwork = Artwork.objects.create(organization=org, title=f"{prefix} Artwork", status="approved", created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status="approved", created_by=owner)
    designed = DesignedProduct.objects.create(organization=org, garment_version=version, artwork_version=artwork_version, title=f"{prefix} Designed", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = create_storefront(organization=org, actor=owner, slug=f"{prefix}-store", name_en=f"{prefix} Store")
    publish_storefront(storefront=store, actor=owner)
    product = create_store_product(storefront=store, actor=owner, designed_product=designed, slug=f"{prefix}-product", title_en=f"{prefix} Product", base_price="500.00", customization_enabled=customization)
    variant = add_variant(product=product, actor=owner, sku=f"{prefix.upper()}-M", size="M")
    image = MediaAsset.objects.create(provider="cloudflare_images", provider_asset_id=f"{prefix}-image", original_filename=f"{prefix}.png", mime_type="image/png", size_bytes=1, access="public", uploaded_by=owner)
    add_product_image(product=product, actor=owner, media_asset=image)
    publish_store_product(product=product, actor=owner)
    return org, product, variant


def fill_shipping(session, customer):
    return update_checkout_shipping(session=session, actor=customer, shipping_name="Customer", shipping_phone="01000000000", shipping_email="customer@example.test", shipping_address1="1 Main St", shipping_city="Cairo", shipping_country="EG")


def ready_studio(customer, product, variant):
    project = create_studio_project(customer=customer, product=product, variant=variant, quantity=1)
    customization = enable_customization(project=project, actor=customer)
    zone = product.designed_product.garment_version.decoration_zones.first()
    add_customization_element(
        customization=customization,
        actor=customer,
        decoration_zone=zone,
        kind=CustomizationElement.Kind.TEXT,
        text="FABINZI",
        production_method=DecorationZone.Method.PRINT,
        transform={"x": .5, "y": .5, "scale": .3, "rotation": 0},
    )
    mark_project_ready(project=project, actor=customer)
    return project


@pytest.mark.django_db
def test_plain_product_cart_never_creates_studio_project():
    customer = User.objects.create_user(username="plain-customer", password="password12345")
    _, product, variant = make_catalog("plain")
    before = StudioProject.objects.count()
    item = add_cart_item(customer=customer, product=product, variant=variant, quantity=2, kind=CartItem.Kind.PLAIN)
    assert item.studio_project_id is None
    assert StudioProject.objects.count() == before


@pytest.mark.django_db
def test_ready_studio_customization_can_be_added_to_cart():
    customer = User.objects.create_user(username="studio-customer", password="password12345")
    _, product, variant = make_catalog("studio", customization=True)
    project = ready_studio(customer, product, variant)
    item = add_cart_item(customer=customer, product=product, variant=variant, kind=CartItem.Kind.STUDIO, studio_project=project)
    assert item.studio_project_id == project.pk


@pytest.mark.django_db
def test_ready_designed_product_can_be_added_without_studio():
    customer = User.objects.create_user(username="ready-customer", password="password12345")
    _, product, variant = make_catalog("ready")
    item = add_cart_item(customer=customer, product=product, variant=variant, kind=CartItem.Kind.READY_DESIGNED)
    assert item.kind == CartItem.Kind.READY_DESIGNED and item.studio_project_id is None


@pytest.mark.django_db
def test_mixed_multi_designer_cart_creates_one_parent_and_operational_children():
    customer = User.objects.create_user(username="mixed-customer", password="password12345")
    org_a, product_a, variant_a = make_catalog("mixa")
    org_b, product_b, variant_b = make_catalog("mixb", customization=True)
    project_b = ready_studio(customer, product_b, variant_b)
    add_cart_item(customer=customer, product=product_a, variant=variant_a, quantity=2, kind=CartItem.Kind.PLAIN)
    add_cart_item(customer=customer, product=product_b, variant=variant_b, kind=CartItem.Kind.STUDIO, studio_project=project_b)
    session = fill_shipping(create_cart_checkout(cart=get_active_cart(customer), actor=customer), customer)
    purchase, attempt = place_cart_purchase(session=session, actor=customer, payment_method="cod")
    children = list(purchase.child_orders.select_related("production_job", "fulfillment", "item"))
    assert len(children) == 2
    assert {o.designer_organization_id for o in children} == {org_a.pk, org_b.pk}
    assert attempt.purchase_id == purchase.pk and attempt.order_id is None and attempt.amount == purchase.total
    assert purchase.status == CustomerPurchase.Status.CONFIRMED
    assert sum(o.subtotal for o in children) == purchase.subtotal
    assert sum(o.shipping_amount for o in children) == purchase.shipping_amount
    assert sum(o.discount_amount for o in children) == purchase.discount_amount
    assert all(o.production_job.manufacturer_id is None for o in children)
    assert all(o.production_job.order_id == o.pk for o in children)
    assert all(o.fulfillment.order_id == o.pk for o in children)


@pytest.mark.django_db
def test_quantity_stays_one_child_operational_order():
    customer = User.objects.create_user(username="quantity-customer", password="password12345")
    _, product, variant = make_catalog("quantity")
    add_cart_item(customer=customer, product=product, variant=variant, quantity=3, kind=CartItem.Kind.PLAIN)
    session = fill_shipping(create_cart_checkout(cart=get_active_cart(customer), actor=customer), customer)
    purchase, _ = place_cart_purchase(session=session, actor=customer, payment_method="cod")
    assert purchase.child_orders.count() == 1
    assert purchase.child_orders.get().item.quantity == 3


@pytest.mark.django_db
def test_parent_payment_webhook_is_idempotent():
    customer = User.objects.create_user(username="webhook-customer", password="password12345")
    _, product, variant = make_catalog("webhook")
    add_cart_item(customer=customer, product=product, variant=variant, kind=CartItem.Kind.PLAIN)
    session = fill_shipping(create_cart_checkout(cart=get_active_cart(customer), actor=customer), customer)
    cfg = IntegrationConfig.objects.get(provider="stripe")
    cfg.enabled = True; cfg.last_test_status = IntegrationConfig.TestStatus.SUCCESS; cfg.save()
    purchase, attempt = place_cart_purchase(session=session, actor=customer, payment_method="stripe")
    attempt.provider_reference = "pi_fabinzi_1"; attempt.save(update_fields=["provider_reference"])
    first = process_webhook(provider="stripe", event_id="evt_fabinzi_1", payload_hash="a" * 64, reference="pi_fabinzi_1", success=True, failed=False, payload={})
    second = process_webhook(provider="stripe", event_id="evt_fabinzi_1", payload_hash="a" * 64, reference="pi_fabinzi_1", success=True, failed=False, payload={})
    purchase.refresh_from_db()
    assert first.pk == second.pk
    assert purchase.status == CustomerPurchase.Status.CONFIRMED
    assert PaymentAttempt.objects.filter(purchase=purchase).count() == 1


@pytest.mark.django_db
def test_legacy_studio_checkout_converges_to_parent_purchase():
    customer = User.objects.create_user(username="legacy-customer", password="password12345")
    _, product, variant = make_catalog("legacy", customization=True)
    project = ready_studio(customer, product, variant)
    session = fill_shipping(create_checkout(project=project, actor=customer), customer)
    order, attempt = place_order(session=session, actor=customer, payment_method="cod")
    assert order.checkout_id == session.pk and order.purchase_id is not None
    assert order.purchase.child_orders.count() == 1
    assert attempt.purchase_id == order.purchase_id
    assert order.item.studio_project_id == project.pk


@pytest.mark.django_db
def test_historical_one_item_order_backfill_remains_readable():
    customer = User.objects.create_user(username="history-customer", password="password12345")
    org, product, variant = make_catalog("history", customization=True)
    project = ready_studio(customer, product, variant)
    session = CheckoutSession.objects.create(customer=customer, studio_project=project, subtotal=500, total=500, currency="EGP")
    order = CustomerOrder.objects.create(checkout=session, customer=customer, designer_organization=org, status=CustomerOrder.Status.CONFIRMED, payment_method="cod", subtotal=500, total=500, currency="EGP", shipping_snapshot={"city": "Cairo"}, confirmed_at=timezone.now())
    OrderItem.objects.create(order=order, store_product=product, variant=variant, studio_project=project, sku=variant.sku, title=product.title_en, unit_price=500, quantity=1, line_total=500)
    PaymentAttempt.objects.create(order=order, provider="cod", status=PaymentAttempt.Status.SUCCEEDED, amount=500, currency="EGP", idempotency_key="legacy-history-attempt")
    migration = importlib.import_module("apps.checkout.migrations.0002_commerce_parent_cart")
    migration.backfill_customer_purchases(django_apps, None)
    order.refresh_from_db()
    assert order.purchase_id is not None and order.purchase.number == order.number
    assert order.payment_attempts.get().purchase_id == order.purchase_id


@pytest.mark.django_db
def test_purchase_fulfillment_state_is_derived():
    customer = User.objects.create_user(username="aggregate-customer", password="password12345")
    _, product_a, variant_a = make_catalog("agga")
    _, product_b, variant_b = make_catalog("aggb")
    add_cart_item(customer=customer, product=product_a, variant=variant_a, kind=CartItem.Kind.PLAIN)
    add_cart_item(customer=customer, product=product_b, variant=variant_b, kind=CartItem.Kind.READY_DESIGNED)
    session = fill_shipping(create_cart_checkout(cart=get_active_cart(customer), actor=customer), customer)
    purchase, _ = place_cart_purchase(session=session, actor=customer, payment_method="cod")
    children = list(purchase.child_orders.all())
    children[0].fulfillment.status = "shipped"; children[0].fulfillment.save(update_fields=["status"])
    assert CustomerPurchase.objects.get(pk=purchase.pk).fulfillment_status == "partially_shipped"
    children[1].fulfillment.status = "shipped"; children[1].fulfillment.save(update_fields=["status"])
    assert CustomerPurchase.objects.get(pk=purchase.pk).fulfillment_status == "shipped"


@pytest.mark.django_db
def test_cart_tenant_isolation():
    customer = User.objects.create_user(username="owner-customer", password="password12345")
    intruder = User.objects.create_user(username="intruder-customer", password="password12345")
    _, product, variant = make_catalog("isolation")
    item = add_cart_item(customer=customer, product=product, variant=variant, kind=CartItem.Kind.PLAIN)
    with pytest.raises(PermissionDenied):
        update_cart_item(item=item, actor=intruder, quantity=3)
