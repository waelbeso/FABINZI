import base64

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion, DesignedProduct
from apps.artwork.public import public_artwork_queryset
from apps.checkout.models import CartItem, CustomerPurchase
from apps.checkout.services import add_cart_item, create_cart_checkout, get_active_cart, place_cart_purchase, update_checkout_shipping
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.integrations.models import IntegrationConfig
from apps.media.models import MediaAsset
from apps.media.services import create_private_studio_image
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomizationElement, StoreProduct, StudioProject
from apps.storefront.services import (
    add_customization_element,
    add_product_image,
    add_variant,
    create_store_product,
    create_storefront,
    create_studio_project,
    enable_customization,
    mark_project_ready,
    normalize_transform,
    publish_store_product,
    publish_storefront,
    update_customization_element,
    validate_studio_project,
)

User = get_user_model()
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
)


def image_upload(name="private.png"):
    return SimpleUploadedFile(name, PNG_1X1, content_type="image/png")


def build_catalog(prefix="creative", *, stock=False, stock_quantity=5, artwork_status=Artwork.Status.APPROVED, version_status=ArtworkVersion.Status.APPROVED):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password12345")
    customer = User.objects.create_user(username=f"{prefix}-customer", password="password12345")
    other = User.objects.create_user(username=f"{prefix}-other", password="password12345")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name=f"{prefix} Studio", email=f"{prefix}@test.local", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    design = GarmentDesign.objects.create(organization=org, title=f"{prefix} Tee", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment = GarmentDesignVersion.objects.create(design=design, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    zone = DecorationZone.objects.create(version=garment, name="Front", method=DecorationZone.Method.BOTH, placement={"x": .45, "y": .35}, max_width_mm=240, max_height_mm=300)
    print_zone = DecorationZone.objects.create(version=garment, name="Sleeve", method=DecorationZone.Method.PRINT, placement={"x": .75, "y": .3}, max_width_mm=100, max_height_mm=120)
    other_garment = GarmentDesignVersion.objects.create(design=design, version_number=2, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    wrong_zone = DecorationZone.objects.create(version=other_garment, name="Wrong version", method=DecorationZone.Method.BOTH, placement={"x": .5, "y": .5})

    artwork = Artwork.objects.create(organization=org, title=f"{prefix} Lines", description="Approved creative work", tags=["line", "modern"], status=artwork_status, created_by=owner)
    version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        status=version_status,
        production_notes="INTERNAL production note",
        review_notes="INTERNAL review note",
        metadata={
            "suitable_for_print": True,
            "suitable_for_embroidery": True,
            "public_production_methods": ["print", "embroidery"],
            "public_suitability": ["t-shirt", "hoodie"],
            "public_product_types": ["apparel"],
            "secret_license_evidence": "DO NOT EXPOSE",
            "royalty_percent": "99.9",
        },
        created_by=owner,
    )
    preview = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="/static/demo/artwork-cairo-lines.svg", original_filename="artwork.svg", mime_type="image/svg+xml", size_bytes=100, access=MediaAsset.Access.PUBLIC, uploaded_by=owner, metadata={"public_url": "/static/demo/artwork-cairo-lines.svg"})
    ArtworkAsset.objects.create(version=version, kind=ArtworkAsset.Kind.PREVIEW, media_asset=preview)

    designed = DesignedProduct.objects.create(organization=org, garment_version=garment, artwork_version=version, title=f"{prefix} Product", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = create_storefront(organization=org, actor=owner, slug=f"{prefix}-store", name_en=f"{prefix} Store", name_ar=f"متجر {prefix}")
    publish_storefront(storefront=store, actor=owner)
    product = create_store_product(
        storefront=store,
        actor=owner,
        designed_product=designed,
        slug=f"{prefix}-tee",
        title_en=f"{prefix} Tee",
        title_ar=f"تيشيرت {prefix}",
        base_price="500.00",
        customization_enabled=True,
        fulfillment_mode=StoreProduct.FulfillmentMode.STOCK if stock else StoreProduct.FulfillmentMode.MADE_TO_ORDER,
    )
    variant = add_variant(product=product, actor=owner, sku=f"{prefix.upper()}-M", size="M", color_name="Black", stock_quantity=stock_quantity if stock else None)
    garment_image = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="/static/demo/garment-mens-tshirt.svg", original_filename="tee.svg", mime_type="image/svg+xml", size_bytes=100, access=MediaAsset.Access.PUBLIC, uploaded_by=owner, metadata={"public_url": "/static/demo/garment-mens-tshirt.svg"})
    add_product_image(product=product, actor=owner, media_asset=garment_image, alt_en=product.title_en, alt_ar=product.title_ar)
    publish_store_product(product=product, actor=owner)
    return {
        "owner": owner, "customer": customer, "other": other, "org": org, "garment": garment,
        "zone": zone, "print_zone": print_zone, "wrong_zone": wrong_zone, "artwork": artwork,
        "version": version, "preview": preview, "designed": designed, "store": store,
        "product": product, "variant": variant,
    }


def draft_with_text(data, *, text="FABINZI", transform=None, method="print"):
    project = create_studio_project(customer=data["customer"], product=data["product"], variant=data["variant"], quantity=1)
    customization = enable_customization(project=project, actor=data["customer"])
    element = add_customization_element(
        customization=customization,
        actor=data["customer"],
        decoration_zone=data["zone"],
        kind=CustomizationElement.Kind.TEXT,
        text=text,
        production_method=method,
        transform=transform or {"x": .5, "y": .5, "scale": .25, "rotation": 0},
    )
    return project, element


def draft_with_artwork(data, *, method="print", transform=None):
    project = create_studio_project(customer=data["customer"], product=data["product"], variant=data["variant"], quantity=1)
    customization = enable_customization(project=project, actor=data["customer"])
    element = add_customization_element(
        customization=customization,
        actor=data["customer"],
        decoration_zone=data["zone"],
        kind=CustomizationElement.Kind.ARTWORK,
        artwork_version=data["version"],
        production_method=method,
        transform=transform or {"x": .5, "y": .5, "scale": .3, "rotation": 0},
    )
    return project, element


def ready_artwork_project(data):
    project, element = draft_with_artwork(data)
    mark_project_ready(project=project, actor=data["customer"])
    project.refresh_from_db()
    return project, element


def enable_cod():
    cfg = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.COD)
    cfg.enabled = True
    cfg.save(update_fields=["enabled", "updated_at"])


