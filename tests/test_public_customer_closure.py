import pytest
from django.contrib.auth import get_user_model

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.media.models import MediaAsset
from apps.organizations.models import Organization

User = get_user_model()


@pytest.mark.django_db
def test_discover_surfaces_only_public_approved_artwork_and_verified_manufacturers(client):
    designer = User.objects.create_user(username="closure-designer", password="password12345")
    designer_org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="Closure Design House",
        email="closure-designer@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=designer,
    )
    approved_art = Artwork.objects.create(
        organization=designer_org,
        title="Closure Approved Artwork",
        status=Artwork.Status.APPROVED,
        created_by=designer,
    )
    approved_version = ArtworkVersion.objects.create(
        artwork=approved_art,
        version_number=1,
        status=ArtworkVersion.Status.APPROVED,
        metadata={"public_suitability": "Casual apparel"},
        created_by=designer,
    )
    public_preview = MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id="/static/brand/fabinzi-logo.svg",
        original_filename="closure-preview.svg",
        mime_type="image/svg+xml",
        size_bytes=1,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=designer,
    )
    ArtworkAsset.objects.create(
        version=approved_version,
        kind=ArtworkAsset.Kind.PREVIEW,
        media_asset=public_preview,
        label="Public preview",
    )
    Artwork.objects.create(
        organization=designer_org,
        title="Closure Draft Artwork",
        status=Artwork.Status.DRAFT,
        created_by=designer,
    )

    manufacturer_user = User.objects.create_user(username="closure-manufacturer", password="password12345")
    manufacturer_org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name="Closure Verified Manufacturing",
        email="closure-manufacturer@example.test",
        city="Alexandria",
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=manufacturer_user,
    )
    listing = ManufacturerListing.objects.create(
        organization=manufacturer_org,
        status=ManufacturerListing.Status.PUBLISHED,
        headline_en="Print and embroidery production",
        headline_ar="إنتاج الطباعة والتطريز",
    )
    ManufacturerCapability.objects.create(
        listing=listing,
        capability_type=ManufacturerCapability.CapabilityType.PRINT,
        name="Screen printing",
        is_active=True,
    )
    ManufacturerCapability.objects.create(
        listing=listing,
        capability_type=ManufacturerCapability.CapabilityType.EMBROIDERY,
        name="Embroidery",
        is_active=False,
    )
    hidden_org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name="Hidden Manufacturing",
        email="hidden-manufacturer@example.test",
        verification_status=Organization.VerificationStatus.PENDING,
        created_by=manufacturer_user,
    )
    ManufacturerListing.objects.create(organization=hidden_org, status=ManufacturerListing.Status.PUBLISHED)

    response = client.get("/discover/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Closure Approved Artwork" in body
    assert "Casual apparel" in body
    assert "/static/brand/fabinzi-logo.svg" in body
    assert "Closure Draft Artwork" not in body
    assert "Closure Verified Manufacturing" in body
    assert "Screen printing" in body
    assert "Hidden Manufacturing" not in body
    assert "Embroidery" not in body


@pytest.mark.django_db
def test_customer_home_uses_preferences_shortcut_and_dedicated_preferences_surface(client):
    customer = User.objects.create_user(
        username="closure-customer",
        password="password12345",
        theme_preference="light",
        language_preference="en",
    )
    client.force_login(customer)

    home = client.get("/app/")
    assert home.status_code == 200
    body = home.content.decode()
    assert 'href="/app/settings/preferences/"' in body
    assert 'id="preference-language"' not in body
    assert "Save preferences" not in body

    preferences = client.get("/app/settings/preferences/")
    assert preferences.status_code == 200
    pref_body = preferences.content.decode()
    assert 'id="preference-language"' in pref_body
    assert 'id="preference-theme"' in pref_body
    assert '<meta name="robots" content="noindex,nofollow,noarchive">' in pref_body

    saved = client.post(
        "/app/settings/preferences/",
        {"language": "ar", "theme": "dark"},
        follow=True,
    )
    assert saved.status_code == 200
    customer.refresh_from_db()
    assert customer.language_preference == "ar"
    assert customer.theme_preference == "dark"
    assert "تم حفظ تفضيلات الحساب" in saved.content.decode()


@pytest.mark.django_db
def test_global_public_navigation_matches_v2_identity_public_shell(client):
    response = client.get("/?lang=en")
    assert response.status_code == 200
    body = response.content.decode()
    assert 'href="/">Shop</a>' in body
    assert 'href="/discover/">Discover</a>' in body
    assert 'href="/how-it-works/">How it works</a>' in body
    assert 'href="/artwork/">Artwork</a>' in body
    assert 'href="/designers/">Designers</a>' in body
    assert 'href="/manufacturers/">Manufacturers</a>' in body
    assert 'href="/account/signup/">Create account</a>' in body
    assert 'href="/account/login/">Sign in</a>' in body

    discover = client.get("/discover/?lang=en")
    assert discover.status_code == 200
    discover_body = discover.content.decode()
    assert 'id="how-fabinzi"' in discover_body
    assert 'id="designer-stores"' in discover_body
    assert 'id="featured-artwork"' in discover_body
    assert 'id="manufacturing-network"' in discover_body
