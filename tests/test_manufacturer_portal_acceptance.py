from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion, DesignedProduct
from apps.audit.models import AuditEvent
from apps.checkout.models import CheckoutSession, CustomerOrder, OrderItem
from apps.design.models import DecorationZone, DesignAsset, GarmentDesign, GarmentDesignVersion, SizeChartRow
from apps.finance.models import FinanceAccount, LedgerEntry, PayoutProfile, SettlementRequest
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing, ManufacturerQuote, RFQ, RFQInvitation
from apps.manufacturer_marketplace.services import submit_quote
from apps.media.models import MediaAsset
from apps.operations.models import FulfillmentRecord, ProductionJob, ProductionMilestone, QCInspection
from apps.operations.services import pack_order, record_qc, request_qc, ship_order, start_production, update_milestone
from apps.organizations.manufacturer_context import resolve_manufacturer_membership
from apps.organizations.manufacturer_services import (
    create_manufacturer_capability,
    deactivate_manufacturer_capability,
    secure_manufacturer_member_deactivate,
    secure_manufacturer_member_upsert,
    update_active_manufacturer_profile,
)
from apps.organizations.models import ManufacturerProfile, Membership, OnboardingApplication, Organization
from apps.storefront.models import CustomerCustomization, CustomizationElement, ProductVariant, StoreProduct, Storefront, StudioProject

User = get_user_model()


def manufacturer(username="mfr", *, status=Organization.VerificationStatus.ACTIVE, app_status=OnboardingApplication.Status.APPROVED, role=Membership.Role.OWNER):
    user = User.objects.create_user(username=username, email=f"{username}@example.test", password="password123")
    org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name=f"Factory {username}",
        legal_name=f"Factory {username} LLC",
        email=f"factory-{username}@example.test",
        phone="01000000000",
        city="Cairo",
        country="EG",
        verification_status=status,
        created_by=user,
    )
    Membership.objects.create(organization=org, user=user, role=role)
    profile = ManufacturerProfile.objects.create(
        organization=org,
        commercial_registration="CR-LOCKED",
        tax_number="TAX-LOCKED",
        primary_contact_person="Operations Lead",
        terms_accepted=True,
        terms_accepted_at=timezone.now(),
    )
    application = OnboardingApplication.objects.create(organization=org, status=app_status)
    return user, org, profile, application


