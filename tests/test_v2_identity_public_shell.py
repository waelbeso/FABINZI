import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings

from apps.accounts.guest_identity import GUEST_SESSION_KEY
from apps.manufacturer_marketplace.models import (
    ManufacturerCapability,
    ManufacturerListing,
    ManufacturerPortfolioAsset,
)
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import Storefront

User = get_user_model()


@pytest.mark.django_db
def test_guest_public_shell_uses_stable_opaque_session_identity_without_fake_user(client):
    assert User.objects.count() == 0
    response = client.get("/")
    assert response.status_code == 200
    identity = client.session[GUEST_SESSION_KEY]
    assert len(identity) >= 32
    assert re.fullmatch(r"[A-Za-z0-9_-]+", identity)
    assert User.objects.count() == 0

    discover = client.get("/discover/")
    assert discover.status_code == 200
    assert client.session[GUEST_SESSION_KEY] == identity
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_web_signup_creates_single_identity_without_business_membership(client):
    response = client.post(
        "/account/signup/",
        {
            "username": "v2-customer",
            "email": "Customer@Example.Test",
            "first_name": "V2",
            "last_name": "Customer",
            "password1": "Unique-v2-password-123!",
            "password2": "Unique-v2-password-123!",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account/login/")
    user = User.objects.get(username="v2-customer")
    assert user.email == "customer@example.test"
    assert Membership.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_signup_rejects_duplicate_email_case_insensitively(client):
    User.objects.create_user(username="existing", email="owner@example.test", password="password12345")
    response = client.post(
        "/account/signup/",
        {
            "username": "duplicate-email",
            "email": "OWNER@EXAMPLE.TEST",
            "password1": "Unique-v2-password-123!",
            "password2": "Unique-v2-password-123!",
        },
    )
    assert response.status_code == 200
    assert "An account already uses this email address." in response.content.decode()
    assert not User.objects.filter(username="duplicate-email").exists()


@pytest.mark.django_db
def test_two_factor_login_does_not_deadlock_account_without_otp_device(client):
    User.objects.create_user(username="no-otp-user", password="password12345")
    response = client.post(
        "/account/login/",
        {
            "login_view-current_step": "auth",
            "auth-username": "no-otp-user",
            "auth-password": "password12345",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/app/")


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_and_change_web_lifecycle(client):
    user = User.objects.create_user(username="password-user", email="password@example.test", password="password12345")
    reset = client.post("/account/password/reset/", {"email": user.email})
    assert reset.status_code == 302
    assert reset.headers["Location"].endswith("/account/password/reset/done/")
    assert len(mail.outbox) == 1
    assert "FABINZI password reset" in mail.outbox[0].subject
    assert "/account/password/reset/" in mail.outbox[0].body

    client.force_login(user)
    changed = client.post(
        "/account/password/change/",
        {
            "old_password": "password12345",
            "new_password1": "Changed-v2-password-456!",
            "new_password2": "Changed-v2-password-456!",
        },
    )
    assert changed.status_code == 302
    assert changed.headers["Location"].endswith("/account/password/change/done/")
    user.refresh_from_db()
    assert user.check_password("Changed-v2-password-456!")


def _professional_user(kind, status, suffix):
    user = User.objects.create_user(username=f"role-{suffix}", password="password12345")
    org = Organization.objects.create(
        kind=kind,
        display_name=f"Role {suffix}",
        email=f"{suffix}@role.test",
        verification_status=status,
        created_by=user,
    )
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER, is_active=True)
    return user


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "status", "expected_path"),
    [
        (Organization.Kind.DESIGNER, Organization.VerificationStatus.ACTIVE, "/designer/"),
        (Organization.Kind.MANUFACTURER, Organization.VerificationStatus.ACTIVE, "/manufacturer/"),
    ],
)
def test_active_approved_professional_navigation_is_available(client, kind, status, expected_path):
    user = _professional_user(kind, status, f"{kind}-active")
    client.force_login(user)
    body = client.get("/").content.decode()
    assert f'href="{expected_path}"' in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "status", "forbidden_path"),
    [
        (Organization.Kind.DESIGNER, Organization.VerificationStatus.PENDING, "/designer/"),
        (Organization.Kind.DESIGNER, Organization.VerificationStatus.SUSPENDED, "/designer/"),
        (Organization.Kind.MANUFACTURER, Organization.VerificationStatus.PENDING, "/manufacturer/"),
        (Organization.Kind.MANUFACTURER, Organization.VerificationStatus.SUSPENDED, "/manufacturer/"),
    ],
)
def test_unapproved_or_suspended_professional_navigation_is_not_activated(client, kind, status, forbidden_path):
    user = _professional_user(kind, status, f"{kind}-{status}")
    client.force_login(user)
    body = client.get("/").content.decode()
    assert f'href="{forbidden_path}"' not in body


