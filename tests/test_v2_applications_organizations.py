import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User
from apps.audit.models import AuditEvent
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
    start_public_profile_review,
    submit_public_profile_revision,
)
from apps.organizations.services import (
    create_designer_onboarding,
    create_manufacturer_onboarding,
    review_application,
    submit_application,
)
from apps.platform_ops.models import ApplicationReviewConfiguration


ROOT = Path(__file__).resolve().parents[1]


def _user(name, *, staff=False):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.com",
        password="StrongPass123!",
        is_staff=staff,
    )


def _grant(user, *codenames):
    permissions = Permission.objects.filter(codename__in=codenames)
    assert permissions.count() == len(set(codenames))
    user.user_permissions.add(*permissions)


def _otp_login(client, user):
    device = TOTPDevice.objects.create(user=user, name=f"v22-{user.pk}", confirmed=True)
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()


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
def test_default_review_target_is_persisted_27_hours_and_does_not_auto_approve(client):
    config = ApplicationReviewConfiguration.objects.get(singleton_key=1)
    assert config.application_initial_review_target_hours == 27

    owner = _user("v22-default-sla")
    application = _designer_application(owner)
    client.force_login(owner)
    assert client.post(f"/onboarding/{application.pk}/submit/").status_code == 302

    application.refresh_from_db()
    assert application.status == OnboardingApplication.Status.SUBMITTED
    assert application.initial_review_target_at == application.submitted_at + timedelta(hours=27)
    assert application.review_target_at == application.initial_review_target_at

    application.initial_review_target_at = timezone.now() - timedelta(hours=1)
    application.save(update_fields=["initial_review_target_at"])
    application.refresh_from_db()
    assert application.status == OnboardingApplication.Status.SUBMITTED
    assert application.organization.verification_status == Organization.VerificationStatus.PENDING


@pytest.mark.django_db
def test_maneg_review_configuration_changes_only_future_first_submission_targets(client):
    first_owner = _user("v22-sla-first")
    first = _designer_application(first_owner)
    submit_application(application=first, actor=first_owner)
    first.refresh_from_db()
    original_target = first.initial_review_target_at

    operator = _user("v22-sla-operator", staff=True)
    _grant(
        operator,
        "view_applicationreviewconfiguration",
        "change_applicationreviewconfiguration",
    )
    _otp_login(client, operator)
    config = ApplicationReviewConfiguration.objects.get(singleton_key=1)
    change_url = reverse(
        "fabinzi_admin:platform_ops_applicationreviewconfiguration_change",
        args=[config.pk],
    )
    response = client.post(
        change_url,
        {"application_initial_review_target_hours": "36", "_save": "Save"},
    )
    assert response.status_code == 302
    config.refresh_from_db()
    assert config.application_initial_review_target_hours == 36
    assert AuditEvent.objects.filter(
        action="control_center.application_review_configuration.updated",
        object_id=str(config.pk),
    ).exists()

    first.refresh_from_db()
    assert first.initial_review_target_at == original_target

    second_owner = _user("v22-sla-second")
    second = _manufacturer_application(second_owner)
    submit_application(application=second, actor=second_owner)
    second.refresh_from_db()
    assert second.initial_review_target_at == second.submitted_at + timedelta(hours=36)

    reviewer = _user("v22-sla-reviewer", staff=True)
    review_application(
        application=second,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.REVISION_REQUIRED,
        notes="Please revise",
    )
    target_before_resubmission = second.initial_review_target_at
    submit_application(application=second, actor=second_owner)
    second.refresh_from_db()
    assert second.initial_review_target_at == target_before_resubmission


