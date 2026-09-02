import re
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User
from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.audit.models import AuditEvent
from apps.checkout.models import CustomerPurchase
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerListing, ManufacturerQuote, RFQ
from apps.manufacturer_marketplace.services import add_capability, create_rfq, get_or_create_listing, open_rfq, publish_listing, submit_quote
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, OnboardingApplication, Organization, PublicProfileRevision
from apps.organizations.public_profile_services import current_public_profile_data, review_public_profile_revision, save_public_profile_revision, start_public_profile_review, submit_public_profile_revision
from apps.organizations.services import create_designer_onboarding, create_manufacturer_onboarding, review_application, submit_application
from apps.public_inquiries.models import PublicInquiry, PublicInquiryAttachment, PublicInquiryEmailChallenge
from apps.public_inquiries.services import request_email_challenge, submit_public_inquiry, verify_email_challenge
from apps.public_profiles.models import ManufacturerCapabilityVerification, ManufacturerPublicProductApproval, ProfessionalPublicState
from apps.public_profiles.services import approved_manufacturer_products, ensure_public_state, hide_public_profile, request_public_profile_visibility, verify_manufacturer_capability, approve_manufacturer_product
from apps.storefront.models import ProductVariant, StoreProduct, Storefront


ROOT = Path(__file__).resolve().parents[1]


def user(name, *, staff=False):
    return User.objects.create_user(username=name, email=f"{name}@example.test", password="StrongPass123!", is_staff=staff)


def grant(u, *codenames):
    permissions = Permission.objects.filter(codename__in=codenames)
    assert permissions.count() == len(set(codenames))
    u.user_permissions.add(*permissions)


def otp_login(client, u):
    device = TOTPDevice.objects.create(user=u, name=f"v25-{u.pk}", confirmed=True)
    client.force_login(u)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()


def approve_application(application, reviewer):
    submit_application(application=application, actor=application.organization.created_by)
    review_application(application=application, reviewer=reviewer, decision=OnboardingApplication.Status.APPROVED, notes="V2-5 approved")
    application.refresh_from_db(); application.organization.refresh_from_db()
    return application.organization


def designer_org(owner, reviewer, name="V25 Designer"):
    app = create_designer_onboarding(
        user=owner,
        organization_data={"display_name": name, "email": f"{owner.username}.private@example.test", "phone": "+201000000001", "city": "Cairo", "region": "Cairo", "country": "EG"},
        profile_data={"studio_name": name, "terms_accepted": True},
    )
    return approve_application(app, reviewer)


def manufacturer_org(owner, reviewer, name="V25 Factory"):
    app = create_manufacturer_onboarding(
        user=owner,
        organization_data={"display_name": name, "email": f"{owner.username}.private@example.test", "phone": "+201000000002", "city": "Giza", "region": "Giza", "country": "EG"},
        profile_data={"commercial_registration": f"CR-{owner.username}", "terms_accepted": True},
    )
    org = approve_application(app, reviewer)
    org.manufacturer_profile.whatsapp = "+201099999999"
    org.manufacturer_profile.primary_contact_person = "PRIVATE CONTACT PERSON"
    org.manufacturer_profile.save()
    return org


def make_visible(org, *, en=None, ar=""):
    state = ensure_public_state(org)
    state.public_name_en = en or org.display_name
    state.public_name_ar = ar
    state.bio_en = "Approved public biography"
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    return state


