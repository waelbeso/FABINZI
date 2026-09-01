import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.artwork.models import Artwork
from apps.audit.services import record_audit_event
from apps.checkout.models import CustomerOrder
from apps.design.models import GarmentDesign
from apps.notifications.models import Notification
from apps.operations.models import FulfillmentRecord, ProductionJob
from apps.organizations.models import Membership, OnboardingApplication, Organization
from apps.storefront.models import StoreProduct
from .models import (
    ArtworkPlanEntitlementState,
    DesignPlanEntitlementState,
    ManufacturerOfferUsage,
    MembershipPlanSuspension,
    OrganizationSubscription,
    StoreProductPlanPause,
    SubscriptionBillingConfirmation,
    SubscriptionPeriod,
    SubscriptionPlanPolicy,
    SubscriptionReminderEvent,
    SubscriptionReminderMilestone,
    SubscriptionTrialException,
    TeamInvitation,
    TeamInvitationConfiguration,
)

DESIGNER_STARTER = "designer_starter"
DESIGNER_PRO = "designer_pro"
MANUFACTURER_STARTER = "manufacturer_starter"
MANUFACTURER_PRO = "manufacturer_pro"

DESIGN_SLOT_STATUSES = {GarmentDesign.Status.IN_REVIEW, GarmentDesign.Status.APPROVED}
ARTWORK_SLOT_STATUSES = {Artwork.Status.IN_REVIEW, Artwork.Status.APPROVED}

DESIGNER_TEAM_ROLES = {
    Membership.Role.MANAGER,
    Membership.Role.DESIGN_MANAGER,
    Membership.Role.DESIGNER,
    Membership.Role.ACCOUNTANT,
}
MANUFACTURER_TEAM_ROLES = {
    Membership.Role.MANAGER,
    Membership.Role.PRODUCTION_MANAGER,
    Membership.Role.OPERATOR,
    Membership.Role.QC,
    Membership.Role.ACCOUNTANT,
}


def _now(value=None):
    return value or timezone.now()


def _local_date(value=None):
    value = _now(value)
    return timezone.localtime(value).date()


def plan_snapshot(plan):
    return {
        "plan_policy_id": plan.pk,
        "code": plan.code,
        "version": plan.version,
        "audience": plan.audience,
        "public_name_ar": plan.public_name_ar,
        "public_name_en": plan.public_name_en,
        "tax_inclusive": plan.tax_inclusive,
        "trial_months": plan.trial_months,
        "designer_active_design_limit": plan.designer_active_design_limit,
        "designer_active_artwork_limit": plan.designer_active_artwork_limit,
        "manufacturer_monthly_offer_limit": plan.manufacturer_monthly_offer_limit,
        "team_subaccount_limit": plan.team_subaccount_limit,
        "effective_from": plan.effective_from.isoformat(),
        "effective_to": plan.effective_to.isoformat() if plan.effective_to else None,
    }


def price_snapshot(plan):
    return {
        "monthly_price": str(plan.monthly_price),
        "currency": plan.currency,
        "tax_inclusive": plan.tax_inclusive,
    }


def get_effective_plan(code, *, at=None):
    day = _local_date(at)
    plan = (
        SubscriptionPlanPolicy.objects.filter(
            code=code,
            active=True,
            effective_from__lte=day,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=day))
        .order_by("-effective_from", "-version", "-pk")
        .first()
    )
    if not plan:
        raise ValidationError(f"No effective subscription policy exists for {code}.")
    return plan


def starter_code_for(organization):
    return DESIGNER_STARTER if organization.kind == Organization.Kind.DESIGNER else MANUFACTURER_STARTER


def pro_code_for(organization):
    return DESIGNER_PRO if organization.kind == Organization.Kind.DESIGNER else MANUFACTURER_PRO


def _activation_at(organization, fallback=None):
    try:
        application = organization.onboarding_application
    except OnboardingApplication.DoesNotExist:
        application = None
    if application and application.status == OnboardingApplication.Status.APPROVED and application.reviewed_at:
        return application.reviewed_at
    return fallback or organization.updated_at or timezone.now()


def _period_end(start, *, hard_end=None):
    end = start + relativedelta(months=1)
    if hard_end and end > hard_end:
        return hard_end
    return end


