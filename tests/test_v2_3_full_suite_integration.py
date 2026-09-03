from pathlib import Path

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import resolve

from apps.artwork.models import Artwork, ArtworkVersion
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.organizations.models import Membership, OnboardingApplication, Organization
from apps.subscriptions.models import MembershipPlanSuspension, OrganizationSubscription
from .v2_3_support import v2_3_reference_rows

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


def _submitted_application(owner, *, kind=Organization.Kind.DESIGNER):
    org = _org(owner, kind=kind, status=Organization.VerificationStatus.PENDING)
    application = OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.SUBMITTED,
    )
    return org, application


@pytest.mark.django_db
def test_application_approval_sets_active_and_creates_exactly_one_subscription(v2_3_reference_rows):
    from apps.organizations.services import review_application

    owner = _user("v23-approval-owner")
    reviewer = _user("v23-approval-reviewer", staff=True)
    org, application = _submitted_application(owner)

    review_application(
        application=application,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.APPROVED,
    )
    org.refresh_from_db()
    application.refresh_from_db()
    assert application.status == OnboardingApplication.Status.APPROVED
    assert org.verification_status == Organization.VerificationStatus.ACTIVE
    assert OrganizationSubscription.objects.filter(organization=org).count() == 1
    assert org.professional_subscription.current_plan.code == "designer_starter"


@pytest.mark.django_db
def test_manufacturer_approval_creates_one_six_month_trial(v2_3_reference_rows):
    from apps.organizations.services import review_application

    owner = _user("v23-manufacturer-approval-owner")
    reviewer = _user("v23-manufacturer-approval-reviewer", staff=True)
    org, application = _submitted_application(owner, kind=Organization.Kind.MANUFACTURER)

    review_application(
        application=application,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.APPROVED,
    )
    sub = OrganizationSubscription.objects.get(organization=org)
    assert sub.status == OrganizationSubscription.Status.TRIALING
    assert sub.current_plan.code == "manufacturer_pro"
    assert sub.trial_consumed is True
    assert sub.trial_ends_at == sub.trial_started_at + relativedelta(months=6)
    assert OrganizationSubscription.objects.filter(organization=org).count() == 1


@pytest.mark.django_db
def test_maneg_reactivation_reuses_existing_subscription_and_trial(v2_3_reference_rows):
    from apps.platform_ops.maneg_services import reactivate_organization, suspend_organization
    from apps.subscriptions.services import ensure_subscription_for_organization

    owner = _user("v23-reactivation-owner")
    staff = _user("v23-reactivation-staff", staff=True)
    org = _org(owner, kind=Organization.Kind.MANUFACTURER)
    application = OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=staff.date_joined,
    )
    sub = ensure_subscription_for_organization(org, activation_at=application.reviewed_at)
    original = (sub.pk, sub.trial_started_at, sub.trial_ends_at)

    suspend_organization(organization=org, actor=staff)
    reactivate_organization(organization=org, actor=staff)
    reused = OrganizationSubscription.objects.get(organization=org)
    assert (reused.pk, reused.trial_started_at, reused.trial_ends_at) == original
    assert OrganizationSubscription.objects.filter(organization=org).count() == 1


@pytest.mark.django_db
def test_pre_approval_team_member_creation_remains_allowed_without_subscription():
    from apps.organizations.services import add_or_update_member

    owner = _user("v23-preactive-owner")
    member = _user("v23-preactive-member")
    org = _org(owner, status=Organization.VerificationStatus.DRAFT)

    created = add_or_update_member(
        organization=org,
        actor=owner,
        user=member,
        role=Membership.Role.DESIGNER,
    )
    assert created.is_active is True
    assert not OrganizationSubscription.objects.filter(organization=org).exists()


@pytest.mark.django_db
def test_activation_plan_suspends_excess_preapproval_team_without_deleting(v2_3_reference_rows):
    from apps.organizations.services import add_or_update_member, review_application

    owner = _user("v23-reconcile-owner")
    reviewer = _user("v23-reconcile-reviewer", staff=True)
    org, application = _submitted_application(owner)
    members = []
    for index in range(3):
        user = _user(f"v23-reconcile-member-{index}")
        members.append(
            add_or_update_member(
                organization=org,
                actor=owner,
                user=user,
                role=Membership.Role.DESIGNER,
            )
        )
    assert Membership.objects.filter(organization=org).count() == 4

    review_application(
        application=application,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.APPROVED,
    )
    active_non_owners = list(
        Membership.objects.filter(organization=org, is_active=True)
        .exclude(role=Membership.Role.OWNER)
        .order_by("joined_at", "id")
    )
    assert [row.pk for row in active_non_owners] == [members[0].pk]
    assert Membership.objects.filter(organization=org).count() == 4
    assert MembershipPlanSuspension.objects.filter(
        membership__organization=org,
        suspended_by_plan=True,
        restored_at__isnull=True,
    ).count() == 2


@pytest.mark.django_db
def test_active_organization_team_seat_limit_remains_enforced(v2_3_reference_rows):
    from apps.organizations.services import add_or_update_member
    from apps.subscriptions.services import ensure_subscription_for_organization

    owner = _user("v23-active-team-owner")
    org = _org(owner)
    ensure_subscription_for_organization(org)
    first = _user("v23-active-team-first")
    second = _user("v23-active-team-second")
    add_or_update_member(
        organization=org,
        actor=owner,
        user=first,
        role=Membership.Role.DESIGNER,
    )
    with pytest.raises(ValidationError):
        add_or_update_member(
            organization=org,
            actor=owner,
            user=second,
            role=Membership.Role.DESIGNER,
        )


@pytest.mark.django_db
def test_organization_save_does_not_auto_provision_subscription():
    owner = _user("v23-no-signal-owner")
    org = _org(owner)
    assert org.verification_status == Organization.VerificationStatus.ACTIVE
    assert not OrganizationSubscription.objects.filter(organization=org).exists()


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