def fill_shipping(session, customer):
    return update_checkout_shipping(session=session, actor=customer, shipping_name="Customer", shipping_phone="01000000000", shipping_address1="1 Main St", shipping_city="Cairo", shipping_country="EG")


@pytest.mark.django_db
def test_public_artwork_is_approved_only_and_suspended_or_rejected_is_invisible(client):
    approved = build_catalog("approved")
    suspended = build_catalog("suspended", artwork_status=Artwork.Status.SUSPENDED)
    rejected = build_catalog("rejected", version_status=ArtworkVersion.Status.REJECTED)
    ids = set(public_artwork_queryset().values_list("id", flat=True))
    assert approved["artwork"].pk in ids
    assert suspended["artwork"].pk not in ids
    assert rejected["artwork"].pk not in ids

    page = client.get(reverse("artwork"))
    assert approved["artwork"].title.encode() in page.content
    assert suspended["artwork"].title.encode() not in page.content
    assert rejected["artwork"].title.encode() not in page.content
    assert client.get(reverse("artwork-detail", args=[suspended["artwork"].pk])).status_code == 404


@pytest.mark.django_db
def test_public_artwork_api_whitelists_metadata_and_internal_review_fields(client):
    data = build_catalog("whitelist")
    response = client.get(reverse("v1:artwork-public"))
    assert response.status_code == 200
    payload = response.json()
    row = next(item for item in payload if item["id"] == data["artwork"].pk)
    assert set(row) == {"id", "title", "description", "tags", "designer", "approved_version_id", "preview", "production_methods", "suitability", "product_types", "updated_at"}
    serialized = str(row)
    assert "INTERNAL production note" not in serialized
    assert "INTERNAL review note" not in serialized
    assert "secret_license_evidence" not in serialized
    assert "royalty_percent" not in serialized


@pytest.mark.django_db
def test_private_customer_upload_never_appears_in_public_artwork_or_open_graph(client, tmp_path):
    data = build_catalog("privatepublic")
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = create_private_studio_image(upload=image_upload(), owner=data["customer"])
        public_page = client.get(reverse("artwork"))
        api = client.get(reverse("v1:artwork-public"))
        detail = client.get(reverse("artwork-detail", args=[data["artwork"].pk]))
    assert str(asset.pk).encode() not in public_page.content
    assert asset.provider_asset_id.encode() not in public_page.content
    assert asset.provider_asset_id not in str(api.json())
    assert asset.provider_asset_id.encode() not in detail.content
    assert b'property="og:image"' in detail.content
    assert b"studio-private/" not in detail.content