def designer_product(prefix="brand"):
    owner = User.objects.create_user(username=f"{prefix}-owner", email=f"{prefix}@example.test", password="password123")
    designer = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=f"{prefix.title()} Studio",
        email=f"{prefix}-studio@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=designer, user=owner, role=Membership.Role.OWNER)
    design = GarmentDesign.objects.create(organization=designer, title="Essential Tee", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        status=GarmentDesignVersion.Status.APPROVED,
        base_material="Cotton",
        construction_notes="Use approved seam definition.",
        technical_specs={"gsm": 180},
        created_by=owner,
    )
    SizeChartRow.objects.create(version=garment, size_label="M", measurements={"chest_cm": 52})
    zone = DecorationZone.objects.create(
        version=garment,
        name="Front chest",
        method=DecorationZone.Method.BOTH,
        placement={"x": 0.5, "y": 0.35},
        max_width_mm=220,
        max_height_mm=260,
    )
    artwork = Artwork.objects.create(organization=designer, title="Wave", status=Artwork.Status.APPROVED, created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    product = DesignedProduct.objects.create(
        organization=designer,
        garment_version=garment,
        artwork_version=artwork_version,
        title="Wave Tee",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )
    store = Storefront.objects.create(organization=designer, slug=f"{prefix}-store", status=Storefront.Status.PUBLISHED, name_en=f"{prefix.title()} Store")
    store_product = StoreProduct.objects.create(
        storefront=store,
        designed_product=product,
        slug="wave-tee",
        status=StoreProduct.Status.PUBLISHED,
        title_en="Wave Tee",
        base_price=Decimal("500.00"),
        currency="EGP",
        fulfillment_mode=StoreProduct.FulfillmentMode.MADE_TO_ORDER,
        customization_enabled=True,
    )
    variant = ProductVariant.objects.create(product=store_product, sku=f"{prefix.upper()}-M", size="M", color_name="Black")
    return owner, designer, product, garment, artwork_version, zone, store_product, variant


def invited_rfq(manufacturer_org, *, prefix="rfq"):
    owner, designer, product, garment, artwork_version, zone, store_product, variant = designer_product(prefix)
    rfq = RFQ.objects.create(
        designer_organization=designer,
        designed_product=product,
        title="Production run",
        quantity=120,
        requested_methods=["print"],
        currency="EGP",
        status=RFQ.Status.OPEN,
        opened_at=timezone.now(),
        created_by=owner,
    )
    invitation = RFQInvitation.objects.create(rfq=rfq, manufacturer=manufacturer_org, status=RFQInvitation.Status.INVITED)
    return owner, designer, product, rfq, invitation


def assigned_job(manufacturer_org, *, prefix="job", role_user=None):
    owner, designer, product, garment, artwork_version, zone, store_product, variant = designer_product(prefix)
    customer = User.objects.create_user(username=f"{prefix}-customer", email=f"{prefix}-customer@example.test", password="password123")
    project = StudioProject.objects.create(customer=customer, product=store_product, variant=variant, status=StudioProject.Status.READY, quantity=2)
    customization = CustomerCustomization.objects.create(project=project, enabled=True)
    checkout = CheckoutSession.objects.create(
        customer=customer,
        studio_project=project,
        status=CheckoutSession.Status.PLACED,
        subtotal=Decimal("1000.00"),
        total=Decimal("1000.00"),
        currency="EGP",
    )
    order = CustomerOrder.objects.create(
        checkout=checkout,
        customer=customer,
        designer_organization=designer,
        status=CustomerOrder.Status.CONFIRMED,
        payment_method="cod",
        subtotal=Decimal("1000.00"),
        total=Decimal("1000.00"),
        currency="EGP",
        shipping_snapshot={
            "name": "Customer Recipient",
            "phone": "01011112222",
            "email": "private-customer@example.test",
            "address1": "1 Production Street",
            "city": "Cairo",
            "country": "EG",
        },
    )
    item = OrderItem.objects.create(
        order=order,
        store_product=store_product,
        variant=variant,
        studio_project=project,
        sku=variant.sku,
        title="Wave Tee",
        size="M",
        color_name="Black",
        unit_price=Decimal("500.00"),
        quantity=2,
        line_total=Decimal("1000.00"),
        customization_snapshot={"enabled": True},
    )
    job = ProductionJob.objects.create(order=order, manufacturer=manufacturer_org, status=ProductionJob.Status.QUEUED)
    for kind in [
        ProductionMilestone.Kind.MATERIALS,
        ProductionMilestone.Kind.CUTTING,
        ProductionMilestone.Kind.ASSEMBLY,
        ProductionMilestone.Kind.DECORATION,
        ProductionMilestone.Kind.FINISHING,
    ]:
        ProductionMilestone.objects.create(job=job, kind=kind)
    fulfillment = FulfillmentRecord.objects.create(order=order, status=FulfillmentRecord.Status.WAITING_PRODUCTION)
    return {
        "owner": owner,
        "designer": designer,
        "product": product,
        "garment": garment,
        "artwork_version": artwork_version,
        "zone": zone,
        "store_product": store_product,
        "variant": variant,
        "customer": customer,
        "project": project,
        "customization": customization,
        "order": order,
        "item": item,
        "job": job,
        "fulfillment": fulfillment,
    }


def private_asset(owner, filename, payload=b"private-production-file", *, mime="application/pdf", metadata=None):
    key = default_storage.save(f"manufacturer-tests/{filename}", ContentFile(payload))
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=key,
        original_filename=filename,
        mime_type=mime,
        size_bytes=len(payload),
        access=MediaAsset.Access.PRIVATE,
        metadata=metadata or {},
        uploaded_by=owner,
    )


@pytest.mark.django_db
def test_onboarding_states_are_truthful_and_production_is_not_bypassed(client):
    user = User.objects.create_user(username="no-org", password="password123")
    client.force_login(user)
    response = client.get(reverse("manufacturer"))
    assert response.status_code == 200
    assert b"Create your Manufacturer organization" in response.content

    for index, (verification, application) in enumerate([
        (Organization.VerificationStatus.DRAFT, OnboardingApplication.Status.DRAFT),
        (Organization.VerificationStatus.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED),
        (Organization.VerificationStatus.PENDING, OnboardingApplication.Status.SUBMITTED),
        (Organization.VerificationStatus.REJECTED, OnboardingApplication.Status.REJECTED),
        (Organization.VerificationStatus.SUSPENDED, OnboardingApplication.Status.APPROVED),
    ]):
        u, org, _, _ = manufacturer(f"state-{index}", status=verification, app_status=application)
        client.force_login(u)
        response = client.get(reverse("manufacturer"))
        assert response.status_code == 200
        assert org.get_verification_status_display().encode() in response.content
        assert client.get(reverse("manufacturer-production")).status_code == 403


