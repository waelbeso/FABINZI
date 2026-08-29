import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.artwork.models import Artwork, ArtworkPlacement, ArtworkVersion, DesignedProduct
from apps.checkout.models import CartItem, CheckoutSession, CustomerPurchase
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import StudioProject
from apps.storefront.services import (
    add_product_image,
    add_variant,
    create_store_product,
    create_storefront,
    publish_store_product,
    publish_storefront,
)

User = get_user_model()


def make_web_catalog(prefix, *, customization=False, ready_designed=False, stock_quantity=None):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password12345")
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=f"{prefix} Brand",
        email=f"{prefix}@brand.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    design = GarmentDesign.objects.create(
        organization=org,
        title=f"{prefix} Tee",
        status=GarmentDesign.Status.APPROVED,
        created_by=owner,
    )
    version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        status=GarmentDesignVersion.Status.APPROVED,
        created_by=owner,
    )
    zone = None
    if customization or ready_designed:
        zone = DecorationZone.objects.create(
            version=version,
            name="Front",
            method=DecorationZone.Method.BOTH,
            placement={"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6},
        )
    artwork = Artwork.objects.create(
        organization=org,
        title=f"{prefix} Artwork",
        status=Artwork.Status.APPROVED,
        created_by=owner,
    )
    artwork_version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        status=ArtworkVersion.Status.APPROVED,
        created_by=owner,
    )
    designed = DesignedProduct.objects.create(
        organization=org,
        garment_version=version,
        artwork_version=artwork_version,
        title=f"{prefix} Designed",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )
    if ready_designed:
        ArtworkPlacement.objects.create(
            product=designed,
            decoration_zone=zone,
            transform={"x": 0.5, "y": 0.5, "scale": 1, "rotation": 0},
            production_method="print",
        )
    store = create_storefront(
        organization=org,
        actor=owner,
        slug=f"{prefix}-store",
        name_en=f"{prefix} Store",
        name_ar=f"متجر {prefix}",
        about_en=f"Live {prefix} storefront",
        about_ar=f"متجر {prefix} منشور",
    )
    publish_storefront(storefront=store, actor=owner)
    product = create_store_product(
        storefront=store,
        actor=owner,
        designed_product=designed,
        slug=f"{prefix}-product",
        title_en=f"{prefix} Product",
        title_ar=f"منتج {prefix}",
        description_en=f"Real {prefix} product description",
        description_ar=f"وصف منتج {prefix}",
        base_price="500.00",
        customization_enabled=customization,
        fulfillment_mode="stock" if stock_quantity is not None else "made_to_order",
    )
    variant = add_variant(
        product=product,
        actor=owner,
        sku=f"{prefix.upper()}-M",
        size="M",
        color_name="Black",
        color_hex="#111111",
        stock_quantity=stock_quantity,
    )
    image = MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id="/static/brand/fabinzi-logo.svg",
        original_filename=f"{prefix}.svg",
        mime_type="image/svg+xml",
        size_bytes=1,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=owner,
    )
    add_product_image(product=product, actor=owner, media_asset=image, alt_en=product.title_en, alt_ar=product.title_ar)
    publish_store_product(product=product, actor=owner)
    return product, variant, zone


def shipping_payload():
    return {
        "action": "place",
        "shipping_name": "Customer",
        "shipping_phone": "01000000000",
        "shipping_email": "customer@example.test",
        "shipping_address1": "1 Main St",
        "shipping_address2": "",
        "shipping_city": "Cairo",
        "shipping_region": "Cairo",
        "shipping_country": "EG",
        "postal_code": "",
        "payment_method": "cod",
    }


def start_checkout(client):
    response = client.get(reverse("cart-checkout-start"))
    assert response.status_code == 302
    session = CheckoutSession.objects.get(status="draft")
    assert response.url == reverse("checkout-detail", args=[session.pk])
    return session