def _create_period(subscription, *, billing_reference=""):
    sequence = (subscription.periods.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
    return SubscriptionPeriod.objects.create(
        subscription=subscription,
        sequence=sequence,
        plan_code=subscription.current_plan.code,
        status_snapshot=subscription.status,
        period_start=subscription.current_period_start,
        period_end=subscription.current_period_end,
        policy_snapshot=dict(subscription.policy_snapshot or {}),
        price_snapshot=dict(subscription.price_snapshot or {}),
        billing_reference=billing_reference,
    )


@transaction.atomic
def ensure_subscription_for_organization(organization, *, activation_at=None, actor=None, request=None):
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    try:
        return OrganizationSubscription.objects.select_for_update().select_related("current_plan").get(organization=organization)
    except OrganizationSubscription.DoesNotExist:
        pass

    if organization.kind not in {Organization.Kind.DESIGNER, Organization.Kind.MANUFACTURER}:
        raise ValidationError("Professional subscriptions require a Designer or Manufacturer Organization.")
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("A professional subscription cannot create or replace Organization approval.")

    started_at = activation_at or _activation_at(organization)
    if organization.kind == Organization.Kind.MANUFACTURER:
        plan = get_effective_plan(MANUFACTURER_PRO, at=started_at)
        trial_ends_at = started_at + relativedelta(months=6)
        status = OrganizationSubscription.Status.TRIALING
        hard_period_end = trial_ends_at
        subscription = OrganizationSubscription.objects.create(
            organization=organization,
            current_plan=plan,
            status=status,
            started_at=started_at,
            trial_started_at=started_at,
            trial_ends_at=trial_ends_at,
            trial_consumed=True,
            current_period_start=started_at,
            current_period_end=_period_end(started_at, hard_end=hard_period_end),
            next_billing_at=trial_ends_at,
            policy_snapshot=plan_snapshot(plan),
            price_snapshot=price_snapshot(plan),
        )
        _create_period(subscription)
        record_audit_event(
            actor=actor,
            action="subscription.manufacturer_trial_started",
            instance=subscription,
            metadata={
                "organization_id": organization.pk,
                "trial_started_at": started_at.isoformat(),
                "trial_ends_at": trial_ends_at.isoformat(),
            },
            request=request,
        )
        return subscription

    plan = get_effective_plan(DESIGNER_STARTER, at=started_at)
    subscription = OrganizationSubscription.objects.create(
        organization=organization,
        current_plan=plan,
        status=OrganizationSubscription.Status.ACTIVE,
        started_at=started_at,
        current_period_start=started_at,
        current_period_end=_period_end(started_at),
        next_billing_at=None,
        policy_snapshot=plan_snapshot(plan),
        price_snapshot=price_snapshot(plan),
    )
    _create_period(subscription)
    record_audit_event(
        actor=actor,
        action="subscription.created",
        instance=subscription,
        metadata={"organization_id": organization.pk, "plan_code": plan.code},
        request=request,
    )
    return subscription


def _owner_membership(actor, organization):
    if not actor or not actor.is_authenticated:
        return None
    return Membership.objects.filter(
        organization=organization,
        user=actor,
        role=Membership.Role.OWNER,
        is_active=True,
    ).first()


def require_owner(actor, organization):
    membership = _owner_membership(actor, organization)
    if not membership:
        raise PermissionDenied("Organization Owner authority is required.")
    return membership


def require_subscription_operator(actor):
    if not actor or not actor.is_authenticated or not actor.is_staff:
        raise PermissionDenied("Authorized operational staff access is required.")
    if not (actor.is_superuser or actor.has_perm("subscriptions.manage_professional_subscription")):
        raise PermissionDenied("Professional subscription lifecycle permission is required.")
    return True


def _require_owner_or_operator(actor, organization):
    if _owner_membership(actor, organization):
        return True
    return require_subscription_operator(actor)


def _roll_nonpaid_period_locked(subscription, *, now=None):
    now = _now(now)
    changed = False
    hard_end = subscription.trial_ends_at if subscription.status == OrganizationSubscription.Status.TRIALING else None
    while now >= subscription.current_period_end and (not hard_end or subscription.current_period_end < hard_end):
        start = subscription.current_period_end
        end = _period_end(start, hard_end=hard_end)
        if end <= start:
            break
        subscription.current_period_start = start
        subscription.current_period_end = end
        subscription.save(update_fields=["current_period_start", "current_period_end", "updated_at"])
        _create_period(subscription)
        changed = True
    return changed


def _subscription_locked_for_org(organization, *, now=None):
    subscription = ensure_subscription_for_organization(organization)
    subscription = OrganizationSubscription.objects.select_for_update().select_related("current_plan", "organization").get(pk=subscription.pk)
    if subscription.status in {OrganizationSubscription.Status.TRIALING, OrganizationSubscription.Status.ACTIVE} and subscription.current_plan.monthly_price == 0:
        _roll_nonpaid_period_locked(subscription, now=now)
    elif subscription.status == OrganizationSubscription.Status.TRIALING:
        _roll_nonpaid_period_locked(subscription, now=now)
    return subscription


def _active_membership_seats(organization):
    return organization.memberships.filter(is_active=True).exclude(role=Membership.Role.OWNER).count()


def _pending_invitation_seats(organization, *, now=None, exclude_invitation_id=None):
    now = _now(now)
    qs = TeamInvitation.objects.filter(
        organization=organization,
        status=TeamInvitation.Status.PENDING,
        expires_at__gt=now,
    )
    if exclude_invitation_id:
        qs = qs.exclude(pk=exclude_invitation_id)
    return qs.count()


def _design_usage(organization):
    return GarmentDesign.objects.filter(
        organization=organization,
        status__in=DESIGN_SLOT_STATUSES,
    ).exclude(plan_entitlement_state__plan_paused=True).count()


def _artwork_usage(organization):
    return Artwork.objects.filter(
        organization=organization,
        status__in=ARTWORK_SLOT_STATUSES,
    ).exclude(plan_entitlement_state__plan_paused=True).count()


def entitlement_summary(organization, *, now=None):
    now = _now(now)
    subscription = _subscription_locked_for_org(organization, now=now)
    snapshot = dict(subscription.policy_snapshot or plan_snapshot(subscription.current_plan))
    summary = {
        "subscription": subscription,
        "plan": subscription.current_plan,
        "plan_code": snapshot.get("code", subscription.current_plan.code),
        "status": subscription.status,
        "benefits_apply": bool(
            organization.verification_status == Organization.VerificationStatus.ACTIVE
            and subscription.status in {
                OrganizationSubscription.Status.TRIALING,
                OrganizationSubscription.Status.ACTIVE,
                OrganizationSubscription.Status.GRACE_PERIOD,
                OrganizationSubscription.Status.DOWNGRADED,
            }
        ),
        "team_limit": int(snapshot.get("team_subaccount_limit") or 0),
        "active_team_seats": _active_membership_seats(organization),
        "pending_team_seats": _pending_invitation_seats(organization, now=now),
    }
    summary["team_used"] = summary["active_team_seats"] + summary["pending_team_seats"]
    summary["team_remaining"] = max(0, summary["team_limit"] - summary["team_used"])
    if organization.kind == Organization.Kind.DESIGNER:
        summary.update({
            "design_limit": int(snapshot.get("designer_active_design_limit") or 0),
            "artwork_limit": int(snapshot.get("designer_active_artwork_limit") or 0),
            "design_used": _design_usage(organization),
            "artwork_used": _artwork_usage(organization),
        })
        summary["design_remaining"] = max(0, summary["design_limit"] - summary["design_used"])
        summary["artwork_remaining"] = max(0, summary["artwork_limit"] - summary["artwork_used"])
    else:
        start_day = timezone.localtime(subscription.current_period_start).date()
        end_day = timezone.localtime(subscription.current_period_end).date()
        used = ManufacturerOfferUsage.objects.filter(organization=organization, period_start=start_day).count()
        summary.update({
            "offer_limit": int(snapshot.get("manufacturer_monthly_offer_limit") or 0),
            "offer_used": used,
            "offer_remaining": max(0, int(snapshot.get("manufacturer_monthly_offer_limit") or 0) - used),
            "usage_period_start": start_day,
            "usage_period_end": end_day,
        })
    return summary


@transaction.atomic
def assert_designer_slot_available(*, organization, kind, object_id=None, now=None):
    if organization.kind != Organization.Kind.DESIGNER or organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("An approved active Designer Organization is required.")
    subscription = _subscription_locked_for_org(organization, now=now)
    snapshot = dict(subscription.policy_snapshot or {})
    if kind == "design":
        limit = int(snapshot.get("designer_active_design_limit") or 0)
        qs = GarmentDesign.objects.filter(organization=organization, status__in=DESIGN_SLOT_STATUSES).exclude(plan_entitlement_state__plan_paused=True)
    elif kind == "artwork":
        limit = int(snapshot.get("designer_active_artwork_limit") or 0)
        qs = Artwork.objects.filter(organization=organization, status__in=ARTWORK_SLOT_STATUSES).exclude(plan_entitlement_state__plan_paused=True)
    else:
        raise ValidationError("Unsupported Designer entitlement slot kind.")
    if object_id:
        qs = qs.exclude(pk=object_id)
    if qs.count() >= limit:
        raise ValidationError(f"The current plan allows {limit} active {kind} slot(s). Archive or pause an active item, or upgrade the plan.")
    return True


@transaction.atomic
def consume_manufacturer_offer(*, quote, now=None):
    organization = quote.invitation.manufacturer
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("An approved active Manufacturer Organization is required to submit a Manufacturing Offer.")
    if ManufacturerOfferUsage.objects.filter(quote=quote).exists():
        return ManufacturerOfferUsage.objects.get(quote=quote)
    subscription = _subscription_locked_for_org(organization, now=now)
    snapshot = dict(subscription.policy_snapshot or {})
    limit = int(snapshot.get("manufacturer_monthly_offer_limit") or 0)
    start_day = timezone.localtime(subscription.current_period_start).date()
    end_day = timezone.localtime(subscription.current_period_end).date()
    used = ManufacturerOfferUsage.objects.filter(organization=organization, period_start=start_day).count()
    if used >= limit:
        raise ValidationError(f"The current plan allows {limit} submitted Manufacturing Offer(s) in this monthly usage period.")
    try:
        usage = ManufacturerOfferUsage.objects.create(
            subscription=subscription,
            organization=organization,
            quote=quote,
            plan_code=snapshot.get("code", subscription.current_plan.code),
            period_start=start_day,
            period_end=end_day,
        )
    except IntegrityError:
        usage = ManufacturerOfferUsage.objects.get(quote=quote)
    if used + 1 >= limit:
        record_audit_event(
            action="subscription.manufacturer_offer_quota_reached",
            instance=subscription,
            metadata={"organization_id": organization.pk, "used": used + 1, "limit": limit},
        )
    return usage


def _validate_team_role(organization, role):
    allowed = DESIGNER_TEAM_ROLES if organization.kind == Organization.Kind.DESIGNER else MANUFACTURER_TEAM_ROLES
    if role == Membership.Role.OWNER:
        raise ValidationError("Ownership cannot be assigned through a team invitation.")
    if role not in allowed:
        raise ValidationError("This team role is not valid for the Organization audience.")
    return role


def _team_limit_locked(organization, *, now=None):
    subscription = _subscription_locked_for_org(organization, now=now)
    return subscription, int((subscription.policy_snapshot or {}).get("team_subaccount_limit") or 0)


@transaction.atomic
def create_team_invitation(*, organization, actor, email, role, request=None, now=None):
    require_owner(actor, organization)
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("Team invitations require an approved active Organization.")
    role = _validate_team_role(organization, role)
    normalized_email = str(email or "").strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise ValidationError("A valid invitation email is required.")
    now = _now(now)
    subscription, limit = _team_limit_locked(organization, now=now)
    active = _active_membership_seats(organization)
    pending = _pending_invitation_seats(organization, now=now)
    if active + pending >= limit:
        raise ValidationError(f"The current plan allows {limit} active/pending subaccount seat(s).")
    existing = TeamInvitation.objects.filter(organization=organization, email__iexact=normalized_email, status=TeamInvitation.Status.PENDING).first()
    if existing and existing.expires_at > now:
        raise ValidationError("A pending invitation already exists for this email.")
    if existing:
        existing.status = TeamInvitation.Status.EXPIRED
        existing.save(update_fields=["status"])
    token = secrets.token_urlsafe(32)
    expiry_days = TeamInvitationConfiguration.current_expiry_days()
    invitation = TeamInvitation.objects.create(
        organization=organization,
        email=normalized_email,
        role=role,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_by=actor,
        expires_at=now + timedelta(days=expiry_days),
    )
    user = get_user_model().objects.filter(email__iexact=normalized_email).first()
    if user:
        Notification.objects.create(
            recipient=user,
            type="team_invitation",
            title_en=f"Invitation to join {organization.display_name}",
            title_ar=f"دعوة للانضمام إلى {organization.display_name}",
            body_en="A FABINZI Organization Owner invited you to join their team.",
            body_ar="دعاك مالك مؤسسة على FABINZI للانضمام إلى الفريق.",
            destination=f"/team/invitations/accept/{token}/",
        )
    record_audit_event(
        actor=actor,
        action="team.invited",
        instance=invitation,
        metadata={"organization_id": organization.pk, "role": role, "expires_at": invitation.expires_at.isoformat()},
        request=request,
    )
    return invitation, token


@transaction.atomic
def revoke_team_invitation(*, invitation, actor, request=None):
    require_owner(actor, invitation.organization)
    invitation = TeamInvitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.status != TeamInvitation.Status.PENDING:
        raise ValidationError("Only a pending team invitation can be revoked.")
    invitation.status = TeamInvitation.Status.REVOKED
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["status", "revoked_at"])
    record_audit_event(actor=actor, action="team.invite_revoked", instance=invitation, metadata={"organization_id": invitation.organization_id}, request=request)
    return invitation


