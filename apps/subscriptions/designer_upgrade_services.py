"""Designer Pro upgrade intent and operator review without paid entitlement mutation."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.organizations.models import Organization

from . import services as subscription_services
from .models import DesignerSubscriptionUpgradeRequest


def _now(value=None):
    return value or timezone.now()


def designer_upgrade_availability(organization, *, now=None):
    """Return truthful Designer request state without changing subscription entitlement."""
    now = _now(now)
    if organization.kind != Organization.Kind.DESIGNER:
        raise ValidationError("Designer upgrade requests require a Designer Organization.")
    summary = subscription_services.entitlement_summary(organization, now=now)
    pending = (
        DesignerSubscriptionUpgradeRequest.objects.filter(
            organization=organization,
            status=DesignerSubscriptionUpgradeRequest.Status.PENDING,
        )
        .select_related("target_plan_policy", "requested_by")
        .first()
    )
    if summary["plan_code"] == subscription_services.DESIGNER_PRO:
        return {"can_request": False, "reason": "already_pro", "request": pending, "target_policy": None}
    if pending:
        return {
            "can_request": False,
            "reason": "already_requested",
            "request": pending,
            "target_policy": pending.target_plan_policy,
        }
    try:
        target = subscription_services.get_effective_plan(subscription_services.DESIGNER_PRO, at=now)
    except ValidationError:
        return {"can_request": False, "reason": "missing_policy", "request": None, "target_policy": None}
    if target.audience != target.Audience.DESIGNER:
        return {"can_request": False, "reason": "missing_policy", "request": None, "target_policy": None}
    return {"can_request": True, "reason": "available", "request": None, "target_policy": target}


@transaction.atomic
def create_designer_upgrade_request(*, organization, actor, request=None, now=None):
    """Record Owner intent idempotently. Never activate, bill, or mutate entitlement."""
    subscription_services.require_owner(actor, organization)
    now = _now(now)
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    if organization.kind != Organization.Kind.DESIGNER:
        raise ValidationError("Designer upgrade requests require a Designer Organization.")
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("An approved active Designer Organization is required.")

    summary = subscription_services.entitlement_summary(organization, now=now)
    if summary["plan_code"] == subscription_services.DESIGNER_PRO:
        raise ValidationError("This Designer already has Pro entitlement.")

    existing = (
        DesignerSubscriptionUpgradeRequest.objects.select_for_update()
        .filter(
            organization=organization,
            status=DesignerSubscriptionUpgradeRequest.Status.PENDING,
        )
        .first()
    )
    if existing:
        return existing, False

    target = subscription_services.get_effective_plan(subscription_services.DESIGNER_PRO, at=now)
    if target.audience != target.Audience.DESIGNER or target.code != subscription_services.DESIGNER_PRO:
        raise ValidationError("The current Pro policy is not a Designer Pro plan.")

    upgrade = DesignerSubscriptionUpgradeRequest(
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
        action="subscription.designer_upgrade_requested",
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


@transaction.atomic
def review_designer_upgrade_request(
    *,
    upgrade_request,
    actor,
    decision,
    rejection_reason="",
    request=None,
    now=None,
):
    """Review Designer intent only; paid activation remains outside this service."""
    subscription_services.require_subscription_operator(actor)
    organization = Organization.objects.select_for_update().get(pk=upgrade_request.organization_id)
    upgrade = (
        DesignerSubscriptionUpgradeRequest.objects.select_for_update()
        .select_related("organization", "target_plan_policy")
        .get(pk=upgrade_request.pk, organization=organization)
    )
    if upgrade.status != DesignerSubscriptionUpgradeRequest.Status.PENDING:
        raise ValidationError("Only a pending Designer upgrade request can be reviewed.")
    if decision not in {
        DesignerSubscriptionUpgradeRequest.Status.APPROVED,
        DesignerSubscriptionUpgradeRequest.Status.REJECTED,
    }:
        raise ValidationError("Unsupported Designer upgrade review decision.")

    reason = str(rejection_reason or "").strip()
    if decision == DesignerSubscriptionUpgradeRequest.Status.REJECTED and not reason:
        raise ValidationError("A rejection reason is required for a rejected Designer upgrade request.")
    if decision == DesignerSubscriptionUpgradeRequest.Status.APPROVED:
        reason = ""

    upgrade.status = decision
    upgrade.reviewed_at = _now(now)
    upgrade.reviewed_by = actor
    upgrade.rejection_reason = reason
    upgrade.full_clean()
    upgrade.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason"])
    record_audit_event(
        actor=actor,
        action=f"subscription.designer_upgrade_{decision}",
        instance=upgrade,
        metadata={
            "organization_id": organization.pk,
            "request_id": upgrade.pk,
            "plan_code": upgrade.plan_code,
            "plan_version": upgrade.plan_version,
            "rejection_reason_present": bool(reason),
            "entitlement_changed": False,
        },
        request=request,
    )
    return upgrade
