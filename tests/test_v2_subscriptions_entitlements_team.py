from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.audit.models import AuditEvent
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerQuote, RFQ, RFQInvitation
from apps.manufacturer_marketplace.services import submit_quote
from apps.notifications.models import Notification
from apps.organizations.models import Membership, Organization
from apps.subscriptions.models import (
    ManufacturerOfferUsage,
    MembershipPlanSuspension,
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
    SubscriptionPlanPolicy,
    SubscriptionReminderEvent,
    TeamInvitation,
    TeamInvitationConfiguration,
)
from apps.subscriptions.services import (
    DESIGNER_PRO,
    DESIGNER_STARTER,
    MANUFACTURER_STARTER,
    accept_team_invitation,
    activate_paid_pro,
    confirm_subscription_billing,
    create_team_invitation,
    downgrade_to_starter,
    entitlement_summary,
    generate_due_reminders,
    renew_paid_subscription,
    suspend_team_member,
)

User = get_user_model()


def make_user(name, *, staff=False, superuser=False):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password12345",
        is_staff=staff or superuser,
        is_superuser=superuser,
    )


def active_org(owner, kind, name):
    org = Organization.objects.create(
        kind=kind,
        display_name=name,
        email=f"{name.lower().replace(' ', '-')}@example.test",
        created_by=owner,
        verification_status=Organization.VerificationStatus.ACTIVE,
    )
    Membership.objects.create(
        organization=org,
        user=owner,
        role=Membership.Role.OWNER,
    )
    return org


def billing_confirmation(org, ops, *, reference, key, amount="350.00", now=None):
    return confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code=DESIGNER_PRO,
        amount=amount,
        currency="EGP",
        provider="verified_test_provider",
        provider_reference=reference,
        idempotency_key=key,
        now=now,
    )


def add_designer_member(org, index, role=Membership.Role.DESIGNER):
    member_user = make_user(f"{org.pk}-designer-member-{index}")
    return Membership.objects.create(
        organization=org,
        user=member_user,
        role=role,
        is_active=True,
    )


def approved_designed_product(owner, org, suffix):
    design = GarmentDesign.objects.create(
        organization=org,
        title=f"Design {suffix}",
        status=GarmentDesign.Status.APPROVED,
        created_by=owner,
    )
    garment_version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        status=GarmentDesignVersion.Status.APPROVED,
        created_by=owner,
    )
    artwork = Artwork.objects.create(
        organization=org,
        title=f"Artwork {suffix}",
        status=Artwork.Status.APPROVED,
        created_by=owner,
    )
    artwork_version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        status=ArtworkVersion.Status.APPROVED,
        created_by=owner,
    )
    return DesignedProduct.objects.create(
        organization=org,
        garment_version=garment_version,
        artwork_version=artwork_version,
        title=f"Designed Product {suffix}",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )


def invitation_for(manufacturer, suffix, *, quantity=100):
    designer_owner = make_user(f"designer-owner-{suffix}")
    designer = active_org(
        designer_owner,
        Organization.Kind.DESIGNER,
        f"Designer {suffix}",
    )
    product = approved_designed_product(designer_owner, designer, suffix)
    rfq = RFQ.objects.create(
        designer_organization=designer,
        designed_product=product,
        title=f"RFQ {suffix}",
        quantity=quantity,
        status=RFQ.Status.OPEN,
        created_by=designer_owner,
    )
    return RFQInvitation.objects.create(rfq=rfq, manufacturer=manufacturer)


@pytest.mark.django_db
def test_canonical_plan_defaults_and_team_invitation_default_are_correct():
    rows = {row.code: row for row in SubscriptionPlanPolicy.objects.filter(version=1)}
    assert rows[DESIGNER_STARTER].monthly_price == Decimal("0.00")
    assert rows[DESIGNER_STARTER].designer_active_design_limit == 2
    assert rows[DESIGNER_STARTER].designer_active_artwork_limit == 2
    assert rows[DESIGNER_STARTER].team_subaccount_limit == 1
    assert rows[DESIGNER_PRO].monthly_price == Decimal("350.00")
    assert rows[DESIGNER_PRO].team_subaccount_limit == 4
    assert rows[MANUFACTURER_STARTER].manufacturer_monthly_offer_limit == 2
    assert rows["manufacturer_pro"].monthly_price == Decimal("1500.00")
    assert rows["manufacturer_pro"].trial_months == 6
    assert rows["manufacturer_pro"].team_subaccount_limit == 4
    assert all(row.currency == "EGP" and row.tax_inclusive for row in rows.values())
    assert TeamInvitationConfiguration.current_expiry_days() == 7