@transaction.atomic
def accept_team_invitation(*, token, actor, request=None, now=None):
    if not actor or not actor.is_authenticated:
        raise PermissionDenied("Sign in to accept a team invitation.")
    now = _now(now)
    token_hash = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
    invitation = TeamInvitation.objects.select_for_update().select_related("organization").filter(token_hash=token_hash).first()
    if not invitation:
        raise ValidationError("Team invitation is invalid.")
    if invitation.status != TeamInvitation.Status.PENDING:
        raise ValidationError("Team invitation is no longer pending.")
    if invitation.expires_at <= now:
        invitation.status = TeamInvitation.Status.EXPIRED
        invitation.save(update_fields=["status"])
        raise ValidationError("Team invitation has expired.")
    if str(actor.email or "").strip().lower() != invitation.email.lower():
        raise PermissionDenied("This invitation belongs to a different email address.")
    organization = Organization.objects.select_for_update().get(pk=invitation.organization_id)
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("The Organization is not currently active.")
    _, limit = _team_limit_locked(organization, now=now)
    active = _active_membership_seats(organization)
    pending_other = _pending_invitation_seats(organization, now=now, exclude_invitation_id=invitation.pk)
    if active + pending_other >= limit:
        raise ValidationError("The Organization no longer has an available team seat.")
    membership, _ = Membership.objects.get_or_create(
        organization=organization,
        user=actor,
        defaults={"role": invitation.role, "is_active": True},
    )
    if membership.role == Membership.Role.OWNER:
        raise ValidationError("An existing Owner membership cannot be changed by invitation acceptance.")
    membership.role = _validate_team_role(organization, invitation.role)
    membership.is_active = True
    membership.full_clean()
    membership.save(update_fields=["role", "is_active"])
    MembershipPlanSuspension.objects.filter(membership=membership).update(suspended_by_plan=False, restored_at=now)
    invitation.status = TeamInvitation.Status.ACCEPTED
    invitation.accepted_by = actor
    invitation.accepted_at = now
    invitation.save(update_fields=["status", "accepted_by", "accepted_at"])
    record_audit_event(actor=actor, action="team.invite_accepted", instance=membership, metadata={"organization_id": organization.pk, "invitation_id": invitation.pk, "role": membership.role}, request=request)
    return membership


