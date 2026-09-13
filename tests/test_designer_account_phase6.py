import io

import pytest
import requests
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.integrations.models import IntegrationConfig
from apps.media.models import MediaAsset
from apps.media.designer_public_services import (
    STORE_PRODUCT_PURPOSE,
    create_designer_store_product_image,
    designer_public_image_eligible,
    designer_store_product_image_eligible,
)
from apps.organizations.models import Membership, Organization
from apps.storefront.designer_services import detach_product_image, set_primary_product_image
from apps.storefront.models import StoreProduct, StoreProductImage
from apps.storefront.services import (
    PRODUCT_GALLERY_ERROR,
    add_product_image,
    add_variant,
    create_store_product,
    create_storefront,
    publish_store_product,
    publish_storefront,
)

User = get_user_model()


def _bytes(fmt="PNG", size=(8, 8)):
    stream = io.BytesIO()
    Image.new("RGB", size, (140, 60, 180)).save(stream, format=fmt)
    return stream.getvalue()


def _upload(fmt="PNG", name=None, payload=None):
    ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(fmt, "bin")
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(fmt, "application/octet-stream")
    return SimpleUploadedFile(name or f"product.{ext}", payload if payload is not None else _bytes(fmt), content_type=mime)


def _catalog(prefix="phase6"):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password12345")
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=f"{prefix} Atelier",
        email=f"{prefix}@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER, is_active=True)
    design = GarmentDesign.objects.create(
        organization=org,
        title=f"{prefix} Garment",
        status=GarmentDesign.Status.APPROVED,
        created_by=owner,
    )
    garment_version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        status=GarmentDesignVersion.Status.APPROVED,
        created_by=owner,
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
        garment_version=garment_version,
        artwork_version=artwork_version,
        title=f"{prefix} Product Definition",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )
    store = create_storefront(
        organization=org,
        actor=owner,
        slug=f"{prefix}-store",
        name_en=f"{prefix} Store",
    )
    product = create_store_product(
        storefront=store,
        actor=owner,
        designed_product=designed,
        slug=f"{prefix}-product",
        title_en=f"{prefix} Product",
        base_price="500.00",
    )
    add_variant(product=product, actor=owner, sku=f"{prefix.upper()}-M", size="M")
    return owner, org, store, product


def _classified_media(*, org, product, actor, key, access=MediaAsset.Access.PUBLIC, metadata=None):
    public_url = f"https://imagedelivery.net/browser/{key}/public"
    contract = {
        "organization_id": org.pk,
        "store_product_id": product.pk,
        "actor_id": actor.pk,
        "purpose": STORE_PRODUCT_PURPOSE,
        "designer_store_product_upload": True,
        "public_url": public_url,
        "validated_format": "png",
        "width": 8,
        "height": 8,
        "checksum_sha256": key.rjust(64, "0")[-64:],
    }
    if metadata is not None:
        contract = metadata
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.CLOUDFLARE_IMAGES,
        provider_asset_id=f"provider-{key}",
        original_filename=f"{key}.png",
        mime_type="image/png",
        size_bytes=100,
        checksum_sha256=key.rjust(64, "0")[-64:],
        access=access,
        uploaded_by=actor,
        metadata=contract,
    )


