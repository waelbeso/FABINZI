from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.operations.v2_7_routing import manufacturer_operationally_eligible
from apps.organizations.models import Membership, Organization, PublicProfileRevision
from apps.public_profiles.models import ManufacturerCapabilityVerification, ProfessionalPublicState
from apps.public_profiles.services import ensure_public_state, verify_manufacturer_capability
from apps.subscriptions.admin import _complete_matching_upgrade_request
from apps.subscriptions.models import (
    ManufacturerSubscriptionUpgradeRequest,
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
)
from apps.subscriptions.services import (
    MANUFACTURER_PRO,
    MANUFACTURER_STARTER,
    activate_paid_pro,
    confirm_subscription_billing,
    entitlement_summary,
    get_effective_plan,
    plan_snapshot,
    price_snapshot,
)

from .test_manufacturer_portal_acceptance import manufacturer

User = get_user_model()


def _url(name, organization):
    return f"{reverse(name)}?org={organization.pk}"


@pytest.mark.django_db
def test_team_missing_malformed_and_ambiguous_identity_stay_inline(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-team-errors")
    client.force_login(owner)
    url = _url("manufacturer-team", org)

    missing = client.post(url, {"action": "upsert", "email": "missing@example.test", "role": Membership.Role.OPERATOR})
    assert missing.status_code == 200
    assert b"No FABINZI identity was found" in missing.content
    assert b"missing@example.test" in missing.content
    assert org.memberships.exclude(role=Membership.Role.OWNER).count() == 0

    malformed = client.post(url, {"action": "upsert", "email": "not-an-email", "role": Membership.Role.QC})
    assert malformed.status_code == 200
    assert b"Enter a valid FABINZI account email" in malformed.content
    assert b"not-an-email" in malformed.content
    assert org.memberships.exclude(role=Membership.Role.OWNER).count() == 0

    duplicate_email = "duplicate@example.test"
    User.objects.create_user(username="round2-duplicate-a", email=duplicate_email, password="password123")
    User.objects.create_user(username="round2-duplicate-b", email=duplicate_email.upper(), password="password123")
    ambiguous = client.post(url, {"action": "upsert", "email": duplicate_email, "role": Membership.Role.OPERATOR})
    assert ambiguous.status_code == 200
    assert b"More than one FABINZI identity matches this email" in ambiguous.content
    assert org.memberships.exclude(role=Membership.Role.OWNER).count() == 0


@pytest.mark.django_db
def test_team_direct_add_accepts_plain_fabinzi_user_and_preserves_seat_limit(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-team-plain")
    teammate = User.objects.create_user(username="round2-plain-user", email="round2-plain@example.test", password="password123")
    assert not Membership.objects.filter(user=teammate).exists()
    assert not Organization.objects.filter(created_by=teammate).exists()

    client.force_login(owner)
    response = client.post(
        _url("manufacturer-team", org),
        {"action": "upsert", "email": teammate.email, "role": Membership.Role.OPERATOR},
    )
    assert response.status_code == 302
    membership = Membership.objects.get(organization=org, user=teammate)
    assert membership.role == Membership.Role.OPERATOR
    assert membership.is_active is True
    assert not Organization.objects.filter(created_by=teammate).exists()

    second = User.objects.create_user(username="round2-second-seat", email="round2-second-seat@example.test", password="password123")
    exhausted = client.post(
        _url("manufacturer-team", org),
        {"action": "upsert", "email": second.email, "role": Membership.Role.QC},
    )
    assert exhausted.status_code == 200
    assert not Membership.objects.filter(organization=org, user=second).exists()


@pytest.mark.django_db
def test_team_manager_cannot_assign_owner_role_and_role_rules_remain_server_side(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-team-rbac")
    subscription = entitlement_summary(org)["subscription"]
    pro = get_effective_plan(MANUFACTURER_PRO)
    subscription.current_plan = pro
    subscription.policy_snapshot = plan_snapshot(pro)
    subscription.price_snapshot = price_snapshot(pro)
    subscription.save(update_fields=["current_plan", "policy_snapshot", "price_snapshot", "updated_at"])

    manager = User.objects.create_user(username="round2-manager", email="round2-manager@example.test", password="password123")
    Membership.objects.create(organization=org, user=manager, role=Membership.Role.MANAGER, is_active=True)
    target = User.objects.create_user(username="round2-owner-target", email="round2-owner-target@example.test", password="password123")

    client.force_login(manager)
    response = client.post(
        _url("manufacturer-team", org),
        {"action": "upsert", "email": target.email, "role": Membership.Role.OWNER},
    )
    assert response.status_code == 200
    assert not Membership.objects.filter(organization=org, user=target).exists()


@pytest.mark.django_db
def test_manufacturer_upgrade_request_is_idempotent_and_never_activates_pro(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-upgrade")
    client.force_login(owner)
    url = _url("manufacturer-subscription", org)

    first = client.post(url, {"action": "upgrade", "organization": org.pk})
    assert first.status_code == 302
    subscription = OrganizationSubscription.objects.select_related("current_plan").get(organization=org)
    assert subscription.current_plan.code == MANUFACTURER_STARTER
    assert ManufacturerSubscriptionUpgradeRequest.objects.filter(organization=org, status="requested").count() == 1
    assert SubscriptionBillingConfirmation.objects.filter(organization=org).count() == 0

    second = client.post(url, {"action": "upgrade", "organization": org.pk})
    assert second.status_code == 302
    assert ManufacturerSubscriptionUpgradeRequest.objects.filter(organization=org, status="requested").count() == 1
    subscription.refresh_from_db()
    assert subscription.current_plan.code == MANUFACTURER_STARTER
    assert SubscriptionBillingConfirmation.objects.filter(organization=org).count() == 0

    withdrawn = client.post(url, {"action": "withdraw_upgrade", "organization": org.pk})
    assert withdrawn.status_code == 302
    request_row = ManufacturerSubscriptionUpgradeRequest.objects.get(organization=org)
    assert request_row.status == ManufacturerSubscriptionUpgradeRequest.Status.CANCELLED
    subscription.refresh_from_db()
    assert subscription.current_plan.code == MANUFACTURER_STARTER


@pytest.mark.django_db
def test_current_pro_or_historical_pro_state_cannot_create_upgrade_request(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-already-pro")
    summary = entitlement_summary(org)
    subscription = summary["subscription"]
    pro = get_effective_plan(MANUFACTURER_PRO)
    subscription.current_plan = pro
    subscription.status = OrganizationSubscription.Status.TRIALING
    subscription.trial_started_at = timezone.now()
    subscription.trial_ends_at = timezone.now() + timedelta(days=30)
    subscription.trial_consumed = True
    subscription.policy_snapshot = plan_snapshot(pro)
    subscription.price_snapshot = price_snapshot(pro)
    subscription.save()

    client.force_login(owner)
    response = client.post(_url("manufacturer-subscription", org), {"action": "upgrade", "organization": org.pk})
    assert response.status_code == 200
    assert ManufacturerSubscriptionUpgradeRequest.objects.filter(organization=org).count() == 0


@pytest.mark.django_db
def test_upgrade_request_completes_only_after_authorized_billing_activation(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-upgrade-complete")
    client.force_login(owner)
    client.post(_url("manufacturer-subscription", org), {"action": "upgrade", "organization": org.pk})
    upgrade = ManufacturerSubscriptionUpgradeRequest.objects.get(organization=org)
    assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED

    operator = User.objects.create_user(
        username="round2-subscription-operator",
        email="round2-subscription-operator@example.test",
        password="password123",
        is_staff=True,
    )
    operator.user_permissions.add(Permission.objects.get(codename="manage_professional_subscription"))
    pro = get_effective_plan(MANUFACTURER_PRO)
    confirmation = confirm_subscription_billing(
        organization=org,
        actor=operator,
        plan_code=pro.code,
        amount=pro.monthly_price,
        currency=pro.currency,
        provider="round2-test",
        provider_reference="round2-confirmation-1",
        idempotency_key="round2-idempotency-1",
    )
    upgrade.refresh_from_db()
    assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED
    assert upgrade.billing_confirmation_id is None

    activate_paid_pro(organization=org, actor=operator, billing_confirmation=confirmation)
    _complete_matching_upgrade_request(organization=org, confirmation=confirmation, actor=operator)
    upgrade.refresh_from_db()
    subscription = OrganizationSubscription.objects.select_related("current_plan").get(organization=org)
    assert subscription.current_plan.code == MANUFACTURER_PRO
    assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.COMPLETED
    assert upgrade.billing_confirmation_id == confirmation.pk
    assert upgrade.resolved_by_id == operator.pk


@pytest.mark.django_db
def test_public_profile_defaults_read_only_and_validation_preserves_attempted_values(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-public-edit")
    ManufacturerListing.objects.create(organization=org, headline_en="Approved headline", overview_en="Approved overview")
    ensure_public_state(org)
    client.force_login(owner)
    url = _url("manufacturer-public-profile", org)

    read_only = client.get(url)
    assert read_only.status_code == 200
    assert b"Approved public information" in read_only.content
    assert b'name="public_name_en"' not in read_only.content

    edit = client.get(f"{url}&edit=1")
    assert edit.status_code == 200
    assert b'name="public_name_en"' in edit.content

    invalid = client.post(
        url,
        {
            "action": "save_revision",
            "organization": org.pk,
            "public_name_en": "Retained Round 2 Name",
            "public_name_ar": "",
            "headline_en": "Retained pending headline",
            "headline_ar": "",
            "overview_en": "Attempted overview",
            "overview_ar": "",
            "region": "Cairo",
            "city": "Cairo",
            "country": "EG",
            "website": "not-a-url",
            "public_google_maps_url": "",
            "public_categories": "T-shirts, Hoodies",
            "public_certifications": "ISO 9001",
            "profile_image_id": "",
            "cover_image_id": "",
        },
    )
    assert invalid.status_code == 200
    assert b"Retained Round 2 Name" in invalid.content
    assert b"Retained pending headline" in invalid.content
    assert b"Proposal was not saved" in invalid.content
    assert not PublicProfileRevision.objects.filter(organization=org).exists()
    org.refresh_from_db()
    assert org.display_name == "Factory round2-public-edit"


@pytest.mark.django_db
def test_canonical_verification_remains_separate_from_visibility_and_routing(v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-routing")
    reviewer = User.objects.create_user(username="round2-routing-reviewer", email="round2-routing-reviewer@example.test", password="password123", is_staff=True)
    listing = ManufacturerListing.objects.create(organization=org)
    capability = ManufacturerCapability.objects.create(
        listing=listing,
        capability_type=ManufacturerCapability.CapabilityType.CUT_SEW,
        name="Garment assembly",
        is_active=True,
    )
    verification = verify_manufacturer_capability(
        capability=capability,
        canonical_code=ManufacturerCapabilityVerification.CanonicalCode.GARMENT_MANUFACTURING,
        reviewer=reviewer,
    )
    required = [ManufacturerCapabilityVerification.CanonicalCode.GARMENT_MANUFACTURING]
    assert manufacturer_operationally_eligible(org, required_codes=required) is True

    state = ensure_public_state(org)
    state.visibility = ProfessionalPublicState.Visibility.HIDDEN
    state.save(update_fields=["visibility", "updated_at"])
    assert manufacturer_operationally_eligible(org, required_codes=required) is True

    verification.status = ManufacturerCapabilityVerification.Status.REVOKED
    verification.revoked_at = timezone.now()
    verification.save(update_fields=["status", "revoked_at", "updated_at"])
    assert manufacturer_operationally_eligible(org, required_codes=required) is False


@pytest.mark.django_db
def test_public_directory_and_detail_use_approved_data_with_logo_fallback_and_privacy(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-public-directory")
    org.region = "Cairo"
    org.save(update_fields=["region", "updated_at"])
    ManufacturerListing.objects.create(
        organization=org,
        headline_en="Approved production headline",
        overview_en="Approved production overview",
        public_email="private-listing@example.test",
        public_phone="01099999999",
        min_order_quantity=999,
        lead_time_min_days=88,
        available_monthly_capacity=777777,
        production_methods=["private-method"],
    )
    state = ensure_public_state(org)
    state.public_name_en = "Approved Round 2 Manufacturer"
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.public_categories = ["Apparel"]
    state.public_certifications = ["ISO 9001"]
    state.save()

    directory = client.get(reverse("manufacturer-marketplace"))
    assert directory.status_code == 200
    assert b"Approved Round 2 Manufacturer" in directory.content
    assert b"Approved production headline" in directory.content
    assert b"data-public-image-fallback" in directory.content
    assert b"private-listing@example.test" not in directory.content
    assert b"01099999999" not in directory.content

    detail = client.get(reverse("manufacturer-public-detail", args=[state.slug]))
    assert detail.status_code == 200
    assert b"Approved production overview" in detail.content
    assert b"private-listing@example.test" not in detail.content
    assert b"01099999999" not in detail.content
    assert b"777777" not in detail.content
    assert b"private-method" not in detail.content
    assert b"No canonically verified capabilities right now" in detail.content
