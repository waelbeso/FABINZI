from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from apps.accounts.guest_identity import GUEST_SESSION_KEY
from apps.artwork.models import Artwork, ArtworkPlacement, ArtworkVersion, DesignedProduct
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
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
from apps.checkout.services import update_checkout_shipping

User = get_user_model()


def make_catalog(prefix, *, ready=False, customization=False, currency="EGP", base_price="500.00", stock_quantity=None):
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
    if ready or customization:
        zone = DecorationZone.objects.create(
            version=version,
            name="Front",
            method=DecorationZone.Method.PRINT,
            placement={"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6},
            max_width_mm=240,
            max_height_mm=300,
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
    if ready:
        placement = ArtworkPlacement(
            product=designed,
            decoration_zone=zone,
            production_method=ArtworkPlacement.ProductionMethod.DTF,
            transform={"x": 0.25, "y": 0.2, "width": 0.5, "height": 0.5, "rotation": 0},
        )
        placement.full_clean()
        placement.save()
    store = create_storefront(organization=org, actor=owner, slug=f"{prefix}-store", name_en=f"{prefix} Store")
    publish_storefront(storefront=store, actor=owner)
    product = create_store_product(
        storefront=store,
        actor=owner,
        designed_product=designed,
        slug=f"{prefix}-product",
        title_en=f"{prefix} Product",
        base_price=base_price,
        currency=currency,
        customization_enabled=customization,
    )
    variant = add_variant(
        product=product,
        actor=owner,
        sku=f"{prefix.upper()}-M",
        size="M",
        stock_quantity=stock_quantity,
    )
    image = MediaAsset.objects.create(
        provider="cloudflare_images",
        provider_asset_id=f"{prefix}-image",
        original_filename=f"{prefix}.png",
        mime_type="image/png",
        size_bytes=1,
        access="public",
        uploaded_by=owner,
    )
    add_product_image(product=product, actor=owner, media_asset=image)
    publish_store_product(product=product, actor=owner)
    return org, product, variant


def seed_guest_identity(client, value="v2-6-test-guest"):
    session = client.session
    session[GUEST_SESSION_KEY] = value
    session.save()
    return value


def fill_guest_shipping(session, guest_identity, *, email="guest@example.test"):
    return update_checkout_shipping(
        session=session,
        actor=AnonymousUser(),
        guest_identity=guest_identity,
        shipping_name="Guest Customer",
        shipping_email=email,
        shipping_phone="01000000000",
        shipping_address1="1 Main St",
        shipping_city="Cairo",
        shipping_region="Cairo",
        shipping_country="EG",
        postal_code="11511",
    )


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
        transform={"x": 0.5, "y": 0.5, "scale": 0.3, "rotation": 0},
    )
    mark_project_ready(project=project, actor=customer)
    return project