@pytest.mark.django_db
def test_billing_confirmation_binds_exact_policy_price_and_tax_state():
    owner = make_user("billing-bind-owner")
    ops = make_user("billing-bind-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Billing Bind Studio")
    confirmation = billing_confirmation(org, ops, reference="BIND-001", key="bind-001")
    plan = SubscriptionPlanPolicy.objects.get(pk=confirmation.plan_policy_id)
    assert confirmation.plan_code == DESIGNER_PRO
    assert confirmation.plan_version == plan.version
    assert confirmation.amount == plan.monthly_price
    assert confirmation.currency == plan.currency
    assert confirmation.tax_inclusive == plan.tax_inclusive
    assert confirmation.policy_snapshot["plan_policy_id"] == plan.pk
    assert confirmation.policy_snapshot["version"] == plan.version
    assert confirmation.price_snapshot["monthly_price"] == "350.00"
    assert confirmation.price_snapshot["tax_inclusive"] is True
    assert confirmation.confirmed_at is not None


@pytest.mark.django_db
def test_provider_reference_and_idempotency_are_immutable_single_evidence_keys():
    owner = make_user("billing-key-owner")
    ops = make_user("billing-key-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Billing Key Studio")
    first = billing_confirmation(org, ops, reference="GLOBAL-REF-001", key="global-key-001")
    retry = billing_confirmation(org, ops, reference="GLOBAL-REF-001", key="global-key-001")
    assert retry.pk == first.pk
    with pytest.raises(ValidationError):
        billing_confirmation(org, ops, reference="GLOBAL-REF-001", key="different-key")


@pytest.mark.django_db
def test_one_billing_confirmation_cannot_create_two_paid_periods():
    owner = make_user("single-use-owner")
    ops = make_user("single-use-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Single Use Studio")
    confirmation = billing_confirmation(org, ops, reference="SINGLE-001", key="single-001")
    sub = activate_paid_pro(organization=org, actor=owner, billing_confirmation=confirmation)
    first_end = sub.current_period_end
    first_period_count = sub.periods.count()
    confirmation.refresh_from_db()
    consumed_period_id = confirmation.consumed_period_id

    same = activate_paid_pro(
        organization=org,
        actor=owner,
        billing_confirmation=confirmation,
        now=first_end + timedelta(days=5),
    )
    same.refresh_from_db()
    confirmation.refresh_from_db()
    assert same.current_period_end == first_end
    assert same.periods.count() == first_period_count
    assert confirmation.consumed_period_id == consumed_period_id
    assert confirmation.consumed_at is not None


@pytest.mark.django_db(transaction=True)
def test_concurrent_billing_confirmation_replay_cannot_duplicate_entitlement():
    owner = make_user("billing-race-owner")
    ops = make_user("billing-race-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Billing Race Studio")
    confirmation = billing_confirmation(org, ops, reference="RACE-001", key="race-001")
    initial_periods = org.professional_subscription.periods.count()

    def activate():
        close_old_connections()
        local_org = Organization.objects.get(pk=org.pk)
        local_owner = User.objects.get(pk=owner.pk)
        local_confirmation = SubscriptionBillingConfirmation.objects.get(pk=confirmation.pk)
        try:
            activate_paid_pro(
                organization=local_org,
                actor=local_owner,
                billing_confirmation=local_confirmation,
            )
            return "ok"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: activate(), range(2)))

    assert results == ["ok", "ok"]
    sub = OrganizationSubscription.objects.get(organization=org)
    confirmation.refresh_from_db()
    assert sub.current_plan.code == DESIGNER_PRO
    assert sub.periods.count() == initial_periods + 1
    assert confirmation.consumed_period_id is not None
    assert sub.periods.filter(pk=confirmation.consumed_period_id).exists()


