from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.audit.services import record_audit_event
from apps.organizations.models import Membership, Organization
from . import services as base
from .models import (
    MembershipPlanSuspension,
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
    SubscriptionPeriod,
)


_original_downgrade_to_starter = base.downgrade_to_starter
_original_restore_plan_limited_resources = base.restore_plan_limited_resources


def _confirmation_expected_values(plan):
    return {
        "plan_policy_id": plan.pk,
        "plan_code": plan.code,
        "plan_version": plan.version,
        "amount": plan.monthly_price,
        "currency": plan.currency,
        "tax_inclusive": plan.tax_inclusive,
        "policy_snapshot": base.plan_snapshot(plan),
        "price_snapshot": base.price_snapshot(plan),
    }


def _confirmation_matches_policy(confirmation, plan):
    expected = _confirmation_expected_values(plan)
    return bool(
        confirmation.plan_policy_id == expected["plan_policy_id"]
        and confirmation.plan_code == expected["plan_code"]
        and confirmation.plan_version == expected["plan_version"]
        and Decimal(confirmation.amount) == Decimal(expected["amount"])
        and confirmation.currency == expected["currency"]
        and confirmation.tax_inclusive == expected["tax_inclusive"]
        and dict(confirmation.policy_snapshot or {}) == expected["policy_snapshot"]
        and dict(confirmation.price_snapshot or {}) == expected["price_snapshot"]
    )


def _validate_confirmation_for_policy(*, confirmation, organization, plan):
    if confirmation.organization_id != organization.pk:
        raise ValidationError("Billing evidence belongs to a different Organization.")
    if confirmation.status != SubscriptionBillingConfirmation.Status.CONFIRMED:
        raise ValidationError("Confirmed billing evidence is required.")
    if plan.audience != organization.kind:
        raise ValidationError("Billing evidence plan audience does not match the Organization.")
    if not _confirmation_matches_policy(confirmation, plan):
        raise ValidationError(
            "Billing evidence does not match the exact effective subscription plan policy/version and price."
        )


def _existing_consumed_period(confirmation, subscription):
    if not confirmation.consumed_period_id:
        return None
    period = SubscriptionPeriod.objects.select_related("subscription").get(pk=confirmation.consumed_period_id)
    if period.subscription_id != subscription.pk:
        raise ValidationError("Billing evidence was already consumed by a different subscription period.")
    return period


def _consume_confirmation(*, confirmation, period, now):
    if confirmation.consumed_period_id:
        if confirmation.consumed_period_id != period.pk:
            raise ValidationError("Billing evidence has already been consumed.")
        return confirmation
    confirmation.consumed_period = period
    confirmation.consumed_at = now
    confirmation.save(update_fields=["consumed_period", "consumed_at"])
    return confirmation