@pytest.mark.django_db
def test_plain_product_browser_journey_never_requires_studio(client):
    customer = User.objects.create_user(username="web-plain-customer", password="password12345")
    product, variant, _ = make_web_catalog("webplain")

    store_response = client.get(reverse("store-marketplace"))
    product_response = client.get(reverse("public-store-product", args=[product.storefront.slug, product.slug]))
    assert store_response.status_code == 200
    assert product_response.status_code == 200
    assert b"Sign in to buy" in product_response.content

    client.force_login(customer)
    authenticated_product = client.get(reverse("public-store-product", args=[product.storefront.slug, product.slug]))
    assert authenticated_product.status_code == 200 and b"Add to Cart" in authenticated_product.content
    response = client.post(reverse("cart-add-product", args=[product.pk]), {"variant": variant.pk, "quantity": 2})
    assert response.status_code == 302 and response.url == reverse("cart")
    assert StudioProject.objects.filter(customer=customer).count() == 0
    item = CartItem.objects.get(cart__customer=customer)
    assert item.kind == CartItem.Kind.PLAIN and item.studio_project_id is None and item.quantity == 2

    cart_response = client.get(reverse("cart"))
    assert cart_response.status_code == 200
    assert product.title_en.encode() in cart_response.content
    session = start_checkout(client)
    checkout_response = client.get(reverse("checkout-detail", args=[session.pk]))
    assert checkout_response.status_code == 200 and b"Cash on Delivery" in checkout_response.content

    placed = client.post(reverse("checkout-detail", args=[session.pk]), shipping_payload())
    purchase = CustomerPurchase.objects.get(customer=customer)
    assert placed.status_code == 302
    assert placed.url == reverse("purchase-confirmation", args=[purchase.pk])
    assert purchase.child_orders.count() == 1
    assert purchase.child_orders.get().item.studio_project_id is None
    assert purchase.status == CustomerPurchase.Status.CONFIRMED

    confirmation = client.get(placed.url)
    detail = client.get(reverse("purchase-detail", args=[purchase.pk]))
    assert confirmation.status_code == 200 and str(purchase.number).encode() in confirmation.content
    assert detail.status_code == 200 and product.title_en.encode() in detail.content


@pytest.mark.django_db
def test_customized_product_browser_journey_enters_same_cart(client):
    customer = User.objects.create_user(username="web-custom-customer", password="password12345")
    product, variant, zone = make_web_catalog("webcustom", customization=True)
    client.force_login(customer)

    product_response = client.get(reverse("public-store-product", args=[product.storefront.slug, product.slug]))
    assert b"Customize in Studio" in product_response.content
    studio_entry = client.get(f"{reverse('studio')}?product={product.pk}")
    assert studio_entry.status_code == 200

    started = client.post(reverse("studio"), {"product": product.pk, "variant": variant.pk, "quantity": 1})
    project = StudioProject.objects.get(customer=customer, product=product)
    assert started.status_code == 302 and started.url == reverse("studio-project", args=[project.pk])

    added_text = client.post(reverse("studio-project", args=[project.pk]), {"action": "add_text", "decoration_zone": zone.pk, "text": "FABINZI"})
    assert added_text.status_code == 302
    ready = client.post(reverse("studio-project", args=[project.pk]), {"action": "ready"})
    project.refresh_from_db()
    assert ready.status_code == 302 and project.status == StudioProject.Status.READY

    added = client.post(reverse("studio-project", args=[project.pk]), {"action": "add_cart"})
    item = CartItem.objects.get(cart__customer=customer)
    assert added.status_code == 302 and added.url == reverse("cart")
    assert item.kind == CartItem.Kind.STUDIO and item.studio_project_id == project.pk


@pytest.mark.django_db
def test_ready_designed_product_browser_adds_without_studio(client):
    customer = User.objects.create_user(username="web-ready-customer", password="password12345")
    product, variant, _ = make_web_catalog("webready", ready_designed=True)
    client.force_login(customer)

    page = client.get(reverse("public-store-product", args=[product.storefront.slug, product.slug]))
    assert page.status_code == 200 and b"Ready designed" in page.content
    response = client.post(reverse("cart-add-product", args=[product.pk]), {"variant": variant.pk, "quantity": 1})
    item = CartItem.objects.get(cart__customer=customer)
    assert response.status_code == 302
    assert item.kind == CartItem.Kind.READY_DESIGNED and item.studio_project_id is None
    assert StudioProject.objects.filter(customer=customer).count() == 0


