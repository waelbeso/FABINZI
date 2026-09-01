from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import resolve

from apps.artwork.models import Artwork, ArtworkVersion
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.organizations.models import Membership, OnboardingApplication, Organization

User = get_user_model()


def _user(name, *, staff=False):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password12345",
        is_staff=staff,
    )


def _org(owner, *, kind=Organization.Kind.DESIGNER, status=Organization.VerificationStatus.ACTIVE):
    org = Organization.objects.create(
        kind=kind,
        display_name=f"{kind}-{owner.username}",
        email=f"org-{owner.username}@example.test",
        created_by=owner,
        verification_status=status,
    )
    Membership.objects.create(
        organization=org,
        user=owner,
        role=Membership.Role.OWNER,
        is_active=True,
    )
    return org


@pytest.mark.django_db
def test_application_approval_is_explicit_subscription_provisioning_boundary(monkeypatch):
    from apps.organizations.services import review_application
    from apps.subscriptions import services as subscription_services

    owner = _user("v23-approval-owner")
    reviewer = _user("v23-approval-reviewer", staff=True)
    org = _org(owner, status=Organization.VerificationStatus.PENDING)
    application = OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.SUBMITTED,
        submitted_at=reviewer.date_joined,
    )
    calls = []

    class SubscriptionEvidence:
        pk = 731

    def fake_ensure(organization, **kwargs):
        calls.append((organization.pk, organization.verification_status, kwargs))
        return SubscriptionEvidence()

    monkeypatch.setattr(subscription_services, "ensure_subscription_for_organization", fake_ensure)
    review_application(
        application=application,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.APPROVED,
    )
    org.refresh_from_db()
    assert org.verification_status == Organization.VerificationStatus.ACTIVE
    assert calls and calls[0][0] == org.pk
    assert calls[0][1] == Organization.VerificationStatus.ACTIVE


@pytest.mark.django_db
def test_maneg_reactivation_uses_same_idempotent_subscription_boundary(monkeypatch):
    from apps.platform_ops.maneg_services import reactivate_organization
    from apps.subscriptions import services as subscription_services

    owner = _user("v23-reactivation-owner")
    staff = _user("v23-reactivation-staff", staff=True)
    org = _org(
        owner,
        kind=Organization.Kind.MANUFACTURER,
        status=Organization.VerificationStatus.SUSPENDED,
    )
    OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=staff.date_joined,
    )
    called = []

    class SubscriptionEvidence:
        pk = 732

    def fake_ensure(organization, **kwargs):
        called.append((organization.pk, organization.verification_status))
        return SubscriptionEvidence()

    monkeypatch.setattr(subscription_services, "ensure_subscription_for_organization", fake_ensure)
    reactivate_organization(organization=org, actor=staff)
    org.refresh_from_db()
    assert org.verification_status == Organization.VerificationStatus.ACTIVE
    assert called == [(org.pk, Organization.VerificationStatus.ACTIVE)]


@pytest.mark.django_db
def test_design_review_entry_calls_subscription_slot_authority(monkeypatch):
    from apps.design import services as design_services
    from apps.subscriptions import services as subscription_services

    owner = _user("v23-design-owner")
    org = _org(owner)
    design = GarmentDesign.objects.create(
        organization=org,
        title="V2-3 transition design",
        created_by=owner,
    )
    version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        created_by=owner,
    )
    calls = []
    monkeypatch.setattr(design_services, "validate_version_ready", lambda value: None)
    monkeypatch.setattr(
        subscription_services,
        "assert_designer_slot_available",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    design_services.submit_version(version=version, actor=owner)
    design.refresh_from_db()
    assert design.status == GarmentDesign.Status.IN_REVIEW
    assert calls == [{"organization": org, "kind": "design", "object_id": design.pk}]


@pytest.mark.django_db
def test_artwork_review_entry_calls_subscription_slot_authority(monkeypatch):
    from apps.artwork import services as artwork_services
    from apps.subscriptions import services as subscription_services

    owner = _user("v23-artwork-owner")
    org = _org(owner)
    artwork = Artwork.objects.create(
        organization=org,
        title="V2-3 transition artwork",
        created_by=owner,
    )
    version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        created_by=owner,
    )
    calls = []
    monkeypatch.setattr(artwork_services, "validate_artwork_ready", lambda value: None)
    monkeypatch.setattr(
        subscription_services,
        "assert_designer_slot_available",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    artwork_services.submit_artwork_version(version=version, actor=owner)
    artwork.refresh_from_db()
    assert artwork.status == Artwork.Status.IN_REVIEW
    assert calls == [{"organization": org, "kind": "artwork", "object_id": artwork.pk}]


def test_subscription_team_routes_do_not_shadow_accepted_portal_routes():
    assert resolve("/designer/team/").url_name == "designer-team"
    assert resolve("/manufacturer/team/").url_name == "manufacturer-team"


def test_runtime_correction_shims_are_absent():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "apps/subscriptions/corrections.py",
        "apps/subscriptions/corrections_followup.py",
        "apps/subscriptions/marketplace_integration.py",
        "apps/subscriptions/signals.py",
    ):
        assert not (root / relative).exists()
