import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerListing
from apps.media.models import MediaAsset
from apps.organizations.models import (
    DesignerProfile,
    ManufacturerProfile,
    Membership,
    OnboardingApplication,
    Organization,
)
from apps.organizations.public_profile_services import (
    current_public_profile_data,
    save_public_profile_revision,
)
from apps.public_profiles.models import ProfessionalPublicState
from apps.public_profiles.services import ensure_public_state
from apps.storefront.models import StoreProduct, Storefront


User = get_user_model()


def _user(name):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="StrongPass123!",
    )


def _designer(owner, name="Phase 5 Designer"):
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=name,
        legal_name="PRIVATE LEGAL DESIGNER NAME",
        email="private-designer@example.test",
        phone="+201011111111",
        website="https://designer.example.test",
        address_line1="PRIVATE DESIGNER ADDRESS",
        city="Cairo",
        region="Cairo",
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(
        organization=org,
        user=owner,
        role=Membership.Role.OWNER,
        is_active=True,
    )
    DesignerProfile.objects.create(
        organization=org,
        studio_name=f"{name} Studio",
        portfolio_url="https://designer.example.test/portfolio",
        legal_registration_number="PRIVATE-REG-123",
        tax_number="PRIVATE-TAX-456",
        payout_information="PRIVATE-PAYOUT-MARKER",
        terms_accepted=True,
        terms_accepted_at=timezone.now(),
    )
    OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=timezone.now(),
    )
    state = ensure_public_state(org)
    state.public_name_en = "Approved Phase 5 Designer"
    state.public_name_ar = "مصمم المرحلة الخامسة المعتمد"
    state.bio_en = "Approved public Phase 5 biography."
    state.bio_ar = "نبذة عامة معتمدة للمرحلة الخامسة."
    state.specializations = [
        "Casualwear",
        "Streetwear",
        "T-Shirt Design",
        "Textile Prints",
        "Graphic Artwork",
        "Pattern Making",
        "Technical Fashion Drawing",
    ]
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    return org, state


def _manufacturer(owner):
    org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name="Phase 5 Regression Factory",
        email="private-factory@example.test",
        phone="+201022222222",
        city="Cairo",
        region="Cairo",
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(
        organization=org,
        user=owner,
        role=Membership.Role.OWNER,
        is_active=True,
    )
    ManufacturerProfile.objects.create(
        organization=org,
        commercial_registration="PRIVATE-MFR-REG",
        tax_number="PRIVATE-MFR-TAX",
        payout_information="PRIVATE-MFR-PAYOUT",
        terms_accepted=True,
        terms_accepted_at=timezone.now(),
    )
    OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=timezone.now(),
    )
    ManufacturerListing.objects.create(
        organization=org,
        headline_en="Approved production partner headline",
        overview_en="Approved public production overview.",
    )
    state = ensure_public_state(org)
    state.public_name_en = "Phase 5 Regression Factory"
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    return org, state


def _public_asset(owner, key, url, *, metadata=None):
    payload = {"public_url": url}
    if metadata:
        payload.update(metadata)
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=f"RAW-PROVIDER-ID-{key}",
        original_filename=f"{key}.png",
        mime_type="image/png",
        size_bytes=64,
        checksum_sha256="a" * 64,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=owner,
        metadata=payload,
    )