@pytest.mark.django_db
def test_active_manufacturer_dashboard_uses_real_counts_and_no_catalog_controls(client):
    user, org, _, _ = manufacturer("dashboard")
    _, _, _, _, invitation = invited_rfq(org, prefix="dashboard-rfq")
    client.force_login(user)
    response = client.get(reverse("manufacturer"))
    assert response.status_code == 200
    assert response.context["metrics"]["open_invitations"] == 1
    assert b"Create Product" not in response.content
    assert b"Store / Catalog" not in response.content
    assert invitation.rfq.title.encode() in response.content


@pytest.mark.django_db
def test_tenant_selection_foreign_org_falls_back_without_leakage(client):
    user, first, _, _ = manufacturer("tenant-owner")
    second = Organization.objects.create(kind=Organization.Kind.MANUFACTURER, display_name="Second Factory", email="second@example.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=user)
    ManufacturerProfile.objects.create(organization=second)
    OnboardingApplication.objects.create(organization=second, status=OnboardingApplication.Status.APPROVED)
    Membership.objects.create(organization=second, user=user, role=Membership.Role.OWNER)
    foreign_user, foreign, _, _ = manufacturer("foreign")
    client.force_login(user)
    response = client.get(reverse("manufacturer"), {"org": foreign.id})
    assert response.status_code == 200
    assert response.context["manufacturer_organization"].id == first.id
    assert response.context["manufacturer_organization"].id != foreign.id
    response = client.get(reverse("manufacturer"), {"org": second.id})
    assert response.context["manufacturer_organization"].id == second.id


@pytest.mark.django_db
def test_profile_safe_allowlist_locks_verification_fields_and_audits(client):
    user, org, profile, _ = manufacturer("profile")
    client.force_login(user)
    response = client.post(reverse("manufacturer-profile"), {
        "display_name": "Factory Updated",
        "email": "updated@example.test",
        "phone": "0200000000",
        "website": "https://example.test",
        "address_line1": "New address",
        "address_line2": "",
        "city": "Giza",
        "region": "Giza",
        "country": "EG",
        "primary_contact_person": "New Contact",
        "contact_job_title": "Plant Manager",
        "whatsapp": "01022223333",
        "google_maps_url": "https://maps.example.test/factory",
        "legal_name": "MUTATED LEGAL NAME",
        "commercial_registration": "MUTATED-CR",
        "tax_number": "MUTATED-TAX",
    })
    assert response.status_code == 302
    org.refresh_from_db(); profile.refresh_from_db()
    assert org.display_name == "Factory Updated"
    assert org.legal_name != "MUTATED LEGAL NAME"
    assert profile.commercial_registration == "CR-LOCKED"
    assert profile.tax_number == "TAX-LOCKED"
    assert AuditEvent.objects.filter(action="manufacturer.profile.updated", object_id=str(org.pk)).exists()


@pytest.mark.django_db
def test_team_owner_protection_and_role_permissions():
    owner, org, _, _ = manufacturer("team-owner")
    manager = User.objects.create_user(username="team-manager", email="manager@example.test", password="password123")
    Membership.objects.create(organization=org, user=manager, role=Membership.Role.MANAGER)
    candidate = User.objects.create_user(username="candidate", email="candidate@example.test", password="password123")
    with pytest.raises(PermissionDenied):
        secure_manufacturer_member_upsert(organization=org, actor=manager, user=candidate, role=Membership.Role.OWNER)
    owner_membership = Membership.objects.get(organization=org, user=owner)
    with pytest.raises(PermissionDenied):
        secure_manufacturer_member_deactivate(membership=owner_membership, actor=manager)
    with pytest.raises(ValidationError):
        secure_manufacturer_member_deactivate(membership=owner_membership, actor=owner)
    secure_manufacturer_member_upsert(organization=org, actor=owner, user=candidate, role=Membership.Role.QC)
    assert Membership.objects.get(organization=org, user=candidate).role == Membership.Role.QC


@pytest.mark.django_db
def test_capability_mutation_is_tenant_scoped_and_real():
    owner, org, _, _ = manufacturer("cap-owner")
    other, other_org, _, _ = manufacturer("cap-other")
    capability = create_manufacturer_capability(
        organization=org,
        actor=owner,
        capability_type=ManufacturerCapability.CapabilityType.EMBROIDERY,
        name="Embroidery",
        methods=["machine embroidery"],
    )
    assert capability.listing.organization_id == org.id
    assert capability.capability_type == ManufacturerCapability.CapabilityType.EMBROIDERY
    with pytest.raises(PermissionDenied):
        deactivate_manufacturer_capability(capability=capability, actor=other)


@pytest.mark.django_db
def test_rfq_visibility_quote_ownership_and_designer_selection_boundary(client):
    muser, morg, _, _ = manufacturer("quote-one", role=Membership.Role.PRODUCTION_MANAGER)
    other, other_org, _, _ = manufacturer("quote-two", role=Membership.Role.PRODUCTION_MANAGER)
    designer, designer_org, product, rfq, invitation = invited_rfq(morg, prefix="quote-flow")
    client.force_login(muser)
    response = client.get(reverse("manufacturer-rfq-detail", args=[invitation.id]))
    assert response.status_code == 200
    client.force_login(other)
    assert client.get(reverse("manufacturer-rfq-detail", args=[invitation.id])).status_code == 404
    with pytest.raises(PermissionDenied):
        submit_quote(invitation=invitation, actor=other, unit_price="120", production_lead_days=7)
    quote = submit_quote(invitation=invitation, actor=muser, unit_price="120", production_lead_days=7, minimum_order_quantity=20)
    assert quote.status == ManufacturerQuote.Status.SUBMITTED
    # Manufacturer has no service/UI path that selects itself; selection remains Designer-owned.
    from apps.manufacturer_marketplace.services import select_quote
    with pytest.raises(PermissionDenied):
        select_quote(quote=quote, actor=muser)


@pytest.mark.django_db
def test_manufacturer_invitations_api_requires_active_quote_role(client):
    operator, org, _, _ = manufacturer("api-operator", role=Membership.Role.OPERATOR)
    invited_rfq(org, prefix="api-rfq")
    client.force_login(operator)
    url = reverse("v1:manufacturer-rfq-invitations", args=[org.id])
    assert client.get(url).status_code == 403
    operator.business_memberships.update(role=Membership.Role.PRODUCTION_MANAGER)
    assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_assigned_job_is_tenant_and_role_scoped(client):
    operator, org, _, _ = manufacturer("job-operator", role=Membership.Role.OPERATOR)
    data = assigned_job(org, prefix="assigned")
    other, other_org, _, _ = manufacturer("job-other", role=Membership.Role.OPERATOR)
    client.force_login(operator)
    response = client.get(reverse("manufacturer-production-detail", args=[data["job"].id]))
    assert response.status_code == 200
    assert data["item"].title.encode() in response.content
    assert b"private-customer@example.test" not in response.content
    assert b"cod" not in response.content.lower()
    client.force_login(other)
    assert client.get(reverse("manufacturer-production-detail", args=[data["job"].id])).status_code == 404
    accountant, acct_org, _, _ = manufacturer("job-accountant", role=Membership.Role.ACCOUNTANT)
    acct_data = assigned_job(acct_org, prefix="acct-job")
    client.force_login(accountant)
    assert client.get(reverse("manufacturer-production-detail", args=[acct_data["job"].id])).status_code == 403


@pytest.mark.django_db
def test_private_production_media_allows_exact_assets_and_denies_rights_and_foreign(client):
    operator, org, _, _ = manufacturer("media-operator", role=Membership.Role.OPERATOR)
    data = assigned_job(org, prefix="media-job")
    tech_media = private_asset(data["owner"], "tech-pack.pdf")
    tech = DesignAsset.objects.create(version=data["garment"], kind=DesignAsset.Kind.TECH_PACK, media_asset=tech_media, label="Tech pack")
    source_media = private_asset(data["owner"], "art-source.pdf")
    source = ArtworkAsset.objects.create(version=data["artwork_version"], kind=ArtworkAsset.Kind.SOURCE, media_asset=source_media, label="Source")
    rights_media = private_asset(data["owner"], "rights.pdf")
    rights = ArtworkAsset.objects.create(version=data["artwork_version"], kind=ArtworkAsset.Kind.RIGHTS_EVIDENCE, media_asset=rights_media, label="Rights")
    customer_image = private_asset(
        data["customer"],
        "customer.png",
        payload=b"customer-image",
        mime="image/png",
        metadata={"studio_private_upload": True},
    )
    element = CustomizationElement.objects.create(
        customization=data["customization"],
        decoration_zone=data["zone"],
        kind=CustomizationElement.Kind.IMAGE,
        media_asset=customer_image,
        production_method="print",
        rights_confirmed=True,
        transform={"x": 0.5, "y": 0.35, "scale": 0.2, "rotation": 0},
    )
    client.force_login(operator)
    assert client.get(reverse("manufacturer-production-media", args=[data["job"].id, "design", tech.id])).status_code == 200
    assert client.get(reverse("manufacturer-production-media", args=[data["job"].id, "artwork", source.id])).status_code == 200
    assert client.get(reverse("manufacturer-production-media", args=[data["job"].id, "studio", element.id])).status_code == 200
    assert client.get(reverse("manufacturer-production-media", args=[data["job"].id, "artwork", rights.id])).status_code == 404
    other, _, _, _ = manufacturer("media-outsider", role=Membership.Role.OPERATOR)
    client.force_login(other)
    assert client.get(reverse("manufacturer-production-media", args=[data["job"].id, "design", tech.id])).status_code == 404


@pytest.mark.django_db
def test_production_transitions_qc_packing_and_shipment_use_canonical_record(client):
    operator, org, _, _ = manufacturer("lifecycle", role=Membership.Role.PRODUCTION_MANAGER)
    data = assigned_job(org, prefix="lifecycle-job")
    job = data["job"]
    client.force_login(operator)
    response = client.post(reverse("manufacturer-production-detail", args=[job.id]), {"action": "start"})
    assert response.status_code == 302
    job.refresh_from_db(); assert job.status == ProductionJob.Status.IN_PRODUCTION
    for milestone in job.milestones.all():
        response = client.post(reverse("manufacturer-production-detail", args=[job.id]), {
            "action": "milestone",
            "milestone_id": milestone.id,
            "status": ProductionMilestone.Status.COMPLETED,
            "notes": "Completed on floor",
        })
        assert response.status_code == 302
    response = client.post(reverse("manufacturer-production-detail", args=[job.id]), {"action": "request_qc"})
    assert response.status_code == 302
    job.refresh_from_db(); assert job.status == ProductionJob.Status.QC_PENDING
    response = client.post(reverse("manufacturer-qc", args=[job.id]), {"decision": QCInspection.Decision.PASSED, "notes": "Passed final inspection"})
    assert response.status_code == 302
    job.refresh_from_db(); data["fulfillment"].refresh_from_db()
    assert job.status == ProductionJob.Status.READY
    assert data["fulfillment"].status == FulfillmentRecord.Status.READY_TO_PACK
    response = client.post(reverse("manufacturer-ready-to-ship", args=[job.id]))
    assert response.status_code == 302
    data["fulfillment"].refresh_from_db(); assert data["fulfillment"].status == FulfillmentRecord.Status.PACKED
    response = client.post(reverse("manufacturer-shipment", args=[job.id]), {
        "carrier": "Recorded Carrier",
        "tracking_number": "TRACK-001",
        "tracking_url": "https://tracking.example.test/TRACK-001",
    })
    assert response.status_code == 302
    data["fulfillment"].refresh_from_db()
    assert data["fulfillment"].status == FulfillmentRecord.Status.SHIPPED
    assert data["order"].fulfillment.pk == data["fulfillment"].pk
    assert data["fulfillment"].tracking_number == "TRACK-001"
    assert AuditEvent.objects.filter(action="production.started", object_id=str(job.pk)).exists()


@pytest.mark.django_db
def test_illegal_and_wrong_role_transitions_remain_server_rejected():
    operator, org, _, _ = manufacturer("transition-operator", role=Membership.Role.OPERATOR)
    data = assigned_job(org, prefix="transition-job")
    with pytest.raises(ValidationError):
        request_qc(job=data["job"], actor=operator)
    qc_user = User.objects.create_user(username="only-qc", email="only-qc@example.test", password="password123")
    Membership.objects.create(organization=org, user=qc_user, role=Membership.Role.QC)
    with pytest.raises(PermissionDenied):
        start_production(job=data["job"], actor=qc_user)
    with pytest.raises(ValidationError):
        pack_order(fulfillment=data["fulfillment"], actor=operator)


@pytest.mark.django_db
def test_shipment_surface_minimizes_customer_pii(client):
    operator, org, _, _ = manufacturer("pii", role=Membership.Role.PRODUCTION_MANAGER)
    data = assigned_job(org, prefix="pii-job")
    data["fulfillment"].status = FulfillmentRecord.Status.PACKED
    data["fulfillment"].save(update_fields=["status"])
    client.force_login(operator)
    response = client.get(reverse("manufacturer-shipment", args=[data["job"].id]))
    content = response.content.decode()
    assert "Customer Recipient" in content
    assert "01011112222" in content
    assert "private-customer@example.test" not in content
    assert "cod" not in content.lower()
    assert data["customer"].username not in content


@pytest.mark.django_db
def test_finance_is_manufacturer_tenant_and_role_scoped(client):
    accountant, org, _, _ = manufacturer("finance-acct", role=Membership.Role.ACCOUNTANT)
    account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=org, currency="EGP")
    LedgerEntry.objects.create(account=account, entry_type=LedgerEntry.EntryType.MANUFACTURER_EARNING, amount=Decimal("250.00"), currency="EGP", available_at=timezone.now())
    other, other_org, _, _ = manufacturer("finance-other", role=Membership.Role.ACCOUNTANT)
    other_account = FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=other_org, currency="EGP")
    LedgerEntry.objects.create(account=other_account, entry_type=LedgerEntry.EntryType.MANUFACTURER_EARNING, amount=Decimal("999.00"), currency="EGP", available_at=timezone.now())
    client.force_login(accountant)
    response = client.get(reverse("manufacturer-finance"))
    assert response.status_code == 200
    assert b"250.00" in response.content
    assert b"999.00" not in response.content
    operator = User.objects.create_user(username="finance-operator", email="finance-operator@example.test", password="password123")
    Membership.objects.create(organization=org, user=operator, role=Membership.Role.OPERATOR)
    client.force_login(operator)
    assert client.get(reverse("manufacturer-finance")).status_code == 403