@pytest.mark.django_db
def test_stale_billing_evidence_cannot_activate_newer_policy_version():
    owner = make_user("stale-policy-owner")
    ops = make_user("stale-policy-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Stale Policy Studio")
    confirmation = billing_confirmation(org, ops, reference="STALE-001", key="stale-001")
    old_policy_id = confirmation.plan_policy_id
    tomorrow = timezone.localdate() + timedelta(days=1)
    newer = SubscriptionPlanPolicy.objects.create(
        code=DESIGNER_PRO,
        version=2,
        public_name_ar="المصمم — Pro v2",
        public_name_en="Designer Pro v2",
        audience=SubscriptionPlanPolicy.Audience.DESIGNER,
        monthly_price=Decimal("375.00"),
        currency="EGP",
        tax_inclusive=True,
        trial_months=0,
        designer_active_design_limit=10,
        designer_active_artwork_limit=5,
        manufacturer_monthly_offer_limit=None,
        team_subaccount_limit=4,
        active=True,
        effective_from=tomorrow,
    )
    when = timezone.make_aware(
        timezone.datetime.combine(tomorrow, timezone.datetime.min.time()),
        timezone.get_current_timezone(),
    ) + timedelta(hours=12)
    with pytest.raises(ValidationError):
        activate_paid_pro(
            organization=org,
            actor=owner,
            billing_confirmation=confirmation,
            now=when,
        )
    confirmation.refresh_from_db()
    assert confirmation.plan_policy_id == old_policy_id
    assert confirmation.consumed_period_id is None
    assert newer.pk != old_policy_id


@pytest.mark.django_db
def test_renewal_uses_one_consistent_effective_policy_and_billing_evidence():
    owner = make_user("renew-policy-owner")
    ops = make_user("renew-policy-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Renew Policy Studio")
    first_confirmation = billing_confirmation(org, ops, reference="RENEW-001", key="renew-001")
    sub = activate_paid_pro(
        organization=org,
        actor=owner,
        billing_confirmation=first_confirmation,
    )
    renewal_start = sub.current_period_end
    effective_day = timezone.localtime(renewal_start).date()
    newer = SubscriptionPlanPolicy.objects.create(
        code=DESIGNER_PRO,
        version=2,
        public_name_ar="المصمم — Pro v2",
        public_name_en="Designer Pro v2",
        audience=SubscriptionPlanPolicy.Audience.DESIGNER,
        monthly_price=Decimal("375.00"),
        currency="EGP",
        tax_inclusive=True,
        trial_months=0,
        designer_active_design_limit=12,
        designer_active_artwork_limit=6,
        manufacturer_monthly_offer_limit=None,
        team_subaccount_limit=4,
        active=True,
        effective_from=effective_day,
    )
    renewal_confirmation = billing_confirmation(
        org,
        ops,
        reference="RENEW-002",
        key="renew-002",
        amount="375.00",
        now=renewal_start,
    )
    renewed = renew_paid_subscription(
        subscription=sub,
        actor=ops,
        billing_confirmation=renewal_confirmation,
        now=renewal_start,
    )
    renewed.refresh_from_db()
    renewal_confirmation.refresh_from_db()
    period = renewal_confirmation.consumed_period
    assert renewed.current_plan_id == newer.pk
    assert renewed.policy_snapshot["plan_policy_id"] == newer.pk
    assert renewed.policy_snapshot["version"] == 2
    assert renewed.price_snapshot["monthly_price"] == "375.00"
    assert period.policy_snapshot["plan_policy_id"] == newer.pk
    assert period.price_snapshot["monthly_price"] == "375.00"
    assert renewal_confirmation.plan_policy_id == newer.pk
    assert renewal_confirmation.plan_version == 2
    assert renewal_confirmation.price_snapshot == period.price_snapshot
    assert period.billing_reference == renewal_confirmation.provider_reference