def _published_public_work(org, owner, prefix="phase5"):
    garment = GarmentDesign.objects.create(
        organization=org,
        title=f"{prefix} Garment",
        category="T-Shirt",
        status=GarmentDesign.Status.APPROVED,
        created_by=owner,
    )
    garment_version = GarmentDesignVersion.objects.create(
        design=garment,
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
    preview = _public_asset(
        owner,
        f"{prefix}-artwork-preview",
        "/static/brand/fabinzi-icon.svg",
    )
    ArtworkAsset.objects.create(
        version=artwork_version,
        kind=ArtworkAsset.Kind.PREVIEW,
        media_asset=preview,
        label="Approved public preview",
    )
    designed = DesignedProduct.objects.create(
        organization=org,
        garment_version=garment_version,
        artwork_version=artwork_version,
        title=f"{prefix} Ready Product",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )
    store = Storefront.objects.create(
        organization=org,
        slug=f"{prefix}-store",
        status=Storefront.Status.PUBLISHED,
        name_en=f"{prefix} Store",
    )
    product = StoreProduct.objects.create(
        storefront=store,
        designed_product=designed,
        slug=f"{prefix}-product",
        status=StoreProduct.Status.PUBLISHED,
        title_en=f"{prefix} Public Ready Product",
        title_ar="منتج عام جاهز",
        base_price="500.00",
        currency="EGP",
    )
    return garment, artwork, designed, store, product


@pytest.mark.django_db
def test_designer_directory_uses_only_approved_state_image_location_specializations_and_localized_name(client):
    owner = _user("phase5-directory-owner")
    org, state = _designer(owner)
    approved_profile = _public_asset(
        owner,
        "approved-profile",
        "https://imagedelivery.net/public/approved-profile/public",
        metadata={"organization_id": org.pk},
    )
    state.profile_image = approved_profile
    state.save(update_fields=["profile_image", "updated_at"])

    response = client.get(reverse("designer-directory") + "?lang=en")
    body = response.content.decode()

    assert response.status_code == 200
    card = response.context["designer_cards"][0]
    assert card["name"] == state.public_name_en
    assert card["location_parts"] == ["Cairo", "EG"]
    assert card["specializations"] == state.specializations
    assert card["profile_image_url"] == "https://imagedelivery.net/public/approved-profile/public"
    assert card["url"] == reverse("designer-public-detail", args=[state.slug])

    assert state.public_name_en in body
    assert "https://imagedelivery.net/public/approved-profile/public" in body
    assert "RAW-PROVIDER-ID-approved-profile" not in body
    for specialization in state.specializations:
        assert specialization in body
    for private_value in (
        org.email,
        org.phone,
        org.address_line1,
        org.legal_name,
        org.designer_profile.legal_registration_number,
        org.designer_profile.tax_number,
        "PRIVATE-PAYOUT-MARKER",
    ):
        assert private_value not in body

    arabic = client.get(reverse("designer-directory") + "?lang=ar")
    arabic_body = arabic.content.decode()
    assert state.public_name_ar in arabic_body
    assert f'{reverse("designer-public-detail", args=[state.slug])}?lang=ar' in arabic_body


@pytest.mark.django_db
def test_designer_directory_no_image_has_accessible_dsg_fallback(client):
    owner = _user("phase5-directory-fallback")
    _org, state = _designer(owner, "Fallback Designer")
    response = client.get(reverse("designer-directory") + "?lang=en")
    body = response.content.decode()

    assert response.status_code == 200
    assert 'data-public-image-fallback' in body
    assert ">DSG<" in body
    assert "Profile image unavailable for Approved Phase 5 Designer" in body
    assert "data-public-profile-image" not in body
    assert state.specializations[-1] in body


@pytest.mark.django_db
def test_pending_revision_name_bio_specializations_location_profile_and_cover_never_leak(client):
    owner = _user("phase5-pending-owner")
    org, state = _designer(owner, "Current Approved Designer")
    approved_profile = _public_asset(
        owner,
        "approved-current-profile",
        "https://imagedelivery.net/public/current-profile/public",
        metadata={"organization_id": org.pk},
    )
    approved_cover = _public_asset(
        owner,
        "approved-current-cover",
        "https://imagedelivery.net/public/current-cover/public",
        metadata={"organization_id": org.pk},
    )
    pending_profile = _public_asset(
        owner,
        "pending-secret-profile",
        "https://imagedelivery.net/public/PENDING-SECRET-PROFILE/public",
        metadata={"organization_id": org.pk},
    )
    pending_cover = _public_asset(
        owner,
        "pending-secret-cover",
        "https://imagedelivery.net/public/PENDING-SECRET-COVER/public",
        metadata={"organization_id": org.pk},
    )
    state.profile_image = approved_profile
    state.cover_image = approved_cover
    state.save(update_fields=["profile_image", "cover_image", "updated_at"])

    payload = current_public_profile_data(org)
    payload["organization"]["city"] = "PENDING SECRET CITY"
    payload["organization"]["region"] = "PENDING SECRET REGION"
    payload["public_state"].update(
        {
            "public_name_en": "PENDING SECRET NAME",
            "bio_en": "PENDING SECRET BIO",
            "specializations": ["PENDING SECRET SPECIALIZATION"],
            "profile_image_id": pending_profile.pk,
            "cover_image_id": pending_cover.pk,
        }
    )
    revision = save_public_profile_revision(
        organization=org,
        actor=owner,
        proposed_data=payload,
    )
    assert revision.status == revision.Status.DRAFT

    directory = client.get(reverse("designer-directory") + "?lang=en")
    detail = client.get(reverse("designer-public-detail", args=[state.slug]) + "?lang=en")
    for response in (directory, detail):
        body = response.content.decode()
        assert "PENDING SECRET NAME" not in body
        assert "PENDING SECRET BIO" not in body
        assert "PENDING SECRET SPECIALIZATION" not in body
        assert "PENDING SECRET CITY" not in body
        assert "PENDING SECRET REGION" not in body
        assert "PENDING-SECRET-PROFILE" not in body
        assert "PENDING-SECRET-COVER" not in body
        assert "public-profile-revision" not in body

    detail_body = detail.content.decode()
    assert state.public_name_en in detail_body
    assert state.bio_en in detail_body
    assert approved_profile.metadata["public_url"] in detail_body
    assert approved_cover.metadata["public_url"] in detail_body
    assert detail.context["public_location_parts"] == ["Cairo", "EG"]


@pytest.mark.django_db
def test_designer_detail_renders_approved_profile_cover_inquiry_and_approved_public_work_only(client):
    owner = _user("phase5-detail-owner")
    org, state = _designer(owner, "Public Work Designer")
    profile = _public_asset(
        owner,
        "detail-profile",
        "https://imagedelivery.net/public/detail-profile/public",
        metadata={
            "organization_id": org.pk,
            "private_url": "https://private.example.test/object?signature=SECRET",
            "api_token": "TEST-CLOUDFLARE-SECRET",
        },
    )
    cover = _public_asset(
        owner,
        "detail-cover",
        "https://imagedelivery.net/public/detail-cover/public",
        metadata={"organization_id": org.pk, "private_object_key": "PRIVATE-OBJECT-KEY"},
    )
    state.profile_image = profile
    state.cover_image = cover
    state.save(update_fields=["profile_image", "cover_image", "updated_at"])
    garment, artwork, _designed, store, product = _published_public_work(
        org, owner, "phase5-visible"
    )

    url = reverse("designer-public-detail", args=[state.slug])
    response = client.get(url + "?lang=en")
    body = response.content.decode()

    assert response.status_code == 200
    assert profile.metadata["public_url"] in body
    assert cover.metadata["public_url"] in body
    assert garment.title in body
    assert artwork.title in body
    assert product.title_en in body
    assert f'{reverse("designer-public-inquiry", args=[state.slug])}?lang=en' in body
    assert f'{reverse("artwork-detail", args=[artwork.pk])}?lang=en' in body
    assert (
        f'{reverse("public-store-product", args=[store.slug, product.slug])}?lang=en'
        in body
    )

    for prohibited in (
        "RAW-PROVIDER-ID-detail-profile",
        "RAW-PROVIDER-ID-detail-cover",
        "PRIVATE-OBJECT-KEY",
        "TEST-CLOUDFLARE-SECRET",
        "signature=SECRET",
        org.email,
        org.phone,
        org.legal_name,
        org.designer_profile.tax_number,
        "PRIVATE-PAYOUT-MARKER",
    ):
        assert prohibited not in body

    seo = json.dumps(response.context["page_seo"], ensure_ascii=False)
    assert state.public_name_en in seo
    assert state.bio_en in seo
    assert "PENDING" not in seo


@pytest.mark.django_db
def test_designer_detail_public_work_eligibility_is_not_broadened(client):
    owner = _user("phase5-eligibility-owner")
    org, state = _designer(owner, "Eligibility Designer")
    garment, artwork, designed, store, product = _published_public_work(
        org, owner, "phase5-eligibility"
    )
    url = reverse("designer-public-detail", args=[state.slug])

    visible = client.get(url + "?lang=en").content.decode()
    assert garment.title in visible
    assert artwork.title in visible
    assert product.title_en in visible

    product.status = StoreProduct.Status.HIDDEN
    product.save(update_fields=["status"])
    product_hidden = client.get(url + "?lang=en").content.decode()
    assert garment.title not in product_hidden
    assert product.title_en not in product_hidden
    assert artwork.title in product_hidden

    product.status = StoreProduct.Status.PUBLISHED
    product.save(update_fields=["status"])
    store.status = Storefront.Status.PAUSED
    store.save(update_fields=["status"])
    store_hidden = client.get(url + "?lang=en").content.decode()
    assert garment.title not in store_hidden
    assert product.title_en not in store_hidden
    assert artwork.title in store_hidden

    store.status = Storefront.Status.PUBLISHED
    store.save(update_fields=["status"])
    designed.status = DesignedProduct.Status.SUSPENDED
    designed.save(update_fields=["status"])
    designed_hidden = client.get(url + "?lang=en").content.decode()
    assert garment.title not in designed_hidden
    assert product.title_en not in designed_hidden
    assert artwork.title in designed_hidden

    artwork.status = Artwork.Status.SUSPENDED
    artwork.save(update_fields=["status"])
    fully_hidden = client.get(url + "?lang=en").content.decode()
    assert artwork.title not in fully_hidden


@pytest.mark.django_db
def test_designer_detail_mixed_work_empty_states_and_no_cover_do_not_invent_content(client):
    owner = _user("phase5-mixed-owner")
    org, state = _designer(owner, "Mixed Work Designer")
    artwork = Artwork.objects.create(
        organization=org,
        title="Only Approved Artwork",
        status=Artwork.Status.APPROVED,
        created_by=owner,
    )
    version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        status=ArtworkVersion.Status.APPROVED,
        created_by=owner,
    )
    preview = _public_asset(
        owner,
        "only-artwork-preview",
        "/static/brand/fabinzi-icon.svg",
    )
    ArtworkAsset.objects.create(
        version=version,
        kind=ArtworkAsset.Kind.PREVIEW,
        media_asset=preview,
    )

    response = client.get(
        reverse("designer-public-detail", args=[state.slug]) + "?lang=en"
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Only Approved Artwork" in body
    assert "No approved public Garment Designs right now." in body
    assert "No approved public Ready Designed Products right now." in body
    assert "No approved public Artwork right now." not in body
    assert 'id="designer-public-cover"' not in body
    assert ">—<" not in body


@pytest.mark.django_db
def test_arabic_designer_detail_preserves_language_for_inquiry_artwork_and_store_product(client):
    owner = _user("phase5-ar-owner")
    org, state = _designer(owner, "Arabic Navigation Designer")
    _garment, artwork, _designed, store, product = _published_public_work(
        org, owner, "phase5-ar"
    )
    response = client.get(
        reverse("designer-public-detail", args=[state.slug]) + "?lang=ar"
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert state.public_name_ar in body
    assert f'{reverse("designer-public-inquiry", args=[state.slug])}?lang=ar' in body
    assert f'{reverse("artwork-detail", args=[artwork.pk])}?lang=ar' in body
    assert (
        f'{reverse("public-store-product", args=[store.slug, product.slug])}?lang=ar'
        in body
    )
    inquiry = client.get(
        reverse("designer-public-inquiry", args=[state.slug]) + "?lang=ar"
    )
    assert inquiry.status_code == 200
    assert inquiry.wsgi_request.LANGUAGE_CODE == "ar"


@pytest.mark.django_db
def test_manufacturer_directory_and_detail_remain_functional(client):
    owner = _user("phase5-manufacturer-regression")
    _org, state = _manufacturer(owner)

    directory = client.get(reverse("manufacturer-marketplace") + "?lang=en")
    detail = client.get(
        reverse("manufacturer-public-detail", args=[state.slug]) + "?lang=en"
    )

    assert directory.status_code == 200
    assert detail.status_code == 200
    assert b"Phase 5 Regression Factory" in directory.content
    assert b"Phase 5 Regression Factory" in detail.content
    assert b"data-public-image-fallback" in directory.content
    assert b"data-public-image-fallback" in detail.content
