from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.organizations.models import Organization

from . import services as subscription_services
from .models import (
    ManufacturerSubscriptionUpgradeRequest,
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
    SubscriptionPeriod,
)


def _now(value=None):
    return value or timezone.now()


def _paid_onboarding_upgrade_in_progress(organization, *, now=None):
    commercial = subscription_services.onboarding_commercial_summary(organization, now=now)
    selection = commercial.get("selection")
    return bool(
        selection
        and selection.plan_code == subscription_services.MANUFACTURER_PRO
        and commercial.get("payment_window_state") in {"active", "paid_pending_activation"}
    )


def _request_confirmation_match(upgrade, confirmation):
    price = dict(upgrade.price_snapshot or {})
    try:
        amount = Decimal(str(price["monthly_price"]))
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        confirmation.organization_id == upgrade.organization_id
        and confirmation.plan_policy_id == upgrade.target_plan_policy_id
        and confirmation.plan_code == upgrade.plan_code
        and confirmation.plan_version == upgrade.plan_version
        and Decimal(confirmation.amount) == amount
        and confirmation.currency == price.get("currency")
        and confirmation.tax_inclusive == price.get("tax_inclusive")
        and dict(confirmation.policy_snapshot or {}) == dict(upgrade.policy_snapshot or {})
        and dict(confirmation.price_snapshot or {}) == price
    )


def _request_matches_current_policy(upgrade, *, now=None):
    try:
        current = subscription_services.get_effective_plan(
            subscription_services.MANUFACTURER_PRO,
            at=_now(now),
        )
    except ValidationError:
        return False
    return bool(
        current.pk == upgrade.target_plan_policy_id
        and current.code == upgrade.plan_code
        and current.version == upgrade.plan_version
        and subscription_services.plan_snapshot(current) == dict(upgrade.policy_snapshot or {})
        and subscription_services.price_snapshot(current) == dict(upgrade.price_snapshot or {})
    )


def manufacturer_upgrade_availability(organization, *, now=None):
    """Return truthful customer-side request state without changing entitlement."""
    now = _now(now)
    summary = subscription_services.entitlement_summary(organization, now=now)
    pending = (
        ManufacturerSubscriptionUpgradeRequest.objects.filter(
            organization=organization,
            status=ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED,
        )
        .select_related("target_plan_policy", "requested_by")
        .first()
    )
    if summary["plan_code"] == subscription_services.MANUFACTURER_PRO:
        return {"can_request": False, "reason": "already_pro", "request": pending, "target_policy": None}
    if _paid_onboarding_upgrade_in_progress(organization, now=now):
        return {"can_request": False, "reason": "onboarding_payment_window", "request": pending, "target_policy": None}
    if pending:
        return {
            "can_request": False,
            "reason": "already_requested",
            "request": pending,
            "target_policy": pending.target_plan_policy if _request_matches_current_policy(pending, now=now) else None,
        }
    try:
        target = subscription_services.get_effective_plan(subscription_services.MANUFACTURER_PRO, at=now)
    except ValidationError:
        return {"can_request": False, "reason": "missing_policy", "request": None, "target_policy": None}
    return {"can_request": True, "reason": "available", "request": None, "target_policy": target}


@transaction.atomic
def create_manufacturer_upgrade_request(*, organization, actor, request=None, now=None):
    subscription_services.require_owner(actor, organization)
    now = _now(now)
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    summary = subscription_services.entitlement_summary(organization, now=now)
    if summary["plan_code"] == subscription_services.MANUFACTURER_PRO:
        raise ValidationError("This Manufacturer already has Pro entitlement or an active historical Pro trial.")
    if _paid_onboarding_upgrade_in_progress(organization, now=now):
        raise ValidationError(
            "An approved Pro onboarding payment window is already the active upgrade path. Complete the authorized billing process for that agreement."
        )
    existing = (
        ManufacturerSubscriptionUpgradeRequest.objects.select_for_update()
        .filter(organization=organization, status=ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED)
        .first()
    )
    if existing:
        return existing, False
    target = subscription_services.get_effective_plan(subscription_services.MANUFACTURER_PRO, at=now)
    if target.audience != target.Audience.MANUFACTURER:
        raise ValidationError("The current Pro policy is not a Manufacturer plan.")
    upgrade = ManufacturerSubscriptionUpgradeRequest(
        organization=organization,
        requested_by=actor,
        target_plan_policy=target,
        plan_code=target.code,
        plan_version=target.version,
        policy_snapshot=subscription_services.plan_snapshot(target),
        price_snapshot=subscription_services.price_snapshot(target),
    )
    upgrade.full_clean()
    upgrade.save()
    record_audit_event(
        actor=actor,
        action="subscription.manufacturer_upgrade_requested",
        instance=upgrade,
        metadata={
            "organization_id": organization.pk,
            "request_id": upgrade.pk,
            "plan_code": upgrade.plan_code,
            "plan_version": upgrade.plan_version,
            "entitlement_changed": False,
        },
        request=request,
    )
    return upgrade, True