@pytest.mark.django_db
def test_private_media_route_enforces_owner_and_is_not_public_media_url(client, tmp_path):
    data = build_catalog("privateisolation")
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = create_private_studio_image(upload=image_upload(), owner=data["customer"])
        protected = reverse("private-studio-media", args=[asset.pk])
        anonymous = client.get(protected)
        assert anonymous.status_code == 302
        client.force_login(data["other"])
        assert client.get(protected).status_code == 404
        assert client.get(reverse("private-studio-media", args=[asset.pk + 9999])).status_code == 404
        client.force_login(data["customer"])
        owner_response = client.get(protected)
        assert owner_response.status_code == 200
        assert "no-store" in owner_response["Cache-Control"]
        assert "noindex" in owner_response["X-Robots-Tag"]
        assert owner_response["X-Content-Type-Options"] == "nosniff"
        direct_public = client.get(f"/media/{asset.provider_asset_id}")
        assert direct_public.status_code == 404


@pytest.mark.django_db
def test_another_customer_cannot_reference_private_media_asset_by_id(client, tmp_path):
    data = build_catalog("assetref")
    project, _ = draft_with_text(data)
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = create_private_studio_image(upload=image_upload(), owner=data["other"])
    client.force_login(data["customer"])
    response = client.post(
        reverse("v1:studio-element", args=[project.pk]),
        data={
            "kind": "image", "decoration_zone": data["zone"].pk, "media_asset": asset.pk,
            "production_method": "print", "rights_confirmed": True,
            "transform": {"x": .5, "y": .5, "scale": .25, "rotation": 0},
        },
        content_type="application/json",
    )
    assert response.status_code == 404
    assert not CustomizationElement.objects.filter(media_asset=asset, customization__project=project).exists()


@pytest.mark.django_db
def test_studio_project_ownership_isolated_in_web_and_api(client):
    data = build_catalog("projectowner")
    project, _ = draft_with_text(data)
    client.force_login(data["other"])
    assert client.get(reverse("studio-project", args=[project.pk])).status_code == 403
    assert client.get(reverse("v1:studio-project-detail", args=[project.pk])).status_code == 403


@pytest.mark.django_db
def test_artwork_source_must_remain_approved_and_eligible():
    data = build_catalog("eligibility")
    project, element = draft_with_artwork(data, method="embroidery")
    assert validate_studio_project(project)["valid"] is True
    data["artwork"].status = Artwork.Status.SUSPENDED
    data["artwork"].save(update_fields=["status", "updated_at"])
    with pytest.raises(ValidationError):
        validate_studio_project(project)
    data["artwork"].status = Artwork.Status.APPROVED
    data["artwork"].save(update_fields=["status", "updated_at"])
    element.production_method = "print"
    element.save(update_fields=["production_method"])
    assert validate_studio_project(project)["valid"] is True


@pytest.mark.django_db
def test_transform_normalizes_persists_reload_and_validates_move_resize_rotate():
    data = build_catalog("transform")
    project, element = draft_with_text(data)
    updated = update_customization_element(element=element, actor=data["customer"], transform={"x": "0.47", "y": .53, "scale": .22, "rotation": 390})
    assert updated.transform == {"x": .47, "y": .53, "scale": .22, "rotation": 30.0}
    element.refresh_from_db()
    assert element.transform == updated.transform
    project.refresh_from_db()
    assert validate_studio_project(project)["valid"] is True
    assert normalize_transform({"x": .5, "y": .5, "scale": .2, "rotation": -540})["rotation"] == -180.0


@pytest.mark.django_db
def test_out_of_bounds_transform_is_rejected_without_persisting_invalid_state():
    data = build_catalog("bounds")
    _, element = draft_with_text(data)
    before = dict(element.transform)
    with pytest.raises(ValidationError):
        update_customization_element(element=element, actor=data["customer"], transform={"x": .95, "y": .5, "scale": .4, "rotation": 45})
    element.refresh_from_db()
    assert element.transform == before


@pytest.mark.django_db
def test_decoration_zone_must_match_current_product_garment_version():
    data = build_catalog("zoneversion")
    project = create_studio_project(customer=data["customer"], product=data["product"], variant=data["variant"])
    customization = enable_customization(project=project, actor=data["customer"])
    with pytest.raises(ValidationError):
        add_customization_element(customization=customization, actor=data["customer"], decoration_zone=data["wrong_zone"], kind=CustomizationElement.Kind.TEXT, text="Wrong", production_method="print")