@transaction.atomic
def confirm_subscription_billing(
    *,
    organization,
    actor,
    plan_code,
    amount,
    currency,
    provider,
    provider_reference,
    idempotency_key,
    request=None,
    now=None,
):
    base.require_subscription_operator(actor)
    now = base._now(now)
    plan = base.get_effective_plan(plan_code, at=now)
    if plan.audience != organization.kind:
        raise ValidationError("Billing confirmation plan audience does not match the Organization.")
    if Decimal(str(amount)) != plan.monthly_price or str(currency).upper() != plan.currency:
        raise ValidationError("Billing confirmation amount/currency must match the exact effective plan policy.")

    provider_value = str(provider or "").strip()
    provider_reference_value = str(provider_reference or "").strip()
    idempotency_value = str(idempotency_key or "").strip()
    if not provider_value or not provider_reference_value or not idempotency_value:
        raise ValidationError("Provider, provider reference, and idempotency key are required.")

    expected_policy_snapshot = base.plan_snapshot(plan)
    expected_price_snapshot = base.price_snapshot(plan)
    defaults = {
        "organization": organization,
        "plan_policy": plan,
        "plan_code": plan.code,
        "plan_version": plan.version,
        "amount": plan.monthly_price,
        "currency": plan.currency,
        "tax_inclusive": plan.tax_inclusive,
        "policy_snapshot": expected_policy_snapshot,
        "price_snapshot": expected_price_snapshot,
        "provider": provider_value,
        "provider_reference": provider_reference_value,
        "confirmed_by": actor,
    }

    confirmation = SubscriptionBillingConfirmation.objects.filter(idempotency_key=idempotency_value).first()
    created = False
    if confirmation is None:
        try:
            with transaction.atomic():
                confirmation = SubscriptionBillingConfirmation.objects.create(
                    idempotency_key=idempotency_value,
                    **defaults,
                )
                created = True
        except IntegrityError:
            confirmation = (
                SubscriptionBillingConfirmation.objects.filter(
                    Q(idempotency_key=idempotency_value)
                    | Q(provider_reference=provider_reference_value)
                )
                .order_by("pk")
                .first()
            )
            if confirmation is None:
                raise ValidationError("Billing evidence conflicts with an existing unique reference.")

    exact_retry = bool(
        confirmation.organization_id == organization.pk
        and confirmation.plan_policy_id == plan.pk
        and confirmation.plan_code == plan.code
        and confirmation.plan_version == plan.version
        and Decimal(confirmation.amount) == plan.monthly_price
        and confirmation.currency == plan.currency
        and confirmation.tax_inclusive == plan.tax_inclusive
        and confirmation.provider == provider_value
        and confirmation.provider_reference == provider_reference_value
        and dict(confirmation.policy_snapshot or {}) == expected_policy_snapshot
        and dict(confirmation.price_snapshot or {}) == expected_price_snapshot
    )
    if not exact_retry:
        raise ValidationError(
            "Billing idempotency/provider reference is already bound to different immutable subscription evidence."
        )

    if created:
        record_audit_event(
            actor=actor,
            action="subscription.billing_confirmed",
            instance=confirmation,
            metadata={
                "organization_id": organization.pk,
                "plan_code": plan.code,
                "plan_policy_id": plan.pk,
                "plan_version": plan.version,
                "provider": confirmation.provider,
                "tax_inclusive": plan.tax_inclusive,
            },
            request=request,
        )
    return confirmation


@transaction.atomic
def activate_paid_pro(*, organization, actor, billing_confirmation, request=None, now=None):
    base._require_owner_or_operator(actor, organization)
    if billing_confirmation is None:
        raise ValidationError("Confirmed billing evidence is required.")
    now = base._now(now)

    confirmation = (
        SubscriptionBillingConfirmation.objects.select_for_update()
        .select_related("plan_policy", "consumed_period__subscription")
        .get(pk=billing_confirmation.pk)
    )
    subscription = base._subscription_locked_for_org(organization, now=now)
    already = _existing_consumed_period(confirmation, subscription)
    if already:
        return subscription

    pro = base.get_effective_plan(base.pro_code_for(organization), at=now)
    _validate_confirmation_for_policy(
        confirmation=confirmation,
        organization=organization,
        plan=pro,
    )

    old_plan = subscription.current_plan.code
    subscription.current_plan = pro
    subscription.status = OrganizationSubscription.Status.ACTIVE
    subscription.current_period_start = now
    subscription.current_period_end = base._period_end(now)
    subscription.next_billing_at = subscription.current_period_end
    subscription.grace_started_on = None
    subscription.grace_ends_on = None
    subscription.policy_snapshot = base.plan_snapshot(pro)
    subscription.price_snapshot = base.price_snapshot(pro)
    subscription.save()
    period = base._create_period(subscription, billing_reference=confirmation.provider_reference)
    _consume_confirmation(confirmation=confirmation, period=period, now=now)
    restore_plan_limited_resources(
        organization=organization,
        actor=actor,
        request=request,
        now=now,
    )
    record_audit_event(
        actor=actor,
        action="subscription.upgraded",
        instance=subscription,
        metadata={
            "organization_id": organization.pk,
            "old_plan": old_plan,
            "new_plan": pro.code,
            "plan_policy_id": pro.pk,
            "plan_version": pro.version,
            "billing_confirmation_id": confirmation.pk,
            "subscription_period_id": period.pk,
        },
        request=request,
    )
    base._notify_subscription_owners(
        subscription,
        "subscription_plan_changed",
        "Subscription plan changed",
        "تم تغيير خطة الاشتراك",
    )
    return subscription


