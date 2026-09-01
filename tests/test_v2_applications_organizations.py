import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.manufacturer_marketplace.models import ManufacturerListing
from apps.organizations.designer_services import update_active_designer_profile
from apps.organizations.manufacturer_services import update_active_manufacturer_profile
from apps.organizations.models import (
    Membership,
    OnboardingApplication,
    Organization,
    PublicProfileRevision,
)
from apps.organizations.public_profile_services import (
    current_public_profile_data,
    review_public_profile_revision,
    save_public_profile_revision,
    submit_public_profile_revision,
)
from apps.organizations.services import (
    create_designer_onboarding,
    create_manufacturer_onboarding,
    review_application,
    submit_application,
)


ROOT = Path(__file__).resolve().parents[1]


def _user(name, *, staff=False):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.com",
        password="StrongPass123!",
        is_staff=staff,
    )


def _designer_application(owner, *, name="V2 Designer"):
    return create_designer_onboarding(
        user=owner,
        organization_data={
            "display_name": name,
            "email": f"{owner.username}.studio@example.com",
            "city": "Cairo",
            "region": "Cairo",
            "country": "EG",
        },
        profile_data={
            "studio_name": name,
            "terms_accepted": True,
        },
    )


def _manufacturer_application(owner, *, name="V2 Factory"):
    return create_manufacturer_onboarding(
        user=owner,
        organization_data={
            "display_name": name,
            "email": f"{owner.username}.factory@example.com",
            "city": "Cairo",
            "region": "Cairo",
            "country": "EG",
        },
        profile_data={
            "commercial_registration": f"CR-{owner.username}",
            "terms_accepted": True,
        },
    )


def _approve(application, reviewer):
    submit_application(application=application, actor=application.organization.created_by)
    review_application(
        application=application,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.APPROVED,
        notes="Approved for V2-2 test",
    )
    application.refresh_from_db()
    application.organization.refresh_from_db()
    return application


@pytest.mark.django_db
def test_customer_can_submit_designer_application_through_web(client):
    owner = _user("v22-designer-submit")
    application = _designer_application(owner)
    client.force_login(owner)

    response = client.post(f"/onboarding/{application.pk}/submit/")

    assert response.status_code == 302
    application.refresh_from_db()
    application.organization.refresh_from_db()
    assert application.status == OnboardingApplication.Status.SUBMITTED
    assert application.organization.verification_status == Organization.VerificationStatus.PENDING
    assert application.review_target_at == application.submitted_at + timedelta(hours=27)


@pytest.mark.django_db
def test_customer_can_submit_manufacturer_application_through_web(client):
    owner = _user("v22-manufacturer-submit")
    application = _manufacturer_application(owner)
    client.force_login(owner)

    response = client.post(f"/onboarding/{application.pk}/submit/")

    assert response.status_code == 302
    application.refresh_from_db()
    application.organization.refresh_from_db()
    assert application.status == OnboardingApplication.Status.SUBMITTED
    assert application.organization.verification_status == Organization.VerificationStatus.PENDING


@pytest.mark.django_db
def test_pending_and_rejected_applications_do_not_activate_professional_navigation(client):
    pending_owner = _user("v22-pending-designer")
    pending = _designer_application(pending_owner)
    submit_application(application=pending, actor=pending_owner)

    client.force_login(pending_owner)
    pending_page = client.get("/")
    assert pending_page.status_code == 200
    assert 'href="/designer/"' not in pending_page.content.decode()

    rejected_owner = _user("v22-rejected-manufacturer")
    reviewer = _user("v22-reject-reviewer", staff=True)
    rejected = _manufacturer_application(rejected_owner)
    submit_application(application=rejected, actor=rejected_owner)
    review_application(
        application=rejected,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.REJECTED,
        notes="Not approved",
    )

    client.force_login(rejected_owner)
    rejected_page = client.get("/")
    assert rejected_page.status_code == 200
    assert 'href="/manufacturer/"' not in rejected_page.content.decode()


@pytest.mark.django_db
def test_approved_application_activates_only_the_intended_professional_path(client):
    owner = _user("v22-approved-designer")
    reviewer = _user("v22-approved-reviewer", staff=True)
    application = _approve(_designer_application(owner), reviewer)

    membership = Membership.objects.get(organization=application.organization, user=owner)
    assert membership.is_active
    assert membership.role == Membership.Role.OWNER
    assert application.organization.verification_status == Organization.VerificationStatus.ACTIVE

    client.force_login(owner)
    page = client.get("/")
    html = page.content.decode()
    assert 'href="/designer/"' in html
    assert 'href="/manufacturer/"' not in html


