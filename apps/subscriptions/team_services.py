from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.organizations.models import Membership, Organization
from .models import MembershipPlanSuspension, OrganizationSubscription, TeamInvitation


@transaction.atomic
def reconcile_team_capacity_for_subscription(*, organization, actor=None, request=None, now=None):
    """Normalize active/pending Team seats to the current subscription limit.

    This is an explicit activation/reactivation boundary service. It never
    provisions a subscription and never changes Organization approval state.
    Excess memberships are plan-suspended, never deleted. Re-entry is
    idempotent because only currently active excess members are suspended.
    """
    now = now or timezone.now()
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("Team entitlement reconciliation requires an active professional Organization.")

    try:
        subscription = (
            OrganizationSubscription.objects.select_for_update()
            .select_related("current_plan")
            .get(organization=organization)
        )
    except OrganizationSubscription.DoesNotExist as exc:
        raise ValidationError("Professional subscription must exist before Team entitlement reconciliation.") from exc

    snapshot = dict(subscription.policy_snapshot or {})
    limit = int(snapshot.get("team_subaccount_limit") or subscription.current_plan.team_subaccount_limit or 0)
    pending = TeamInvitation.objects.filter(
        organization=organization,
        status=TeamInvitation.Status.PENDING,
        expires_at__gt=now,
    ).count()
    member_capacity = max(0, limit - pending)

    active_non_owners = list(
        Membership.objects.select_for_update()
        .filter(organization=organization, is_active=True)
        .exclude(role=Membership.Role.OWNER)
        .order_by("joined_at", "id")
    )
    suspended_ids = []
    for membership in active_non_owners[member_capacity:]:
        membership.is_active = False
        membership.save(update_fields=["is_active"])
        suspension, _ = MembershipPlanSuspension.objects.get_or_create(
            membership=membership,
            defaults={
                "suspended_by_plan": True,
                "reason": "subscription_team_limit",
                "suspended_at": now,
                "restored_at": None,
            },
        )
        changed_fields = []
        if not suspension.suspended_by_plan:
            suspension.suspended_by_plan = True
            changed_fields.append("suspended_by_plan")
        if suspension.reason != "subscription_team_limit":
            suspension.reason = "subscription_team_limit"
            changed_fields.append("reason")
        if suspension.restored_at is not None:
            suspension.restored_at = None
            changed_fields.append("restored_at")
        if changed_fields:
            suspension.suspended_at = now
            changed_fields.append("suspended_at")
            suspension.save(update_fields=changed_fields)
        suspended_ids.append(membership.pk)
        record_audit_event(
            actor=actor,
            action="subscription.team_member_plan_suspended",
            instance=membership,
            metadata={
                "organization_id": organization.pk,
                "reason": "activation_team_limit",
                "team_limit": limit,
                "pending_invitation_seats": pending,
            },
            request=request,
        )

    used = (
        Membership.objects.filter(organization=organization, is_active=True)
        .exclude(role=Membership.Role.OWNER)
        .count()
        + pending
    )
    remaining = max(0, limit - used)
    restored_ids = []
    if remaining:
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
        for suspension in suspensions:
            if remaining <= 0:
                break
            membership = suspension.membership
            if membership.role == Membership.Role.OWNER:
                continue
            if membership.is_active:
                suspension.suspended_by_plan = False
                suspension.restored_at = now
                suspension.save(update_fields=["suspended_by_plan", "restored_at"])
                continue
            membership.is_active = True
            membership.full_clean()
            membership.save(update_fields=["is_active"])
            suspension.suspended_by_plan = False
            suspension.restored_at = now
            suspension.save(update_fields=["suspended_by_plan", "restored_at"])
            restored_ids.append(membership.pk)
            remaining -= 1
            record_audit_event(
                actor=actor,
                action="subscription.team_member_plan_restored",
                instance=membership,
                metadata={"organization_id": organization.pk, "reason": "activation_team_capacity"},
                request=request,
            )

    return {
        "subscription_id": subscription.pk,
        "team_limit": limit,
        "pending_invitation_seats": pending,
        "suspended_membership_ids": suspended_ids,
        "restored_membership_ids": restored_ids,
    }