def _cancel_locked(upgrade, *, actor, reason, request=None, now=None):
    if upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.COMPLETED:
        raise ValidationError("A completed Manufacturer upgrade request cannot be cancelled.")
    if upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.CANCELLED:
        return upgrade, False
    upgrade.status = ManufacturerSubscriptionUpgradeRequest.Status.CANCELLED
    upgrade.resolved_at = _now(now)
    upgrade.resolved_by = actor
    upgrade.full_clean()
    upgrade.save(update_fields=["status", "resolved_at", "resolved_by"])
    record_audit_event(
        actor=actor,
        action="subscription.manufacturer_upgrade_cancelled",
        instance=upgrade,
        metadata={
            "organization_id": upgrade.organization_id,
            "request_id": upgrade.pk,
            "reason": reason,
            "entitlement_changed": False,
        },
        request=request,
    )
    return upgrade, True


@transaction.atomic
def withdraw_manufacturer_upgrade_request(*, organization, actor, request=None, now=None):
    subscription_services.require_owner(actor, organization)
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    upgrade = (
        ManufacturerSubscriptionUpgradeRequest.objects.select_for_update()
        .filter(organization=organization, status=ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED)
        .first()
    )
    if not upgrade:
        raise ValidationError("There is no pending Manufacturer Pro upgrade request to withdraw.")
    result, _ = _cancel_locked(
        upgrade,
        actor=actor,
        reason="owner_withdrawal",
        request=request,
        now=now,
    )
    return result


@transaction.atomic
def cancel_manufacturer_upgrade_request(*, upgrade_request, actor, request=None, now=None):
    subscription_services.require_subscription_operator(actor)
    organization = Organization.objects.select_for_update().get(pk=upgrade_request.organization_id)
    upgrade = ManufacturerSubscriptionUpgradeRequest.objects.select_for_update().get(
        pk=upgrade_request.pk,
        organization=organization,
    )
    return _cancel_locked(
        upgrade,
        actor=actor,
        reason="operator_cancelled",
        request=request,
        now=now,
    )


def eligible_billing_confirmations(upgrade_request):
    if upgrade_request.status != ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED:
        return []
    return [
        row
        for row in SubscriptionBillingConfirmation.objects.filter(
            organization_id=upgrade_request.organization_id,
            plan_policy_id=upgrade_request.target_plan_policy_id,
            plan_code=upgrade_request.plan_code,
            plan_version=upgrade_request.plan_version,
            status=SubscriptionBillingConfirmation.Status.CONFIRMED,
            consumed_period__isnull=True,
            consumed_at__isnull=True,
        ).select_related("plan_policy", "confirmed_by").order_by("confirmed_at", "pk")
        if _request_confirmation_match(upgrade_request, row)
    ]


def _assert_activation_consumed_request(upgrade, confirmation, subscription):
    if confirmation.status != SubscriptionBillingConfirmation.Status.CONFIRMED:
        raise ValidationError("Upgrade completion requires confirmed billing evidence.")
    if not confirmation.consumed_period_id or not confirmation.consumed_at:
        raise ValidationError("Upgrade completion requires billing evidence consumed by a successful activation period.")
    period = SubscriptionPeriod.objects.select_related("subscription").get(pk=confirmation.consumed_period_id)
    if period.subscription_id != subscription.pk or subscription.organization_id != upgrade.organization_id:
        raise ValidationError("Consumed billing evidence does not belong to this Manufacturer subscription.")
    if subscription.status != OrganizationSubscription.Status.ACTIVE:
        raise ValidationError("Upgrade completion requires an active subscription transition.")
    if subscription.current_plan_id != upgrade.target_plan_policy_id:
        raise ValidationError("Activated subscription policy does not match the pending upgrade request.")
    if not _request_confirmation_match(upgrade, confirmation):
        raise ValidationError("Consumed billing evidence does not match the pending upgrade request snapshot.")
    if period.plan_code != upgrade.plan_code:
        raise ValidationError("Consumed subscription period does not match the requested Pro plan.")
    if dict(period.policy_snapshot or {}) != dict(upgrade.policy_snapshot or {}):
        raise ValidationError("Consumed subscription period policy snapshot does not match the request.")
    if dict(period.price_snapshot or {}) != dict(upgrade.price_snapshot or {}):
        raise ValidationError("Consumed subscription period price snapshot does not match the request.")
    return period