@pytest.mark.django_db
def test_active_organization_and_active_membership_are_both_required_and_suspension_removes_role(client):
    owner = _user("v22-role-gates")
    reviewer = _user("v22-role-gates-reviewer", staff=True)
    application = _approve(_manufacturer_application(owner), reviewer)
    organization = application.organization
    membership = Membership.objects.get(organization=organization, user=owner)

    client.force_login(owner)
    assert 'href="/manufacturer/"' in client.get("/").content.decode()

    membership.is_active = False
    membership.save(update_fields=["is_active"])
    assert 'href="/manufacturer/"' not in client.get("/").content.decode()

    membership.is_active = True
    membership.save(update_fields=["is_active"])
    organization.verification_status = Organization.VerificationStatus.SUSPENDED
    organization.save(update_fields=["verification_status"])
    assert 'href="/manufacturer/"' not in client.get("/").content.decode()


@pytest.mark.django_db
def test_duplicate_professional_application_for_same_role_is_rejected():
    owner = _user("v22-duplicate")
    application = _designer_application(owner)
    submit_application(application=application, actor=owner)

    with pytest.raises(ValidationError):
        _designer_application(owner, name="Duplicate Studio")

    assert OnboardingApplication.objects.filter(
        organization__created_by=owner,
        organization__kind=Organization.Kind.DESIGNER,
    ).count() == 1


@pytest.mark.django_db
def test_application_ownership_and_reviewer_boundaries():
    owner = _user("v22-app-owner")
    outsider = _user("v22-app-outsider")
    application = _designer_application(owner)

    with pytest.raises(PermissionDenied):
        submit_application(application=application, actor=outsider)

    submit_application(application=application, actor=owner)
    with pytest.raises(PermissionDenied):
        review_application(
            application=application,
            reviewer=outsider,
            decision=OnboardingApplication.Status.APPROVED,
        )


@pytest.mark.django_db
def test_designer_public_revision_has_draft_submitted_and_approved_states():
    owner = _user("v22-designer-revision")
    reviewer = _user("v22-designer-revision-reviewer", staff=True)
    application = _approve(_designer_application(owner, name="Approved Studio"), reviewer)
    organization = application.organization

    payload = current_public_profile_data(organization)
    payload["organization"]["display_name"] = "Proposed Studio"
    payload["profile"]["studio_name"] = "Proposed Studio"
    draft = save_public_profile_revision(organization=organization, actor=owner, proposed_data=payload)

    assert draft.status == PublicProfileRevision.Status.DRAFT
    organization.refresh_from_db()
    assert organization.display_name == "Approved Studio"

    submit_public_profile_revision(revision=draft, actor=owner)
    draft.refresh_from_db()
    assert draft.status == PublicProfileRevision.Status.SUBMITTED
    organization.refresh_from_db()
    assert organization.display_name == "Approved Studio"

    with pytest.raises(PermissionDenied):
        review_public_profile_revision(
            revision=draft,
            reviewer=owner,
            decision=PublicProfileRevision.Status.APPROVED,
        )

    review_public_profile_revision(
        revision=draft,
        reviewer=reviewer,
        decision=PublicProfileRevision.Status.APPROVED,
        notes="Public identity approved",
    )
    organization.refresh_from_db()
    organization.designer_profile.refresh_from_db()
    assert organization.display_name == "Proposed Studio"
    assert organization.designer_profile.studio_name == "Proposed Studio"