@pytest.mark.django_db
def test_unauthorized_staff_cannot_change_review_configuration(client):
    viewer = _user("v22-sla-viewer", staff=True)
    _grant(viewer, "view_applicationreviewconfiguration")
    _otp_login(client, viewer)
    config = ApplicationReviewConfiguration.objects.get(singleton_key=1)
    response = client.post(
        reverse(
            "fabinzi_admin:platform_ops_applicationreviewconfiguration_change",
            args=[config.pk],
        ),
        {"application_initial_review_target_hours": "72", "_save": "Save"},
    )
    assert response.status_code == 403
    config.refresh_from_db()
    assert config.application_initial_review_target_hours == 27


@pytest.mark.django_db
def test_duplicate_open_and_approved_same_role_applications_are_blocked():
    owner = _user("v22-duplicate")
    draft = _designer_application(owner)
    with pytest.raises(ValidationError):
        _designer_application(owner, name="Duplicate Draft Studio")

    submit_application(application=draft, actor=owner)
    with pytest.raises(ValidationError):
        _designer_application(owner, name="Duplicate Submitted Studio")

    reviewer = _user("v22-duplicate-reviewer", staff=True)
    review_application(
        application=draft,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.REVISION_REQUIRED,
    )
    with pytest.raises(ValidationError):
        _designer_application(owner, name="Duplicate Revision Studio")

    submit_application(application=draft, actor=owner)
    review_application(
        application=draft,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.APPROVED,
    )
    with pytest.raises(ValidationError):
        _designer_application(owner, name="Duplicate Approved Studio")


@pytest.mark.django_db
def test_rejected_application_can_reapply_through_supported_web_path_without_rewriting_history(client):
    owner = _user("v22-reapply")
    reviewer = _user("v22-reapply-reviewer", staff=True)
    rejected = _designer_application(owner, name="Rejected Studio")
    submit_application(application=rejected, actor=owner)
    review_application(
        application=rejected,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.REJECTED,
        notes="Final rejection",
    )
    old_application_id = rejected.pk
    old_organization_id = rejected.organization_id

    client.force_login(owner)
    state_page = client.get("/designer/")
    assert state_page.status_code == 200
    assert "Start a new application" in state_page.content.decode()
    response = client.post(
        f"/onboarding/{rejected.pk}/submit/",
        {"action": "reapply"},
    )
    assert response.status_code == 302

    rejected.refresh_from_db()
    rejected.organization.refresh_from_db()
    assert rejected.pk == old_application_id
    assert rejected.organization_id == old_organization_id
    assert rejected.status == OnboardingApplication.Status.REJECTED
    assert rejected.organization.verification_status == Organization.VerificationStatus.REJECTED

    attempts = OnboardingApplication.objects.filter(
        organization__created_by=owner,
        organization__kind=Organization.Kind.DESIGNER,
    ).order_by("id")
    assert attempts.count() == 2
    new_application = attempts.exclude(pk=rejected.pk).get()
    assert new_application.status == OnboardingApplication.Status.DRAFT
    assert new_application.organization_id != old_organization_id
    assert new_application.organization.verification_status == Organization.VerificationStatus.DRAFT
    assert new_application.initial_review_target_at is None
    assert client.session["designer_organization_id"] == new_application.organization_id
    assert AuditEvent.objects.filter(
        action="onboarding.reapplication.created",
        object_id=str(new_application.pk),
    ).exists()

    with pytest.raises(ValidationError):
        _designer_application(owner, name="Concurrent Third Studio")


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
def test_approved_application_activates_only_intended_professional_path(client):
    owner = _user("v22-approved-designer")
    reviewer = _user("v22-approved-reviewer", staff=True)
    application = _approve(_designer_application(owner), reviewer)
    membership = Membership.objects.get(organization=application.organization, user=owner)
    assert membership.is_active and membership.role == Membership.Role.OWNER
    client.force_login(owner)
    html = client.get("/").content.decode()
    assert 'href="/designer/"' in html
    assert 'href="/manufacturer/"' not in html


