from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.operations.v2_7_routing import manufacturer_operationally_eligible
from apps.organizations.models import Membership, Organization, PublicProfileRevision
from apps.public_profiles.models import ManufacturerCapabilityVerification, ProfessionalPublicState
from apps.public_profiles.services import ensure_public_state, verify_manufacturer_capability
from apps.subscriptions.manufacturer_upgrade_services import (
    activate_paid_pro_with_upgrade_resolution,
    cancel_manufacturer_upgrade_request,
    eligible_billing_confirmations,
    process_manufacturer_upgrade_request,
)
from apps.subscriptions.models import (
    ManufacturerSubscriptionUpgradeRequest,
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
    SubscriptionPeriod,
    SubscriptionPlanPolicy,
)
from apps.subscriptions.services import (
    MANUFACTURER_PRO,
    MANUFACTURER_STARTER,
    confirm_subscription_billing,
    downgrade_to_starter,
    entitlement_summary,
    get_effective_plan,
    plan_snapshot,
    price_snapshot,
)

from .test_manufacturer_portal_acceptance import manufacturer

User = get_user_model()


def _url(name, organization):
    return f"{reverse(name)}?org={organization.pk}"


def _operator(name="round2-operator", *, allowed=True):
    user = User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password123",
        is_staff=True,
    )
    if allowed:
        user.user_permissions.add(Permission.objects.get(codename="manage_professional_subscription"))
    return user