@pytest.mark.django_db
def test_production_method_intersection_and_invalid_method_rejection():
    data = build_catalog("methods")
    project = create_studio_project(customer=data["customer"], product=data["product"], variant=data["variant"])
    customization = enable_customization(project=project, actor=data["customer"])
    with pytest.raises(ValidationError):
        add_customization_element(customization=customization, actor=data["customer"], decoration_zone=data["print_zone"], kind=CustomizationElement.Kind.ARTWORK, artwork_version=data["version"], production_method="embroidery")
    with pytest.raises(ValidationError):
        add_customization_element(customization=customization, actor=data["customer"], decoration_zone=data["zone"], kind=CustomizationElement.Kind.TEXT, text="Bad", production_method="laser")
    valid = add_customization_element(customization=customization, actor=data["customer"], decoration_zone=data["print_zone"], kind=CustomizationElement.Kind.ARTWORK, artwork_version=data["version"], production_method="print", transform={"x": .5, "y": .5, "scale": .2, "rotation": 0})
    assert valid.production_method == "print"


@pytest.mark.django_db
def test_private_upload_rights_confirmation_is_required(client, tmp_path):
    data = build_catalog("rights")
    project = create_studio_project(customer=data["customer"], product=data["product"], variant=data["variant"])
    customization = enable_customization(project=project, actor=data["customer"])
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = create_private_studio_image(upload=image_upload(), owner=data["customer"])
    with pytest.raises(ValidationError):
        add_customization_element(customization=customization, actor=data["customer"], decoration_zone=data["zone"], kind=CustomizationElement.Kind.IMAGE, media_asset=asset, production_method="print", rights_confirmed=False)
    element = add_customization_element(customization=customization, actor=data["customer"], decoration_zone=data["zone"], kind=CustomizationElement.Kind.IMAGE, media_asset=asset, production_method="print", rights_confirmed=True, transform={"x": .5, "y": .5, "scale": .2, "rotation": 0})
    assert element.rights_confirmed is True

    client.force_login(data["customer"])
    api_false = client.post(reverse("v1:studio-element", args=[project.pk]), data={"kind": "image", "decoration_zone": data["zone"].pk, "media_asset": asset.pk, "production_method": "print", "rights_confirmed": "false", "transform": {"x": .5, "y": .5, "scale": .2, "rotation": 0}}, content_type="application/json")
    assert api_false.status_code == 400


@pytest.mark.django_db
def test_ready_requires_valid_element_and_revocation_product_or_variant_changes_block_ready():
    empty = build_catalog("emptyready")
    project = create_studio_project(customer=empty["customer"], product=empty["product"], variant=empty["variant"])
    enable_customization(project=project, actor=empty["customer"])
    with pytest.raises(ValidationError):
        mark_project_ready(project=project, actor=empty["customer"])

    revoked = build_catalog("revokedready")
    project, _ = draft_with_artwork(revoked)
    revoked["artwork"].status = Artwork.Status.SUSPENDED
    revoked["artwork"].save(update_fields=["status", "updated_at"])
    with pytest.raises(ValidationError):
        mark_project_ready(project=project, actor=revoked["customer"])

    unpublished = build_catalog("unpublishedready")
    project, _ = draft_with_text(unpublished)
    unpublished["product"].status = StoreProduct.Status.HIDDEN
    unpublished["product"].save(update_fields=["status", "updated_at"])
    with pytest.raises(ValidationError):
        mark_project_ready(project=project, actor=unpublished["customer"])

    inactive = build_catalog("inactiveready")
    project, _ = draft_with_text(inactive)
    inactive["variant"].is_active = False
    inactive["variant"].save(update_fields=["is_active"])
    with pytest.raises(ValidationError):
        mark_project_ready(project=project, actor=inactive["customer"])

    stock = build_catalog("stockready", stock=True, stock_quantity=1)
    project, _ = draft_with_text(stock)
    stock["variant"].stock_quantity = 0
    stock["variant"].save(update_fields=["stock_quantity"])
    with pytest.raises(ValidationError):
        mark_project_ready(project=project, actor=stock["customer"])


@pytest.mark.django_db
def test_studio_ready_enters_existing_cart_without_manufacturer_dependency():
    data = build_catalog("cartstudio")
    project, _ = ready_artwork_project(data)
    item = add_cart_item(customer=data["customer"], product=data["product"], variant=data["variant"], quantity=1, kind=CartItem.Kind.STUDIO, studio_project=project)
    assert item.cart == get_active_cart(data["customer"])
    assert item.studio_project == project
    assert item.kind == CartItem.Kind.STUDIO