def _cloudflare(monkeypatch, *, response=None):
    from apps.media import designer_public_services as media_service
    IntegrationConfig.objects.update_or_create(
        provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES,
        defaults={"enabled": True, "config": {"account_id": "a" * 32}},
    )
    monkeypatch.setattr(IntegrationConfig, "get_secrets", lambda self: {"api_token": "phase6-test-token"})

    class Response:
        ok = True
        def json(self):
            return response or {
                "success": True,
                "result": {
                    "id": "phase6-provider-image",
                    "requireSignedURLs": False,
                    "variants": ["https://imagedelivery.net/browser/phase6-provider-image/public"],
                },
            }

    post_calls = []
    delete_calls = []

    def post(*args, **kwargs):
        post_calls.append((args, kwargs))
        return Response()

    class DeleteResponse:
        ok = True
        def json(self):
            return {"success": True}

    def delete(*args, **kwargs):
        delete_calls.append((args, kwargs))
        return DeleteResponse()

    monkeypatch.setattr(media_service.requests, "post", post)
    monkeypatch.setattr(media_service.requests, "delete", delete)
    return post_calls, delete_calls


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fmt", "expected_mime", "expected_format"),
    [("PNG", "image/png", "png"), ("JPEG", "image/jpeg", "jpg"), ("WEBP", "image/webp", "webp")],
)
def test_phase6_direct_upload_accepts_valid_decoded_formats_and_persists_contract(monkeypatch, fmt, expected_mime, expected_format):
    owner, org, _store, product = _catalog(f"valid-{fmt.lower()}")
    post_calls, delete_calls = _cloudflare(monkeypatch)

    asset, relation = create_designer_store_product_image(
        upload=_upload(fmt), product=product, organization=org, actor=owner, alt_en="Front product photo"
    )

    assert len(post_calls) == 1
    assert delete_calls == []
    assert relation.product_id == product.pk
    assert relation.sort_order == 0
    assert asset.access == MediaAsset.Access.PUBLIC
    assert asset.mime_type == expected_mime
    assert asset.metadata["organization_id"] == org.pk
    assert asset.metadata["store_product_id"] == product.pk
    assert asset.metadata["actor_id"] == owner.pk
    assert asset.metadata["purpose"] == STORE_PRODUCT_PURPOSE
    assert asset.metadata["designer_store_product_upload"] is True
    assert asset.metadata["validated_format"] == expected_format
    assert asset.metadata["width"] == 8 and asset.metadata["height"] == 8
    assert asset.metadata["checksum_sha256"] == asset.checksum_sha256
    assert asset.metadata["public_url"].startswith("https://imagedelivery.net/")
    assert "phase6-test-token" not in str(asset.metadata)
    assert designer_store_product_image_eligible(asset, org) is True
    assert designer_public_image_eligible(asset, org) is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "upload",
    [None, SimpleUploadedFile("empty.png", b"", content_type="image/png"), _upload("PNG", name="forged.png", payload=b"not-an-image")],
)
def test_phase6_pre_provider_invalid_uploads_make_no_provider_request(monkeypatch, upload):
    owner, org, _store, product = _catalog("invalid-pre")
    post_calls, delete_calls = _cloudflare(monkeypatch)
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=upload, product=product, organization=org, actor=owner)
    assert post_calls == []
    assert delete_calls == []
    assert product.images.count() == 0


@pytest.mark.django_db
def test_phase6_oversized_and_decompression_bomb_reject_before_provider(monkeypatch):
    owner, org, _store, product = _catalog("invalid-size")
    post_calls, _delete_calls = _cloudflare(monkeypatch)
    oversized = SimpleUploadedFile("huge.png", b"x" * (10 * 1024 * 1024 + 1), content_type="image/png")
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=oversized, product=product, organization=org, actor=owner)
    assert post_calls == []

    from apps.media import manufacturer_public_services as validator_module
    monkeypatch.setattr(validator_module.Image, "open", lambda *_a, **_k: (_ for _ in ()).throw(Image.DecompressionBombError("bomb")))
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload("PNG"), product=product, organization=org, actor=owner)
    assert post_calls == []


@pytest.mark.django_db
def test_phase6_missing_disabled_invalid_integration_make_no_provider_request(monkeypatch):
    from apps.media import designer_public_services as media_service
    owner, org, _store, product = _catalog("integration")
    calls = []
    monkeypatch.setattr(media_service.requests, "post", lambda *a, **k: calls.append((a, k)))

    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=owner)
    assert calls == []

    IntegrationConfig.objects.create(
        provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES, enabled=False, config={"account_id": "a" * 32}
    )
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=owner)
    assert calls == []

    row = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES)
    row.enabled = True
    row.config = {"account_id": "bad"}
    row.save(update_fields=["enabled", "config"])
    monkeypatch.setattr(IntegrationConfig, "get_secrets", lambda self: {"api_token": "token"})
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=owner)
    assert calls == []