@transaction.atomic
def suspend_team_member(*, membership, actor, request=None, reason="owner_action"):
    require_owner(actor, membership.organization)
    membership = Membership.objects.select_for_update().get(pk=membership.pk)
    if membership.role == Membership.Role.OWNER:
        raise ValidationError("Organization Owner membership cannot be suspended through Team management.")
    if not membership.is_active:
        return membership
    membership.is_active = False
    membership.save(update_fields=["is_active"])
    record_audit_event(actor=actor, action="team.member_suspended", instance=membership, metadata={"organization_id": membership.organization_id, "reason": reason}, request=request)
    return membership


@transaction.atomic
def restore_team_member(*, membership, actor, request=None):
    require_owner(actor, membership.organization)
    membership = Membership.objects.select_for_update().select_related("organization").get(pk=membership.pk)
    if membership.role == Membership.Role.OWNER:
        raise ValidationError("Owner restoration is not managed through subaccount seats.")
    _, limit = _team_limit_locked(membership.organization)
    used = _active_membership_seats(membership.organization) + _pending_invitation_seats(membership.organization)
    if not membership.is_active and used >= limit:
        raise ValidationError("The current plan has no available team seat.")
    membership.is_active = True
    membership.full_clean()
    membership.save(update_fields=["is_active"])
    MembershipPlanSuspension.objects.filter(membership=membership).update(suspended_by_plan=False, restored_at=timezone.now())
    record_audit_event(actor=actor, action="team.member_restored", instance=membership, metadata={"organization_id": membership.organization_id}, request=request)
    return membership


@transaction.atomic
def change_team_member_role(*, membership, actor, role, request=None):
    require_owner(actor, membership.organization)
    membership = Membership.objects.select_for_update().get(pk=membership.pk)
    if membership.role == Membership.Role.OWNER or role == Membership.Role.OWNER:
        raise ValidationError("Organization ownership cannot be changed through Team role management.")
    membership.role = _validate_team_role(membership.organization, role)
    membership.full_clean()
    membership.save(update_fields=["role"])
    record_audit_event(actor=actor, action="team.member_role_changed", instance=membership, metadata={"organization_id": membership.organization_id, "role": role}, request=request)
    return membership


