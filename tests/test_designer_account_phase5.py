import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerListing
from apps.media.models import MediaAsset
from apps.organizations.models import DesignerProfile, ManufacturerProfile, Membership, OnboardingApplication, Organization, PublicProfileRevision
from apps.organizations.public_profile_services import current_public_profile_data, save_public_profile_revision
from apps.public_profiles.models import ProfessionalPublicState
from apps.public_profiles.services import ensure_public_state
from apps.storefront.models import StoreProduct, Storefront


User = get_user_model()


def _user(name):
    return User.objects.create_user(username=name, email=f"{name}@example.test", password="StrongPass123!")


def _designer(owner, name="Phase 5 Designer"):
    organization = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=name,
        legal_name="PRIVATE DESIGNER LEGAL NAME",
        email="designer-private@example.test",
        phone="+201000000111",
        website="https://designer.example.test",
        address_line1="PRIVATE DESIGNER ADDRESS",
        city="Cairo",
        region="Cairo",
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=organization, user=owner, role=Membership.Role.OWNER, is_active=True)
    DesignerProfile.objects.create(
        organization=organization,
        studio_name=name,
        portfolio_url="https://portfolio.example.test",
        legal_registration_number="PRIVATE-CR-123",
        tax_number="PRIVATE-TAX-123",
        payout_information="PRIVATE-PAYOUT-MARKER",
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(
        organization=organization,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=timezone.now(),
    )
    return organization


def _manufacturer(owner, name="Phase 5 Manufacturer"):
    organization = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name=name,
        email="manufacturer-private@example.test",
        phone="+201000000222",
        city="Giza",
        region="Giza",
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=organization, user=owner, role=Membership.Role.OWNER, is_active=True)
    ManufacturerProfile.objects.create(
        organization=organization,
        commercial_registration="MFR-PRIVATE-CR",
        tax_number="MFR-PRIVATE-TAX",
        payout_information="MFR-PRIVATE-PAYOUT",
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(
        organization=organization,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=timezone.now(),
    )
    ManufacturerListing.objects.create(
        organization=organization,
        status=ManufacturerListing.Status.PUBLISHED,
        headline_en="Approved manufacturer headline",
        overview_en="Approved manufacturer overview",
    )
    state = ensure_public_state(organization)
    state.public_name_en = name
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    return organization


def _public_asset(owner, *, key, url=None, metadata=None):
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=key,
        original_filename=f"{key}.png",
        mime_type="image/png",
        size_bytes=16,
        checksum_sha256="a" * 64,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=owner,
        metadata={**(metadata or {}), "public_url": url or f"https://cdn.example.test/{key}.png"},
    )


