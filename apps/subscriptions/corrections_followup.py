from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.audit.services import record_audit_event
from . import corrections, services as base
from .models import OrganizationSubscription, SubscriptionBillingConfirmation


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
            confirmation = SubscriptionBillingConfirmation.objects.filter(
                provider_reference=provider_reference_value
            ).first()
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
        and confirmation.idempotency_key == idempotency_value
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


def _lock_confirmation(pk):
    # Lock only the billing-evidence row itself. Joining the nullable consumed
    # period under SELECT FOR UPDATE would create an outer join that PostgreSQL
    # correctly refuses to lock.
    return (
        SubscriptionBillingConfirmation.objects.select_for_update()
        .select_related("plan_policy")
        .get(pk=pk)
    )


@transaction.atomic
def activate_paid_pro(*, organization, actor, billing_confirmation, request=None, now=None):
    base._require_owner_or_operator(actor, organization)
    if billing_confirmation is None:
        raise ValidationError("Confirmed billing evidence is required.")
    now = base._now(now)

    confirmation = _lock_confirmation(billing_confirmation.pk)
    subscription = base._subscription_locked_for_org(organization, now=now)
    already = corrections._existing_consumed_period(confirmation, subscription)
    if already:
        return subscription

    pro = base.get_effective_plan(base.pro_code_for(organization), at=now)
    corrections._validate_confirmation_for_policy(
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
    corrections._consume_confirmation(confirmation=confirmation, period=period, now=now)
    base.restore_plan_limited_resources(
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

    confirmation = _lock_confirmation(billing_confirmation.pk)
    subscription = (
        OrganizationSubscription.objects.select_for_update()
        .select_related("organization", "current_plan")
        .get(pk=subscription.pk)
    )
    already = corrections._existing_consumed_period(confirmation, subscription)
    if already:
        return subscription

    start = max(now, subscription.current_period_end)
    effective_plan = base.get_effective_plan(subscription.current_plan.code, at=start)
    corrections._validate_confirmation_for_policy(
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
    corrections._consume_confirmation(confirmation=confirmation, period=period, now=now)
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


SERVICE_OVERRIDES = {
    "confirm_subscription_billing": confirm_subscription_billing,
    "activate_paid_pro": activate_paid_pro,
    "renew_paid_subscription": renew_paid_subscription,
}