@pytest.mark.django_db
def test_inactive_membership_does_not_activate_professional_navigation(client):
    user = User.objects.create_user(username="inactive-membership", password="password12345")
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="Inactive Membership Designer",
        email="inactive-membership@role.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=user,
    )
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER, is_active=False)
    client.force_login(user)
    assert 'href="/designer/"' not in client.get("/").content.decode()


@pytest.mark.django_db
def test_staff_navigation_is_independent_of_professional_role_activation(client):
    staff = User.objects.create_user(username="role-staff", password="password12345", is_staff=True)
    client.force_login(staff)
    staff_body = client.get("/").content.decode()
    assert 'href="/Maneg/"' in staff_body
    assert 'href="/designer/"' not in staff_body
    assert 'href="/manufacturer/"' not in staff_body


@pytest.mark.django_db
def test_designer_directory_requires_active_organization_and_published_store(client):
    owner = User.objects.create_user(username="directory-owner", password="password12345")
    public_org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="Visible Designer Legal Identity",
        email="private-visible@example.test",
        phone="+201111111111",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Storefront.objects.create(
        organization=public_org,
        slug="visible-designer",
        status=Storefront.Status.PUBLISHED,
        name_en="Visible Designer",
        name_ar="مصمم ظاهر",
        about_en="Publicly approved storefront identity.",
    )
    hidden_org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="Hidden Designer",
        email="hidden@example.test",
        verification_status=Organization.VerificationStatus.PENDING,
        created_by=owner,
    )
    Storefront.objects.create(
        organization=hidden_org,
        slug="hidden-designer",
        status=Storefront.Status.PUBLISHED,
        name_en="Hidden Designer Store",
    )

    response = client.get("/designers/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Visible Designer" in body
    assert "Hidden Designer" not in body
    assert "private-visible@example.test" not in body
    assert "+201111111111" not in body


@pytest.mark.django_db
def test_manufacturer_public_projection_hides_private_contact_capacity_and_legacy_taxonomy(client):
    owner = User.objects.create_user(username="factory-owner", password="password12345")
    org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name="V2 Factory",
        email="private-factory@example.test",
        phone="+201222222222",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    listing = ManufacturerListing.objects.create(
        organization=org,
        status=ManufacturerListing.Status.PUBLISHED,
        headline_en="Qualified production partner",
        overview_en="Published production-partner overview.",
        public_email="listed-contact@example.test",
        public_phone="+201333333333",
        available_monthly_capacity=987654,
        min_order_quantity=4321,
    )
    ManufacturerCapability.objects.create(
        listing=listing,
        capability_type=ManufacturerCapability.CapabilityType.PRINT,
        name="Decorative transfer service",
        description="Published free-text service information.",
        is_active=True,
    )
    ManufacturerCapability.objects.create(
        listing=listing,
        capability_type=ManufacturerCapability.CapabilityType.SAMPLING,
        name="Prototype preparation service",
        is_active=True,
    )

    directory = client.get("/manufacturers/?capability=print")
    assert directory.status_code == 200
    directory_body = directory.content.decode()
    assert "V2 Factory" in directory_body
    assert 'name="capability"' not in directory_body
    assert "Decorative transfer service" not in directory_body

    detail = client.get(f"/manufacturers/{listing.pk}/")
    assert detail.status_code == 200
    body = detail.content.decode()
    assert "V2 Factory" in body
    assert "Decorative transfer service" in body
    assert "Prototype preparation service" in body
    assert "Published free-text service information." in body
    for legacy_label in (
        "Cut & sew",
        "Printing",
        "Sampling",
        "Pattern making",
        "Finishing",
        "Packaging",
        "Other",
    ):
        assert legacy_label not in body
    assert "private-factory@example.test" not in body
    assert "listed-contact@example.test" not in body
    assert "+201222222222" not in body
    assert "+201333333333" not in body
    assert "987654" not in body
    assert "4321" not in body


@pytest.mark.django_db
def test_manufacturer_public_media_requires_public_access_and_explicit_delivery_url(client):
    owner = User.objects.create_user(username="media-factory-owner", password="password12345")
    org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name="Media Safe Factory",
        email="media-factory@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    listing = ManufacturerListing.objects.create(
        organization=org,
        status=ManufacturerListing.Status.PUBLISHED,
        headline_en="Published factory profile",
    )

    safe_public = MediaAsset.objects.create(
        provider=MediaAsset.Provider.CLOUDFLARE_IMAGES,
        provider_asset_id="provider-internal-safe-id",
        original_filename="safe.jpg",
        mime_type="image/jpeg",
        size_bytes=10,
        access=MediaAsset.Access.PUBLIC,
        metadata={"public_url": "https://images.example.test/factory-safe.jpg"},
        uploaded_by=owner,
    )
    ManufacturerPortfolioAsset.objects.create(
        listing=listing,
        media_asset=safe_public,
        caption="Approved factory image",
    )

    public_without_url = MediaAsset.objects.create(
        provider=MediaAsset.Provider.CLOUDFLARE_IMAGES,
        provider_asset_id="provider-internal-must-not-leak",
        original_filename="missing-url.jpg",
        mime_type="image/jpeg",
        size_bytes=10,
        access=MediaAsset.Access.PUBLIC,
        metadata={},
        uploaded_by=owner,
    )
    ManufacturerPortfolioAsset.objects.create(
        listing=listing,
        media_asset=public_without_url,
        caption="No delivery URL image",
    )

    private_asset = MediaAsset.objects.create(
        provider=MediaAsset.Provider.AMAZON_S3,
        provider_asset_id="private/signed/internal-object-key",
        original_filename="private.jpg",
        mime_type="image/jpeg",
        size_bytes=10,
        access=MediaAsset.Access.PRIVATE,
        metadata={"public_url": "https://should-not-render.example.test/private.jpg"},
        uploaded_by=owner,
    )
    ManufacturerPortfolioAsset.objects.create(
        listing=listing,
        media_asset=private_asset,
        caption="Private image must stay hidden",
    )

    response = client.get(f"/manufacturers/{listing.pk}/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "https://images.example.test/factory-safe.jpg" in body
    assert "Approved factory image" in body
    assert "provider-internal-safe-id" not in body
    assert "provider-internal-must-not-leak" not in body
    assert "No delivery URL image" not in body
    assert "private/signed/internal-object-key" not in body
    assert "https://should-not-render.example.test/private.jpg" not in body
    assert "Private image must stay hidden" not in body


@pytest.mark.django_db
def test_how_it_works_preserves_domain_boundaries_and_bilingual_rtl(client):
    response = client.get("/how-it-works/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Garment Design" in body
    assert "Artwork" in body
    assert "Ready Design or Customer Customization" in body
    assert "Production Job" in body
    assert "Manufacturer does not own the public retail catalog" in body
    assert '<meta name="robots" content="index,follow' in body

    ar = client.get("/how-it-works/?lang=ar")
    assert ar.status_code == 200
    ar_body = ar.content.decode()
    assert '<html lang="ar" dir="rtl"' in ar_body
    assert "أربعة أدوار واضحة" in ar_body


@pytest.mark.django_db
def test_identity_surfaces_are_noindex(client):
    for path in ("/account/signup/", "/account/login/", "/account/password/reset/"):
        response = client.get(path)
        assert response.status_code == 200
        body = response.content.decode()
        assert '<meta name="robots" content="noindex,nofollow,noarchive">' in body
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