@pytest.mark.django_db
def test_mixed_plain_customized_ready_browser_checkout_creates_one_parent(client):
    customer = User.objects.create_user(username="web-mixed-customer", password="password12345")
    plain, plain_variant, _ = make_web_catalog("mixplain")
    custom, custom_variant, zone = make_web_catalog("mixcustom", customization=True)
    ready, ready_variant, _ = make_web_catalog("mixready", ready_designed=True)
    client.force_login(customer)

    assert client.post(reverse("cart-add-product", args=[plain.pk]), {"variant": plain_variant.pk, "quantity": 1}).status_code == 302
    assert client.post(reverse("cart-add-product", args=[ready.pk]), {"variant": ready_variant.pk, "quantity": 1}).status_code == 302
    client.post(reverse("studio"), {"product": custom.pk, "variant": custom_variant.pk, "quantity": 1})
    project = StudioProject.objects.get(customer=customer, product=custom)
    client.post(reverse("studio-project", args=[project.pk]), {"action": "add_text", "decoration_zone": zone.pk, "text": "MIX"})
    client.post(reverse("studio-project", args=[project.pk]), {"action": "ready"})
    client.post(reverse("studio-project", args=[project.pk]), {"action": "add_cart"})

    cart_response = client.get(reverse("cart"))
    assert cart_response.status_code == 200
    assert CartItem.objects.filter(cart__customer=customer).count() == 3
    assert set(CartItem.objects.filter(cart__customer=customer).values_list("kind", flat=True)) == {
        CartItem.Kind.PLAIN,
        CartItem.Kind.STUDIO,
        CartItem.Kind.READY_DESIGNED,
    }

    session = start_checkout(client)
    placed = client.post(reverse("checkout-detail", args=[session.pk]), shipping_payload())
    purchase = CustomerPurchase.objects.get(customer=customer)
    assert placed.status_code == 302 and placed.url == reverse("purchase-confirmation", args=[purchase.pk])
    assert purchase.child_orders.count() == 3
    assert purchase.status == CustomerPurchase.Status.CONFIRMED
    assert purchase.child_orders.filter(item__studio_project=project).count() == 1
    assert all(order.production_job.manufacturer_id is None for order in purchase.child_orders.all())


@pytest.mark.django_db
def test_customer_commerce_renders_arabic_rtl_and_dark_theme(client):
    customer = User.objects.create_user(
        username="web-ar-customer",
        password="password12345",
        theme_preference="dark",
    )
    product, _, _ = make_web_catalog("webar", customization=True)
    client.force_login(customer)
    response = client.get(
        reverse("public-store-product", args=[product.storefront.slug, product.slug]),
        HTTP_ACCEPT_LANGUAGE="ar",
    )
    content = response.content.decode()
    assert response.status_code == 200
    assert 'lang="ar"' in content and 'dir="rtl"' in content and 'data-theme="dark"' in content
    assert "أضف إلى السلة" in content and "خصّص في الاستوديو" in content


@pytest.mark.django_db
def test_parent_purchase_web_permission_is_enforced(client):
    owner = User.objects.create_user(username="purchase-web-owner", password="password12345")
    intruder = User.objects.create_user(username="purchase-web-intruder", password="password12345")
    product, variant, _ = make_web_catalog("webpermission")
    client.force_login(owner)
    client.post(reverse("cart-add-product", args=[product.pk]), {"variant": variant.pk, "quantity": 1})
    session = start_checkout(client)
    client.post(reverse("checkout-detail", args=[session.pk]), shipping_payload())
    purchase = CustomerPurchase.objects.get(customer=owner)

    client.force_login(intruder)
    response = client.get(reverse("purchase-detail", args=[purchase.pk]))
    assert response.status_code == 403
