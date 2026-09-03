from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion, IPCase
from apps.audit.models import AuditEvent
from apps.checkout.models import CustomerPurchase
from apps.design.models import GarmentDesign, GarmentDesignVersion, TechnicalReview
from apps.finance.models import FinanceAccount, LedgerEntry, PayoutProfile, SettlementRequest
from apps.integrations.models import IntegrationConfig
from apps.media.models import MediaAsset
from apps.operations.models import FulfillmentRecord, ProductionJob
from apps.organizations.models import Membership, OnboardingApplication, Organization, VerificationDocument
from apps.platform_ops.models import MaintenanceWindow, PlatformAnnouncement

from .test_manufacturer_portal_acceptance import assigned_job, manufacturer

User = get_user_model()


def grant(user, *codenames):
    perms = Permission.objects.filter(codename__in=codenames)
    assert perms.count() == len(set(codenames)), (codenames, list(perms.values_list("codename", flat=True)))
    user.user_permissions.add(*perms)


def otp_login(client, user):
    device = TOTPDevice.objects.create(user=user, name=f"maneg-{user.pk}", confirmed=True)
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    return device


def staff(username="ops", *, superuser=False):
    if superuser:
        return User.objects.create_superuser(username=username, email=f"{username}@example.test", password="strong-pass-123")
    return User.objects.create_user(username=username, email=f"{username}@example.test", password="strong-pass-123", is_staff=True)


def private_media(owner, filename="evidence.pdf", payload=b"private-evidence"):
    key = default_storage.save(f"maneg-tests/{filename}", ContentFile(payload))
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=key,
        original_filename=filename,
        mime_type="application/pdf",
        size_bytes=len(payload),
        access=MediaAsset.Access.PRIVATE,
        uploaded_by=owner,
    )


@pytest.mark.django_db
def test_maneg_authentication_mfa_permissions_and_superuser(client):
    assert client.get("/Maneg/").status_code == 302

    ordinary = User.objects.create_user(username="ordinary", password="strong-pass-123")
    otp_login(client, ordinary)
    assert client.get("/Maneg/").status_code == 302

    operator = staff("staff-no-otp")
    client.force_login(operator)
    assert client.get("/Maneg/").status_code == 302

    otp_login(client, operator)
    assert client.get("/Maneg/").status_code == 200
    assert client.get("/Maneg/users/").status_code == 403

    grant(operator, "view_user")
    assert client.get("/Maneg/users/").status_code == 200
    assert client.get("/Maneg/finance/").status_code == 403

    root = staff("root", superuser=True)
    otp_login(client, root)
    response = client.get("/Maneg/system/")
    assert response.status_code == 200
    assert b"DATABASE_URL" not in response.content
    assert b"REDIS_URL" not in response.content


@pytest.mark.django_db
def test_user_suspension_is_permission_checked_self_safe_and_audited(client):
    operator = staff("user-operator")
    target = User.objects.create_user(username="target-user", email="target@example.test", password="strong-pass-123")
    grant(operator, "view_user", "change_user")
    otp_login(client, operator)

    response = client.get(reverse("fabinzi_admin:maneg-users"))
    html = response.content.decode()
    assert response.status_code == 200
    assert "pbkdf2_" not in html
    assert "secret" not in html.lower()

    response = client.post(reverse("fabinzi_admin:maneg-users"), {"action": "suspend", "user_id": target.pk})
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.is_active is False
    assert AuditEvent.objects.filter(action="control_center.user.suspended", object_id=str(target.pk)).exists()

    response = client.post(reverse("fabinzi_admin:maneg-users"), {"action": "suspend", "user_id": operator.pk})
    assert response.status_code == 302
    operator.refresh_from_db()
    assert operator.is_active is True