def _content_active_chain_qs(kind, object_id):
    active_order_statuses = [CustomerOrder.Status.CONFIRMED]
    active_job_statuses = [
        ProductionJob.Status.AWAITING_ASSIGNMENT,
        ProductionJob.Status.QUEUED,
        ProductionJob.Status.IN_PRODUCTION,
        ProductionJob.Status.QC_PENDING,
        ProductionJob.Status.QC_FAILED,
        ProductionJob.Status.READY,
    ]
    active_fulfillment_statuses = [
        FulfillmentRecord.Status.WAITING_PRODUCTION,
        FulfillmentRecord.Status.READY_TO_PACK,
        FulfillmentRecord.Status.PACKED,
        FulfillmentRecord.Status.SHIPPED,
        FulfillmentRecord.Status.FAILED,
    ]
    base = StoreProduct.objects.all()
    if kind == "design":
        base = base.filter(designed_product__garment_version__design_id=object_id)
    else:
        base = base.filter(designed_product__artwork_version__artwork_id=object_id)
    return base.filter(
        Q(order_items__order__status__in=active_order_statuses)
        | Q(order_items__order__production_job__status__in=active_job_statuses)
        | Q(order_items__order__fulfillment__status__in=active_fulfillment_statuses)
    ).distinct()


def content_has_active_chain(kind, object_id):
    return _content_active_chain_qs(kind, object_id).exists()


def _pause_store_products_for_content(kind, object_id, *, now=None):
    now = _now(now)
    qs = StoreProduct.objects.filter(status=StoreProduct.Status.PUBLISHED)
    if kind == "design":
        qs = qs.filter(designed_product__garment_version__design_id=object_id)
    else:
        qs = qs.filter(designed_product__artwork_version__artwork_id=object_id)
    for product in qs.select_for_update():
        StoreProductPlanPause.objects.update_or_create(
            store_product=product,
            defaults={"previous_status": product.status, "active": True, "paused_at": now, "restored_at": None},
        )
        product.status = StoreProduct.Status.HIDDEN
        product.save(update_fields=["status", "updated_at"])


def _restore_store_product_pauses(organization, *, now=None):
    now = _now(now)
    pauses = StoreProductPlanPause.objects.filter(store_product__storefront__organization=organization, active=True).select_related("store_product")
    for pause in pauses:
        product = pause.store_product
        if product.status == StoreProduct.Status.HIDDEN and pause.previous_status == StoreProduct.Status.PUBLISHED:
            product.status = StoreProduct.Status.PUBLISHED
            product.save(update_fields=["status", "updated_at"])
        pause.active = False
        pause.restored_at = now
        pause.save(update_fields=["active", "restored_at"])


@transaction.atomic
def apply_designer_downgrade(*, organization, actor=None, retained_design_ids=None, retained_artwork_ids=None, request=None, now=None):
    now = _now(now)
    if organization.kind != Organization.Kind.DESIGNER:
        return
    starter = get_effective_plan(DESIGNER_STARTER, at=now)
    design_limit = int(starter.designer_active_design_limit or 0)
    artwork_limit = int(starter.designer_active_artwork_limit or 0)
    active_designs = list(GarmentDesign.objects.select_for_update().filter(organization=organization, status__in=DESIGN_SLOT_STATUSES).order_by("created_at", "id"))
    active_artworks = list(Artwork.objects.select_for_update().filter(organization=organization, status__in=ARTWORK_SLOT_STATUSES).order_by("created_at", "id"))

    selected_designs = [d.pk for d in active_designs[:design_limit]] if retained_design_ids is None else [int(x) for x in retained_design_ids]
    selected_artworks = [a.pk for a in active_artworks[:artwork_limit]] if retained_artwork_ids is None else [int(x) for x in retained_artwork_ids]
    valid_design_ids = {d.pk for d in active_designs}
    valid_artwork_ids = {a.pk for a in active_artworks}
    if len(set(selected_designs)) > design_limit or not set(selected_designs).issubset(valid_design_ids):
        raise ValidationError("Designer retained Design selection exceeds Starter capacity or includes invalid content.")
    if len(set(selected_artworks)) > artwork_limit or not set(selected_artworks).issubset(valid_artwork_ids):
        raise ValidationError("Designer retained Artwork selection exceeds Starter capacity or includes invalid content.")

    for design in active_designs:
        retained = design.pk in set(selected_designs)
        protected = content_has_active_chain("design", design.pk)
        state, _ = DesignPlanEntitlementState.objects.get_or_create(design=design)
        state.retained = retained
        state.plan_paused = not retained
        state.protected_active_chain = protected if not retained else False
        state.pause_reason = "starter_plan_limit" if not retained else ""
        state.paused_at = now if not retained else None
        state.save()
        if not retained:
            _pause_store_products_for_content("design", design.pk, now=now)
            record_audit_event(actor=actor, action="subscription.designer_content_plan_paused", instance=design, metadata={"organization_id": organization.pk, "protected_active_chain": protected}, request=request)
    for artwork in active_artworks:
        retained = artwork.pk in set(selected_artworks)
        protected = content_has_active_chain("artwork", artwork.pk)
        state, _ = ArtworkPlanEntitlementState.objects.get_or_create(artwork=artwork)
        state.retained = retained
        state.plan_paused = not retained
        state.protected_active_chain = protected if not retained else False
        state.pause_reason = "starter_plan_limit" if not retained else ""
        state.paused_at = now if not retained else None
        state.save()
        if not retained:
            _pause_store_products_for_content("artwork", artwork.pk, now=now)
            record_audit_event(actor=actor, action="subscription.designer_content_plan_paused", instance=artwork, metadata={"organization_id": organization.pk, "protected_active_chain": protected}, request=request)
    record_audit_event(actor=actor, action="subscription.designer_excess_selection", instance=organization, metadata={"retained_design_ids": selected_designs, "retained_artwork_ids": selected_artworks}, request=request)