@pytest.mark.django_db
def test_designer_pro_to_starter_plan_suspends_excess_team_without_deleting_history():
    owner = make_user("designer-downgrade-owner")
    ops = make_user("designer-downgrade-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Designer Downgrade Studio")
    c = billing_confirmation(org, ops, reference="TEAM-DOWN-001", key="team-down-001")
    activate_paid_pro(organization=org, actor=owner, billing_confirmation=c)
    members = [add_designer_member(org, index) for index in range(4)]

    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)

    active = list(
        Membership.objects.filter(organization=org, is_active=True)
        .exclude(role=Membership.Role.OWNER)
        .order_by("joined_at", "id")
    )
    assert [membership.pk for membership in active] == [members[0].pk]
    suspended = MembershipPlanSuspension.objects.filter(
        membership__organization=org,
        suspended_by_plan=True,
        restored_at__isnull=True,
    )
    assert suspended.count() == 3
    assert Membership.objects.filter(organization=org).count() == 5
    assert AuditEvent.objects.filter(action="subscription.team_member_plan_suspended").count() >= 3


@pytest.mark.django_db
def test_designer_upgrade_restores_plan_suspended_members_only_within_current_seat_capacity():
    owner = make_user("designer-restore-owner")
    ops = make_user("designer-restore-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Designer Restore Studio")
    first = billing_confirmation(org, ops, reference="TEAM-UP-001", key="team-up-001")
    activate_paid_pro(organization=org, actor=owner, billing_confirmation=first)
    members = [add_designer_member(org, index) for index in range(4)]
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)

    retained = Membership.objects.get(pk=members[0].pk)
    suspend_team_member(membership=retained, actor=owner)
    invitee = make_user("designer-restore-invitee")
    invitation, _ = create_team_invitation(
        organization=org,
        actor=owner,
        email=invitee.email,
        role=Membership.Role.DESIGNER,
    )
    assert invitation.status == TeamInvitation.Status.PENDING

    second = billing_confirmation(org, ops, reference="TEAM-UP-002", key="team-up-002")
    activate_paid_pro(organization=org, actor=owner, billing_confirmation=second)
    summary = entitlement_summary(org)
    assert summary["team_limit"] == 4
    assert summary["active_team_seats"] == 3
    assert summary["pending_team_seats"] == 1
    assert summary["team_used"] == 4
    retained.refresh_from_db()
    assert retained.is_active is False
    assert MembershipPlanSuspension.objects.filter(
        membership__organization=org,
        suspended_by_plan=True,
        restored_at__isnull=True,
    ).count() == 0


@pytest.mark.django_db
def test_pending_invitation_cannot_bypass_designer_downgraded_seat_limit():
    owner = make_user("invite-limit-owner")
    ops = make_user("invite-limit-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Invite Limit Studio")
    c = billing_confirmation(org, ops, reference="INV-LIMIT-001", key="inv-limit-001")
    activate_paid_pro(organization=org, actor=owner, billing_confirmation=c)
    add_designer_member(org, 1)
    add_designer_member(org, 2)
    invitee = make_user("invite-limit-user")
    invitation, token = create_team_invitation(
        organization=org,
        actor=owner,
        email=invitee.email,
        role=Membership.Role.DESIGNER,
    )
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    with pytest.raises(ValidationError):
        accept_team_invitation(token=token, actor=invitee)
    invitation.refresh_from_db()
    assert invitation.status == TeamInvitation.Status.PENDING
    assert Membership.objects.filter(organization=org, user=invitee, is_active=True).count() == 0


@pytest.mark.django_db
def test_manager_cannot_invite_or_mutate_owner_only_team_capacity():
    owner = make_user("owner-boundary-owner")
    org = active_org(owner, Organization.Kind.DESIGNER, "Owner Boundary Studio")
    manager_user = make_user("owner-boundary-manager")
    Membership.objects.create(
        organization=org,
        user=manager_user,
        role=Membership.Role.MANAGER,
        is_active=True,
    )
    target = make_user("owner-boundary-target")
    with pytest.raises(PermissionDenied):
        create_team_invitation(
            organization=org,
            actor=manager_user,
            email=target.email,
            role=Membership.Role.DESIGNER,
        )


