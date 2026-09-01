import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings

from apps.accounts.guest_identity import GUEST_SESSION_KEY
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
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


@pytest.mark.django_db
def test_role_aware_header_shows_only_authorized_portal_shortcuts(client):
    designer_user = User.objects.create_user(username="role-designer", password="password12345")
    designer_org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="Role Designer",
        email="designer@role.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=designer_user,
    )
    Membership.objects.create(organization=designer_org, user=designer_user, role=Membership.Role.OWNER)
    client.force_login(designer_user)
    body = client.get("/").content.decode()
    assert 'href="/designer/"' in body
    assert 'href="/manufacturer/"' not in body
    assert 'href="/Maneg/"' not in body

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
def test_manufacturer_public_projection_hides_private_contact_and_capacity(client):
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
        overview_en="Published capability overview.",
        public_email="listed-contact@example.test",
        public_phone="+201333333333",
        available_monthly_capacity=987654,
        min_order_quantity=4321,
    )
    ManufacturerCapability.objects.create(
        listing=listing,
        capability_type=ManufacturerCapability.CapabilityType.EMBROIDERY,
        name="Embroidery capability",
        is_active=True,
    )

    for path in ("/manufacturers/", f"/manufacturers/{listing.pk}/"):
        response = client.get(path)
        assert response.status_code == 200
        body = response.content.decode()
        assert "V2 Factory" in body
        assert "Embroidery capability" in body
        assert "private-factory@example.test" not in body
        assert "listed-contact@example.test" not in body
        assert "+201222222222" not in body
        assert "+201333333333" not in body
        assert "987654" not in body
        assert "4321" not in body


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