@pytest.mark.django_db
def test_organization_verification_and_private_document_permissions(client):
    applicant = User.objects.create_user(username="designer-applicant", password="strong-pass-123")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="Review Studio", email="review@example.test", verification_status=Organization.VerificationStatus.PENDING, created_by=applicant)
    Membership.objects.create(organization=org, user=applicant, role=Membership.Role.OWNER)
    application = OnboardingApplication.objects.create(organization=org, status=OnboardingApplication.Status.SUBMITTED, submitted_at=timezone.now())
    media = private_media(applicant, "registration.pdf")
    document = VerificationDocument.objects.create(application=application, document_type=VerificationDocument.DocumentType.REGISTRATION, media_asset=media, description="Registration")

    operator = staff("verification-operator")
    grant(operator, "view_onboardingapplication", "change_onboardingapplication", "change_organization", "view_verificationdocument")
    otp_login(client, operator)

    page = client.get(reverse("fabinzi_admin:maneg-verification-detail", args=[application.pk]))
    assert page.status_code == 200
    assert "registration.pdf" in page.content.decode()
    assert client.get(reverse("fabinzi_admin:maneg-private-evidence", args=["verification", document.pk])).status_code == 403

    grant(operator, "view_mediaasset")
    evidence = client.get(reverse("fabinzi_admin:maneg-private-evidence", args=["verification", document.pk]))
    assert evidence.status_code == 200
    cache_directives = {directive.strip().lower() for directive in evidence["Cache-Control"].split(",")}
    assert {"private", "no-store"}.issubset(cache_directives)
    assert evidence["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert evidence["Referrer-Policy"] == "no-referrer"
    assert evidence["X-Content-Type-Options"] == "nosniff"

    response = client.post(reverse("fabinzi_admin:maneg-verification-detail", args=[application.pk]), {"decision": "approved", "review_notes": "Evidence verified"})
    assert response.status_code == 302
    application.refresh_from_db(); org.refresh_from_db()
    assert application.status == OnboardingApplication.Status.APPROVED
    assert org.verification_status == Organization.VerificationStatus.ACTIVE
    assert AuditEvent.objects.filter(action="onboarding.approved", object_id=str(application.pk)).exists()


@pytest.mark.django_db
def test_design_review_uses_existing_service_and_preserves_technical_content(client):
    owner = User.objects.create_user(username="design-owner-maneg", password="strong-pass-123")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="Technical Studio", email="technical@example.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    design = GarmentDesign.objects.create(organization=org, title="Review Jacket", status=GarmentDesign.Status.IN_REVIEW, created_by=owner)
    version = GarmentDesignVersion.objects.create(design=design, version_number=1, status=GarmentDesignVersion.Status.SUBMITTED, base_material="Cotton twill", technical_specs={"gsm": 260, "construction": {"seam_mm": 8}}, created_by=owner, submitted_at=timezone.now())
    original_specs = dict(version.technical_specs)

    operator = staff("design-reviewer")
    grant(operator, "view_garmentdesignversion", "change_garmentdesignversion", "add_technicalreview")
    otp_login(client, operator)
    page = client.get(reverse("fabinzi_admin:maneg-design-review-detail", args=[version.pk]))
    assert page.status_code == 200
    assert "Cotton twill" in page.content.decode()

    response = client.post(reverse("fabinzi_admin:maneg-design-review-detail", args=[version.pk]), {"decision": TechnicalReview.Decision.APPROVED, "review_notes": "Technical definition accepted"})
    assert response.status_code == 302
    version.refresh_from_db(); design.refresh_from_db()
    assert version.status == GarmentDesignVersion.Status.APPROVED
    assert design.status == GarmentDesign.Status.APPROVED
    assert version.technical_specs == original_specs
    assert version.reviews.filter(reviewer=operator, decision=TechnicalReview.Decision.APPROVED).exists()
    assert AuditEvent.objects.filter(action="design.version.approved", object_id=str(version.pk)).exists()


@pytest.mark.django_db
def test_artwork_ip_privacy_takedown_and_typed_private_media(client):
    owner = User.objects.create_user(username="art-owner-maneg", password="strong-pass-123")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="IP Studio", email="ip@example.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    artwork = Artwork.objects.create(organization=org, title="Protected Mark", status=Artwork.Status.APPROVED, created_by=owner)
    version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    source_media = private_media(owner, "production-source.pdf", b"source-private")
    source = ArtworkAsset.objects.create(version=version, kind=ArtworkAsset.Kind.SOURCE, media_asset=source_media, label="Production source")
    case = IPCase.objects.create(artwork=artwork, reporter_name="Rights Holder", reporter_email="rights@example.test", claimant_rights="Registered rights", allegation="Unauthorized use")

    viewer = staff("ip-viewer")
    grant(viewer, "view_artworkversion", "view_artworkasset", "view_ipcase")
    otp_login(client, viewer)
    page = client.get(reverse("fabinzi_admin:maneg-ip-case-detail", args=[case.pk]))
    html = page.content.decode()
    assert page.status_code == 200
    assert "rights@example.test" not in html
    assert "r•••@example.test" in html
    assert "Unauthorized use" not in html
    assert client.get(reverse("fabinzi_admin:maneg-private-evidence", args=["artwork-source", source.pk])).status_code == 403

    grant(viewer, "view_mediaasset")
    source_response = client.get(reverse("fabinzi_admin:maneg-private-evidence", args=["artwork-source", source.pk]))
    assert source_response.status_code == 200

    grant(viewer, "change_ipcase")
    action = client.post(reverse("fabinzi_admin:maneg-ip-case-detail", args=[case.pk]), {"action": "takedown", "staff_notes": "Rights evidence substantiated"})
    assert action.status_code == 302
    case.refresh_from_db(); artwork.refresh_from_db()
    assert case.resolution == IPCase.Resolution.TAKEDOWN
    assert artwork.status == Artwork.Status.SUSPENDED
    assert AuditEvent.objects.filter(action="ip_case.moderated", object_id=str(case.pk)).exists()


@pytest.mark.django_db
def test_commerce_parent_child_and_canonical_production_fulfillment_are_distinct(client):
    _, org, _, _ = manufacturer("maneg-ops-manufacturer")
    production = assigned_job(org, prefix="maneg-ops-design")
    purchase = CustomerPurchase.objects.create(
        checkout=production["order"].checkout,
        customer=production["customer"],
        status=CustomerPurchase.Status.CONFIRMED,
        payment_method=CustomerPurchase.PaymentMethod.COD,
        subtotal=production["order"].subtotal,
        total=production["order"].total,
        currency=production["order"].currency,
        shipping_snapshot=production["order"].shipping_snapshot,
        confirmed_at=timezone.now(),
    )
    production["order"].purchase = purchase
    production["order"].save(update_fields=["purchase"])

    operator = staff("commerce-operator")
    grant(operator, "view_customerpurchase", "view_customerorder", "view_productionjob", "view_fulfillmentrecord")
    otp_login(client, operator)

    orders = client.get(reverse("fabinzi_admin:maneg-orders"))
    html = orders.content.decode()
    assert orders.status_code == 200
    assert str(purchase.number) in html
    assert str(production["order"].number) in html
    assert "CustomerPurchase" in html and "CustomerOrder" in html

    ops = client.get(reverse("fabinzi_admin:maneg-production"))
    assert ops.status_code == 200
    assert str(production["job"].pk) in ops.content.decode()
    assert str(production["order"].number) in ops.content.decode()
    assert ProductionJob.objects.filter(order=production["order"]).count() == 1
    assert FulfillmentRecord.objects.filter(order=production["order"]).count() == 1


@pytest.mark.django_db
def test_finance_uses_real_ledger_masks_payout_and_service_reviews_settlement(client):
    _, org, _, _ = manufacturer("maneg-finance-org")
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=org, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.MANUFACTURER_EARNING, amount=Decimal("420.00"), currency="EGP", available_at=timezone.now(), memo="Persisted payable")
    payout = PayoutProfile.objects.create(organization=org, method=PayoutProfile.Method.BANK, account_holder="Factory Finance", destination_hint="•••• 8899", status=PayoutProfile.Status.VERIFIED)
    settlement = SettlementRequest.objects.create(organization=org, account=account, payout_profile=payout, amount=Decimal("120.00"), currency="EGP", payout_snapshot={"method":"bank","account_holder":"Factory Finance","destination_hint":"•••• 8899"}, requested_by=User.objects.create_user(username="finance-requester"))

    operator = staff("finance-operator")
    grant(operator, "view_financeaccount", "view_settlementrequest", "view_payoutprofile", "change_settlementrequest")
    otp_login(client, operator)
    page = client.get(reverse("fabinzi_admin:maneg-finance"))
    html = page.content.decode()
    assert page.status_code == 200
    assert "420.00" in html
    assert "•••• 8899" in html
    assert "account_number" not in html
    assert "bank_password" not in html

    response = client.post(reverse("fabinzi_admin:maneg-finance"), {"action":"approve_settlement", "settlement_id": settlement.pk, "review_notes":"Approved against ledger"})
    assert response.status_code == 302
    settlement.refresh_from_db()
    assert settlement.status == SettlementRequest.Status.APPROVED
    assert AuditEvent.objects.filter(action="finance.settlement.approved", object_id=str(settlement.pk)).exists()


