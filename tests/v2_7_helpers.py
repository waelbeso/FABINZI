from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkPlacement, ArtworkVersion, DesignedProduct
from apps.checkout.models import Cart, CartItem, CheckoutSession, CustomerOrder, CustomerPurchase, OrderItem
from apps.design.models import (
    DecorationZone,
    DesignAsset,
    DesignColorway,
    DesignColorwayImage,
    DesignMaterial,
    DesignPOMValue,
    DesignPatternRequirement,
    DesignPointOfMeasure,
    GarmentDesign,
    GarmentDesignVersion,
    SizeChartRow,
)
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.media.models import MediaAsset
from apps.operations.services import start_order_operations
from apps.organizations.models import Membership, OnboardingApplication, Organization
from apps.public_profiles.models import ManufacturerCapabilityVerification
from apps.storefront.models import ProductVariant, StoreProduct, Storefront
from apps.subscriptions.services import ensure_subscription_for_organization
from tests.v2_3_support import ensure_v2_3_reference_rows

User = get_user_model()


def user(name, *, staff=False, superuser=False):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password12345",
        is_staff=staff or superuser,
        is_superuser=superuser,
    )


def org(owner, *, kind, name=None, status=Organization.VerificationStatus.ACTIVE, approved=True):
    organization = Organization.objects.create(
        kind=kind,
        display_name=name or f"{kind}-{owner.username}",
        email=f"org-{owner.username}@example.test",
        verification_status=status,
        created_by=owner,
    )
    Membership.objects.create(organization=organization, user=owner, role=Membership.Role.OWNER, is_active=True)
    if approved:
        OnboardingApplication.objects.create(
            organization=organization,
            status=OnboardingApplication.Status.APPROVED,
            reviewed_at=timezone.now(),
        )
    return organization


def media(owner, name, *, access=MediaAsset.Access.PRIVATE, mime="application/pdf", marker="v27"):
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=f"tests/{marker}/{owner.pk}/{name}",
        original_filename=name,
        mime_type=mime,
        size_bytes=123,
        checksum_sha256=("a" * 64),
        access=access,
        uploaded_by=owner,
    )


