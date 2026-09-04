from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.artwork.models import Artwork
from apps.design.models import GarmentDesign
from apps.organizations.designer_context import designer_context
from apps.organizations.manufacturer_context import manufacturer_context
from apps.organizations.models import Membership, Organization
from .models import SubscriptionBillingConfirmation, TeamInvitation
from .services import (
    ARTWORK_SLOT_STATUSES,
    DESIGN_SLOT_STATUSES,
    accept_team_invitation,
    apply_designer_downgrade,
    cancel_subscription,
    downgrade_to_starter,
    entitlement_summary,
    onboarding_commercial_summary,
    require_owner,
)


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _error_text(exc):
    if isinstance(exc, ValidationError):
        try:
            return "; ".join(exc.messages)
        except Exception:
            return str(exc)
    return str(exc)


def _designer(request):
    context = designer_context(request, required=True)
    organization = context["designer_organization"]
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise PermissionDenied("An approved active Designer Organization is required.")
    return context, organization


def _manufacturer(request):
    context = manufacturer_context(request, required=True)
    organization = context["manufacturer_organization"]
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise PermissionDenied("An approved active Manufacturer Organization is required.")
    return context, organization


def _commercial_context(organization):
    commercial = onboarding_commercial_summary(organization)
    history = [
        {
            "confirmed_at": row.confirmed_at,
            "plan_code": row.plan_code,
            "plan_version": row.plan_version,
            "amount": row.amount,
            "currency": row.currency,
            "status": row.status,
            "consumed": bool(row.consumed_period_id),
        }
        for row in SubscriptionBillingConfirmation.objects.filter(organization=organization).order_by("-confirmed_at", "-pk")[:50]
    ]
    return {
        "onboarding_commercial": commercial,
        "billing_history": history,
    }


def _subscription_action(request, organization, context, *, designer):
    if request.method != "POST":
        return None
    action = request.POST.get("action", "")
    if action not in {"downgrade", "cancel", "upgrade", "retain"}:
        return None
    require_owner(request.user, organization)
    summary = entitlement_summary(organization)
    subscription = summary["subscription"]
    if action == "upgrade":
        raise ValidationError(
            "Pro activation requires explicit confirmed billing evidence through authorized operations; browser/client requests cannot activate paid entitlement."
        )
    if action == "cancel":
        cancel_subscription(subscription=subscription, actor=request.user, request=request)
        return _localized(request, "Subscription cancelled and Starter safeguards applied.", "تم إلغاء الاشتراك وتطبيق حدود Starter بأمان.")
    if action == "downgrade":
        retained_design_ids = request.POST.getlist("retained_design_ids") if designer else None
        retained_artwork_ids = request.POST.getlist("retained_artwork_ids") if designer else None
        retained_membership_ids = request.POST.getlist("retained_membership_ids") if not designer else None
        downgrade_to_starter(
            subscription=subscription,
            actor=request.user,
            retained_design_ids=retained_design_ids or None,
            retained_artwork_ids=retained_artwork_ids or None,
            retained_membership_ids=retained_membership_ids or None,
            request=request,
        )
        return _localized(request, "Subscription moved to Starter without deleting business history.", "تم نقل الاشتراك إلى Starter دون حذف سجل الأعمال.")
    if action == "retain" and designer:
        apply_designer_downgrade(
            organization=organization,
            actor=request.user,
            retained_design_ids=request.POST.getlist("retained_design_ids"),
            retained_artwork_ids=request.POST.getlist("retained_artwork_ids"),
            request=request,
        )
        return _localized(request, "Starter retained-content selection updated.", "تم تحديث اختيار المحتوى المحتفظ به ضمن Starter.")
    return None


@login_required
def designer_subscription(request):
    context, organization = _designer(request)
    try:
        success = _subscription_action(request, organization, context, designer=True)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _error_text(exc))
    else:
        if success:
            messages.success(request, success)
            return redirect(f"/designer/subscription/?org={organization.pk}")
    summary = entitlement_summary(organization)
    active_designs = GarmentDesign.objects.filter(organization=organization, status__in=DESIGN_SLOT_STATUSES).order_by("created_at", "id")
    active_artworks = Artwork.objects.filter(organization=organization, status__in=ARTWORK_SLOT_STATUSES).order_by("created_at", "id")
    context.update({
        "subscription_summary": summary,
        "active_designs_for_retention": active_designs,
        "active_artworks_for_retention": active_artworks,
        "is_subscription_owner": context["designer_membership"].role == Membership.Role.OWNER,
    })
    context.update(_commercial_context(organization))
    return render(request, "designer/subscription.html", context)


@login_required
def manufacturer_subscription(request):
    context, organization = _manufacturer(request)
    try:
        success = _subscription_action(request, organization, context, designer=False)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _error_text(exc))
    else:
        if success:
            messages.success(request, success)
            return redirect(f"/manufacturer/subscription/?org={organization.pk}")
    summary = entitlement_summary(organization)
    context.update({
        "subscription_summary": summary,
        "is_subscription_owner": context["manufacturer_membership"].role == Membership.Role.OWNER,
    })
    context.update(_commercial_context(organization))
    return render(request, "manufacturer/subscription.html", context)


@login_required
def team_invitation_accept(request, token):
    if request.method == "POST" and request.POST.get("action") == "decline":
        import hashlib
        from django.utils import timezone

        token_hash = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
        invitation = get_object_or_404(TeamInvitation, token_hash=token_hash, status=TeamInvitation.Status.PENDING)
        if (request.user.email or "").strip().lower() != invitation.email.lower():
            raise PermissionDenied("This invitation belongs to a different email address.")
        invitation.status = TeamInvitation.Status.DECLINED
        invitation.declined_at = timezone.now()
        invitation.save(update_fields=["status", "declined_at"])
        messages.success(request, _localized(request, "Invitation declined.", "تم رفض الدعوة."))
        return redirect("app-home")
    if request.method == "POST":
        try:
            membership = accept_team_invitation(token=token, actor=request.user, request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _error_text(exc))
        else:
            if membership.organization.kind == Organization.Kind.DESIGNER:
                return redirect(f"/designer/team/?org={membership.organization_id}")
            return redirect(f"/manufacturer/team/?org={membership.organization_id}")
    return render(request, "subscriptions/team_invitation_accept.html", {"token": token})