@pytest.mark.django_db
def test_integrations_keep_secrets_write_only_and_connection_state_truthful(client):
    cod = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.COD)
    stripe = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.STRIPE)
    stripe.set_secrets({"secret_key": "sk_never_render_this"})
    stripe.save(update_fields=["encrypted_secrets", "updated_at"])
    sentry = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.SENTRY)

    operator = staff("integration-operator")
    grant(operator, "view_integrationconfig", "change_integrationconfig")
    otp_login(client, operator)

    dashboard = client.get("/Maneg/")
    assert dashboard.status_code == 200
    assert dashboard.content.count(b'href="/Maneg/integrations/') == 0
    assert b'href="/super/' not in dashboard.content
    assert b"sk_never_render_this" not in dashboard.content

    detail = client.get(reverse("fabinzi_admin:maneg-integration-detail", args=[stripe.pk]))
    assert detail.status_code == 403
    original_cod_status = cod.last_test_status
    denied_test = client.post(reverse("fabinzi_admin:maneg-integration-detail", args=[cod.pk]), {"action":"test", "provider":"cod", "config":"{}", "enabled":"on"})
    assert denied_test.status_code == 403
    cod.refresh_from_db()
    assert cod.last_test_status == original_cod_status
    assert not AuditEvent.objects.filter(action="integration.connection.tested", object_id=str(cod.pk)).exists()

    root = staff("integration-root", superuser=True)
    otp_login(client, root)
    root_dashboard = client.get("/Maneg/")
    assert root_dashboard.status_code == 200
    assert root_dashboard.content.count(b'href="/Maneg/integrations/') == 1
    assert root_dashboard.content.count(b'href="/super/') == 1

    detail = client.get(reverse("fabinzi_admin:maneg-integration-detail", args=[stripe.pk]))
    html = detail.content.decode()
    assert detail.status_code == 200
    assert "sk_never_render_this" not in html
    assert stripe.encrypted_secrets not in html
    assert 'type="password"' in html

    test_cod = client.post(reverse("fabinzi_admin:maneg-integration-detail", args=[cod.pk]), {"action":"test", "provider":"cod", "config":"{}", "enabled":"on"})
    assert test_cod.status_code == 302
    cod.refresh_from_db()
    assert cod.last_test_status == IntegrationConfig.TestStatus.SUCCESS
    assert AuditEvent.objects.filter(action="integration.connection.tested", object_id=str(cod.pk)).exists()

    sentry_test = client.post(reverse("fabinzi_admin:maneg-integration-detail", args=[sentry.pk]), {"action":"test"})
    assert sentry_test.status_code == 302
    sentry.refresh_from_db()
    assert sentry.last_test_status == IntegrationConfig.TestStatus.NEVER
    assert all("sk_never_render_this" not in str(event.metadata) for event in AuditEvent.objects.all())