def complete_product(prefix, *, purchase_kind=CartItem.Kind.PLAIN, production_validated=True):
    designer = user(f"{prefix}-designer")
    designer_org = org(designer, kind=Organization.Kind.DESIGNER, name=f"{prefix} Designer")
    design = GarmentDesign.objects.create(organization=designer_org, title=f"{prefix} garment", status=GarmentDesign.Status.APPROVED, created_by=designer)
    version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        status=GarmentDesignVersion.Status.APPROVED,
        base_material="180 GSM cotton",
        construction_notes="Factory-ready construction notes.",
        technical_specs={"seam": "reference"},
        technical_schema_version="2.4",
        product_class=GarmentDesignVersion.ProductClass.APPAREL,
        size_system=GarmentDesignVersion.SizeSystem.MULTI_SIZE,
        decoration_applicability=GarmentDesignVersion.DecorationApplicability.NOT_APPLICABLE if purchase_kind == CartItem.Kind.PLAIN else GarmentDesignVersion.DecorationApplicability.CONFIGURED,
        requires_3d_source=True,
        qc_requirements={"measurement_check": True},
        production_engineering_validated=production_validated,
        created_by=designer,
    )
    size = SizeChartRow.objects.create(version=version, size_label="M", measurements={"half_chest_cm": "53"})
    point = DesignPointOfMeasure.objects.create(version=version, symbolic_ref=f"{prefix}-POM-01", name="Half chest", unit=DesignPointOfMeasure.Unit.CM, tolerance_plus="1", tolerance_minus="1")
    DesignPOMValue.objects.create(point=point, size=size, value="53")
    DesignMaterial.objects.create(version=version, symbolic_ref=f"{prefix}-MAT-01", role="main_body", name="Cotton jersey", composition="100% cotton", gsm="180")

    pattern_media = media(designer, f"{prefix}-pattern-M.dxf", mime="application/dxf")
    techpack_media = media(designer, f"{prefix}-techpack.pdf")
    threed_media = media(designer, f"{prefix}-source.glb", mime="model/gltf-binary")
    technical_media = media(designer, f"{prefix}-construction.pdf")
    image_media = media(designer, f"{prefix}-product.png", access=MediaAsset.Access.PUBLIC, mime="image/png")
    pattern = DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.PATTERN, media_asset=pattern_media, label="M pattern", size_label="M")
    DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.TECH_PACK, media_asset=techpack_media, label="Tech pack")
    DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.THREE_D, media_asset=threed_media, label="3D")
    DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.TECHNICAL, media_asset=technical_media, label="Construction")
    image_asset = DesignAsset.objects.create(version=version, kind=DesignAsset.Kind.PRODUCT_IMAGE, media_asset=image_media, label="Product")
    DesignPatternRequirement.objects.create(version=version, size=size, required=True, declared_scale_1_to_1=True, pattern_asset=pattern)
    colorway = DesignColorway.objects.create(version=version, symbolic_ref=f"{prefix}-CW-BLK", name="Black", hex_color="#000000")
    DesignColorwayImage.objects.create(colorway=colorway, asset=image_asset, role=DesignColorwayImage.Role.PRODUCT_DETAIL)

    zone = None
    if purchase_kind != CartItem.Kind.PLAIN:
        method = DecorationZone.Method.EMBROIDERY if purchase_kind == CartItem.Kind.STUDIO else DecorationZone.Method.PRINT
        allowed = [DecorationZone.ProductionMethod.EMBROIDERY] if purchase_kind == CartItem.Kind.STUDIO else [DecorationZone.ProductionMethod.DTF]
        zone = DecorationZone.objects.create(
            version=version,
            symbolic_ref=f"{prefix}-DZ-FRONT",
            name="Front",
            surface="FRONT",
            method=method,
            allowed_methods=allowed,
            placement={"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.5},
            max_width_mm="300",
            max_height_mm="380",
        )

    artwork = Artwork.objects.create(organization=designer_org, title=f"{prefix} artwork", status=Artwork.Status.APPROVED, created_by=designer)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, intended_methods=["dtf", "embroidery"], created_by=designer)
    artwork_source_media = media(designer, f"{prefix}-artwork.svg", mime="image/svg+xml")
    artwork_source = ArtworkAsset.objects.create(version=artwork_version, kind=ArtworkAsset.Kind.SOURCE, media_asset=artwork_source_media, label="Artwork source")
    designed = DesignedProduct.objects.create(organization=designer_org, garment_version=version, artwork_version=artwork_version, title=f"{prefix} designed", status=DesignedProduct.Status.PUBLISHED, created_by=designer)
    if purchase_kind == CartItem.Kind.READY_DESIGNED:
        ArtworkPlacement.objects.create(product=designed, decoration_zone=zone, production_method=ArtworkPlacement.ProductionMethod.DTF, transform={"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.5, "rotation": 0})

    storefront = Storefront.objects.create(organization=designer_org, slug=f"{prefix}-store", status=Storefront.Status.PUBLISHED, name_en=f"{prefix} Store")
    product = StoreProduct.objects.create(storefront=storefront, designed_product=designed, slug=f"{prefix}-product", status=StoreProduct.Status.PUBLISHED, title_en=f"{prefix} Product", base_price=Decimal("500"), currency="EGP", customization_enabled=(purchase_kind == CartItem.Kind.STUDIO))
    variant = ProductVariant.objects.create(product=product, sku=f"{prefix.upper()}-M", size="M", color_name="Black")
    return designer, designer_org, version, product, variant, artwork_source


def order_line(prefix, *, purchase_kind=CartItem.Kind.PLAIN, production_validated=True):
    customer = user(f"{prefix}-customer")
    designer, designer_org, version, product, variant, artwork_source = complete_product(prefix, purchase_kind=purchase_kind, production_validated=production_validated)
    cart = Cart.objects.create(customer=customer, guest_key_hash="")
    checkout = CheckoutSession.objects.create(customer=customer, cart=cart, status=CheckoutSession.Status.PLACED, subtotal=Decimal("500"), total=Decimal("500"), currency="EGP", shipping_name="Customer", shipping_phone="01000000000", shipping_address1="1 Main St", shipping_city="Cairo", shipping_country="EG")
    purchase = CustomerPurchase.objects.create(checkout=checkout, customer=customer, status=CustomerPurchase.Status.CONFIRMED, payment_method=CustomerPurchase.PaymentMethod.COD, subtotal=Decimal("500"), total=Decimal("500"), currency="EGP", shipping_snapshot={"name": "Customer", "phone": "01000000000", "address1": "1 Main St", "city": "Cairo", "country": "EG"})
    order = CustomerOrder.objects.create(checkout=None, purchase=purchase, customer=customer, designer_organization=designer_org, status=CustomerOrder.Status.CONFIRMED, payment_method=CustomerOrder.PaymentMethod.COD, subtotal=Decimal("500"), total=Decimal("500"), currency="EGP", shipping_snapshot=purchase.shipping_snapshot)
    production_snapshot = {
        "product_type": purchase_kind,
        "store_product_id": product.pk,
        "designed_product_id": product.designed_product_id,
        "garment_design_id": version.design_id,
        "garment_version_id": version.pk,
        "variant_id": variant.pk,
        "sku": variant.sku,
        "size": "M",
        "color_name": "Black",
        "quantity": 1,
    }
    customization_snapshot = {}
    if purchase_kind == CartItem.Kind.READY_DESIGNED:
        production_snapshot["artwork_id"] = product.designed_product.artwork_version.artwork_id
        production_snapshot["artwork_version_id"] = product.designed_product.artwork_version_id
        production_snapshot["placements"] = [{"decoration_zone_id": product.designed_product.placements.get().decoration_zone_id, "production_method": "dtf", "transform": product.designed_product.placements.get().transform}]
    elif purchase_kind == CartItem.Kind.STUDIO:
        customization_snapshot = {"enabled": True, "elements": [{"kind": "text", "zone_id": zone_id(product), "production_method": "embroidery", "text": "FABINZI", "transform": {"x": 0.5, "y": 0.5, "scale": 0.2, "rotation": 0}}]}
        production_snapshot["customization"] = customization_snapshot
    item = OrderItem.objects.create(order=order, store_product=product, variant=variant, purchase_kind=purchase_kind, sku=variant.sku, title=product.title_en, size="M", color_name="Black", unit_price=Decimal("500"), quantity=1, line_total=Decimal("500"), pricing_snapshot={"unit_customer_price": "500.00"}, production_snapshot=production_snapshot, customization_snapshot=customization_snapshot)
    job, fulfillment = start_order_operations(order=order, actor=customer)
    return {"customer": customer, "designer": designer, "designer_org": designer_org, "version": version, "product": product, "variant": variant, "purchase": purchase, "order": order, "item": item, "job": job, "fulfillment": fulfillment, "artwork_source": artwork_source}


def zone_id(product):
    return product.designed_product.garment_version.decoration_zones.get().pk


def manufacturer(prefix, canonical_codes, *, status=Organization.VerificationStatus.ACTIVE, approved=True, listing_status=ManufacturerListing.Status.DRAFT):
    ensure_v2_3_reference_rows()
    owner = user(f"{prefix}-manufacturer")
    organization = org(owner, kind=Organization.Kind.MANUFACTURER, name=f"{prefix} Factory", status=status, approved=approved)
    listing = ManufacturerListing.objects.create(organization=organization, status=listing_status, accepts_rfq=False)
    for index, code in enumerate(canonical_codes):
        cap = ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.OTHER, name=f"Explicit capability {index}-{code}", is_active=True)
        ManufacturerCapabilityVerification.objects.create(capability=cap, canonical_code=code, status=ManufacturerCapabilityVerification.Status.VERIFIED, verified_at=timezone.now())
    if status == Organization.VerificationStatus.ACTIVE and approved:
        ensure_subscription_for_organization(organization)
    return owner, organization, listing