@pytest.mark.django_db
def test_public_profile_full_state_machine_applies_only_after_approval():
    owner = _user("v22-designer-revision")
    reviewer = _user("v22-designer-revision-reviewer", staff=True)
    application = _approve(_designer_application(owner, name="Approved Studio"), reviewer)
    organization = application.organization

    payload = current_public_profile_data(organization)
    payload["organization"]["display_name"] = "Proposed Studio"
    payload["profile"]["studio_name"] = "Proposed Studio"
    revision = save_public_profile_revision(
        organization=organization,
        actor=owner,
        proposed_data=payload,
    )
    assert revision.status == PublicProfileRevision.Status.DRAFT
    assert organization.display_name == "Approved Studio"

    submit_public_profile_revision(revision=revision, actor=owner)
    revision.refresh_from_db(); organization.refresh_from_db()
    assert revision.status == PublicProfileRevision.Status.SUBMITTED
    assert organization.display_name == "Approved Studio"

    with pytest.raises(PermissionDenied):
        start_public_profile_review(revision=revision, reviewer=owner)
    with pytest.raises(ValidationError):
        review_public_profile_revision(
            revision=revision,
            reviewer=reviewer,
            decision=PublicProfileRevision.Status.APPROVED,
        )

    start_public_profile_review(revision=revision, reviewer=reviewer)
    revision.refresh_from_db(); organization.refresh_from_db()
    assert revision.status == PublicProfileRevision.Status.UNDER_REVIEW
    assert organization.display_name == "Approved Studio"

    review_public_profile_revision(
        revision=revision,
        reviewer=reviewer,
        decision=PublicProfileRevision.Status.APPROVED,
        notes="Public identity approved",
    )
    revision.refresh_from_db(); organization.refresh_from_db()
    organization.designer_profile.refresh_from_db()
    assert revision.status == PublicProfileRevision.Status.APPROVED
    assert organization.display_name == "Proposed Studio"
    assert organization.designer_profile.studio_name == "Proposed Studio"


@pytest.mark.django_db
def test_changes_required_is_editable_and_resubmits_same_revision_without_public_mutation():
    owner = _user("v22-changes-owner")
    reviewer = _user("v22-changes-reviewer", staff=True)
    organization = _approve(_designer_application(owner, name="Current Studio"), reviewer).organization

    payload = current_public_profile_data(organization)
    payload["organization"]["display_name"] = "First Proposal"
    revision = save_public_profile_revision(organization=organization, actor=owner, proposed_data=payload)
    submit_public_profile_revision(revision=revision, actor=owner)
    start_public_profile_review(revision=revision, reviewer=reviewer)
    review_public_profile_revision(
        revision=revision,
        reviewer=reviewer,
        decision=PublicProfileRevision.Status.CHANGES_REQUIRED,
        notes="Use the registered public name",
    )
    revision.refresh_from_db(); organization.refresh_from_db()
    assert revision.status == PublicProfileRevision.Status.CHANGES_REQUIRED
    assert revision.review_notes == "Use the registered public name"
    assert organization.display_name == "Current Studio"
    revision_id = revision.pk

    corrected = dict(revision.proposed_data)
    corrected["organization"] = dict(corrected["organization"])
    corrected["organization"]["display_name"] = "Corrected Proposal"
    same_revision = save_public_profile_revision(
        organization=organization,
        actor=owner,
        proposed_data=corrected,
    )
    assert same_revision.pk == revision_id
    assert same_revision.status == PublicProfileRevision.Status.CHANGES_REQUIRED
    submit_public_profile_revision(revision=same_revision, actor=owner)
    same_revision.refresh_from_db()
    assert same_revision.pk == revision_id
    assert same_revision.status == PublicProfileRevision.Status.SUBMITTED
    assert organization.public_profile_revisions.filter(
        status__in=PublicProfileRevision.OPEN_STATUSES
    ).count() == 1

    start_public_profile_review(revision=same_revision, reviewer=reviewer)
    review_public_profile_revision(
        revision=same_revision,
        reviewer=reviewer,
        decision=PublicProfileRevision.Status.APPROVED,
        notes="Corrected identity approved",
    )
    organization.refresh_from_db()
    assert organization.display_name == "Corrected Proposal"

    actions = set(
        AuditEvent.objects.filter(object_id=str(revision_id)).values_list("action", flat=True)
    )
    assert {
        "public_profile.revision.draft_saved",
        "public_profile.revision.submitted",
        "public_profile.revision.review_started",
        "public_profile.revision.changes_required",
        "public_profile.revision.updated",
        "public_profile.revision.approved",
    }.issubset(actions)
    assert AuditEvent.objects.filter(
        action="public_profile.revision.changes_required",
        object_id=str(revision_id),
        metadata__review_notes="Use the registered public name",
    ).exists()


