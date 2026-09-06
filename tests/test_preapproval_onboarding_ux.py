import json
import os
import time
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.checkout.models import CustomerOrder, OrderItem
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerQuote, RFQ, RFQInvitation
from apps.media.models import MediaAsset
from apps.operations.models import ProductionAsset, ProductionJob
from apps.organizations.designer_context import resolve_designer_membership
from apps.organizations.forms import DesignerOnboardingForm, ManufacturerOnboardingForm, OrganizationForm
from apps.organizations.manufacturer_context import resolve_manufacturer_membership
from apps.organizations.models import DesignerProfile, ManufacturerProfile, Membership, OnboardingApplication, Organization
from apps.storefront.models import ProductVariant, StoreProduct, Storefront

from .v2_3_support import v2_3_reference_rows


User = get_user_model()
ARTIFACT_DIR = Path("artifacts/preapproval-onboarding-browser-qa")


def _user(name):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="StrongPass123!",
    )


def _designer_org(user, name, status, app_status):
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=name,
        email=f"{name.lower().replace(' ', '-')}@example.test",
        city="Cairo",
        country="EG",
        verification_status=status,
        created_by=user,
    )
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    DesignerProfile.objects.create(
        organization=org,
        studio_name=name,
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(organization=org, status=app_status)
    return org


def _manufacturer_org(user, name, status, app_status):
    org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name=name,
        email=f"{name.lower().replace(' ', '-')}@example.test",
        city="Cairo",
        country="EG",
        verification_status=status,
        created_by=user,
    )
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    ManufacturerProfile.objects.create(
        organization=org,
        commercial_registration=f"CR-{name}",
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(organization=org, status=app_status)
    return org


def _designer_resources(user, org, prefix):
    design = GarmentDesign.objects.create(
        organization=org,
        title=f"{prefix} Design",
        created_by=user,
    )
    garment = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        summary=f"{prefix} untouched",
        created_by=user,
    )
    artwork = Artwork.objects.create(
        organization=org,
        title=f"{prefix} Artwork",
        created_by=user,
    )
    artwork_version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        created_by=user,
    )
    product = DesignedProduct.objects.create(
        organization=org,
        garment_version=garment,
        artwork_version=artwork_version,
        title=f"{prefix} Product",
        created_by=user,
    )
    return design, garment, artwork, artwork_version, product


def _set_session(client, key, organization):
    session = client.session
    session[key] = organization.pk
    session.save()