@transaction.atomic
def apply_manufacturer_team_downgrade(*, organization, actor=None, retained_membership_ids=None, request=None, now=None):
    now = _now(now)
    if organization.kind != Organization.Kind.MANUFACTURER:
        return
    starter = get_effective_plan(MANUFACTURER_STARTER, at=now)
    limit = int(starter.team_subaccount_limit or 0)
    members = list(Membership.objects.select_for_update().filter(organization=organization, is_active=True).exclude(role=Membership.Role.OWNER).order_by("joined_at", "id"))
    retained = [m.pk for m in members[:limit]] if retained_membership_ids is None else [int(x) for x in retained_membership_ids]
    if len(set(retained)) > limit or not set(retained).issubset({m.pk for m in members}):
        raise ValidationError("Retained Manufacturer team selection exceeds Starter seat capacity or includes invalid members.")
    for membership in members:
        if membership.pk in set(retained):
            continue
        membership.is_active = False
        membership.save(update_fields=["is_active"])
        MembershipPlanSuspension.objects.update_or_create(
            membership=membership,
            defaults={"suspended_by_plan": True, "reason": "starter_plan_limit", "suspended_at": now, "restored_at": None},
        )
        record_audit_event(actor=actor, action="subscription.team_member_plan_suspended", instance=membership, metadata={"organization_id": organization.pk}, request=request)


@transaction.atomic
def restore_plan_limited_resources(*, organization, actor=None, request=None, now=None):
    now = _now(now)
    if organization.kind == Organization.Kind.DESIGNER:
        DesignPlanEntitlementState.objects.filter(design__organization=organization, plan_paused=True).update(plan_paused=False, retained=False, protected_active_chain=False, pause_reason="", paused_at=None)
        ArtworkPlanEntitlementState.objects.filter(artwork__organization=organization, plan_paused=True).update(plan_paused=False, retained=False, protected_active_chain=False, pause_reason="", paused_at=None)
        _restore_store_product_pauses(organization, now=now)
    else:
        subscription = _subscription_locked_for_org(organization, now=now)
        limit = int((subscription.policy_snapshot or {}).get("team_subaccount_limit") or 0)
        current = _active_membership_seats(organization) + _pending_invitation_seats(organization, now=now)
        suspensions = MembershipPlanSuspension.objects.select_related("membership").filter(membership__organization=organization, suspended_by_plan=True, restored_at__isnull=True).order_by("membership__joined_at", "membership_id")
        for suspension in suspensions:
            if current >= limit:
                break
            membership = suspension.membership
            membership.is_active = True
            membership.save(update_fields=["is_active"])
            suspension.suspended_by_plan = False
            suspension.restored_at = now
            suspension.save(update_fields=["suspended_by_plan", "restored_at"])
            current += 1
            record_audit_event(actor=actor, action="subscription.team_member_plan_restored", instance=membership, metadata={"organization_id": organization.pk}, request=request)


@transaction.atomic
def downgrade_to_starter(*, subscription, actor=None, automatic=False, retained_design_ids=None, retained_artwork_ids=None, retained_membership_ids=None, request=None, now=None, cancelled=False):
    now = _now(now)
    subscription = OrganizationSubscription.objects.select_for_update().select_related("organization", "current_plan").get(pk=subscription.pk)
    organization = subscription.organization
    if actor and not automatic:
        _require_owner_or_operator(actor, organization)
    starter = get_effective_plan(starter_code_for(organization), at=now)
    old_plan = subscription.current_plan.code
    subscription.current_plan = starter
    subscription.status = OrganizationSubscription.Status.CANCELLED if cancelled else OrganizationSubscription.Status.DOWNGRADED
    subscription.current_period_start = now
    subscription.current_period_end = _period_end(now)
    subscription.next_billing_at = None
    subscription.grace_started_on = None
    subscription.grace_ends_on = None
    subscription.downgraded_at = now
    subscription.cancelled_at = now if cancelled else subscription.cancelled_at
    subscription.policy_snapshot = plan_snapshot(starter)
    subscription.price_snapshot = price_snapshot(starter)
    subscription.save()
    _create_period(subscription)
    if organization.kind == Organization.Kind.DESIGNER:
        apply_designer_downgrade(organization=organization, actor=actor, retained_design_ids=retained_design_ids, retained_artwork_ids=retained_artwork_ids, request=request, now=now)
    else:
        apply_manufacturer_team_downgrade(organization=organization, actor=actor, retained_membership_ids=retained_membership_ids, request=request, now=now)
    action = "subscription.cancelled" if cancelled else ("subscription.automatic_downgrade" if automatic else "subscription.downgraded")
    record_audit_event(actor=actor, action=action, instance=subscription, metadata={"organization_id": organization.pk, "old_plan": old_plan, "new_plan": starter.code}, request=request)
    _notify_subscription_owners(subscription, "subscription_downgraded", "Subscription moved to Starter", "تم نقل الاشتراك إلى Starter")
    return subscription


@transaction.atomic
def cancel_subscription(*, subscription, actor, request=None):
    require_owner(actor, subscription.organization)
    return downgrade_to_starter(subscription=subscription, actor=actor, cancelled=True, request=request)