@pytest.mark.django_db
def test_rejected_manufacturer_revision_never_replaces_public_content_or_leaks_private_data(client):
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
    organization.refresh_from_db(); organization.manufacturer_profile.refresh_from_db()
    assert organization.display_name == "Approved Factory"
    assert organization.email == "private-ops@example.com"
    assert organization.manufacturer_profile.whatsapp == "PRIVATE-WHATSAPP"

    revision = PublicProfileRevision.objects.get(organization=organization)
    assert revision.status == PublicProfileRevision.Status.SUBMITTED
    serialized_revision = repr(revision.proposed_data)
    for secret in (
        "private-ops@example.com", "PRIVATE-PHONE-0100", "PRIVATE FACTORY ADDRESS",
        "PRIVATE FLOOR", "PRIVATE CONTACT PERSON", "PRIVATE ROLE", "PRIVATE-WHATSAPP",
        "PRIVATE-CR", "PRIVATE-TAX", "private-factory",
    ):
        assert secret not in serialized_revision

    pending_html = client.get(f"/manufacturers/{listing.pk}/").content.decode()
    assert "Approved Factory" in pending_html and "Pending Factory" not in pending_html

    start_public_profile_review(revision=revision, reviewer=reviewer)
    review_public_profile_revision(
        revision=revision,
        reviewer=reviewer,
        decision=PublicProfileRevision.Status.REJECTED,
        notes="Keep current approved identity",
    )
    revision.refresh_from_db(); organization.refresh_from_db()
    assert revision.status == PublicProfileRevision.Status.REJECTED
    assert organization.display_name == "Approved Factory"
    rejected_html = client.get(f"/manufacturers/{listing.pk}/").content.decode()
    assert "Approved Factory" in rejected_html and "Pending Factory" not in rejected_html
    assert AuditEvent.objects.filter(
        action="public_profile.revision.rejected",
        object_id=str(revision.pk),
    ).exists()


@pytest.mark.django_db
def test_profile_update_services_preserve_private_working_data_and_stable_audit_ids():
    reviewer = _user("v22-profile-audit-reviewer", staff=True)

    designer_owner = _user("v22-designer-service")
    designer = _approve(_designer_application(designer_owner, name="Current Designer"), reviewer).organization
    update_active_designer_profile(
        organization=designer,
        actor=designer_owner,
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
            "social_links": {},
        },
    )
    designer.refresh_from_db(); designer.designer_profile.refresh_from_db()
    assert designer.display_name == "Current Designer"
    assert designer.email == "private-designer@example.com"
    assert AuditEvent.objects.filter(action="designer.profile.updated", object_id=str(designer.pk)).exists()

    manufacturer_owner = _user("v22-manufacturer-service")
    manufacturer = _approve(_manufacturer_application(manufacturer_owner, name="Current Factory"), reviewer).organization
    update_active_manufacturer_profile(
        organization=manufacturer,
        actor=manufacturer_owner,
        organization_data={
            "display_name": "Pending Factory",
            "email": "private-factory@example.com",
            "phone": "01000000001",
            "website": "",
            "address_line1": "Factory private address",
            "address_line2": "",
            "city": "Giza",
            "region": "Giza",
            "country": "EG",
        },
        profile_data={
            "primary_contact_person": "Private Contact",
            "contact_job_title": "Operations",
            "whatsapp": "01012345678",
            "google_maps_url": "",
        },
    )
    manufacturer.refresh_from_db()
    assert manufacturer.display_name == "Current Factory"
    assert manufacturer.email == "private-factory@example.com"
    assert AuditEvent.objects.filter(action="manufacturer.profile.updated", object_id=str(manufacturer.pk)).exists()