def _confirm_pro(org, operator, *, suffix="1"):
    pro = get_effective_plan(MANUFACTURER_PRO)
    return confirm_subscription_billing(
        organization=org,
        actor=operator,
        plan_code=pro.code,
        amount=pro.monthly_price,
        currency=pro.currency,
        provider="round2-test",
        provider_reference=f"round2-confirmation-{suffix}",
        idempotency_key=f"round2-idempotency-{suffix}",
    )


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
def test_team_direct_add_plain_user_repeated_add_and_cross_org_isolation(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-team-plain")
    teammate = User.objects.create_user(username="round2-plain-user", email="round2-plain@example.test", password="password123")
    client.force_login(owner)
    response = client.post(_url("manufacturer-team", org), {"action": "upsert", "email": teammate.email, "role": Membership.Role.OPERATOR})
    assert response.status_code == 302
    membership = Membership.objects.get(organization=org, user=teammate)
    assert membership.role == Membership.Role.OPERATOR and membership.is_active
    assert not Organization.objects.filter(created_by=teammate).exists()

    repeat = client.post(_url("manufacturer-team", org), {"action": "upsert", "email": teammate.email, "role": Membership.Role.QC})
    assert repeat.status_code == 302
    membership.refresh_from_db()
    assert membership.role == Membership.Role.QC
    assert Membership.objects.filter(organization=org, user=teammate).count() == 1

    _other_owner, other_org, _other_profile, _other_app = manufacturer("round2-team-other")
    other_member = User.objects.create_user(username="round2-other-member", email="round2-other-member@example.test", password="password123")
    Membership.objects.create(organization=other_org, user=other_member, role=Membership.Role.OPERATOR)
    forged = client.post(
        f"{reverse('manufacturer-team')}?org={other_org.pk}",
        {"action": "upsert", "email": other_member.email, "role": Membership.Role.QC, "organization": other_org.pk},
    )
    assert forged.status_code in {200, 302}
    assert Membership.objects.get(organization=other_org, user=other_member).role == Membership.Role.OPERATOR


@pytest.mark.django_db
def test_team_starter_seat_limit_and_manager_cannot_assign_owner(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-team-rbac")
    teammate = User.objects.create_user(username="round2-seat-one", email="round2-seat-one@example.test", password="password123")
    client.force_login(owner)
    assert client.post(_url("manufacturer-team", org), {"action": "upsert", "email": teammate.email, "role": Membership.Role.OPERATOR}).status_code == 302
    second = User.objects.create_user(username="round2-seat-two", email="round2-seat-two@example.test", password="password123")
    exhausted = client.post(_url("manufacturer-team", org), {"action": "upsert", "email": second.email, "role": Membership.Role.QC})
    assert exhausted.status_code == 200
    assert not Membership.objects.filter(organization=org, user=second).exists()

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
    response = client.post(_url("manufacturer-team", org), {"action": "upsert", "email": target.email, "role": Membership.Role.OWNER})
    assert response.status_code == 200
    assert not Membership.objects.filter(organization=org, user=target).exists()


@pytest.mark.django_db
def test_manufacturer_upgrade_request_is_idempotent_and_never_activates_pro(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-upgrade")
    client.force_login(owner)
    url = _url("manufacturer-subscription", org)
    subscription = entitlement_summary(org)["subscription"]
    before = (subscription.current_plan_id, subscription.status, dict(subscription.policy_snapshot), dict(subscription.price_snapshot))
    periods_before = subscription.periods.count()

    assert client.post(url, {"action": "upgrade", "organization": org.pk}).status_code == 302
    assert client.post(url, {"action": "upgrade", "organization": org.pk}).status_code == 302
    request_row = ManufacturerSubscriptionUpgradeRequest.objects.get(organization=org)
    assert request_row.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED
    assert request_row.price_snapshot == price_snapshot(request_row.target_plan_policy)
    assert SubscriptionBillingConfirmation.objects.filter(organization=org).count() == 0
    subscription.refresh_from_db()
    assert (subscription.current_plan_id, subscription.status, subscription.policy_snapshot, subscription.price_snapshot) == before
    assert subscription.periods.count() == periods_before

    assert client.post(url, {"action": "withdraw_upgrade", "organization": org.pk}).status_code == 302
    request_row.refresh_from_db(); subscription.refresh_from_db()
    assert request_row.status == ManufacturerSubscriptionUpgradeRequest.Status.CANCELLED
    assert (subscription.current_plan_id, subscription.status, subscription.policy_snapshot, subscription.price_snapshot) == before


@pytest.mark.django_db
def test_current_pro_or_historical_pro_state_cannot_create_upgrade_request(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-already-pro")
    subscription = entitlement_summary(org)["subscription"]
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
def test_maneg_upgrade_route_requires_permission_csrf_and_consumed_activation(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-maneg-upgrade")
    client.force_login(owner)
    client.post(_url("manufacturer-subscription", org), {"action": "upgrade"})
    upgrade = ManufacturerSubscriptionUpgradeRequest.objects.get(organization=org)
    operator = _operator("round2-route-operator")
    unrelated_staff = _operator("round2-unrelated-staff", allowed=False)
    confirmation = _confirm_pro(org, operator, suffix="route")
    subscription = OrganizationSubscription.objects.get(organization=org)
    periods_before = subscription.periods.count()
    completion_audits_before = AuditEvent.objects.filter(action="subscription.manufacturer_upgrade_completed").count()

    # Confirmation existence alone does not complete or activate anything.
    upgrade.refresh_from_db(); confirmation.refresh_from_db(); subscription.refresh_from_db()
    assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED
    assert confirmation.consumed_period_id is None
    assert subscription.current_plan.code == MANUFACTURER_STARTER

    route = reverse("fabinzi_admin:maneg-v2-9-subscriptions")
    client.force_login(unrelated_staff)
    denied = client.post(route, {"action": "process_manufacturer_upgrade", "upgrade_request_id": upgrade.pk, "billing_confirmation_id": confirmation.pk})
    assert denied.status_code == 403
    confirmation.refresh_from_db(); assert confirmation.consumed_period_id is None

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(operator)
    get_page = csrf_client.get(route)
    assert get_page.status_code == 200
    assert b"Manufacturer Pro upgrade requests" in get_page.content
    assert str(upgrade.pk).encode() in get_page.content
    no_csrf = csrf_client.post(route, {"action": "process_manufacturer_upgrade", "upgrade_request_id": upgrade.pk, "billing_confirmation_id": confirmation.pk})
    assert no_csrf.status_code == 403
    token = csrf_client.cookies["csrftoken"].value
    processed = csrf_client.post(
        route,
        {"action": "process_manufacturer_upgrade", "upgrade_request_id": upgrade.pk, "billing_confirmation_id": confirmation.pk, "csrfmiddlewaretoken": token},
        HTTP_X_CSRFTOKEN=token,
    )
    assert processed.status_code == 302
    upgrade.refresh_from_db(); confirmation.refresh_from_db(); subscription.refresh_from_db()
    assert subscription.current_plan.code == MANUFACTURER_PRO
    assert subscription.status == OrganizationSubscription.Status.ACTIVE
    assert confirmation.consumed_period_id is not None and confirmation.consumed_at is not None
    assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.COMPLETED
    assert upgrade.billing_confirmation_id == confirmation.pk
    assert upgrade.resolved_by_id == operator.pk
    assert subscription.periods.count() == periods_before + 1
    assert AuditEvent.objects.filter(action="subscription.manufacturer_upgrade_completed").count() == completion_audits_before + 1

    # Exact retry is idempotent: no duplicate period/evidence association/audit.
    token = csrf_client.cookies["csrftoken"].value
    retry = csrf_client.post(
        route,
        {"action": "process_manufacturer_upgrade", "upgrade_request_id": upgrade.pk, "billing_confirmation_id": confirmation.pk, "csrfmiddlewaretoken": token},
        HTTP_X_CSRFTOKEN=token,
    )
    assert retry.status_code == 302
    subscription.refresh_from_db(); confirmation.refresh_from_db()
    assert subscription.periods.count() == periods_before + 1
    assert AuditEvent.objects.filter(action="subscription.manufacturer_upgrade_completed").count() == completion_audits_before + 1


@pytest.mark.django_db
def test_upgrade_processing_rejects_wrong_revoked_and_replayed_evidence(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-negative-evidence")
    client.force_login(owner); client.post(_url("manufacturer-subscription", org), {"action": "upgrade"})
    upgrade = ManufacturerSubscriptionUpgradeRequest.objects.get(organization=org)
    operator = _operator("round2-negative-operator")

    other_owner, other_org, _other_profile, _other_app = manufacturer("round2-evidence-other")
    wrong = _confirm_pro(other_org, operator, suffix="wrong-org")
    with pytest.raises(ValidationError):
        process_manufacturer_upgrade_request(upgrade_request=upgrade, actor=operator, billing_confirmation=wrong)
    upgrade.refresh_from_db(); assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED

    revoked = _confirm_pro(org, operator, suffix="revoked")
    revoked.status = SubscriptionBillingConfirmation.Status.REVOKED
    revoked.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        process_manufacturer_upgrade_request(upgrade_request=upgrade, actor=operator, billing_confirmation=revoked)
    upgrade.refresh_from_db(); assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED

    good = _confirm_pro(org, operator, suffix="good")
    assert eligible_billing_confirmations(upgrade)[0].pk == good.pk
    subscription, completed = process_manufacturer_upgrade_request(upgrade_request=upgrade, actor=operator, billing_confirmation=good)
    assert completed.status == ManufacturerSubscriptionUpgradeRequest.Status.COMPLETED
    periods_after_activation = subscription.periods.count()

    # After a legitimate downgrade a consumed confirmation replay is a no-op and
    # cannot complete a newly created request or reactivate Pro.
    downgrade_to_starter(subscription=subscription, actor=operator)
    client.force_login(owner)
    client.post(_url("manufacturer-subscription", org), {"action": "upgrade"})
    newer = ManufacturerSubscriptionUpgradeRequest.objects.get(organization=org, status=ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED)
    periods_before_replay = OrganizationSubscription.objects.get(organization=org).periods.count()
    replayed = activate_paid_pro_with_upgrade_resolution(organization=org, actor=operator, billing_confirmation=good)
    replayed.refresh_from_db(); newer.refresh_from_db(); good.refresh_from_db()
    assert replayed.current_plan.code == MANUFACTURER_STARTER
    assert newer.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED
    assert newer.billing_confirmation_id is None
    assert replayed.periods.count() == periods_before_replay
    assert periods_before_replay == periods_after_activation + 1


@pytest.mark.django_db
def test_pending_upgrade_snapshot_is_not_price_guarantee_and_stale_request_is_cancelled(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-policy-drift")
    client.force_login(owner); client.post(_url("manufacturer-subscription", org), {"action": "upgrade"})
    upgrade = ManufacturerSubscriptionUpgradeRequest.objects.get(organization=org)
    old_policy = upgrade.target_plan_policy
    today = timezone.localdate()
    old_policy.effective_to = today
    old_policy.save(update_fields=["effective_to"])
    new_policy = SubscriptionPlanPolicy.objects.create(
        code=MANUFACTURER_PRO,
        version=old_policy.version + 1,
        public_name_ar=old_policy.public_name_ar,
        public_name_en=old_policy.public_name_en,
        audience=old_policy.audience,
        monthly_price=old_policy.monthly_price + Decimal("100.00"),
        currency=old_policy.currency,
        tax_inclusive=old_policy.tax_inclusive,
        trial_months=old_policy.trial_months,
        manufacturer_monthly_offer_limit=old_policy.manufacturer_monthly_offer_limit,
        team_subaccount_limit=old_policy.team_subaccount_limit,
        active=True,
        effective_from=today,
    )
    operator = _operator("round2-drift-operator")
    confirmation = confirm_subscription_billing(
        organization=org,
        actor=operator,
        plan_code=MANUFACTURER_PRO,
        amount=new_policy.monthly_price,
        currency=new_policy.currency,
        provider="round2-test",
        provider_reference="round2-drift-confirmation",
        idempotency_key="round2-drift-idempotency",
    )
    assert eligible_billing_confirmations(upgrade) == []
    with pytest.raises(ValidationError, match="no longer current"):
        process_manufacturer_upgrade_request(upgrade_request=upgrade, actor=operator, billing_confirmation=confirmation)
    upgrade.refresh_from_db(); confirmation.refresh_from_db()
    assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED
    assert confirmation.consumed_period_id is None
    cancelled, changed = cancel_manufacturer_upgrade_request(upgrade_request=upgrade, actor=operator)
    assert changed and cancelled.status == ManufacturerSubscriptionUpgradeRequest.Status.CANCELLED

    new_policy.active = False
    new_policy.save(update_fields=["active"])
    page = client.get(_url("manufacturer-subscription", org))
    assert page.status_code == 200
    assert b"no effective Pro policy exists" in page.content
    assert b"Request Pro upgrade" not in page.content


@pytest.mark.django_db
def test_public_profile_defaults_read_only_validation_and_submitted_lock(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-public-edit")
    ManufacturerListing.objects.create(organization=org, headline_en="Approved headline", overview_en="Approved overview")
    ensure_public_state(org)
    client.force_login(owner)
    url = _url("manufacturer-public-profile", org)
    read_only = client.get(url)
    assert read_only.status_code == 200 and b"Approved public information" in read_only.content
    assert b'name="public_name_en"' not in read_only.content
    edit = client.get(f"{url}&edit=1")
    assert edit.status_code == 200 and b'name="public_name_en"' in edit.content

    invalid = client.post(url, {"action": "save_revision", "organization": org.pk, "public_name_en": "Retained Round 2 Name", "public_name_ar": "", "headline_en": "Retained pending headline", "headline_ar": "", "overview_en": "Attempted overview", "overview_ar": "", "region": "Cairo", "city": "Cairo", "country": "EG", "website": "not-a-url", "public_google_maps_url": "", "public_categories": "T-shirts, Hoodies", "public_certifications": "ISO 9001", "profile_image_id": "", "cover_image_id": ""})
    assert invalid.status_code == 200
    assert b"Retained Round 2 Name" in invalid.content and b"Retained pending headline" in invalid.content
    assert b"Proposal was not saved" in invalid.content
    assert not PublicProfileRevision.objects.filter(organization=org).exists()

    submitted = client.post(url, {"action": "submit_revision", "organization": org.pk, "public_name_en": "Pending name", "public_name_ar": "", "headline_en": "Pending headline", "headline_ar": "", "overview_en": "Pending overview", "overview_ar": "", "region": "Alexandria", "city": "Alexandria", "country": "EG", "website": "", "public_google_maps_url": "", "public_categories": "T-shirts", "public_certifications": "ISO 9001", "profile_image_id": "", "cover_image_id": ""})
    assert submitted.status_code == 302
    revision = PublicProfileRevision.objects.get(organization=org)
    assert revision.status == PublicProfileRevision.Status.SUBMITTED
    locked_get = client.get(f"{url}&edit=1")
    assert b'name="public_name_en"' not in locked_get.content
    assert b"Pending headline" in locked_get.content
    locked_post = client.post(url, {"action": "save_revision", "organization": org.pk, "public_name_en": "Forged change"})
    assert locked_post.status_code == 302
    revision.refresh_from_db(); org.refresh_from_db()
    assert revision.proposed_data["public_state"]["public_name_en"] == "Pending name"
    assert org.display_name == "Factory round2-public-edit"


@pytest.mark.django_db
def test_canonical_verification_remains_separate_from_visibility_and_routing(v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-routing")
    reviewer = User.objects.create_user(username="round2-routing-reviewer", email="round2-routing-reviewer@example.test", password="password123", is_staff=True)
    listing = ManufacturerListing.objects.create(organization=org)
    capability = ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.CUT_SEW, name="Garment assembly", is_active=True)
    verification = verify_manufacturer_capability(capability=capability, canonical_code=ManufacturerCapabilityVerification.CanonicalCode.GARMENT_MANUFACTURING, reviewer=reviewer)
    required = [ManufacturerCapabilityVerification.CanonicalCode.GARMENT_MANUFACTURING]
    assert manufacturer_operationally_eligible(org, required_codes=required) is True
    state = ensure_public_state(org); state.visibility = ProfessionalPublicState.Visibility.HIDDEN; state.save(update_fields=["visibility", "updated_at"])
    assert manufacturer_operationally_eligible(org, required_codes=required) is True
    verification.status = ManufacturerCapabilityVerification.Status.REVOKED; verification.revoked_at = timezone.now(); verification.save(update_fields=["status", "revoked_at", "updated_at"])
    assert manufacturer_operationally_eligible(org, required_codes=required) is False


@pytest.mark.django_db
def test_public_directory_and_detail_use_approved_data_with_logo_fallback_and_privacy(client, v2_3_reference_rows):
    owner, org, _profile, _application = manufacturer("round2-public-directory")
    org.region = "Cairo"; org.save(update_fields=["region", "updated_at"])
    ManufacturerListing.objects.create(organization=org, headline_en="Approved production headline", overview_en="Approved production overview", public_email="private-listing@example.test", public_phone="01099999999", min_order_quantity=999, lead_time_min_days=88, available_monthly_capacity=777777, production_methods=["private-method"])
    state = ensure_public_state(org); state.public_name_en = "Approved Round 2 Manufacturer"; state.visibility = ProfessionalPublicState.Visibility.VISIBLE; state.public_categories = ["Apparel"]; state.public_certifications = ["ISO 9001"]; state.save()
    directory = client.get(reverse("manufacturer-marketplace"))
    assert directory.status_code == 200 and b"Approved Round 2 Manufacturer" in directory.content and b"Approved production headline" in directory.content and b"data-public-image-fallback" in directory.content
    assert b"private-listing@example.test" not in directory.content and b"01099999999" not in directory.content
    detail = client.get(reverse("manufacturer-public-detail", args=[state.slug]))
    assert detail.status_code == 200 and b"Approved production overview" in detail.content
    assert b"private-listing@example.test" not in detail.content and b"01099999999" not in detail.content and b"777777" not in detail.content and b"private-method" not in detail.content
    assert b"No canonically verified capabilities right now" in detail.content