@pytest.mark.django_db
def test_phase6_provider_failures_are_controlled_and_malformed_delivery_is_compensated(monkeypatch):
    from apps.media import designer_public_services as media_service
    owner, org, _store, product = _catalog("provider-failure")
    _cloudflare(monkeypatch)
    delete_calls = []
    monkeypatch.setattr(media_service.requests, "delete", lambda *a, **k: delete_calls.append((a, k)))

    monkeypatch.setattr(media_service.requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("timeout")))
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=owner)
    assert delete_calls == [] and product.images.count() == 0

    class BadDelivery:
        ok = True
        def json(self):
            return {"success": True, "result": {"id": "created-id", "requireSignedURLs": False, "variants": ["https://evil.test/x"]}}
    class DeleteOk:
        ok = True
        def json(self):
            return {"success": True}
    monkeypatch.setattr(media_service.requests, "post", lambda *a, **k: BadDelivery())
    monkeypatch.setattr(media_service.requests, "delete", lambda *a, **k: (delete_calls.append((a, k)) or DeleteOk()))
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=owner)
    assert len(delete_calls) == 1
    assert product.images.count() == 0


@pytest.mark.django_db
def test_phase6_post_provider_audit_failure_rolls_back_and_compensates(monkeypatch):
    from apps.storefront import services as store_services
    owner, org, _store, product = _catalog("audit-rollback")
    _post_calls, delete_calls = _cloudflare(monkeypatch)
    before = MediaAsset.objects.count()
    monkeypatch.setattr(store_services, "record_audit_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))

    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=owner)

    assert MediaAsset.objects.count() == before
    assert product.images.count() == 0
    assert len(delete_calls) == 1


@pytest.mark.django_db
def test_phase6_compensation_failure_keeps_database_clean_and_logs_safely(monkeypatch, caplog):
    from apps.media import designer_public_services as media_service
    from apps.storefront import services as store_services
    owner, org, _store, product = _catalog("cleanup-failure")
    _cloudflare(monkeypatch)
    before = MediaAsset.objects.count()
    monkeypatch.setattr(store_services, "record_audit_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    monkeypatch.setattr(media_service.requests, "delete", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("delete timeout")))

    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=owner)

    assert MediaAsset.objects.count() == before
    assert product.images.count() == 0
    assert "cleanup failed organization=" in caplog.text
    assert "phase6-test-token" not in caplog.text
    assert "phase6-provider-image" not in caplog.text


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGN_MANAGER])
def test_phase6_store_editor_roles_can_attach_explicit_product_media(role):
    owner, org, _store, product = _catalog(f"role-{role}")
    actor = owner
    if role != Membership.Role.OWNER:
        actor = User.objects.create_user(username=f"role-{role}-actor", password="password12345")
        Membership.objects.create(organization=org, user=actor, role=role, is_active=True)
    media = _classified_media(org=org, product=product, actor=actor, key=f"allow-{role}")
    relation = add_product_image(product=product, actor=actor, media_asset=media)
    assert relation.product_id == product.pk


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Membership.Role.DESIGNER, Membership.Role.ACCOUNTANT])
def test_phase6_non_store_editor_roles_are_denied_before_provider(monkeypatch, role):
    owner, org, _store, product = _catalog(f"deny-{role}")
    actor = User.objects.create_user(username=f"deny-{role}-actor", password="password12345")
    Membership.objects.create(organization=org, user=actor, role=role, is_active=True)
    post_calls, _delete_calls = _cloudflare(monkeypatch)
    with pytest.raises(PermissionDenied):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=actor)
    assert post_calls == []


@pytest.mark.django_db
def test_phase6_nonmember_cross_tenant_and_published_uploads_fail_before_provider(monkeypatch):
    owner, org, _store, product = _catalog("tenant-a")
    other_owner, other_org, _other_store, other_product = _catalog("tenant-b")
    outsider = User.objects.create_user(username="phase6-outsider", password="password12345")
    post_calls, _delete_calls = _cloudflare(monkeypatch)

    with pytest.raises(PermissionDenied):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=outsider)
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=other_org, actor=other_owner)
    product.status = StoreProduct.Status.PUBLISHED
    product.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        create_designer_store_product_image(upload=_upload(), product=product, organization=org, actor=owner)
    assert post_calls == []
    assert other_product.images.count() == 0