@transaction.atomic
def renew_paid_subscription(*, subscription, actor, billing_confirmation, request=None, now=None):
    base.require_subscription_operator(actor)
    if billing_confirmation is None:
        raise ValidationError("Confirmed billing evidence is required.")
    now = base._now(now)

    confirmation = (
        SubscriptionBillingConfirmation.objects.select_for_update()
        .select_related("plan_policy", "consumed_period__subscription")
        .get(pk=billing_confirmation.pk)
    )
    subscription = (
        OrganizationSubscription.objects.select_for_update()
        .select_related("organization", "current_plan")
        .get(pk=subscription.pk)
    )
    already = _existing_consumed_period(confirmation, subscription)
    if already:
        return subscription

    start = max(now, subscription.current_period_end)
    effective_plan = base.get_effective_plan(subscription.current_plan.code, at=start)
    _validate_confirmation_for_policy(
        confirmation=confirmation,
        organization=subscription.organization,
        plan=effective_plan,
    )

    subscription.current_plan = effective_plan
    subscription.current_period_start = start
    subscription.current_period_end = base._period_end(start)
    subscription.next_billing_at = subscription.current_period_end
    subscription.status = OrganizationSubscription.Status.ACTIVE
    subscription.grace_started_on = None
    subscription.grace_ends_on = None
    subscription.policy_snapshot = base.plan_snapshot(effective_plan)
    subscription.price_snapshot = base.price_snapshot(effective_plan)
    subscription.save()
    period = base._create_period(subscription, billing_reference=confirmation.provider_reference)
    _consume_confirmation(confirmation=confirmation, period=period, now=now)
    record_audit_event(
        actor=actor,
        action="subscription.renewed",
        instance=subscription,
        metadata={
            "billing_confirmation_id": confirmation.pk,
            "subscription_period_id": period.pk,
            "plan_policy_id": effective_plan.pk,
            "plan_version": effective_plan.version,
        },
        request=request,
    )
    return subscription


def _team_members_for_downgrade(organization):
    return list(
        Membership.objects.select_for_update()
        .filter(organization=organization, is_active=True)
        .exclude(role=Membership.Role.OWNER)
        .order_by("joined_at", "id")
    )


@transaction.atomic
def apply_designer_team_downgrade(
    *,
    organization,
    actor=None,
    retained_membership_ids=None,
    request=None,
    now=None,
):
    now = base._now(now)
    if organization.kind != Organization.Kind.DESIGNER:
        return []
    starter = base.get_effective_plan(base.DESIGNER_STARTER, at=now)
    limit = int(starter.team_subaccount_limit or 0)
    members = _team_members_for_downgrade(organization)
    valid = {membership.pk for membership in members}
    if retained_membership_ids is None:
        retained = [membership.pk for membership in members[:limit]]
    else:
        retained = [int(value) for value in retained_membership_ids]
    if len(set(retained)) > limit or not set(retained).issubset(valid):
        raise ValidationError(
            "Retained Designer team selection exceeds Starter seat capacity or includes invalid members."
        )

    suspended = []
    retained_set = set(retained)
    for membership in members:
        if membership.pk in retained_set:
            continue
        membership.is_active = False
        membership.save(update_fields=["is_active"])
        MembershipPlanSuspension.objects.update_or_create(
            membership=membership,
            defaults={
                "suspended_by_plan": True,
                "reason": "starter_plan_limit",
                "suspended_at": now,
                "restored_at": None,
            },
        )
        suspended.append(membership.pk)
        record_audit_event(
            actor=actor,
            action="subscription.team_member_plan_suspended",
            instance=membership,
            metadata={"organization_id": organization.pk, "audience": "designer"},
            request=request,
        )
    return suspended