def published_product(org, owner, prefix="v25"):
    garment = GarmentDesign.objects.create(organization=org, title=f"{prefix} Garment", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment_version = GarmentDesignVersion.objects.create(design=garment, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    artwork = Artwork.objects.create(organization=org, title=f"{prefix} Artwork", status=Artwork.Status.APPROVED, created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    designed = DesignedProduct.objects.create(organization=org, garment_version=garment_version, artwork_version=artwork_version, title=f"{prefix} Ready", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    storefront = Storefront.objects.create(organization=org, slug=f"{prefix}-store", status=Storefront.Status.PUBLISHED, name_en=f"{prefix} Store")
    product = StoreProduct.objects.create(storefront=storefront, designed_product=designed, slug=f"{prefix}-product", status=StoreProduct.Status.PUBLISHED, title_en=f"{prefix} Product", base_price="700.00", currency="EGP")
    variant = ProductVariant.objects.create(product=product, sku=f"{prefix.upper()}-M", size="M", color_name="Black", color_hex="#111111", stock_quantity=5)
    return garment, artwork, designed, product, variant


@pytest.mark.django_db
def test_visibility_off_is_immediate_and_audited():
    owner, reviewer = user("hide-owner"), user("hide-reviewer", staff=True)
    org = designer_org(owner, reviewer)
    state = make_visible(org)
    hide_public_profile(organization=org, actor=owner)
    state.refresh_from_db()
    assert state.visibility == ProfessionalPublicState.Visibility.HIDDEN
    assert AuditEvent.objects.filter(action="public_profile.visibility.hidden", object_id=str(state.pk)).exists()


@pytest.mark.django_db
def test_visibility_on_requires_moderation_and_approval_publishes():
    owner, reviewer = user("show-owner"), user("show-reviewer", staff=True)
    org = designer_org(owner, reviewer)
    state = ensure_public_state(org)
    request_public_profile_visibility(organization=org, actor=owner)
    state.refresh_from_db()
    revision = org.public_profile_revisions.get()
    assert state.visibility == ProfessionalPublicState.Visibility.PENDING_APPROVAL
    assert revision.status == PublicProfileRevision.Status.SUBMITTED
    start_public_profile_review(revision=revision, reviewer=reviewer)
    review_public_profile_revision(revision=revision, reviewer=reviewer, decision=PublicProfileRevision.Status.APPROVED)
    state.refresh_from_db()
    assert state.visibility == ProfessionalPublicState.Visibility.VISIBLE


@pytest.mark.django_db
def test_pending_and_changes_required_revision_do_not_leak_current_approved_state(client):
    owner, reviewer = user("pending-owner"), user("pending-reviewer", staff=True)
    org = designer_org(owner, reviewer, "Current Designer")
    state = make_visible(org, en="CURRENT PUBLIC NAME")
    payload = current_public_profile_data(org)
    payload["public_state"]["public_name_en"] = "SECRET PENDING NAME"
    revision = save_public_profile_revision(organization=org, actor=owner, proposed_data=payload)
    submit_public_profile_revision(revision=revision, actor=owner)
    detail = client.get(reverse("designer-public-detail", args=[state.slug]))
    assert detail.status_code == 200
    assert "CURRENT PUBLIC NAME" in detail.content.decode()
    assert "SECRET PENDING NAME" not in detail.content.decode()
    start_public_profile_review(revision=revision, reviewer=reviewer)
    review_public_profile_revision(revision=revision, reviewer=reviewer, decision=PublicProfileRevision.Status.CHANGES_REQUIRED, notes="Revise")
    state.refresh_from_db()
    assert state.public_name_en == "CURRENT PUBLIC NAME"


@pytest.mark.django_db
def test_rejected_revision_preserves_current_public_state():
    owner, reviewer = user("reject-owner"), user("reject-reviewer", staff=True)
    org = designer_org(owner, reviewer)
    state = make_visible(org, en="APPROVED NAME")
    payload = current_public_profile_data(org)
    payload["public_state"]["public_name_en"] = "REJECTED NAME"
    revision = save_public_profile_revision(organization=org, actor=owner, proposed_data=payload)
    submit_public_profile_revision(revision=revision, actor=owner)
    start_public_profile_review(revision=revision, reviewer=reviewer)
    review_public_profile_revision(revision=revision, reviewer=reviewer, decision=PublicProfileRevision.Status.REJECTED)
    state.refresh_from_db()
    assert state.public_name_en == "APPROVED NAME"
    assert state.visibility == ProfessionalPublicState.Visibility.VISIBLE


@pytest.mark.django_db
def test_suspended_professional_is_not_public_and_reactivation_does_not_publish_pending(client):
    owner, reviewer = user("suspend-owner"), user("suspend-reviewer", staff=True)
    org = designer_org(owner, reviewer)
    state = make_visible(org)
    org.verification_status = Organization.VerificationStatus.SUSPENDED
    org.save(update_fields=["verification_status"])
    assert client.get(reverse("designer-public-detail", args=[state.slug])).status_code == 404
    org.verification_status = Organization.VerificationStatus.ACTIVE
    org.save(update_fields=["verification_status"])
    state.visibility = ProfessionalPublicState.Visibility.PENDING_APPROVAL
    state.save(update_fields=["visibility"])
    assert client.get(reverse("designer-public-detail", args=[state.slug])).status_code == 404


@pytest.mark.django_db
def test_designer_directory_is_independent_from_storefront_and_private_fields_never_leak(client):
    owner, reviewer = user("directory-owner"), user("directory-reviewer", staff=True)
    org = designer_org(owner, reviewer, "NO STOREFRONT DESIGNER")
    state = make_visible(org)
    response = client.get("/designers/")
    body = response.content.decode()
    assert response.status_code == 200 and "NO STOREFRONT DESIGNER" in body
    assert org.email not in body and org.phone not in body
    detail = client.get(reverse("designer-public-detail", args=[state.slug])).content.decode()
    assert org.email not in detail and org.phone not in detail


@pytest.mark.django_db
def test_manufacturer_public_surface_excludes_private_fields_and_quote_price(client):
    owner, reviewer = user("mfr-private-owner"), user("mfr-private-reviewer", staff=True)
    org = manufacturer_org(owner, reviewer, "SAFE PUBLIC FACTORY")
    state = make_visible(org)
    listing = get_or_create_listing(organization=org, actor=owner)
    listing.headline_en = "Public production partner"
    listing.overview_en = "Public overview"
    listing.save()
    response = client.get(reverse("manufacturer-public-detail", args=[state.slug]))
    body = response.content.decode()
    assert response.status_code == 200
    for secret in [org.email, org.phone, org.manufacturer_profile.whatsapp, "PRIVATE CONTACT PERSON", "150.00"]:
        assert secret not in body


@pytest.mark.django_db
def test_one_legacy_print_capability_can_receive_explicit_dtf_and_dtg_without_inference():
    owner, reviewer = user("cap-owner"), user("cap-reviewer", staff=True)
    org = manufacturer_org(owner, reviewer)
    listing = get_or_create_listing(organization=org, actor=owner)
    capability = add_capability(listing=listing, actor=owner, capability_type="print", name="Digital print")
    assert capability.public_verifications.count() == 0
    dtf = verify_manufacturer_capability(capability=capability, canonical_code=ManufacturerCapabilityVerification.CanonicalCode.DTF, reviewer=reviewer)
    dtg = verify_manufacturer_capability(capability=capability, canonical_code=ManufacturerCapabilityVerification.CanonicalCode.DTG, reviewer=reviewer)
    assert dtf.pk != dtg.pk
    assert set(capability.public_verifications.values_list("canonical_code", flat=True)) == {"dtf", "dtg"}


@pytest.mark.django_db
def test_manufacturer_product_requires_explicit_approval_and_current_designed_product_publication():
    d_owner, m_owner, reviewer = user("prod-designer"), user("prod-mfr"), user("prod-reviewer", staff=True)
    designer = designer_org(d_owner, reviewer)
    manufacturer = manufacturer_org(m_owner, reviewer)
    make_visible(manufacturer)
    _garment, _artwork, designed, product, _variant = published_product(designer, d_owner, "stale")
    assert not approved_manufacturer_products(manufacturer).exists()
    approval = approve_manufacturer_product(manufacturer=manufacturer, store_product=product, reviewer=reviewer)
    assert approved_manufacturer_products(manufacturer).filter(pk=approval.pk).exists()
    designed.status = DesignedProduct.Status.SUSPENDED
    designed.save(update_fields=["status"])
    assert not approved_manufacturer_products(manufacturer).filter(pk=approval.pk).exists()


@pytest.mark.django_db
def test_rfq_and_quote_do_not_create_public_product_approval():
    d_owner, m_owner, reviewer = user("rfq-designer"), user("rfq-mfr"), user("rfq-reviewer", staff=True)
    designer = designer_org(d_owner, reviewer)
    manufacturer = manufacturer_org(m_owner, reviewer)
    _garment, _artwork, designed, _product, _variant = published_product(designer, d_owner, "rfq")
    listing = get_or_create_listing(organization=manufacturer, actor=m_owner)
    listing.headline_en = "Factory"
    listing.save()
    add_capability(listing=listing, actor=m_owner, capability_type="cut_sew", name="Garment")
    publish_listing(listing=listing, actor=m_owner)
    rfq = create_rfq(designer_organization=designer, actor=d_owner, designed_product=designed, title="Private manufacturing request", quantity=100)
    open_rfq(rfq=rfq, actor=d_owner, manufacturer_ids=[manufacturer.pk])
    submit_quote(invitation=rfq.invitations.get(), actor=m_owner, unit_price="150.00", production_lead_days=12, minimum_order_quantity=50)
    assert ManufacturerQuote.objects.count() == 1 and RFQ.objects.count() == 1
    assert ManufacturerPublicProductApproval.objects.count() == 0


@pytest.mark.django_db
def test_public_inquiry_is_separate_and_authenticated_submission_creates_no_commerce_or_quote(client):
    d_owner, reviewer, customer = user("inq-designer"), user("inq-reviewer", staff=True), user("inq-customer")
    designer = designer_org(d_owner, reviewer)
    state = make_visible(designer)
    _garment, _artwork, designed, _product, _variant = published_product(designer, d_owner, "inq")
    client.force_login(customer)
    response = client.post(reverse("designer-public-inquiry", args=[state.slug]), {"action": "submit", "work_ref": f"ready_product:{designed.pk}", "quantity": "3", "sizes": "M,L", "colors": "Black", "requirements": "Need event pieces"})
    assert response.status_code == 302
    inquiry = PublicInquiry.objects.get()
    assert inquiry.sender_user == customer and inquiry.ready_product == designed and inquiry.status == PublicInquiry.Status.SUBMITTED
    assert RFQ.objects.count() == 0 and ManufacturerQuote.objects.count() == 0 and CustomerPurchase.objects.count() == 0


@pytest.mark.django_db
def test_anonymous_unverified_final_submission_is_denied(client):
    d_owner, reviewer = user("anon-designer"), user("anon-reviewer", staff=True)
    designer = designer_org(d_owner, reviewer)
    state = make_visible(designer)
    _garment, _artwork, designed, _product, _variant = published_product(designer, d_owner, "anon")
    response = client.post(reverse("designer-public-inquiry", args=[state.slug]), {"action": "submit", "email": "anon@example.test", "work_ref": f"ready_product:{designed.pk}", "quantity": "1"})
    assert response.status_code == 200
    assert PublicInquiry.objects.count() == 0


@pytest.mark.django_db
def test_email_otp_is_hashed_session_bound_consumed_and_allows_verified_submission(client):
    cache.clear(); mail.outbox = []
    d_owner, reviewer = user("otp-designer"), user("otp-reviewer", staff=True)
    designer = designer_org(d_owner, reviewer)
    state = make_visible(designer)
    _garment, _artwork, designed, _product, _variant = published_product(designer, d_owner, "otp")
    url = reverse("designer-public-inquiry", args=[state.slug])
    sent = client.post(url, {"action": "send_otp", "email": "verified@example.test"})
    assert sent.status_code == 200 and len(mail.outbox) == 1
    otp = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
    challenge = PublicInquiryEmailChallenge.objects.latest("id")
    assert otp not in challenge.otp_hash
    verified = client.post(url, {"action": "verify_otp", "email": "verified@example.test", "otp": otp, "challenge_reference": str(challenge.reference)})
    assert verified.status_code == 200
    submitted = client.post(url, {"action": "submit", "email": "verified@example.test", "work_ref": f"ready_product:{designed.pk}", "quantity": "2"})
    assert submitted.status_code == 302
    challenge.refresh_from_db()
    assert challenge.verified_at and challenge.consumed_at
    assert PublicInquiry.objects.get().sender_email_verified is True


@pytest.mark.django_db
def test_otp_expiry_attempt_limit_and_request_rate_limit(client):
    cache.clear(); mail.outbox = []
    request = client.get("/").wsgi_request
    challenge = request_email_challenge(request=request, email="limits@example.test")
    otp = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
    challenge.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    challenge.save(update_fields=["expires_at"])
    with pytest.raises(ValidationError):
        verify_email_challenge(request=request, reference=challenge.reference, email=challenge.email, otp=otp)
    cache.clear()
    for index in range(3):
        req = client.get("/").wsgi_request
        request_email_challenge(request=req, email="ratelimit@example.test")
    req = client.get("/").wsgi_request
    with pytest.raises(ValidationError):
        request_email_challenge(request=req, email="ratelimit@example.test")


@pytest.mark.django_db
def test_manufacturer_inquiry_rechecks_stale_underlying_designed_product(client):
    d_owner, m_owner, reviewer, customer = user("mi-designer"), user("mi-mfr"), user("mi-reviewer", staff=True), user("mi-customer")
    designer = designer_org(d_owner, reviewer)
    manufacturer = manufacturer_org(m_owner, reviewer)
    state = make_visible(manufacturer)
    _garment, _artwork, designed, product, _variant = published_product(designer, d_owner, "mi")
    approval = approve_manufacturer_product(manufacturer=manufacturer, store_product=product, reviewer=reviewer)
    client.force_login(customer)
    url = reverse("manufacturer-public-inquiry", args=[state.slug])
    ok = client.post(url, {"action": "submit", "product_approval_id": str(approval.pk), "quantity": "10", "delivery_city": "Cairo", "delivery_country": "EG"})
    assert ok.status_code == 302
    PublicInquiry.objects.all().delete()
    designed.status = DesignedProduct.Status.ARCHIVED
    designed.save(update_fields=["status"])
    denied = client.post(url, {"action": "submit", "product_approval_id": str(approval.pk), "quantity": "10"})
    assert denied.status_code == 200 and PublicInquiry.objects.count() == 0


@pytest.mark.django_db
def test_private_attachment_is_private_and_only_participants_can_access(client):
    d_owner, reviewer, customer = user("attach-designer"), user("attach-reviewer", staff=True), user("attach-customer")
    designer = designer_org(d_owner, reviewer)
    state = make_visible(designer)
    _garment, _artwork, designed, _product, _variant = published_product(designer, d_owner, "attach")
    client.force_login(customer)
    upload = SimpleUploadedFile("brief.pdf", b"%PDF-1.4\nV2-5 private brief\n", content_type="application/pdf")
    response = client.post(reverse("designer-public-inquiry", args=[state.slug]), {"action": "submit", "work_ref": f"ready_product:{designed.pk}", "quantity": "1", "attachment": upload})
    assert response.status_code == 302
    attachment = PublicInquiryAttachment.objects.select_related("media_asset").get()
    assert attachment.media_asset.access == MediaAsset.Access.PRIVATE
    media_url = reverse("public-inquiry-attachment-media", args=[attachment.pk])
    assert client.get(media_url).status_code == 200
    from django.test import Client
    outsider = Client()
    assert outsider.get(media_url).status_code == 404
    client.force_login(d_owner)
    assert client.get(media_url).status_code == 200


@pytest.mark.django_db
def test_non_manager_member_cannot_manage_manufacturer_public_profile_or_inquiries(client):
    owner, reviewer, operator = user("perm-owner"), user("perm-reviewer", staff=True), user("perm-operator")
    org = manufacturer_org(owner, reviewer)
    Membership.objects.create(organization=org, user=operator, role=Membership.Role.OPERATOR, is_active=True)
    client.force_login(operator)
    assert client.get(f"/manufacturer/public-profile/?org={org.pk}").status_code == 403
    assert client.get(f"/manufacturer/public-inquiries/?org={org.pk}").status_code == 403


@pytest.mark.django_db
def test_staff_maneg_moderation_requires_permissions_and_actions_are_audited(client):
    owner, reviewer, staff = user("maneg-owner"), user("maneg-reviewer", staff=True), user("maneg-staff", staff=True)
    org = designer_org(owner, reviewer)
    request_public_profile_visibility(organization=org, actor=owner)
    revision = org.public_profile_revisions.get()
    otp_login(client, staff)
    queue = reverse("fabinzi_admin:maneg-v2-5-public-profiles")
    assert client.get(queue).status_code == 403
    grant(staff, "view_publicprofilerevision", "change_publicprofilerevision")
    assert client.get(queue).status_code == 200
    detail = reverse("fabinzi_admin:maneg-v2-5-public-profile-detail", args=[revision.pk])
    assert client.post(detail, {"action": "start"}).status_code == 302
    assert client.post(detail, {"action": "approve", "notes": "Approved in Control Center"}).status_code == 302
    assert AuditEvent.objects.filter(action="public_profile.revision.approved", object_id=str(revision.pk)).exists()


@pytest.mark.django_db
def test_hidden_and_suspended_profiles_leave_sitemap_and_public_metadata_contains_only_public_facts(client):
    owner, reviewer = user("seo-owner"), user("seo-reviewer", staff=True)
    org = manufacturer_org(owner, reviewer, "SEO PUBLIC FACTORY")
    state = make_visible(org)
    listing = get_or_create_listing(organization=org, actor=owner)
    listing.headline_en = "Public headline"; listing.overview_en = "Public overview"; listing.save()
    detail_url = reverse("manufacturer-public-detail", args=[state.slug])
    body = client.get(detail_url).content.decode()
    assert '"@type":"Organization"' in body and '"@type":"BreadcrumbList"' in body
    assert org.email not in body and org.phone not in body and org.manufacturer_profile.whatsapp not in body
    sitemap = client.get("/sitemap.xml").content.decode()
    assert detail_url in sitemap
    hide_public_profile(organization=org, actor=owner)
    assert client.get(detail_url).status_code == 404
    assert detail_url not in client.get("/sitemap.xml").content.decode()


@pytest.mark.django_db
def test_public_directories_are_bilingual_rtl_and_responsive_css_exists(client):
    owner, reviewer = user("rtl-owner"), user("rtl-reviewer", staff=True)
    org = designer_org(owner, reviewer)
    make_visible(org, ar="مصمم تجريبي")
    response = client.get("/designers/?lang=ar")
    body = response.content.decode()
    assert response.status_code == 200
    assert '<html lang="ar" dir="rtl"' in body
    assert "مصمم تجريبي" in body
    css = (ROOT / "static/css/v2-5-public.css").read_text()
    assert "@media(max-width:760px)" in css


@pytest.mark.django_db
def test_manufacturer_public_page_never_exposes_store_product_retail_price(client):
    d_owner, m_owner, reviewer = user("price-designer"), user("price-mfr"), user("price-reviewer", staff=True)
    designer = designer_org(d_owner, reviewer)
    manufacturer = manufacturer_org(m_owner, reviewer)
    state = make_visible(manufacturer)
    _garment, _artwork, _designed, product, _variant = published_product(designer, d_owner, "price")
    product.base_price = "98765.43"; product.save(update_fields=["base_price"])
    approve_manufacturer_product(manufacturer=manufacturer, store_product=product, reviewer=reviewer)
    body = client.get(reverse("manufacturer-public-detail", args=[state.slug])).content.decode()
    assert "98765.43" not in body


@pytest.mark.django_db
def test_public_inquiry_attachment_and_status_routes_are_noindex(client):
    robots = client.get("/robots.txt").content.decode()
    assert "Disallow: /inquiry/media/" in robots
    assert "Disallow: /inquiry/status/" in robots