@pytest.mark.django_db
def test_private_manufacturer_routes_are_noindex_and_absent_from_sitemap(client):
    user, org, _, _ = manufacturer("seo")
    client.force_login(user)
    for name in ["manufacturer", "manufacturer-profile", "manufacturer-team", "manufacturer-capabilities", "manufacturer-opportunities", "manufacturer-production", "manufacturer-finance"]:
        response = client.get(reverse(name))
        assert response.status_code == 200
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
        assert b'name="robots" content="noindex, nofollow, noarchive"' in response.content
    sitemap = client.get(reverse("sitemap-xml")).content.decode()
    assert "/manufacturer/" not in sitemap


@pytest.mark.django_db
def test_arabic_rtl_dark_and_theme_preferences_are_reused(client):
    user, org, _, _ = manufacturer("arabic")
    user.theme_preference = User.Theme.DARK
    user.language_preference = User.Language.ARABIC
    user.save(update_fields=["theme_preference", "language_preference"])
    client.force_login(user)
    response = client.get(reverse("manufacturer") + "?lang=ar")
    content = response.content.decode()
    assert response.status_code == 200
    assert 'dir="rtl"' in content
    assert 'data-theme="dark"' in content
    assert "مساحة التصنيع" in content


@pytest.mark.django_db
def test_manufacturer_cannot_access_designer_or_platform_finance_by_portal_selection(client):
    accountant, org, _, _ = manufacturer("finance-boundary", role=Membership.Role.ACCOUNTANT)
    designer_owner, designer, *_ = designer_product("finance-designer")
    FinanceAccount.objects.create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=designer, currency="EGP")
    client.force_login(accountant)
    response = client.get(reverse("manufacturer-finance"), {"org": designer.id})
    assert response.status_code == 200
    assert response.context["manufacturer_organization"].id == org.id
    assert all(row["account"].organization_id == org.id for row in response.context["finance_rows"])