def _published_public_work(organization, owner, prefix="p5"):
    garment = GarmentDesign.objects.create(
        organization=organization,
        title=f"{prefix} Garment",
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
        organization=organization,
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
    preview = _public_asset(owner, key=f"{prefix}-artwork-preview")
    ArtworkAsset.objects.create(version=artwork_version, kind=ArtworkAsset.Kind.PREVIEW, media_asset=preview)
    designed = DesignedProduct.objects.create(
        organization=organization,
        garment_version=garment_version,
        artwork_version=artwork_version,
        title=f"{prefix} Ready",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )
    storefront = Storefront.objects.create(
        organization=organization,
        slug=f"{prefix}-store",
        status=Storefront.Status.PUBLISHED,
        name_en=f"{prefix} Store",
    )
    product = StoreProduct.objects.create(
        storefront=storefront,
        designed_product=designed,
        slug=f"{prefix}-product",
        status=StoreProduct.Status.PUBLISHED,
        title_en=f"{prefix} Product",
        title_ar=f"منتج {prefix}",
        base_price="700.00",
        currency="EGP",
    )
    return garment, artwork, designed, storefront, product


@pytest.mark.django_db
def test_phase5_directory_uses_current_approved_image_localization_location_and_all_specializations(client):
    owner = _user("p5-directory-owner")
    organization = _designer(owner, "Private Organization Name")
    state = ensure_public_state(organization)
    state.public_name_en = "Approved English Designer"
    state.public_name_ar = "المصمم المعتمد"
    state.bio_en = "Approved public biography"
    state.specializations = ["Casualwear", "Streetwear", "T-Shirt Design", "Pattern Making"]
    state.profile_image = _public_asset(
        owner,
        key="approved-directory-profile",
        metadata={"organization_id": organization.pk, "designer_public_upload": True},
    )
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()

    response = client.get(reverse("designer-directory") + "?lang=en")
    body = response.content.decode()
    assert response.status_code == 200
    assert "Approved English Designer" in body
    assert state.profile_image.metadata["public_url"] in body
    assert 'data-public-profile-image' in body
    assert 'data-public-image-fallback' in body
    assert body.count("Casualwear") == 1
    assert body.count("Streetwear") == 1
    assert body.count("T-Shirt Design") == 1
    assert body.count("Pattern Making") == 1
    assert "Cairo · Cairo" not in body
    assert "Cairo · EG" in body
    assert organization.email not in body
    assert organization.phone not in body
    assert organization.legal_name not in body

    arabic = client.get(reverse("designer-directory") + "?lang=ar").content.decode()
    assert "المصمم المعتمد" in arabic
    assert "Approved English Designer" not in arabic


@pytest.mark.django_db
def test_phase5_directory_no_image_uses_accessible_dsg_fallback(client):
    owner = _user("p5-directory-fallback-owner")
    organization = _designer(owner, "Fallback Designer")
    state = ensure_public_state(organization)
    state.public_name_en = "Fallback Designer"
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()

    body = client.get(reverse("designer-directory") + "?lang=en").content.decode()
    assert "DSG" in body
    assert "Profile image unavailable for Fallback Designer" in body
    assert "data-public-profile-image" not in body
    assert f'{reverse("designer-public-detail", args=[state.slug])}?lang=en' in body


@pytest.mark.django_db
def test_phase5_pending_revision_values_and_media_never_leak_from_directory_or_detail(client):
    owner = _user("p5-pending-owner")
    organization = _designer(owner, "Approved Organization")
    state = ensure_public_state(organization)
    approved_profile = _public_asset(
        owner,
        key="approved-current-profile",
        metadata={"organization_id": organization.pk, "designer_public_upload": True},
    )
    approved_cover = _public_asset(
        owner,
        key="approved-current-cover",
        metadata={"organization_id": organization.pk, "designer_public_upload": True},
    )
    state.public_name_en = "APPROVED CURRENT NAME"
    state.bio_en = "APPROVED CURRENT BIO"
    state.specializations = ["APPROVED CURRENT SPECIALIZATION"]
    state.profile_image = approved_profile
    state.cover_image = approved_cover
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()

    pending_profile = _public_asset(
        owner,
        key="PENDING-SECRET-PROFILE",
        metadata={"organization_id": organization.pk, "designer_public_upload": True},
    )
    pending_cover = _public_asset(
        owner,
        key="PENDING-SECRET-COVER",
        metadata={"organization_id": organization.pk, "designer_public_upload": True},
    )
    payload = current_public_profile_data(organization)
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
    revision = save_public_profile_revision(organization=organization, actor=owner, proposed_data=payload)
    assert revision.status == PublicProfileRevision.Status.DRAFT

    directory = client.get(reverse("designer-directory") + "?lang=en")
    detail = client.get(reverse("designer-public-detail", args=[state.slug]) + "?lang=en")
    for response in (directory, detail):
        body = response.content.decode()
        assert "APPROVED CURRENT NAME" in body
        assert approved_profile.metadata["public_url"] in body
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
def test_phase5_detail_renders_only_approved_profile_cover_inquiry_and_current_public_work(client):
    owner = _user("p5-detail-owner")
    organization = _designer(owner, "Phase 5 Detail Designer")
    state = ensure_public_state(organization)
    profile = _public_asset(
        owner,
        key="phase5-public-profile",
        metadata={"organization_id": organization.pk, "designer_public_upload": True},
    )
    cover = _public_asset(
        owner,
        key="phase5-public-cover",
        metadata={"organization_id": organization.pk, "designer_public_upload": True},
    )
    state.public_name_en = "Phase 5 Public Designer"
    state.bio_en = "Approved Designer biography for Phase 5."
    state.specializations = ["Outerwear", "Technical Fashion Drawing"]
    state.profile_image = profile
    state.cover_image = cover
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    garment, artwork, designed, storefront, product = _published_public_work(organization, owner, "p5-detail")

    response = client.get(reverse("designer-public-detail", args=[state.slug]) + "?lang=en")
    body = response.content.decode()
    assert response.status_code == 200
    assert profile.metadata["public_url"] in body
    assert cover.metadata["public_url"] in body
    assert "Phase 5 Public Designer" in body
    assert "Approved Designer biography for Phase 5." in body
    assert garment.title in body
    assert artwork.title in body
    assert product.title_en in body
    assert f'{reverse("designer-public-inquiry", args=[state.slug])}?lang=en' in body
    assert f'{reverse("artwork-detail", args=[artwork.pk])}?lang=en' in body
    assert f'{reverse("public-store-product", args=[storefront.slug, product.slug])}?lang=en' in body

    private_markers = [
        organization.email,
        organization.phone,
        organization.legal_name,
        organization.designer_profile.legal_registration_number,
        organization.designer_profile.tax_number,
        organization.designer_profile.payout_information,
        "PRIVATE-ASSET-KEY",
        "test-api-token",
        "cloudflare-test-secret",
        "X-Amz-Signature",
    ]
    for marker in private_markers:
        assert marker not in body
    assert profile.provider_asset_id not in body
    assert cover.provider_asset_id not in body

    seo = response.context["page_seo"]
    schema = json.loads(seo["json_ld"])
    assert seo["title"] == "Phase 5 Public Designer | FABINZI"
    assert schema[0]["name"] == "Phase 5 Public Designer"
    assert schema[0]["description"] == "Approved Designer biography for Phase 5."
    assert schema[0]["image"].endswith(profile.metadata["public_url"])


@pytest.mark.django_db
def test_phase5_public_work_eligibility_is_not_broadened(client):
    owner = _user("p5-work-owner")
    organization = _designer(owner, "Phase 5 Work Designer")
    state = ensure_public_state(organization)
    state.public_name_en = "Phase 5 Work Designer"
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    garment, artwork, designed, storefront, product = _published_public_work(organization, owner, "p5-work")
    url = reverse("designer-public-detail", args=[state.slug]) + "?lang=en"

    body = client.get(url).content.decode()
    assert garment.title in body and artwork.title in body and product.title_en in body

    product.status = StoreProduct.Status.HIDDEN
    product.save(update_fields=["status"])
    body = client.get(url).content.decode()
    assert garment.title not in body
    assert product.title_en not in body
    assert artwork.title in body

    product.status = StoreProduct.Status.PUBLISHED
    product.save(update_fields=["status"])
    storefront.status = Storefront.Status.PAUSED
    storefront.save(update_fields=["status"])
    body = client.get(url).content.decode()
    assert garment.title not in body and product.title_en not in body and artwork.title in body

    storefront.status = Storefront.Status.PUBLISHED
    storefront.save(update_fields=["status"])
    designed.status = DesignedProduct.Status.SUSPENDED
    designed.save(update_fields=["status"])
    body = client.get(url).content.decode()
    assert garment.title not in body and product.title_en not in body and artwork.title in body

    artwork.status = Artwork.Status.SUSPENDED
    artwork.save(update_fields=["status"])
    body = client.get(url).content.decode()
    assert artwork.title not in body


@pytest.mark.django_db
def test_phase5_mixed_and_empty_work_states_and_no_cover_are_intentional(client):
    owner = _user("p5-empty-owner")
    organization = _designer(owner, "Phase 5 Empty Designer")
    state = ensure_public_state(organization)
    state.public_name_en = "Phase 5 Empty Designer"
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    url = reverse("designer-public-detail", args=[state.slug]) + "?lang=en"

    response = client.get(url)
    body = response.content.decode()
    assert response.status_code == 200
    assert 'id="designer-public-cover"' not in body
    assert "No approved public Garment Designs right now." in body
    assert "No approved public Artwork right now." in body
    assert "No approved public Ready Designed Products right now." in body
    assert ">—<" not in body

    artwork = Artwork.objects.create(
        organization=organization,
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
    ArtworkAsset.objects.create(
        version=version,
        kind=ArtworkAsset.Kind.PREVIEW,
        media_asset=_public_asset(owner, key="only-artwork-preview"),
    )
    body = client.get(url).content.decode()
    assert "Only Approved Artwork" in body
    assert "No approved public Garment Designs right now." in body
    assert "No approved public Ready Designed Products right now." in body


@pytest.mark.django_db
def test_phase5_arabic_public_navigation_preserves_lang_without_changing_routes(client):
    owner = _user("p5-ar-owner")
    organization = _designer(owner, "Arabic Phase 5 Designer")
    state = ensure_public_state(organization)
    state.public_name_en = "English Public Name"
    state.public_name_ar = "اسم المصمم المعتمد"
    state.bio_ar = "نبذة عامة معتمدة"
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    _garment, artwork, _designed, storefront, product = _published_public_work(organization, owner, "p5-ar")

    directory = client.get(reverse("designer-directory") + "?lang=ar")
    directory_body = directory.content.decode()
    assert "اسم المصمم المعتمد" in directory_body
    assert f'{reverse("designer-public-detail", args=[state.slug])}?lang=ar' in directory_body

    detail = client.get(reverse("designer-public-detail", args=[state.slug]) + "?lang=ar")
    body = detail.content.decode()
    assert detail.status_code == 200
    assert "اسم المصمم المعتمد" in body
    assert "نبذة عامة معتمدة" in body
    assert f'{reverse("designer-public-inquiry", args=[state.slug])}?lang=ar' in body
    assert f'{reverse("artwork-detail", args=[artwork.pk])}?lang=ar' in body
    assert f'{reverse("public-store-product", args=[storefront.slug, product.slug])}?lang=ar' in body

    inquiry = client.get(reverse("designer-public-inquiry", args=[state.slug]) + "?lang=ar")
    assert inquiry.status_code == 200
    assert inquiry.wsgi_request.LANGUAGE_CODE == "ar"


@pytest.mark.django_db
def test_phase5_manufacturer_directory_and_detail_contract_remains_functional(client):
    owner = _user("p5-mfr-owner")
    organization = _manufacturer(owner)
    state = organization.public_state

    directory = client.get(reverse("manufacturer-marketplace") + "?lang=en")
    detail = client.get(reverse("manufacturer-public-detail", args=[state.slug]) + "?lang=en")
    assert directory.status_code == 200
    assert detail.status_code == 200
    assert organization.display_name in directory.content.decode()
    assert organization.display_name in detail.content.decode()
    assert "data-public-image-fallback" in directory.content.decode()
    assert "data-public-image-fallback" in detail.content.decode()
    assert organization.email not in directory.content.decode()
    assert organization.phone not in detail.content.decode()