@pytest.mark.django_db
def test_maneg_suspend_and_reactivate_preserve_history_and_gate_professional_access(client):
    owner = _user("v22-lifecycle-owner")
    reviewer = _user("v22-lifecycle-reviewer", staff=True)
    application = _approve(_designer_application(owner, name="Lifecycle Studio"), reviewer)
    organization = application.organization
    membership = Membership.objects.get(organization=organization, user=owner)

    owner_client = client
    owner_client.force_login(owner)
    assert 'href="/designer/"' in owner_client.get("/").content.decode()

    from django.test import Client
    staff_client = Client()
    operator = _user("v22-lifecycle-operator", staff=True)
    _grant(operator, "view_organization", "change_organization")
    _otp_login(staff_client, operator)
    detail = reverse("fabinzi_admin:maneg-organization-detail", args=[organization.pk])

    response = staff_client.post(detail, {"action": "suspend"})
    assert response.status_code == 302
    organization.refresh_from_db(); membership.refresh_from_db()
    assert organization.verification_status == Organization.VerificationStatus.SUSPENDED
    assert membership.is_active is True
    assert application.status == OnboardingApplication.Status.APPROVED
    assert 'href="/designer/"' not in owner_client.get("/").content.decode()
    portal = owner_client.get(f"/designer/?org={organization.pk}")
    assert portal.status_code == 200
    assert "Organization suspended" in portal.content.decode()

    response = staff_client.post(detail, {"action": "reactivate"})
    assert response.status_code == 302
    organization.refresh_from_db(); membership.refresh_from_db()
    assert organization.verification_status == Organization.VerificationStatus.ACTIVE
    assert membership.is_active is True
    assert 'href="/designer/"' in owner_client.get("/").content.decode()
    assert AuditEvent.objects.filter(action="control_center.organization.suspended", object_id=str(organization.pk)).exists()
    assert AuditEvent.objects.filter(action="control_center.organization.reactivated", object_id=str(organization.pk)).exists()


@pytest.mark.django_db
def test_unauthorized_or_ineligible_maneg_lifecycle_changes_are_rejected(client):
    owner = _user("v22-lifecycle-denied-owner")
    reviewer = _user("v22-lifecycle-denied-reviewer", staff=True)
    application = _approve(_manufacturer_application(owner), reviewer)
    organization = application.organization

    viewer = _user("v22-lifecycle-viewer", staff=True)
    _grant(viewer, "view_organization")
    _otp_login(client, viewer)
    detail = reverse("fabinzi_admin:maneg-organization-detail", args=[organization.pk])
    assert client.post(detail, {"action": "suspend"}).status_code == 403
    organization.refresh_from_db()
    assert organization.verification_status == Organization.VerificationStatus.ACTIVE

    operator = _user("v22-lifecycle-valid-operator", staff=True)
    _grant(operator, "view_organization", "change_organization")
    _otp_login(client, operator)
    organization.verification_status = Organization.VerificationStatus.SUSPENDED
    organization.save(update_fields=["verification_status"])
    application.status = OnboardingApplication.Status.REJECTED
    application.save(update_fields=["status"])
    response = client.post(detail, {"action": "reactivate"})
    assert response.status_code == 302
    organization.refresh_from_db()
    assert organization.verification_status == Organization.VerificationStatus.SUSPENDED


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