@pytest.mark.django_db
def test_announcement_and_maintenance_are_bilingual_scheduled_audited_and_maneg_bypasses_restriction(client):
    operator = staff("ops-comms")
    grant(operator, "view_platformannouncement", "add_platformannouncement", "view_maintenancewindow", "add_maintenancewindow")
    otp_login(client, operator)
    starts = timezone.localtime().strftime("%Y-%m-%dT%H:%M")

    announcement = client.post(reverse("fabinzi_admin:maneg-announcements"), {
        "enabled":"on", "title_en":"Service notice", "title_ar":"تنبيه خدمة", "message_en":"Persisted message", "message_ar":"رسالة محفوظة",
        "severity":"info", "audience":"all", "starts_at":starts, "ends_at":"", "dismissible":"on", "cta_label_en":"", "cta_label_ar":"", "cta_url":"", "priority":"100",
    })
    assert announcement.status_code == 302
    saved = PlatformAnnouncement.objects.get(title_en="Service notice")
    assert saved.title_ar == "تنبيه خدمة"
    assert AuditEvent.objects.filter(action="platform_ops.platformannouncement.updated", object_id=str(saved.pk)).exists()

    maintenance = client.post(reverse("fabinzi_admin:maneg-maintenance"), {
        "enabled":"on", "mode":"restrict", "message_en":"Scheduled maintenance", "message_ar":"صيانة مجدولة", "starts_at":starts, "ends_at":"",
    })
    assert maintenance.status_code == 302
    window = MaintenanceWindow.objects.get(message_en="Scheduled maintenance")
    assert window.message_ar == "صيانة مجدولة"
    assert AuditEvent.objects.filter(action="platform_ops.maintenancewindow.updated", object_id=str(window.pk)).exists()
    assert client.get("/").status_code == 503
    assert client.get(reverse("fabinzi_admin:maneg-maintenance")).status_code == 200