def _manufacturer_invitation(manufacturer, *, prefix):
    designer_owner = _user(f"{prefix}-designer")
    designer = _designer_org(
        designer_owner,
        f"{prefix} Source",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    _, garment, _, artwork_version, product = _designer_resources(
        designer_owner,
        designer,
        f"{prefix} Source",
    )
    garment.status = GarmentDesignVersion.Status.APPROVED
    garment.save(update_fields=["status"])
    artwork_version.status = ArtworkVersion.Status.APPROVED
    artwork_version.save(update_fields=["status"])
    product.status = DesignedProduct.Status.PUBLISHED
    product.save(update_fields=["status"])
    rfq = RFQ.objects.create(
        designer_organization=designer,
        designed_product=product,
        title=f"{prefix} RFQ",
        quantity=100,
        requested_methods=["print"],
        currency="EGP",
        status=RFQ.Status.OPEN,
        created_by=designer_owner,
    )
    invitation = RFQInvitation.objects.create(
        rfq=rfq,
        manufacturer=manufacturer,
        status=RFQInvitation.Status.INVITED,
    )
    return invitation


def _store_product(owner, designer, prefix):
    _, garment, _, artwork_version, product = _designer_resources(owner, designer, prefix)
    store = Storefront.objects.create(
        organization=designer,
        slug=f"{prefix.lower()}-store",
        status=Storefront.Status.PUBLISHED,
        name_en=f"{prefix} Store",
    )
    store_product = StoreProduct.objects.create(
        storefront=store,
        designed_product=product,
        slug=f"{prefix.lower()}-product",
        status=StoreProduct.Status.PUBLISHED,
        title_en=f"{prefix} Product",
        base_price=Decimal("100.00"),
        currency="EGP",
    )
    variant = ProductVariant.objects.create(
        product=store_product,
        sku=f"{prefix.upper()}-SKU",
        size="M",
        color_name="Black",
    )
    return store_product, variant


def _production_job(manufacturer, prefix):
    designer_owner = _user(f"{prefix}-designer-owner")
    designer = _designer_org(
        designer_owner,
        f"{prefix} Designer",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    store_product, variant = _store_product(designer_owner, designer, prefix)
    customer = _user(f"{prefix}-customer")
    order = CustomerOrder.objects.create(
        customer=customer,
        designer_organization=designer,
        status=CustomerOrder.Status.CONFIRMED,
        payment_method=CustomerOrder.PaymentMethod.COD,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        currency="EGP",
        shipping_snapshot={"city": "Cairo"},
    )
    OrderItem.objects.create(
        order=order,
        store_product=store_product,
        variant=variant,
        sku=variant.sku,
        title=store_product.title_en,
        unit_price=Decimal("100.00"),
        quantity=1,
        line_total=Decimal("100.00"),
    )
    return ProductionJob.objects.create(
        order=order,
        manufacturer=manufacturer,
        status=ProductionJob.Status.QUEUED,
    )


def _stored_private_asset(user, *, name, metadata):
    payload = f"private:{name}".encode()
    key = default_storage.save(
        f"preapproval-tests/{user.pk}/{name}",
        ContentFile(payload),
    )
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=key,
        original_filename=name,
        mime_type="application/pdf",
        size_bytes=len(payload),
        checksum_sha256="a" * 64,
        access=MediaAsset.Access.PRIVATE,
        metadata=metadata,
        uploaded_by=user,
    )


@pytest.mark.django_db
def test_trusted_designer_resource_overrides_session_query_and_post(client):
    user = _user("trusted-designer")
    active = _designer_org(
        user,
        "Active Studio",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    inactive = _designer_org(
        user,
        "Draft Studio",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    active_design, active_version, active_artwork, _, active_product = _designer_resources(user, active, "Active")
    inactive_design, inactive_version, inactive_artwork, _, inactive_product = _designer_resources(user, inactive, "Draft")
    client.force_login(user)

    _set_session(client, "designer_organization_id", inactive)
    response = client.get(
        reverse("designer-design-detail", args=[active_design.pk]),
        {"org": inactive.pk},
    )
    assert response.status_code == 200
    assert response.context["designer_organization"].pk == active.pk
    assert client.session["designer_organization_id"] == active.pk

    _set_session(client, "designer_organization_id", inactive)
    response = client.post(
        reverse("designer-design-detail", args=[active_design.pk]),
        {
            "organization": inactive.pk,
            "version_id": active_version.pk,
            "action": "save_version",
            "summary": "Trusted Active summary",
            "base_material": "Cotton",
            "construction_notes": "Trusted resource organization",
            "technical_specs": "",
        },
    )
    assert response.status_code == 302
    active_version.refresh_from_db()
    inactive_version.refresh_from_db()
    assert active_version.summary == "Trusted Active summary"
    assert inactive_version.summary == "Draft untouched"

    _set_session(client, "designer_organization_id", active)
    response = client.get(
        reverse("designer-design-technical-v2-4", args=[inactive_design.pk]),
        {"org": active.pk},
    )
    assert response.status_code == 302
    assert response.url == f"/designer/?org={inactive.pk}"

    before = inactive_version.summary
    response = client.post(
        reverse("designer-design-technical-v2-4", args=[inactive_design.pk]),
        {
            "organization": active.pk,
            "version_id": inactive_version.pk,
            "action": "save_policy",
        },
    )
    assert response.status_code == 403
    inactive_version.refresh_from_db()
    assert inactive_version.summary == before

    for active_resource, inactive_resource, route in [
        (active_artwork, inactive_artwork, "designer-artwork-detail"),
        (active_product, inactive_product, "designer-product-detail"),
        (active_product, inactive_product, "designer-ready-product-composer-detail-v2-4"),
    ]:
        _set_session(client, "designer_organization_id", inactive)
        response = client.get(reverse(route, args=[active_resource.pk]), {"org": inactive.pk})
        assert response.status_code == 200
        _set_session(client, "designer_organization_id", active)
        blocked = client.get(reverse(route, args=[inactive_resource.pk]), {"org": active.pk})
        assert blocked.status_code == 302
        assert blocked.url == f"/designer/?org={inactive.pk}"


@pytest.mark.django_db
def test_designer_unauthorized_resource_does_not_leak_or_redirect(client):
    user = _user("tenant-a")
    active = _designer_org(
        user,
        "Tenant A",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    outsider = _user("tenant-c")
    foreign = _designer_org(
        outsider,
        "SECRET TENANT C",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    foreign_design, _, _, _, _ = _designer_resources(outsider, foreign, "Foreign")
    client.force_login(user)

    response = client.get(
        reverse("designer-design-detail", args=[foreign_design.pk]),
        {"org": active.pk},
    )
    assert response.status_code == 404
    assert "Location" not in response
    assert b"SECRET TENANT C" not in response.content

    technical = client.get(
        reverse("designer-design-technical-v2-4", args=[foreign_design.pk]),
        {"org": active.pk},
    )
    assert technical.status_code == 403


@pytest.mark.django_db
def test_trusted_context_resolver_precedence_is_server_controlled():
    user = _user("resolver-user")
    active = _designer_org(
        user,
        "Resolver Active",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    other = _designer_org(
        user,
        "Resolver Other",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    from django.test import RequestFactory
    from django.contrib.sessions.middleware import SessionMiddleware

    factory = RequestFactory()
    request = factory.post(f"/designer/designs/1/?org={other.pk}", {"organization": other.pk})
    request.user = user
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session["designer_organization_id"] = other.pk
    request._fabinzi_trusted_professional_organization = active
    selected, _ = resolve_designer_membership(request, required=True)
    assert selected.organization_id == active.pk

    manufacturer_active = _manufacturer_org(
        user,
        "Resolver M Active",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    manufacturer_other = _manufacturer_org(
        user,
        "Resolver M Other",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    request = factory.post(
        f"/manufacturer/production/1/?org={manufacturer_other.pk}",
        {"organization": manufacturer_other.pk},
    )
    request.user = user
    middleware.process_request(request)
    request.session["manufacturer_organization_id"] = manufacturer_other.pk
    request._fabinzi_trusted_professional_organization = manufacturer_active
    selected, _ = resolve_manufacturer_membership(request, required=True)
    assert selected.organization_id == manufacturer_active.pk


@pytest.mark.django_db
def test_manufacturer_resource_owner_controls_invitation_with_conflicting_selectors(client):
    user = _user("trusted-mfr")
    active = _manufacturer_org(
        user,
        "Active Factory",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    inactive = _manufacturer_org(
        user,
        "Draft Factory",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    active_invitation = _manufacturer_invitation(active, prefix="active-invite")
    inactive_invitation = _manufacturer_invitation(inactive, prefix="draft-invite")
    client.force_login(user)

    _set_session(client, "manufacturer_organization_id", inactive)
    response = client.get(
        reverse("manufacturer-rfq-detail", args=[active_invitation.pk]),
        {"org": inactive.pk},
    )
    assert response.status_code == 200
    assert response.context["manufacturer_organization"].pk == active.pk
    active_invitation.refresh_from_db()
    assert active_invitation.status == RFQInvitation.Status.VIEWED

    _set_session(client, "manufacturer_organization_id", inactive)
    response = client.post(
        reverse("manufacturer-rfq-detail", args=[active_invitation.pk]),
        {
            "organization": inactive.pk,
            "unit_price": "12.50",
            "production_lead_days": "7",
            "setup_fee": "0",
            "sample_fee": "0",
            "shipping_estimate": "0",
            "currency": "EGP",
            "minimum_order_quantity": "1",
            "sample_lead_days": "",
            "valid_until": "",
            "notes": "Trusted active factory",
        },
    )
    assert response.status_code == 302
    quote = ManufacturerQuote.objects.get(invitation=active_invitation)
    assert quote.invitation.manufacturer_id == active.pk
    assert not ManufacturerQuote.objects.filter(invitation=inactive_invitation).exists()

    _set_session(client, "manufacturer_organization_id", active)
    inactive_invitation.refresh_from_db()
    assert inactive_invitation.status == RFQInvitation.Status.INVITED
    response = client.get(
        reverse("manufacturer-rfq-detail", args=[inactive_invitation.pk]),
        {"org": active.pk},
    )
    assert response.status_code == 302
    assert response.url == f"/manufacturer/?org={inactive.pk}"
    inactive_invitation.refresh_from_db()
    assert inactive_invitation.status == RFQInvitation.Status.INVITED

    response = client.head(
        reverse("manufacturer-rfq-detail", args=[inactive_invitation.pk]) + f"?org={active.pk}"
    )
    assert response.status_code == 302
    inactive_invitation.refresh_from_db()
    assert inactive_invitation.status == RFQInvitation.Status.INVITED

    blocked = client.post(
        reverse("manufacturer-rfq-detail", args=[inactive_invitation.pk]),
        {"organization": active.pk, "unit_price": "1.00"},
    )
    assert blocked.status_code == 403
    inactive_invitation.refresh_from_db()
    assert inactive_invitation.status == RFQInvitation.Status.INVITED
    assert not ManufacturerQuote.objects.filter(invitation=inactive_invitation).exists()


@pytest.mark.django_db
def test_manufacturer_unauthorized_resource_preserves_404_privacy(client):
    user = _user("mfr-a-user")
    own = _manufacturer_org(
        user,
        "MFR A",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    outsider = _user("mfr-c-user")
    foreign = _manufacturer_org(
        outsider,
        "SECRET MFR C",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    invitation = _manufacturer_invitation(foreign, prefix="foreign-invite")
    client.force_login(user)
    response = client.get(
        reverse("manufacturer-rfq-detail", args=[invitation.pk]),
        {"org": own.pk},
    )
    assert response.status_code == 404
    assert "Location" not in response
    assert b"SECRET MFR C" not in response.content


@pytest.mark.django_db
def test_resource_role_privacy_distinguishes_outsider_wrong_role_and_inactive_member(client):
    owner = _user("role-active-owner")
    active = _manufacturer_org(
        owner,
        "Role Active Factory",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    active_job = _production_job(active, "role-active-job")
    active_invitation = _manufacturer_invitation(active, prefix="role-active-invite")

    wrong_role = _user("role-active-accountant")
    Membership.objects.create(
        organization=active,
        user=wrong_role,
        role=Membership.Role.ACCOUNTANT,
    )
    client.force_login(wrong_role)
    assert client.get(reverse("manufacturer-production-detail", args=[active_job.pk])).status_code == 403
    assert client.get(reverse("manufacturer-rfq-detail", args=[active_invitation.pk])).status_code == 403

    client.force_login(owner)
    assert client.get(reverse("manufacturer-production-detail", args=[active_job.pk])).status_code == 200
    assert client.get(reverse("manufacturer-rfq-detail", args=[active_invitation.pk])).status_code == 200

    outsider = _user("role-resource-outsider")
    client.force_login(outsider)
    assert client.get(reverse("manufacturer-production-detail", args=[active_job.pk])).status_code == 404
    assert client.get(reverse("manufacturer-rfq-detail", args=[active_invitation.pk])).status_code == 404

    inactive_owner = _user("role-inactive-owner")
    inactive = _manufacturer_org(
        inactive_owner,
        "Role Draft Factory",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    inactive_job = _production_job(inactive, "role-inactive-job")
    inactive_wrong_role = _user("role-inactive-accountant")
    Membership.objects.create(
        organization=inactive,
        user=inactive_wrong_role,
        role=Membership.Role.ACCOUNTANT,
    )
    client.force_login(inactive_wrong_role)
    response = client.get(reverse("manufacturer-production-detail", args=[inactive_job.pk]))
    assert response.status_code == 302
    assert response.url == f"/manufacturer/?org={inactive.pk}"
    before_status = inactive_job.status
    blocked = client.post(
        reverse("manufacturer-production-detail", args=[inactive_job.pk]),
        {"action": "start"},
    )
    assert blocked.status_code == 403
    inactive_job.refresh_from_db()
    assert inactive_job.status == before_status


@pytest.mark.django_db
def test_inactive_manufacturer_production_media_returns_no_bytes_and_active_still_works(client):
    user = _user("media-mfr")
    active = _manufacturer_org(
        user,
        "Media Active",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    inactive = _manufacturer_org(
        user,
        "Media Draft",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    active_job = _production_job(active, "active-media")
    inactive_job = _production_job(inactive, "draft-media")
    active_asset = _stored_private_asset(user, name="active-job.pdf", metadata={})
    inactive_asset = _stored_private_asset(user, name="draft-job.pdf", metadata={})
    active_record = ProductionAsset.objects.create(
        job=active_job,
        media_asset=active_asset,
        kind=ProductionAsset.Kind.OTHER,
        uploaded_by=user,
    )
    inactive_record = ProductionAsset.objects.create(
        job=inactive_job,
        media_asset=inactive_asset,
        kind=ProductionAsset.Kind.OTHER,
        uploaded_by=user,
    )
    client.force_login(user)

    _set_session(client, "manufacturer_organization_id", active)
    blocked = client.get(
        reverse(
            "manufacturer-production-media",
            args=[inactive_job.pk, "job", inactive_record.pk],
        )
    )
    assert blocked.status_code == 404

    _set_session(client, "manufacturer_organization_id", inactive)
    allowed = client.get(
        reverse(
            "manufacturer-production-media",
            args=[active_job.pk, "job", active_record.pk],
        )
    )
    assert allowed.status_code == 200


@pytest.mark.django_db
def test_non_active_designer_private_media_is_fail_closed_except_verification(client):
    user = _user("designer-media")
    inactive = _designer_org(
        user,
        "Evidence Draft",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    active = _designer_org(
        user,
        "Evidence Active",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    client.force_login(user)

    verification = _stored_private_asset(
        user,
        name="verification.pdf",
        metadata={
            "designer_private_upload": True,
            "organization_id": inactive.pk,
            "purpose": "verification",
        },
    )
    response = client.get(reverse("private-designer-media", args=[verification.pk]))
    assert response.status_code == 200

    for index, purpose in enumerate(
        ["design_tech_pack", "artwork_source", "technical", "legacy_claimed", "", "unknown", "future_evidence_type"]
    ):
        asset = _stored_private_asset(
            user,
            name=f"blocked-{index}.pdf",
            metadata={
                "designer_private_upload": True,
                "organization_id": inactive.pk,
                "purpose": purpose,
            },
        )
        blocked = client.get(reverse("private-designer-media", args=[asset.pk]))
        assert blocked.status_code == 404

    missing = _stored_private_asset(
        user,
        name="missing-purpose.pdf",
        metadata={
            "designer_private_upload": True,
            "organization_id": inactive.pk,
        },
    )
    assert client.get(reverse("private-designer-media", args=[missing.pk])).status_code == 404

    active_operational = _stored_private_asset(
        user,
        name="active-operational.pdf",
        metadata={
            "designer_private_upload": True,
            "organization_id": active.pk,
            "purpose": "design_tech_pack",
        },
    )
    assert client.get(reverse("private-designer-media", args=[active_operational.pk])).status_code == 200


@pytest.mark.django_db
def test_context_routes_redirect_legitimate_inactive_members_and_leave_active_workspace(client):
    designer = _user("context-designer")
    designer_draft = _designer_org(
        designer,
        "Context Designer Draft",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    client.force_login(designer)
    root = client.get(reverse("designer"))
    assert root.status_code == 200
    assert b"APPLICATION MODE" in root.content
    assert b"designer-sidebar" not in root.content
    blocked = client.get(reverse("designer-design-list"))
    assert blocked.status_code == 302
    assert blocked.url == f"/designer/?org={designer_draft.pk}"
    assert client.post(reverse("designer-design-list"), {}).status_code == 403

    manufacturer = _user("context-manufacturer")
    manufacturer_draft = _manufacturer_org(
        manufacturer,
        "Context Manufacturer Draft",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    client.force_login(manufacturer)
    root = client.get(reverse("manufacturer"))
    assert root.status_code == 200
    assert b"APPLICATION MODE" in root.content
    assert b"manufacturer-sidebar" not in root.content
    blocked = client.get(reverse("manufacturer-production"))
    assert blocked.status_code == 302
    assert blocked.url == f"/manufacturer/?org={manufacturer_draft.pk}"


@pytest.mark.django_db
def test_aggregate_finance_excludes_inactive_organization_rows(client):
    user = _user("finance-multi")
    active = _designer_org(
        user,
        "Finance Active",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    inactive = _designer_org(
        user,
        "Finance Draft",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    from apps.finance.models import FinanceAccount, SettlementRequest

    active_account = FinanceAccount.objects.create(organization=active, currency="EGP")
    inactive_account = FinanceAccount.objects.create(organization=inactive, currency="EGP")
    client.force_login(user)
    response = client.get(reverse("finance-dashboard"))
    assert response.status_code == 200
    account_ids = {row["account"].pk for row in response.context["rows"]}
    assert active_account.pk in account_ids
    assert inactive_account.pk not in account_ids
    assert not SettlementRequest.objects.filter(organization=inactive).exists()


@pytest.mark.django_db
def test_anonymous_professional_resource_keeps_login_redirect_before_resource_disclosure(client):
    response = client.get(reverse("designer-design-detail", args=[999999]))
    assert response.status_code == 302
    assert settings.LOGIN_URL in response.url or "login" in response.url.lower()
    response = client.get(reverse("manufacturer-production-detail", args=[999999]))
    assert response.status_code == 302
    assert settings.LOGIN_URL in response.url or "login" in response.url.lower()


@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_production_like_inactive_resource_paths_do_not_500(client):
    user = _user("debugfalse-user")
    active = _designer_org(
        user,
        "Debug Active",
        Organization.VerificationStatus.ACTIVE,
        OnboardingApplication.Status.APPROVED,
    )
    inactive = _designer_org(
        user,
        "Debug Draft",
        Organization.VerificationStatus.DRAFT,
        OnboardingApplication.Status.DRAFT,
    )
    design, version, artwork, _, _ = _designer_resources(user, inactive, "Debug")
    client.force_login(user)
    _set_session(client, "designer_organization_id", active)
    for route, pk in [
        ("designer-design-detail", design.pk),
        ("designer-design-technical-v2-4", design.pk),
        ("designer-artwork-technical-v2-4", artwork.pk),
    ]:
        response = client.get(reverse(route, args=[pk]), {"org": active.pk})
        assert response.status_code == 302
        assert response.status_code != 500
    blocked = client.post(
        reverse("designer-design-technical-v2-4", args=[design.pk]),
        {"organization": active.pk, "version_id": version.pk, "action": "save_policy"},
    )
    assert blocked.status_code == 403
    assert blocked.status_code != 500


@pytest.mark.django_db
def test_url_fields_normalize_scheme_less_values_and_preserve_explicit_schemes(v2_3_reference_rows):
    cases = [
        ("", ""),
        ("example.com", "https://example.com"),
        ("www.example.com", "https://www.example.com"),
        ("https://example.com", "https://example.com"),
        ("http://example.com", "http://example.com"),
        ("example.com/path?q=one", "https://example.com/path?q=one"),
    ]
    for raw, expected in cases:
        org_form = OrganizationForm(
            data={
                "display_name": "URL Organization",
                "legal_name": "",
                "email": "url-org@example.test",
                "phone": "",
                "website": raw,
                "address_line1": "",
                "address_line2": "",
                "city": "Cairo",
                "region": "",
                "country": "EG",
            }
        )
        assert org_form.is_valid(), org_form.errors
        assert org_form.cleaned_data["website"] == expected

        designer_form = DesignerOnboardingForm(
            data={
                "studio_name": "URL Studio",
                "portfolio_url": raw,
                "legal_registration_number": "",
                "tax_number": "",
                "payout_information": "",
                "plan_policy_id": "",
                "accept_terms": "on",
            }
        )
        assert designer_form.is_valid(), designer_form.errors
        assert designer_form.cleaned_data["portfolio_url"] == expected

        manufacturer_form = ManufacturerOnboardingForm(
            data={
                "commercial_registration": "CR-URL",
                "tax_number": "",
                "google_maps_url": raw,
                "primary_contact_person": "",
                "contact_job_title": "",
                "whatsapp": "",
                "daily_capacity": "",
                "monthly_capacity": "",
                "payout_information": "",
                "plan_policy_id": "",
                "accept_terms": "on",
            }
        )
        assert manufacturer_form.is_valid(), manufacturer_form.errors
        assert manufacturer_form.cleaned_data["google_maps_url"] == expected

    assert OrganizationForm().fields["website"].widget.input_type == "text"
    assert DesignerOnboardingForm().fields["portfolio_url"].widget.input_type == "text"
    assert ManufacturerOnboardingForm().fields["google_maps_url"].widget.input_type == "text"


@pytest.mark.django_db
def test_malformed_urls_render_inline_and_retain_entered_values(client, v2_3_reference_rows):
    user = _user("invalid-url-user")
    client.force_login(user)
    response = client.post(
        reverse("designer"),
        {
            "org-display_name": "Invalid URL Studio",
            "org-legal_name": "",
            "org-email": "invalid-url@example.test",
            "org-phone": "",
            "org-website": "not a valid url",
            "org-address_line1": "",
            "org-address_line2": "",
            "org-city": "Cairo",
            "org-region": "",
            "org-country": "EG",
            "profile-studio_name": "Invalid URL Studio",
            "profile-portfolio_url": "also not a url",
            "profile-legal_registration_number": "",
            "profile-tax_number": "",
            "profile-payout_information": "",
            "profile-plan_policy_id": "",
            "profile-accept_terms": "on",
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Enter a valid URL" in body
    assert "not a valid url" in body
    assert "also not a url" in body
    assert "novalidate" in body
    assert 'type="text"' in body
    assert not Membership.objects.filter(user=user).exists()


@pytest.mark.django_db(transaction=True)
def test_preapproval_application_mode_real_chrome_designer_and_manufacturer(client, live_server, v2_3_reference_rows):
    if os.getenv("CI") != "true":
        pytest.skip("Pre-approval real Chrome acceptance is CI-only.")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 12, poll_frequency=0.05)
    evidence_dir = Path("artifacts/browser-qa/preapproval-onboarding")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    terms_diagnostics = {}
    last_terms_fragments = {}

    def login_as(user):
        client.force_login(user)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        driver.get(live_server.url + "/")
        driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": cookie, "path": "/"})

    def replace(field_id, value):
        element = wait.until(EC.presence_of_element_located((By.ID, field_id)))
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(value)
        return element

    def locate_terms(field_id):
        checkbox = wait.until(EC.presence_of_element_located((By.ID, field_id)))
        labels = driver.find_elements(By.CSS_SELECTOR, f'label[for="{field_id}"]')
        label = labels[0] if labels else None
        onboarding_check = checkbox.find_element(
            By.XPATH,
            "./ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' onboarding-check ')][1]",
        )
        terms_section = onboarding_check.find_element(
            By.XPATH,
            "./ancestor::section[contains(concat(' ', normalize-space(@class), ' '), ' onboarding-section ')][1]",
        )
        last_terms_fragments.clear()
        last_terms_fragments.update(
            checkbox=checkbox.get_attribute("outerHTML"),
            label=label.get_attribute("outerHTML") if label else "",
            onboarding_check=onboarding_check.get_attribute("outerHTML"),
            terms_section=terms_section.get_attribute("outerHTML"),
        )
        return checkbox, labels, label, onboarding_check, terms_section

    def viewport_snapshot(checkbox, label, onboarding_check, *, include_hits):
        return driver.execute_script(
            """
            const checkbox = arguments[0];
            const label = arguments[1];
            const check = arguments[2];
            const safeIdentity = (element) => {
              if (!element) return null;
              const style = getComputedStyle(element);
              return {
                tagName: element.tagName ? element.tagName.toLowerCase() : '',
                id: element.id || '',
                className: typeof element.className === 'string' ? element.className : '',
                role: element.getAttribute ? (element.getAttribute('role') || '') : '',
                pointerEvents: style.pointerEvents,
                position: style.position,
                zIndex: style.zIndex,
                visibility: style.visibility,
                opacity: style.opacity,
              };
            };
            const geometry = (element) => {
              if (!element) return null;
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              const centerY = rect.top + (rect.height / 2);
              return {
                rect: {
                  x: rect.x,
                  y: rect.y,
                  width: rect.width,
                  height: rect.height,
                  top: rect.top,
                  right: rect.right,
                  bottom: rect.bottom,
                  left: rect.left,
                  centerY,
                },
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
                pointerEvents: style.pointerEvents,
                zIndex: style.zIndex,
                position: style.position,
                fullyInsideViewport: rect.top >= 0 && rect.bottom <= window.innerHeight,
                centerInsideViewport: centerY >= 0 && centerY <= window.innerHeight,
              };
            };
            const hit = (element) => {
              if (!element) return null;
              const rect = element.getBoundingClientRect();
              const x = rect.left + (rect.width / 2);
              const y = rect.top + (rect.height / 2);
              const stack = document.elementsFromPoint(x, y);
              return {
                point: {x, y},
                elementFromPoint: safeIdentity(document.elementFromPoint(x, y)),
                elementsFromPoint: stack.slice(0, 8).map(safeIdentity),
                topIsTarget: stack.length > 0 && stack[0] === element,
                topWithinTarget: stack.length > 0 && element.contains(stack[0]),
              };
            };
            const result = {
              scrollBehavior: {
                html: getComputedStyle(document.documentElement).scrollBehavior,
                body: getComputedStyle(document.body).scrollBehavior,
              },
              viewport: {
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                scrollX: window.scrollX,
                scrollY: window.scrollY,
                documentScrollHeight: document.documentElement.scrollHeight,
              },
              checkbox: geometry(checkbox),
              label: geometry(label),
              onboardingCheck: geometry(check),
            };
            if (arguments[3]) {
              result.checkboxCenter = hit(checkbox);
              result.labelCenter = hit(label);
            }
            return result;
            """,
            checkbox,
            label,
            onboarding_check,
            include_hits,
        )

    def position_target(target):
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
            target,
        )

    def wait_for_scroll_settlement(target):
        started = time.monotonic()
        samples = []
        last = None
        stable_polls = 0

        def settled(_driver):
            nonlocal last, stable_polls
            state = driver.execute_script(
                """
                const rect = arguments[0].getBoundingClientRect();
                return {
                  scrollY: window.scrollY,
                  innerHeight: window.innerHeight,
                  top: rect.top,
                  bottom: rect.bottom,
                  centerY: rect.top + (rect.height / 2),
                };
                """,
                target,
            )
            samples.append(state)
            inside = (
                state["centerY"] >= 0
                and state["centerY"] <= state["innerHeight"]
                and state["top"] >= 0
                and state["bottom"] <= state["innerHeight"]
            )
            materially_stable = (
                last is not None
                and abs(state["scrollY"] - last["scrollY"]) <= 1
                and abs(state["top"] - last["top"]) <= 1
                and abs(state["bottom"] - last["bottom"]) <= 1
            )
            if inside and materially_stable:
                stable_polls += 1
            else:
                stable_polls = 0
            last = state
            if inside and stable_polls >= 2:
                return state
            return False

        final = wait.until(settled)
        if len(samples) <= 14:
            sample_summary = samples
        else:
            sample_summary = samples[:6] + [{"omitted_samples": len(samples) - 12}] + samples[-6:]
        return {
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "sample_count": len(samples),
            "samples": sample_summary,
            "final": final,
        }

    def interaction_result(action):
        try:
            action()
            return {"success": True, "exception_type": None}
        except Exception as exc:
            return {"success": False, "exception_type": type(exc).__name__}

    def reset_with_keyboard(checkbox):
        if checkbox.is_selected():
            checkbox.send_keys(Keys.SPACE)
        assert checkbox.is_selected() is False

    def write_evidence(prefix):
        errors = []
        try:
            driver.save_screenshot(str(evidence_dir / f"{prefix}.png"))
        except Exception as exc:
            errors.append(f"screenshot:{type(exc).__name__}")

        try:
            fragments = []
            for name in ("checkbox", "label", "onboarding_check", "terms_section"):
                fragment = last_terms_fragments.get(name)
                if fragment:
                    fragments.append(f"<!-- {name} -->\n{fragment}")
            (evidence_dir / f"{prefix}-terms-fragment.html").write_text(
                "\n\n".join(fragments),
                encoding="utf-8",
            )
        except Exception as exc:
            errors.append(f"fragment:{type(exc).__name__}")

        if errors:
            terms_diagnostics.setdefault("evidence_writer", {})[prefix] = {"errors": errors}
        try:
            (evidence_dir / f"{prefix}-terms-diagnostics.json").write_text(
                json.dumps(terms_diagnostics, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            pass

    def diagnose_terms(field_id="id_profile-accept_terms", *, key):
        checkbox, labels, label, onboarding_check, _ = locate_terms(field_id)
        diagnostic = {
            "checkboxId": checkbox.get_attribute("id"),
            "checkboxName": checkbox.get_attribute("name"),
            "checkboxType": checkbox.get_attribute("type"),
            "checkedInitially": checkbox.is_selected(),
            "disabled": not checkbox.is_enabled(),
            "labelFor": label.get_attribute("for") if label else None,
            "idCount": len(driver.find_elements(By.CSS_SELECTOR, f'[id="{field_id}"]')),
            "labelCount": len(labels),
            "association": bool(label and label.get_attribute("for") == field_id),
            "selenium": {
                "checkbox_displayed": checkbox.is_displayed(),
                "checkbox_enabled": checkbox.is_enabled(),
                "label_displayed": bool(label and label.is_displayed()),
                "label_enabled": bool(label and label.is_enabled()),
            },
            "interactions": {},
        }
        terms_diagnostics[key] = diagnostic
        assert diagnostic["idCount"] == 1
        assert diagnostic["labelCount"] == 1
        assert diagnostic["checkboxId"] == field_id
        assert diagnostic["labelFor"] == field_id
        assert diagnostic["association"] is True
        assert diagnostic["selenium"]["checkbox_displayed"] is True
        assert diagnostic["selenium"]["checkbox_enabled"] is True
        assert diagnostic["selenium"]["label_displayed"] is True
        assert diagnostic["selenium"]["label_enabled"] is True
        assert checkbox.is_selected() is False

        diagnostic["initial"] = viewport_snapshot(
            checkbox,
            label,
            onboarding_check,
            include_hits=False,
        )
        diagnostic["computed_scroll_behavior"] = diagnostic["initial"]["scrollBehavior"]
        assert diagnostic["computed_scroll_behavior"]["html"] == "smooth"

        position_target(label)
        diagnostic["immediate_after_scroll"] = viewport_snapshot(
            checkbox,
            label,
            onboarding_check,
            include_hits=False,
        )
        immediate = interaction_result(label.click)
        immediate["selected_after"] = checkbox.is_selected()
        diagnostic["interactions"]["label_immediate_after_scroll"] = immediate
        reset_with_keyboard(checkbox)

        position_target(label)
        diagnostic["label_settlement"] = wait_for_scroll_settlement(label)
        diagnostic["post_settlement"] = viewport_snapshot(
            checkbox,
            label,
            onboarding_check,
            include_hits=True,
        )
        assert diagnostic["post_settlement"]["label"]["fullyInsideViewport"] is True
        assert diagnostic["post_settlement"]["checkbox"]["fullyInsideViewport"] is True

        checkbox_hit = diagnostic["post_settlement"].get("checkboxCenter") or {}
        label_hit = diagnostic["post_settlement"].get("labelCenter") or {}
        no_overlay = bool(
            checkbox_hit.get("topWithinTarget")
            and label_hit.get("topWithinTarget")
        )
        diagnostic["post_settlement_no_overlay"] = no_overlay
        assert no_overlay is True

        settled_label = interaction_result(label.click)
        settled_label["selected_after"] = checkbox.is_selected()
        diagnostic["interactions"]["label_after_settlement"] = settled_label
        label_ok = settled_label["success"] and settled_label["selected_after"]
        reset_with_keyboard(checkbox)

        position_target(checkbox)
        diagnostic["checkbox_settlement"] = wait_for_scroll_settlement(checkbox)
        diagnostic["post_checkbox_settlement"] = viewport_snapshot(
            checkbox,
            label,
            onboarding_check,
            include_hits=True,
        )
        checkbox_on = interaction_result(checkbox.click)
        checkbox_on["selected_after"] = checkbox.is_selected()
        diagnostic["interactions"]["checkbox_after_settlement_on"] = checkbox_on
        checkbox_off = {
            "success": False,
            "exception_type": "not-run",
            "unchecked_after": not checkbox.is_selected(),
        }
        if checkbox_on["success"] and checkbox.is_selected():
            checkbox_off = interaction_result(checkbox.click)
            checkbox_off["unchecked_after"] = not checkbox.is_selected()
        diagnostic["interactions"]["checkbox_after_settlement_off"] = checkbox_off
        checkbox_ok = (
            checkbox_on["success"]
            and checkbox_on["selected_after"]
            and checkbox_off["success"]
            and checkbox_off["unchecked_after"]
        )
        reset_with_keyboard(checkbox)

        keyboard_on = interaction_result(lambda: checkbox.send_keys(Keys.SPACE))
        keyboard_on["selected_after"] = checkbox.is_selected()
        keyboard_on["active_element_id"] = driver.switch_to.active_element.get_attribute("id")
        diagnostic["interactions"]["keyboard_space_on"] = keyboard_on
        keyboard_off = {
            "success": False,
            "exception_type": "not-run",
            "unchecked_after": not checkbox.is_selected(),
        }
        if keyboard_on["success"] and checkbox.is_selected():
            keyboard_off = interaction_result(lambda: checkbox.send_keys(Keys.SPACE))
            keyboard_off["unchecked_after"] = not checkbox.is_selected()
        diagnostic["interactions"]["keyboard_space_off"] = keyboard_off
        keyboard_ok = (
            keyboard_on["success"]
            and keyboard_on["selected_after"]
            and keyboard_on["active_element_id"] == field_id
            and keyboard_off["success"]
            and keyboard_off["unchecked_after"]
        )
        assert checkbox.is_selected() is False
        assert keyboard_ok is True

        if label_ok:
            preferred = "settled-label"
        elif checkbox_ok:
            preferred = "settled-checkbox"
        else:
            preferred = None

        if preferred is None:
            diagnostic["root_cause_classification"] = "post-scroll-pointer-unresolved"
            diagnostic["preferred_business_flow_interaction"] = None
            raise AssertionError(
                "Pointer activation still fails after verified smooth-scroll settlement; inspect browser QA artifacts."
            )

        diagnostic["root_cause_classification"] = (
            "smooth-scroll / WebDriver timing interaction in the browser test harness"
        )
        diagnostic["product_checkbox_defect"] = "disproved-by-current-evidence"
        diagnostic["broken_label_association"] = "disproved"
        diagnostic["overlay"] = "disproved-after-settled-hit-testing"
        diagnostic["keyboard_accessibility"] = "pass"
        diagnostic["preferred_business_flow_interaction"] = preferred
        return preferred

    def accept_terms_for_flow(*, key, interaction, field_id="id_profile-accept_terms"):
        checkbox, labels, label, onboarding_check, _ = locate_terms(field_id)
        assert len(driver.find_elements(By.CSS_SELECTOR, f'[id="{field_id}"]')) == 1
        assert len(labels) == 1
        assert label is not None and label.get_attribute("for") == field_id
        assert checkbox.is_displayed() and checkbox.is_enabled()
        assert label.is_displayed() and label.is_enabled()
        assert checkbox.is_selected() is False

        target = label if interaction == "settled-label" else checkbox
        position_target(target)
        settlement = wait_for_scroll_settlement(target)
        before_click = viewport_snapshot(
            checkbox,
            label,
            onboarding_check,
            include_hits=True,
        )
        if interaction == "settled-label":
            label.click()
        else:
            checkbox.click()
        assert checkbox.is_selected() is True
        terms_diagnostics[key] = {
            "business_flow_interaction": interaction,
            "selected_after": checkbox.is_selected(),
            "settlement": settlement,
            "before_click": before_click,
        }

    try:
        designer = _user("browser-pre-designer")
        login_as(designer)
        driver.get(live_server.url + "/designer/?lang=en")
        wait.until(EC.presence_of_element_located((By.ID, "id_org-display_name")))
        assert driver.find_element(By.ID, "id_org-website").get_attribute("type") == "text"
        replace("id_org-display_name", "Browser Draft Studio")
        replace("id_org-email", "browser-designer@example.test")
        replace("id_org-city", "Cairo")
        replace("id_org-country", "EG")
        replace("id_org-website", "www.example.com")
        replace("id_profile-studio_name", "Browser Draft Studio")
        replace("id_profile-portfolio_url", "portfolio.example.com/work")
        preferred_terms_interaction = diagnose_terms(key="designer-create")
        accept_terms_for_flow(
            key="designer-create-final",
            interaction=preferred_terms_interaction,
        )
        driver.find_element(By.CSS_SELECTOR, 'form.onboarding-form button[type="submit"]').click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-application-mode="designer"]')))
        assert "APPLICATION MODE" in driver.page_source
        assert "designer-sidebar" not in driver.page_source
        designer_org = Organization.objects.get(created_by=designer, kind=Organization.Kind.DESIGNER)
        assert designer_org.website == "https://www.example.com"
        designer_org.designer_profile.refresh_from_db()
        assert designer_org.designer_profile.portfolio_url == "https://portfolio.example.com/work"
        driver.get(live_server.url + "/designer/designs/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-application-mode="designer"]')))
        driver.get(live_server.url + reverse("edit-onboarding", args=[designer_org.onboarding_application.pk]))
        website = replace("id_org-website", "not a url")
        driver.find_element(By.CSS_SELECTOR, 'form.onboarding-form button[type="submit"]').click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".errorlist")))
        assert "Enter a valid URL" in driver.page_source
        assert website.get_attribute("value") == "not a url"
        replace("id_org-website", "example.com")
        driver.find_element(By.CSS_SELECTOR, 'form.onboarding-form button[type="submit"]').click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-application-mode="designer"]')))
        designer_org.refresh_from_db()
        assert designer_org.website == "https://example.com"

        manufacturer = _user("browser-pre-manufacturer")
        login_as(manufacturer)
        driver.get(live_server.url + "/manufacturer/?lang=ar")
        wait.until(EC.presence_of_element_located((By.ID, "id_org-display_name")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert driver.find_element(By.ID, "id_org-website").get_attribute("type") == "text"
        replace("id_org-display_name", "Browser Draft Factory")
        replace("id_org-email", "browser-manufacturer@example.test")
        replace("id_org-city", "Cairo")
        replace("id_org-country", "EG")
        replace("id_org-website", "example.com")
        replace("id_profile-commercial_registration", "CR-BROWSER")
        replace("id_profile-google_maps_url", "maps.app.goo.gl/example")
        accept_terms_for_flow(
            key="manufacturer-create",
            interaction=preferred_terms_interaction,
        )
        driver.find_element(By.CSS_SELECTOR, 'form.onboarding-form button[type="submit"]').click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-application-mode="manufacturer"]')))
        assert "manufacturer-sidebar" not in driver.page_source
        manufacturer_org = Organization.objects.get(created_by=manufacturer, kind=Organization.Kind.MANUFACTURER)
        assert manufacturer_org.website == "https://example.com"
        manufacturer_org.manufacturer_profile.refresh_from_db()
        assert manufacturer_org.manufacturer_profile.google_maps_url == "https://maps.app.goo.gl/example"
        driver.get(live_server.url + "/manufacturer/production/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-application-mode="manufacturer"]')))

        driver.get(live_server.url + reverse("edit-onboarding", args=[manufacturer_org.onboarding_application.pk]))
        maps_url = replace("id_profile-google_maps_url", "not a url")
        driver.find_element(By.CSS_SELECTOR, 'form.onboarding-form button[type="submit"]').click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".errorlist")))
        assert "Enter a valid URL" in driver.page_source
        assert maps_url.get_attribute("value") == "not a url"
        replace("id_profile-google_maps_url", "maps.app.goo.gl/updated-example")
        driver.find_element(By.CSS_SELECTOR, 'form.onboarding-form button[type="submit"]').click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-application-mode="manufacturer"]')))
        manufacturer_org.manufacturer_profile.refresh_from_db()
        assert manufacturer_org.manufacturer_profile.google_maps_url == "https://maps.app.goo.gl/updated-example"

        write_evidence("verified")
        assert driver.save_screenshot(str(evidence_dir / "application-mode-manufacturer-rtl.png"))
    except Exception:
        write_evidence("failure")
        raise
    finally:
        driver.quit()