@transaction.atomic
def confirm_subscription_billing(*, organization, actor, plan_code, amount, currency, provider, provider_reference, idempotency_key, request=None):
    require_subscription_operator(actor)
    plan = get_effective_plan(plan_code)
    if plan.audience != organization.kind:
        raise ValidationError("Billing confirmation plan audience does not match the Organization.")
    if Decimal(str(amount)) != plan.monthly_price or str(currency).upper() != plan.currency:
        raise ValidationError("Billing confirmation amount/currency must match the effective plan policy.")
    confirmation, created = SubscriptionBillingConfirmation.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "organization": organization,
            "plan_code": plan.code,
            "amount": plan.monthly_price,
            "currency": plan.currency,
            "provider": str(provider).strip(),
            "provider_reference": str(provider_reference).strip(),
            "confirmed_by": actor,
        },
    )
    if not created and (confirmation.organization_id != organization.pk or confirmation.plan_code != plan.code):
        raise ValidationError("Billing idempotency key is already bound to different subscription evidence.")
    record_audit_event(actor=actor, action="subscription.billing_confirmed", instance=confirmation, metadata={"organization_id": organization.pk, "plan_code": plan.code, "provider": confirmation.provider}, request=request)
    return confirmation


@transaction.atomic
def activate_paid_pro(*, organization, actor, billing_confirmation, request=None, now=None):
    _require_owner_or_operator(actor, organization)
    now = _now(now)
    confirmation = SubscriptionBillingConfirmation.objects.select_for_update().get(pk=billing_confirmation.pk)
    if confirmation.organization_id != organization.pk or confirmation.status != SubscriptionBillingConfirmation.Status.CONFIRMED:
        raise ValidationError("Confirmed billing evidence for this Organization is required.")
    pro = get_effective_plan(pro_code_for(organization), at=now)
    if confirmation.plan_code != pro.code:
        raise ValidationError("Billing evidence does not confirm the current Pro plan.")
    subscription = _subscription_locked_for_org(organization, now=now)
    old_plan = subscription.current_plan.code
    subscription.current_plan = pro
    subscription.status = OrganizationSubscription.Status.ACTIVE
    subscription.current_period_start = now
    subscription.current_period_end = _period_end(now)
    subscription.next_billing_at = subscription.current_period_end
    subscription.grace_started_on = None
    subscription.grace_ends_on = None
    subscription.policy_snapshot = plan_snapshot(pro)
    subscription.price_snapshot = price_snapshot(pro)
    subscription.save()
    _create_period(subscription, billing_reference=confirmation.provider_reference)
    restore_plan_limited_resources(organization=organization, actor=actor, request=request, now=now)
    record_audit_event(actor=actor, action="subscription.upgraded", instance=subscription, metadata={"organization_id": organization.pk, "old_plan": old_plan, "new_plan": pro.code, "billing_confirmation_id": confirmation.pk}, request=request)
    _notify_subscription_owners(subscription, "subscription_plan_changed", "Subscription plan changed", "تم تغيير خطة الاشتراك")
    return subscription


@transaction.atomic
def renew_paid_subscription(*, subscription, actor, billing_confirmation, request=None, now=None):
    require_subscription_operator(actor)
    now = _now(now)
    subscription = OrganizationSubscription.objects.select_for_update().select_related("organization", "current_plan").get(pk=subscription.pk)
    confirmation = SubscriptionBillingConfirmation.objects.select_for_update().get(pk=billing_confirmation.pk)
    if confirmation.organization_id != subscription.organization_id or confirmation.plan_code != subscription.current_plan.code or confirmation.status != SubscriptionBillingConfirmation.Status.CONFIRMED:
        raise ValidationError("Renewal requires matching confirmed billing evidence.")
    start = max(now, subscription.current_period_end)
    subscription.current_period_start = start
    subscription.current_period_end = _period_end(start)
    subscription.next_billing_at = subscription.current_period_end
    subscription.status = OrganizationSubscription.Status.ACTIVE
    subscription.grace_started_on = None
    subscription.grace_ends_on = None
    subscription.policy_snapshot = plan_snapshot(get_effective_plan(subscription.current_plan.code, at=start))
    subscription.price_snapshot = price_snapshot(subscription.current_plan)
    subscription.save()
    _create_period(subscription, billing_reference=confirmation.provider_reference)
    record_audit_event(actor=actor, action="subscription.renewed", instance=subscription, metadata={"billing_confirmation_id": confirmation.pk}, request=request)
    return subscription


def _notify_subscription_owners(subscription, notification_type, title_en, title_ar, body_en="", body_ar=""):
    notifications = []
    for membership in subscription.organization.memberships.filter(role=Membership.Role.OWNER, is_active=True).select_related("user"):
        notifications.append(Notification.objects.create(
            recipient=membership.user,
            type=notification_type,
            title_en=title_en,
            title_ar=title_ar,
            body_en=body_en,
            body_ar=body_ar,
            destination="/designer/subscription/" if subscription.organization.kind == Organization.Kind.DESIGNER else "/manufacturer/subscription/",
        ))
    return notifications


def _milestone_notification(subscription, milestone):
    if milestone.offset_days < 0:
        return "subscription_renewal_approaching", "Subscription renewal approaching", "موعد تجديد الاشتراك يقترب"
    if milestone.offset_days == 0:
        return "subscription_renewal_due", "Subscription renewal due", "حان موعد تجديد الاشتراك"
    return "subscription_grace_reminder", f"Subscription grace day {milestone.offset_days}", f"اليوم {milestone.offset_days} من مهلة الاشتراك"