@pytest.mark.django_db
def test_manufacturer_trial_pre_expiry_notification_uses_trial_specific_semantics_and_is_idempotent():
    owner = make_user("trial-reminder-owner")
    org = active_org(owner, Organization.Kind.MANUFACTURER, "Trial Reminder Factory")
    sub = org.professional_subscription
    assert sub.status == OrganizationSubscription.Status.TRIALING
    due = timezone.localtime(sub.trial_ends_at).date()
    when = timezone.make_aware(
        timezone.datetime.combine(due - timedelta(days=7), timezone.datetime.min.time()),
        timezone.get_current_timezone(),
    )
    generate_due_reminders(subscription=sub, now=when)
    generate_due_reminders(subscription=sub, now=when)
    events = SubscriptionReminderEvent.objects.filter(subscription=sub, due_date=due)
    assert events.count() == 1
    event = events.get()
    assert event.notification_id is not None
    assert event.notification.type == "subscription_trial_expiring"
    assert Notification.objects.filter(
        recipient=owner,
        type="subscription_trial_expiring",
    ).count() == 1


@pytest.mark.django_db
def test_manufacturer_first_successful_submit_consumes_exactly_one_quota_and_preserves_workflow():
    owner = make_user("quota-success-owner")
    manufacturer = active_org(owner, Organization.Kind.MANUFACTURER, "Quota Success Factory")
    downgrade_to_starter(subscription=manufacturer.professional_subscription, actor=owner)
    invitation = invitation_for(manufacturer, "quota-success")
    quote = submit_quote(
        invitation=invitation,
        actor=owner,
        unit_price="120.00",
        production_lead_days=10,
        minimum_order_quantity=20,
    )
    quote.refresh_from_db()
    invitation.refresh_from_db()
    invitation.rfq.refresh_from_db()
    assert quote.status == ManufacturerQuote.Status.SUBMITTED
    assert invitation.status == RFQInvitation.Status.QUOTED
    assert invitation.rfq.status == RFQ.Status.QUOTED
    assert ManufacturerOfferUsage.objects.filter(quote=quote, organization=manufacturer).count() == 1


@pytest.mark.django_db
def test_failed_manufacturer_submission_does_not_consume_permanent_quota():
    owner = make_user("quota-fail-owner")
    manufacturer = active_org(owner, Organization.Kind.MANUFACTURER, "Quota Fail Factory")
    downgrade_to_starter(subscription=manufacturer.professional_subscription, actor=owner)
    invitation = invitation_for(manufacturer, "quota-fail", quantity=10)
    with pytest.raises(ValidationError):
        submit_quote(
            invitation=invitation,
            actor=owner,
            unit_price="120.00",
            production_lead_days=10,
            minimum_order_quantity=20,
        )
    assert ManufacturerOfferUsage.objects.filter(organization=manufacturer).count() == 0
    assert not ManufacturerQuote.objects.filter(invitation=invitation).exists()
    invitation.refresh_from_db()
    invitation.rfq.refresh_from_db()
    assert invitation.status == RFQInvitation.Status.INVITED
    assert invitation.rfq.status == RFQ.Status.OPEN


@pytest.mark.django_db
def test_manufacturer_quota_failure_rolls_back_submitted_transition():
    owner = make_user("quota-limit-owner")
    manufacturer = active_org(owner, Organization.Kind.MANUFACTURER, "Quota Limit Factory")
    downgrade_to_starter(subscription=manufacturer.professional_subscription, actor=owner)
    invitations = [invitation_for(manufacturer, f"quota-limit-{index}") for index in range(3)]
    for invitation in invitations[:2]:
        submit_quote(
            invitation=invitation,
            actor=owner,
            unit_price="120.00",
            production_lead_days=10,
            minimum_order_quantity=20,
        )
    assert ManufacturerOfferUsage.objects.filter(organization=manufacturer).count() == 2
    with pytest.raises(ValidationError):
        submit_quote(
            invitation=invitations[2],
            actor=owner,
            unit_price="120.00",
            production_lead_days=10,
            minimum_order_quantity=20,
        )
    assert ManufacturerOfferUsage.objects.filter(organization=manufacturer).count() == 2
    assert not ManufacturerQuote.objects.filter(invitation=invitations[2]).exists()
    invitations[2].refresh_from_db()
    assert invitations[2].status == RFQInvitation.Status.INVITED