def _complete_locked(upgrade, *, confirmation, subscription, actor, request=None, now=None):
    if upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.COMPLETED:
        if upgrade.billing_confirmation_id == confirmation.pk:
            return upgrade, False
        raise ValidationError("This Manufacturer upgrade request was already completed with different billing evidence.")
    if upgrade.status != ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED:
        raise ValidationError("Only a pending Manufacturer upgrade request can be completed.")
    _assert_activation_consumed_request(upgrade, confirmation, subscription)
    upgrade.status = ManufacturerSubscriptionUpgradeRequest.Status.COMPLETED
    upgrade.resolved_at = _now(now)
    upgrade.resolved_by = actor
    upgrade.billing_confirmation = confirmation
    upgrade.full_clean()
    upgrade.save(update_fields=["status", "resolved_at", "resolved_by", "billing_confirmation"])
    record_audit_event(
        actor=actor,
        action="subscription.manufacturer_upgrade_completed",
        instance=upgrade,
        metadata={
            "organization_id": upgrade.organization_id,
            "request_id": upgrade.pk,
            "billing_confirmation_id": confirmation.pk,
            "subscription_period_id": confirmation.consumed_period_id,
            "plan_code": confirmation.plan_code,
            "plan_version": confirmation.plan_version,
        },
        request=request,
    )
    return upgrade, True


@transaction.atomic
def process_manufacturer_upgrade_request(
    *,
    upgrade_request,
    actor,
    billing_confirmation,
    request=None,
    now=None,
):
    """Activate a pending request only with currently authoritative, unconsumed evidence."""
    subscription_services.require_subscription_operator(actor)
    now = _now(now)
    organization = Organization.objects.select_for_update().get(pk=upgrade_request.organization_id)
    upgrade = (
        ManufacturerSubscriptionUpgradeRequest.objects.select_for_update()
        .select_related("target_plan_policy")
        .get(pk=upgrade_request.pk, organization=organization)
    )
    if upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.COMPLETED:
        if upgrade.billing_confirmation_id == getattr(billing_confirmation, "pk", None):
            return OrganizationSubscription.objects.get(organization=organization), upgrade
        raise ValidationError("This Manufacturer upgrade request is already completed.")
    if upgrade.status != ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED:
        raise ValidationError("Only a pending Manufacturer upgrade request can be processed.")
    if not _request_matches_current_policy(upgrade, now=now):
        raise ValidationError(
            "The requested Pro policy/version or price snapshot is no longer current. Cancel this request and create a new request under the current policy."
        )
    confirmation = SubscriptionBillingConfirmation.objects.select_for_update().get(pk=billing_confirmation.pk)
    if confirmation.status != SubscriptionBillingConfirmation.Status.CONFIRMED:
        raise ValidationError("Only confirmed billing evidence can process a Manufacturer upgrade request.")
    if confirmation.consumed_period_id or confirmation.consumed_at:
        raise ValidationError("This billing evidence has already been consumed and cannot process a new upgrade request.")
    if not _request_confirmation_match(upgrade, confirmation):
        raise ValidationError("Billing evidence does not match this Manufacturer upgrade request policy/version and snapshot.")

    subscription = subscription_services.activate_paid_pro(
        organization=organization,
        actor=actor,
        billing_confirmation=confirmation,
        request=request,
        now=now,
    )
    confirmation.refresh_from_db()
    subscription.refresh_from_db()
    _complete_locked(
        upgrade,
        confirmation=confirmation,
        subscription=subscription,
        actor=actor,
        request=request,
        now=now,
    )
    return subscription, upgrade


@transaction.atomic
def activate_paid_pro_with_upgrade_resolution(
    *,
    organization,
    actor,
    billing_confirmation,
    request=None,
    now=None,
):
    """Trusted operational activation that resolves or supersedes pending Manufacturer intent."""
    subscription_services.require_subscription_operator(actor)
    now = _now(now)
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    confirmation = SubscriptionBillingConfirmation.objects.select_for_update().get(pk=billing_confirmation.pk)
    pending = (
        ManufacturerSubscriptionUpgradeRequest.objects.select_for_update()
        .select_related("target_plan_policy")
        .filter(organization=organization, status=ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED)
        .first()
    )
    was_consumed = bool(confirmation.consumed_period_id or confirmation.consumed_at)

    if pending and not was_consumed and _request_matches_current_policy(pending, now=now) and _request_confirmation_match(pending, confirmation):
        subscription, _ = process_manufacturer_upgrade_request(
            upgrade_request=pending,
            actor=actor,
            billing_confirmation=confirmation,
            request=request,
            now=now,
        )
        return subscription

    subscription = subscription_services.activate_paid_pro(
        organization=organization,
        actor=actor,
        billing_confirmation=confirmation,
        request=request,
        now=now,
    )
    confirmation.refresh_from_db()

    # Exact consumed-evidence replay is deliberately a no-op. It must not
    # reactivate Pro, complete, cancel, or otherwise mutate a newer request.
    if was_consumed:
        return subscription

    if pending and confirmation.consumed_period_id and confirmation.consumed_at:
        pending.refresh_from_db()
        if pending.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED:
            _cancel_locked(
                pending,
                actor=actor,
                reason="superseded_by_other_authorized_activation",
                request=request,
                now=now,
            )
    return subscription