def _restore_plan_suspended_team(*, organization, actor=None, request=None, now=None):
    now = base._now(now)
    subscription = base._subscription_locked_for_org(organization, now=now)
    limit = int((subscription.policy_snapshot or {}).get("team_subaccount_limit") or 0)
    current = base._active_membership_seats(organization) + base._pending_invitation_seats(
        organization, now=now
    )
    suspensions = (
        MembershipPlanSuspension.objects.select_for_update()
        .select_related("membership")
        .filter(
            membership__organization=organization,
            suspended_by_plan=True,
            restored_at__isnull=True,
        )
        .order_by("membership__joined_at", "membership_id")
    )
    restored = []
    for suspension in suspensions:
        if current >= limit:
            break
        membership = suspension.membership
        if membership.role == Membership.Role.OWNER:
            continue
        if not membership.is_active:
            membership.is_active = True
            membership.full_clean()
            membership.save(update_fields=["is_active"])
        suspension.suspended_by_plan = False
        suspension.restored_at = now
        suspension.save(update_fields=["suspended_by_plan", "restored_at"])
        current += 1
        restored.append(membership.pk)
        record_audit_event(
            actor=actor,
            action="subscription.team_member_plan_restored",
            instance=membership,
            metadata={"organization_id": organization.pk},
            request=request,
        )
    return restored


@transaction.atomic
def restore_plan_limited_resources(*, organization, actor=None, request=None, now=None):
    _original_restore_plan_limited_resources(
        organization=organization,
        actor=actor,
        request=request,
        now=now,
    )
    _restore_plan_suspended_team(
        organization=organization,
        actor=actor,
        request=request,
        now=now,
    )


@transaction.atomic
def downgrade_to_starter(
    *,
    subscription,
    actor=None,
    automatic=False,
    retained_design_ids=None,
    retained_artwork_ids=None,
    retained_membership_ids=None,
    request=None,
    now=None,
    cancelled=False,
):
    result = _original_downgrade_to_starter(
        subscription=subscription,
        actor=actor,
        automatic=automatic,
        retained_design_ids=retained_design_ids,
        retained_artwork_ids=retained_artwork_ids,
        retained_membership_ids=retained_membership_ids,
        request=request,
        now=now,
        cancelled=cancelled,
    )
    if result.organization.kind == Organization.Kind.DESIGNER:
        apply_designer_team_downgrade(
            organization=result.organization,
            actor=actor,
            retained_membership_ids=retained_membership_ids,
            request=request,
            now=now,
        )
    return result


def milestone_notification(subscription, milestone):
    if subscription.status == OrganizationSubscription.Status.TRIALING:
        if milestone.offset_days < 0:
            return (
                "subscription_trial_expiring",
                "Manufacturer Pro trial expiring",
                "تجربة Manufacturer Pro تقترب من الانتهاء",
            )
        if milestone.offset_days == 0:
            return (
                "subscription_trial_ends_today",
                "Manufacturer Pro trial ends today",
                "تنتهي تجربة Manufacturer Pro اليوم",
            )
    if milestone.offset_days < 0:
        return (
            "subscription_renewal_approaching",
            "Subscription renewal approaching",
            "موعد تجديد الاشتراك يقترب",
        )
    if milestone.offset_days == 0:
        return (
            "subscription_renewal_due",
            "Subscription renewal due",
            "حان موعد تجديد الاشتراك",
        )
    return (
        "subscription_grace_reminder",
        f"Subscription grace day {milestone.offset_days}",
        f"اليوم {milestone.offset_days} من مهلة الاشتراك",
    )


SERVICE_OVERRIDES = {
    "confirm_subscription_billing": confirm_subscription_billing,
    "activate_paid_pro": activate_paid_pro,
    "renew_paid_subscription": renew_paid_subscription,
    "downgrade_to_starter": downgrade_to_starter,
    "restore_plan_limited_resources": restore_plan_limited_resources,
    "_milestone_notification": milestone_notification,
}