@pytest.mark.django_db(transaction=True)
def test_concurrent_manufacturer_submissions_cannot_exceed_starter_quota():
    owner = make_user("quota-race-owner")
    manufacturer = active_org(owner, Organization.Kind.MANUFACTURER, "Quota Race Factory")
    downgrade_to_starter(subscription=manufacturer.professional_subscription, actor=owner)
    invitations = [invitation_for(manufacturer, f"quota-race-{index}") for index in range(3)]

    def submit(invitation_id):
        close_old_connections()
        local_invitation = RFQInvitation.objects.get(pk=invitation_id)
        local_owner = User.objects.get(pk=owner.pk)
        try:
            submit_quote(
                invitation=local_invitation,
                actor=local_owner,
                unit_price="120.00",
                production_lead_days=10,
                minimum_order_quantity=20,
            )
            return "ok"
        except ValidationError:
            return "quota"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(submit, [row.pk for row in invitations]))
    assert results.count("ok") == 2
    assert results.count("quota") == 1
    assert ManufacturerOfferUsage.objects.filter(organization=manufacturer).count() == 2
    assert ManufacturerQuote.objects.filter(
        invitation__manufacturer=manufacturer,
        status=ManufacturerQuote.Status.SUBMITTED,
    ).count() == 2


@pytest.mark.django_db
def test_direct_quote_edit_and_withdrawal_do_not_double_consume_existing_usage():
    owner = make_user("quota-edit-owner")
    manufacturer = active_org(owner, Organization.Kind.MANUFACTURER, "Quota Edit Factory")
    downgrade_to_starter(subscription=manufacturer.professional_subscription, actor=owner)
    invitation = invitation_for(manufacturer, "quota-edit")
    quote = submit_quote(
        invitation=invitation,
        actor=owner,
        unit_price="120.00",
        production_lead_days=10,
        minimum_order_quantity=20,
    )
    usage_id = quote.subscription_usage.pk
    quote.notes = "edited after submission"
    quote.save(update_fields=["notes", "updated_at"])
    quote.status = ManufacturerQuote.Status.WITHDRAWN
    quote.save(update_fields=["status", "updated_at"])
    assert ManufacturerOfferUsage.objects.filter(quote=quote).count() == 1
    assert ManufacturerOfferUsage.objects.get(quote=quote).pk == usage_id


@pytest.mark.django_db
def test_subscription_and_team_usage_summary_respects_owner_zero_seat_rule():
    owner = make_user("summary-owner")
    org = active_org(owner, Organization.Kind.DESIGNER, "Summary Studio")
    summary = entitlement_summary(org)
    assert summary["team_limit"] == 1
    assert summary["active_team_seats"] == 0
    assert summary["team_used"] == 0
    add_designer_member(org, 1)
    summary = entitlement_summary(org)
    assert summary["active_team_seats"] == 1
    assert summary["team_used"] == 1
    assert summary["team_remaining"] == 0


@pytest.mark.django_db
def test_billing_and_team_corrections_emit_audit_evidence():
    owner = make_user("audit-owner")
    ops = make_user("audit-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Audit Subscription Studio")
    confirmation = billing_confirmation(org, ops, reference="AUDIT-001", key="audit-001")
    activate_paid_pro(organization=org, actor=owner, billing_confirmation=confirmation)
    add_designer_member(org, 1)
    add_designer_member(org, 2)
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    assert AuditEvent.objects.filter(action="subscription.billing_confirmed").exists()
    assert AuditEvent.objects.filter(action="subscription.upgraded").exists()
    assert AuditEvent.objects.filter(action="subscription.team_member_plan_suspended").exists()