@transaction.atomic
def generate_due_reminders(*, subscription, now=None):
    now = _now(now)
    subscription = OrganizationSubscription.objects.select_for_update().select_related("organization", "current_plan").get(pk=subscription.pk)
    due = timezone.localtime(subscription.next_billing_at or subscription.current_period_end).date()
    today = _local_date(now)
    created = []
    for milestone in SubscriptionReminderMilestone.objects.filter(active=True):
        if today != due + timedelta(days=milestone.offset_days):
            continue
        event, is_new = SubscriptionReminderEvent.objects.get_or_create(subscription=subscription, due_date=due, milestone=milestone)
        if not is_new:
            continue
        ntype, title_en, title_ar = _milestone_notification(subscription, milestone)
        notifications = _notify_subscription_owners(subscription, ntype, title_en, title_ar)
        if notifications:
            event.notification = notifications[0]
            event.save(update_fields=["notification"])
        created.append(event)
    return created


@transaction.atomic
def process_subscription(*, subscription, now=None):
    now = _now(now)
    subscription = OrganizationSubscription.objects.select_for_update().select_related("organization", "current_plan").get(pk=subscription.pk)
    organization = subscription.organization
    if subscription.status in {OrganizationSubscription.Status.CANCELLED, OrganizationSubscription.Status.EXPIRED}:
        return subscription
    if subscription.status == OrganizationSubscription.Status.TRIALING:
        _roll_nonpaid_period_locked(subscription, now=now)
        generate_due_reminders(subscription=subscription, now=now)
        if subscription.trial_ends_at and now >= subscription.trial_ends_at:
            return downgrade_to_starter(subscription=subscription, automatic=True, now=now)
        return subscription
    if subscription.current_plan.monthly_price == 0:
        _roll_nonpaid_period_locked(subscription, now=now)
        return subscription

    generate_due_reminders(subscription=subscription, now=now)
    due_date = timezone.localtime(subscription.current_period_end).date()
    today = _local_date(now)
    if subscription.status == OrganizationSubscription.Status.ACTIVE and today >= due_date:
        subscription.status = OrganizationSubscription.Status.GRACE_PERIOD
        subscription.grace_started_on = due_date
        subscription.grace_ends_on = due_date + timedelta(days=3)
        subscription.save(update_fields=["status", "grace_started_on", "grace_ends_on", "updated_at"])
        record_audit_event(action="subscription.grace_entered", instance=subscription, metadata={"organization_id": organization.pk, "due_date": due_date.isoformat(), "grace_ends_on": subscription.grace_ends_on.isoformat()})
        _notify_subscription_owners(subscription, "subscription_grace_entered", "Subscription grace period started", "بدأت مهلة تجديد الاشتراك")
    if subscription.status == OrganizationSubscription.Status.GRACE_PERIOD:
        generate_due_reminders(subscription=subscription, now=now)
        if subscription.grace_ends_on and today > subscription.grace_ends_on:
            return downgrade_to_starter(subscription=subscription, automatic=True, now=now)
    return subscription


def process_all_subscriptions(*, now=None):
    ids = list(OrganizationSubscription.objects.values_list("pk", flat=True))
    processed = 0
    for pk in ids:
        with transaction.atomic():
            subscription = OrganizationSubscription.objects.select_for_update().get(pk=pk)
            process_subscription(subscription=subscription, now=now)
            processed += 1
    TeamInvitation.objects.filter(status=TeamInvitation.Status.PENDING, expires_at__lte=_now(now)).update(status=TeamInvitation.Status.EXPIRED)
    return processed


@transaction.atomic
def grant_manufacturer_trial_exception(*, subscription, actor, reason, months=6, request=None, now=None):
    if not actor or not actor.is_superuser:
        raise PermissionDenied("Only a superuser may grant a Manufacturer trial exception.")
    now = _now(now)
    subscription = OrganizationSubscription.objects.select_for_update().select_related("organization").get(pk=subscription.pk)
    if subscription.organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Trial exceptions apply only to Manufacturer Organizations.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("A trial exception reason is required.")
    old_state = {
        "trial_started_at": subscription.trial_started_at.isoformat() if subscription.trial_started_at else None,
        "trial_ends_at": subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else None,
        "trial_consumed": subscription.trial_consumed,
        "status": subscription.status,
        "plan_code": subscription.current_plan.code,
    }
    pro = get_effective_plan(MANUFACTURER_PRO, at=now)
    subscription.current_plan = pro
    subscription.status = OrganizationSubscription.Status.TRIALING
    subscription.trial_started_at = now
    subscription.trial_ends_at = now + relativedelta(months=int(months))
    subscription.trial_consumed = True
    subscription.current_period_start = now
    subscription.current_period_end = _period_end(now, hard_end=subscription.trial_ends_at)
    subscription.next_billing_at = subscription.trial_ends_at
    subscription.policy_snapshot = plan_snapshot(pro)
    subscription.price_snapshot = price_snapshot(pro)
    subscription.grace_started_on = None
    subscription.grace_ends_on = None
    subscription.save()
    _create_period(subscription)
    new_state = {
        "trial_started_at": subscription.trial_started_at.isoformat(),
        "trial_ends_at": subscription.trial_ends_at.isoformat(),
        "trial_consumed": True,
        "status": subscription.status,
        "plan_code": pro.code,
    }
    exception = SubscriptionTrialException.objects.create(subscription=subscription, actor=actor, reason=reason, old_trial_state=old_state, new_trial_state=new_state)
    record_audit_event(actor=actor, action="subscription.trial_exception_granted", instance=exception, metadata={"organization_id": subscription.organization_id, "reason_present": True, "old_trial_state": old_state, "new_trial_state": new_state}, request=request)
    return subscription