@pytest.mark.django_db
def test_stale_state_is_revalidated_before_checkout_and_again_before_purchase():
    data = build_catalog("stale")
    project, _ = ready_artwork_project(data)
    add_cart_item(customer=data["customer"], product=data["product"], variant=data["variant"], quantity=1, kind=CartItem.Kind.STUDIO, studio_project=project)
    cart = get_active_cart(data["customer"])

    data["artwork"].status = Artwork.Status.SUSPENDED
    data["artwork"].save(update_fields=["status", "updated_at"])
    with pytest.raises(ValidationError):
        create_cart_checkout(cart=cart, actor=data["customer"])
    assert CustomerPurchase.objects.filter(customer=data["customer"]).count() == 0

    data["artwork"].status = Artwork.Status.APPROVED
    data["artwork"].save(update_fields=["status", "updated_at"])
    session = fill_shipping(create_cart_checkout(cart=cart, actor=data["customer"]), data["customer"])
    data["variant"].is_active = False
    data["variant"].save(update_fields=["is_active"])
    enable_cod()
    with pytest.raises(ValidationError):
        place_cart_purchase(session=session, actor=data["customer"], payment_method="cod")
    assert CustomerPurchase.objects.filter(customer=data["customer"]).count() == 0


@pytest.mark.django_db
def test_place_order_recalculates_authoritative_variant_price():
    data = build_catalog("reprice")
    project, _ = ready_artwork_project(data)
    add_cart_item(customer=data["customer"], product=data["product"], variant=data["variant"], quantity=1, kind=CartItem.Kind.STUDIO, studio_project=project)
    cart = get_active_cart(data["customer"])
    session = fill_shipping(create_cart_checkout(cart=cart, actor=data["customer"]), data["customer"])
    assert session.total == 500
    StoreProduct.objects.filter(pk=data["product"].pk).update(base_price="625.00")
    enable_cod()
    purchase, _ = place_cart_purchase(session=session, actor=data["customer"], payment_method="cod")
    assert purchase.total == 625
    assert purchase.child_orders.get().item.unit_price == 625


@pytest.mark.django_db
def test_web_checkout_stale_customization_returns_friendly_path_to_studio(client):
    data = build_catalog("staleweb")
    project, _ = ready_artwork_project(data)
    add_cart_item(customer=data["customer"], product=data["product"], variant=data["variant"], quantity=1, kind=CartItem.Kind.STUDIO, studio_project=project)
    data["artwork"].status = Artwork.Status.SUSPENDED
    data["artwork"].save(update_fields=["status", "updated_at"])
    client.force_login(data["customer"])
    response = client.get(reverse("cart-checkout-start"), follow=True)
    assert response.redirect_chain[-1][0] == reverse("cart")
    assert b"needs attention" in response.content
    assert reverse("studio-project", args=[project.pk]).encode() in response.content


@pytest.mark.django_db
def test_public_private_seo_and_sitemap_boundaries(client, tmp_path):
    data = build_catalog("seoart")
    with override_settings(MEDIA_ROOT=tmp_path):
        private_asset = create_private_studio_image(upload=image_upload(), owner=data["customer"])
    robots = client.get(reverse("robots-txt")).content.decode()
    sitemap = client.get(reverse("sitemap-xml")).content.decode()
    detail_url = reverse("artwork-detail", args=[data["artwork"].pk])
    assert "Disallow: /studio/" in robots
    assert "Disallow: /media/private/" in robots
    assert detail_url in sitemap
    assert "/studio/" not in sitemap
    assert "/media/private/" not in sitemap
    assert private_asset.provider_asset_id not in sitemap

    detail = client.get(detail_url).content.decode()
    assert 'property="og:image"' in detail
    assert private_asset.provider_asset_id not in detail
    assert "studio-private/" not in detail


@pytest.mark.django_db
def test_suspended_artwork_is_removed_from_sitemap(client):
    data = build_catalog("sitemaprevoked")
    data["artwork"].status = Artwork.Status.SUSPENDED
    data["artwork"].save(update_fields=["status", "updated_at"])
    sitemap = client.get(reverse("sitemap-xml")).content.decode()
    assert reverse("artwork-detail", args=[data["artwork"].pk]) not in sitemap