@pytest.mark.django_db
def test_pending_and_rejected_manufacturer_revision_never_replaces_public_content_or_leaks_private_data(client):
    owner = _user("v22-private-manufacturer")
    reviewer = _user("v22-private-reviewer", staff=True)
    application = _approve(_manufacturer_application(owner, name="Approved Factory"), reviewer)
    organization = application.organization
    listing = ManufacturerListing.objects.create(
        organization=organization,
        status=ManufacturerListing.Status.PUBLISHED,
        headline_en="Published production partner",
        overview_en="Approved public overview",
    )

    update_active_manufacturer_profile(
        organization=organization,
        actor=owner,
        organization_data={
            "display_name": "Pending Factory",
            "email": "private-ops@example.com",
            "phone": "PRIVATE-PHONE-0100",
            "website": "https://pending-factory.example.com",
            "address_line1": "PRIVATE FACTORY ADDRESS",
            "address_line2": "PRIVATE FLOOR",
            "city": "Giza",
            "region": "Giza",
            "country": "EG",
            "legal_name": "PRIVATE LEGAL NAME",
        },
        profile_data={
            "google_maps_url": "https://maps.example.com/private-factory",
            "primary_contact_person": "PRIVATE CONTACT PERSON",
            "contact_job_title": "PRIVATE ROLE",
            "whatsapp": "PRIVATE-WHATSAPP",
            "commercial_registration": "PRIVATE-CR",
            "tax_number": "PRIVATE-TAX",
        },
    )

    organization.refresh_from_db()
    organization.manufacturer_profile.refresh_from_db()
    assert organization.display_name == "Approved Factory"
    assert organization.email == "private-ops@example.com"
    assert organization.manufacturer_profile.whatsapp == "PRIVATE-WHATSAPP"

    revision = PublicProfileRevision.objects.get(organization=organization, status=PublicProfileRevision.Status.SUBMITTED)
    serialized_revision = repr(revision.proposed_data)
    for secret in (
        "private-ops@example.com",
        "PRIVATE-PHONE-0100",
        "PRIVATE FACTORY ADDRESS",
        "PRIVATE FLOOR",
        "PRIVATE CONTACT PERSON",
        "PRIVATE ROLE",
        "PRIVATE-WHATSAPP",
        "PRIVATE-CR",
        "PRIVATE-TAX",
        "private-factory",
    ):
        assert secret not in serialized_revision

    public_pending = client.get(f"/manufacturers/{listing.pk}/")
    pending_html = public_pending.content.decode()
    assert public_pending.status_code == 200
    assert "Approved Factory" in pending_html
    assert "Pending Factory" not in pending_html
    assert "PRIVATE-WHATSAPP" not in pending_html
    assert "private-ops@example.com" not in pending_html

    review_public_profile_revision(
        revision=revision,
        reviewer=reviewer,
        decision=PublicProfileRevision.Status.REJECTED,
        notes="Keep current approved identity",
    )
    organization.refresh_from_db()
    assert organization.display_name == "Approved Factory"
    public_rejected = client.get(f"/manufacturers/{listing.pk}/")
    rejected_html = public_rejected.content.decode()
    assert "Approved Factory" in rejected_html
    assert "Pending Factory" not in rejected_html


@pytest.mark.django_db
def test_profile_update_service_submits_public_revision_without_overwriting_approved_designer_content():
    owner = _user("v22-designer-service-revision")
    reviewer = _user("v22-designer-service-reviewer", staff=True)
    application = _approve(_designer_application(owner, name="Current Designer"), reviewer)
    organization = application.organization

    update_active_designer_profile(
        organization=organization,
        actor=owner,
        organization_data={
            "display_name": "Pending Designer",
            "email": "private-designer@example.com",
            "phone": "01000000000",
            "website": "https://pending-designer.example.com",
            "address_line1": "Private address",
            "address_line2": "",
            "city": "Alexandria",
            "region": "Alexandria",
            "country": "EG",
        },
        profile_data={
            "studio_name": "Pending Designer",
            "portfolio_url": "https://portfolio.example.com",
            "social_links": {"instagram": "https://instagram.com/fabinzi-test"},
        },
    )

    organization.refresh_from_db()
    organization.designer_profile.refresh_from_db()
    assert organization.display_name == "Current Designer"
    assert organization.designer_profile.studio_name == "Current Designer"
    assert organization.email == "private-designer@example.com"
    revision = PublicProfileRevision.objects.get(organization=organization, status=PublicProfileRevision.Status.SUBMITTED)
    assert revision.proposed_data["organization"]["display_name"] == "Pending Designer"


@pytest.mark.django_db
def test_v2_1_public_shell_surfaces_remain_available(client):
    for path in ("/", "/discover/", "/how-it-works/", "/designers/", "/manufacturers/"):
        response = client.get(path)
        assert response.status_code == 200


def test_canonical_brand_master_hashes_are_unchanged():
    expected = {
        "static/brand/fabinzi-logo.svg": "27fd3226825c47717b0899cbdb76bdaf9c38a0d7fea2e88257c8db8bf71b4e1b",
        "static/brand/fabinzi-icon.svg": "6d5732cfd6014fcb0fa6029241e87d793814ce430934cd632be82289d6219b61",
    }
    for relative_path, digest in expected.items():
        assert hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() == digest