@pytest.mark.django_db
def test_phase6_unrelated_private_cross_tenant_and_profile_media_cannot_attach_or_publish():
    owner, org, store, product = _catalog("contract-a")
    other_owner, other_org, _other_store, other_product = _catalog("contract-b")
    publish_storefront(storefront=store, actor=owner)

    invalid = [
        _classified_media(org=org, product=product, actor=owner, key="generic", metadata={}),
        _classified_media(org=org, product=product, actor=owner, key="profile", metadata={"organization_id": org.pk, "purpose": "profile", "designer_public_upload": True}),
        _classified_media(org=org, product=product, actor=owner, key="cover", metadata={"organization_id": org.pk, "purpose": "cover", "designer_public_upload": True}),
        _classified_media(org=org, product=product, actor=owner, key="private", access=MediaAsset.Access.PRIVATE),
        _classified_media(org=other_org, product=other_product, actor=other_owner, key="other-tenant"),
    ]
    for media in invalid:
        with pytest.raises(ValidationError):
            add_product_image(product=product, actor=owner, media_asset=media)

    genuine = _classified_media(org=org, product=product, actor=owner, key="genuine")
    add_product_image(product=product, actor=owner, media_asset=genuine)
    legacy = invalid[0]
    StoreProductImage.objects.create(product=product, media_asset=legacy, sort_order=1)
    with pytest.raises(ValidationError, match="Every public gallery image"):
        publish_store_product(product=product, actor=owner)
    product.refresh_from_db()
    assert product.status == StoreProduct.Status.DRAFT


@pytest.mark.django_db
def test_phase6_order_primary_detach_and_publication_contract():
    owner, org, store, product = _catalog("ordering")
    first = _classified_media(org=org, product=product, actor=owner, key="first")
    second = _classified_media(org=org, product=product, actor=owner, key="second")
    first_row = add_product_image(product=product, actor=owner, media_asset=first)
    second_row = add_product_image(product=product, actor=owner, media_asset=second)
    assert list(product.images.order_by("sort_order", "id").values_list("media_asset_id", flat=True)) == [first.pk, second.pk]

    set_primary_product_image(product=product, actor=owner, image_id=second_row.pk)
    assert list(product.images.order_by("sort_order", "id").values_list("sort_order", flat=True)) == [0, 1]
    assert product.images.order_by("sort_order", "id").first().media_asset_id == second.pk

    detach_product_image(product=product, actor=owner, image_id=first_row.pk)
    assert MediaAsset.objects.filter(pk=first.pk).exists()
    assert list(product.images.values_list("sort_order", flat=True)) == [0]

    publish_storefront(storefront=store, actor=owner)
    publish_store_product(product=product, actor=owner)
    product.refresh_from_db()
    assert product.status == StoreProduct.Status.PUBLISHED
    assert product.images.first().media_asset_id == second.pk
    with pytest.raises(ValidationError):
        add_product_image(product=product, actor=owner, media_asset=first)
    with pytest.raises(ValidationError):
        set_primary_product_image(product=product, actor=owner, image_id=second_row.pk)
    with pytest.raises(ValidationError):
        detach_product_image(product=product, actor=owner, image_id=second_row.pk)


@pytest.mark.django_db
def test_phase6_legacy_only_gallery_cannot_publish_and_legacy_cannot_be_primary():
    owner, org, store, product = _catalog("legacy")
    publish_storefront(storefront=store, actor=owner)
    legacy = _classified_media(org=org, product=product, actor=owner, key="legacy-only", metadata={})
    legacy_row = StoreProductImage.objects.create(product=product, media_asset=legacy, sort_order=0)
    with pytest.raises(ValidationError):
        publish_store_product(product=product, actor=owner)
    with pytest.raises(ValidationError):
        set_primary_product_image(product=product, actor=owner, image_id=legacy_row.pk)


@pytest.mark.django_db
def test_phase6_product_media_isolated_from_profile_picker_and_profile_media_still_eligible():
    owner, org, _store, product = _catalog("profile-isolation")
    product_media = _classified_media(org=org, product=product, actor=owner, key="product-photo")
    profile_media = _classified_media(
        org=org,
        product=product,
        actor=owner,
        key="profile-photo",
        metadata={"organization_id": org.pk, "purpose": "profile", "designer_public_upload": True, "public_url": "https://imagedelivery.net/browser/profile/public"},
    )
    assert designer_public_image_eligible(product_media, org) is False
    assert designer_public_image_eligible(profile_media, org) is True