@pytest.mark.django_db
def test_audit_is_read_only_filters_and_redacts_sensitive_metadata(client):
    event = AuditEvent.objects.create(action="integration.example", metadata={
        "api_key":"visible-never", "nested":{"password":"also-never", "safe":"visible-safe"},
        "items":[{"webhook_secret":"nested-never", "label":"allowed-label"}],
    })
    operator = staff("audit-operator")
    grant(operator, "view_auditevent")
    otp_login(client, operator)
    page = client.get(reverse("fabinzi_admin:maneg-audit"), {"action":"integration"})
    html = page.content.decode()
    assert page.status_code == 200
    assert "visible-safe" in html and "allowed-label" in html
    assert "visible-never" not in html
    assert "also-never" not in html
    assert "nested-never" not in html
    assert html.count("Hidden") >= 3
    assert AuditEvent.objects.get(pk=event.pk).action == "integration.example"
    assert client.post(reverse("fabinzi_admin:maneg-audit"), {"action":"delete"}).status_code == 200
    assert AuditEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_maneg_noindex_localization_theme_and_no_social_internal_metadata(client):
    operator = staff("localization-operator")
    operator.theme_preference = User.Theme.DARK
    operator.language_preference = User.Language.ARABIC
    operator.save(update_fields=["theme_preference", "language_preference"])
    otp_login(client, operator)

    ar = client.get("/Maneg/", {"lang":"ar"})
    ar_html = ar.content.decode()
    assert ar.status_code == 200
    assert ar["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert '<html lang="ar" dir="rtl" data-theme="dark">' in ar_html
    assert '<meta name="robots" content="noindex,nofollow,noarchive">' in ar_html
    assert "property=\"og:" not in ar_html and "property='og:" not in ar_html

    en = client.get("/Maneg/", {"lang":"en"})
    en_html = en.content.decode()
    assert '<html lang="en" dir="ltr" data-theme="dark">' in en_html

    robots = client.get("/robots.txt").content.decode()
    assert "Disallow: /Maneg/" in robots
    sitemap = client.get("/sitemap.xml").content.decode()
    assert "/Maneg/" not in sitemap
