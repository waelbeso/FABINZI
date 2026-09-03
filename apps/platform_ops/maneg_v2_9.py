from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse

from apps.artwork.models import ArtworkVersion, IPCase
from apps.audit.services import record_audit_event
from apps.finance.models import FinancePolicy, FinanceRecognitionPending, SettlementRequest
from apps.integrations.models import IntegrationConfig
from apps.operations.models import FulfillmentRecord, ProductionJob
from apps.organizations.models import OnboardingApplication
from apps.public_profiles.models import ProfessionalPublicState
from apps.subscriptions.models import (
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
    SubscriptionPlanPolicy,
    TeamInvitationConfiguration,
)

from . import maneg_views
from .models import ApplicationReviewConfiguration, MaintenanceWindow, PlatformAnnouncement


def _can_any(user, *permissions):
    return user.is_superuser or any(user.has_perm(permission) for permission in permissions)


def _update_application_review_target(*, request, config, raw_hours):
    maneg_views._require(request, "platform_ops.change_applicationreviewconfiguration")
    try:
        hours = int(raw_hours)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Application review target must be a whole number of hours.") from exc
    config.application_initial_review_target_hours = hours
    config.updated_by = request.user
    config.full_clean()
    config.save()
    record_audit_event(
        actor=request.user,
        action="control_center.application_review_configuration.updated",
        instance=config,
        metadata={"application_initial_review_target_hours": hours},
        request=request,
    )
    return config


def dashboard(request, extra_context=None):
    metrics = []
    if request.user.has_perm("organizations.view_onboardingapplication"):
        metrics.append({"label_en": "Pending applications", "label_ar": "طلبات انضمام معلقة", "value": OnboardingApplication.objects.filter(status=OnboardingApplication.Status.SUBMITTED).count(), "url": reverse("fabinzi_admin:maneg-verification")})
    if request.user.has_perm("public_profiles.view_professionalpublicstate"):
        metrics.append({"label_en": "Profiles pending approval", "label_ar": "ملفات عامة بانتظار الاعتماد", "value": ProfessionalPublicState.objects.filter(visibility=ProfessionalPublicState.Visibility.PENDING_APPROVAL).count(), "url": reverse("fabinzi_admin:maneg-v2-5-public-profiles")})
    if request.user.has_perm("design.view_garmentdesignversion"):
        from apps.design.models import GarmentDesignVersion
        metrics.append({"label_en": "Designs awaiting review", "label_ar": "تصاميم بانتظار المراجعة", "value": GarmentDesignVersion.objects.filter(status=GarmentDesignVersion.Status.SUBMITTED).count(), "url": reverse("fabinzi_admin:maneg-design-review")})
    if request.user.has_perm("artwork.view_artworkversion"):
        metrics.append({"label_en": "Artwork awaiting review", "label_ar": "أعمال فنية بانتظار المراجعة", "value": ArtworkVersion.objects.filter(status=ArtworkVersion.Status.SUBMITTED).count(), "url": reverse("fabinzi_admin:maneg-artwork-ip")})
    if request.user.has_perm("artwork.view_ipcase"):
        metrics.append({"label_en": "Open IP cases", "label_ar": "قضايا حقوق مفتوحة", "value": IPCase.objects.filter(status__in=[IPCase.Status.OPEN, IPCase.Status.UNDER_REVIEW, IPCase.Status.ACTION_REQUIRED]).count(), "url": reverse("fabinzi_admin:maneg-artwork-ip")})
    if request.user.has_perm("operations.view_productionjob"):
        metrics.append({"label_en": "Production attention", "label_ar": "إنتاج يحتاج متابعة", "value": ProductionJob.objects.filter(status__in=[ProductionJob.Status.QC_FAILED, ProductionJob.Status.AWAITING_ASSIGNMENT]).count(), "url": reverse("fabinzi_admin:maneg-production")})
    if request.user.has_perm("operations.view_fulfillmentrecord"):
        metrics.append({"label_en": "Fulfillment exceptions", "label_ar": "استثناءات التنفيذ", "value": FulfillmentRecord.objects.filter(status__in=[FulfillmentRecord.Status.FAILED, FulfillmentRecord.Status.RETURNED]).count(), "url": reverse("fabinzi_admin:maneg-production")})
    if request.user.has_perm("finance.reconcile_finance_recognition") or request.user.has_perm("finance.view_financerecognitionpending"):
        metrics.append({"label_en": "Finance recognition blocked", "label_ar": "إثباتات مالية محجوبة", "value": FinanceRecognitionPending.objects.filter(status=FinanceRecognitionPending.Status.BLOCKED).count(), "url": reverse("fabinzi_admin:maneg-v2-8-finance-pending")})
    if request.user.has_perm("finance.view_settlementrequest"):
        metrics.append({"label_en": "Pending settlements", "label_ar": "تسويات معلقة", "value": SettlementRequest.objects.filter(status=SettlementRequest.Status.REQUESTED).count(), "url": reverse("fabinzi_admin:maneg-v2-8-finance-payouts")})
    if request.user.has_perm("subscriptions.view_organizationsubscription"):
        metrics.append({"label_en": "Subscriptions needing attention", "label_ar": "اشتراكات تحتاج متابعة", "value": OrganizationSubscription.objects.filter(status__in=[OrganizationSubscription.Status.PAST_DUE, OrganizationSubscription.Status.GRACE_PERIOD]).count(), "url": reverse("fabinzi_admin:maneg-v2-9-subscriptions")})

    integration_summary = None
    if request.user.is_superuser:
        integration_summary = {
            "enabled": IntegrationConfig.objects.filter(enabled=True).count(),
            "failed": IntegrationConfig.objects.filter(last_test_status=IntegrationConfig.TestStatus.FAILURE).count(),
            "never": IntegrationConfig.objects.filter(last_test_status=IntegrationConfig.TestStatus.NEVER).count(),
        }

    announcement = PlatformAnnouncement.active().first() if request.user.has_perm("platform_ops.view_platformannouncement") else None
    maintenance = MaintenanceWindow.current() if request.user.has_perm("platform_ops.view_maintenancewindow") else None
    context = maneg_views._context(
        request,
        section="overview",
        title_en="Control Center",
        title_ar="مركز التحكم",
        metrics=metrics,
        integration_summary=integration_summary,
        current_announcement=announcement,
        current_maintenance=maintenance,
    )
    if extra_context:
        context.update(extra_context)
    return maneg_views._render(request, "maneg/dashboard.html", **context)


def subscriptions(request):
    if not _can_any(request.user, "subscriptions.view_organizationsubscription", "subscriptions.view_subscriptionplanpolicy", "subscriptions.view_subscriptionbillingconfirmation"):
        raise PermissionDenied("Subscription operational visibility is not allowed for this staff role.")

    query = maneg_views._q(request)
    rows = OrganizationSubscription.objects.select_related("organization", "current_plan").order_by("current_period_end", "organization__display_name")
    if query:
        rows = rows.filter(Q(organization__display_name__icontains=query) | Q(organization__legal_name__icontains=query) | Q(current_plan__code__icontains=query))
    status = request.GET.get("status", "")
    if status in OrganizationSubscription.Status.values:
        rows = rows.filter(status=status)

    plans = SubscriptionPlanPolicy.objects.order_by("audience", "code", "-version") if request.user.has_perm("subscriptions.view_subscriptionplanpolicy") else SubscriptionPlanPolicy.objects.none()
    confirmations = SubscriptionBillingConfirmation.objects.select_related("organization", "plan_policy", "confirmed_by").order_by("-confirmed_at")[:50] if request.user.has_perm("subscriptions.view_subscriptionbillingconfirmation") else []
    context = maneg_views._context(
        request,
        section="subscriptions",
        title_en="Subscriptions",
        title_ar="الاشتراكات",
        subscriptions=list(rows[:100]),
        subscription_plans=list(plans[:100]),
        billing_confirmations=list(confirmations),
        query=query,
        status_filter=status,
        status_choices=OrganizationSubscription.Status.choices,
    )
    return maneg_views._render(request, "maneg/subscriptions.html", **context)


def application_review_configuration_compat(request, pk):
    """Preserve the accepted internal reverse name without reviving Admin UX."""
    config = get_object_or_404(ApplicationReviewConfiguration, pk=pk)
    if request.method == "POST":
        _update_application_review_target(
            request=request,
            config=config,
            raw_hours=request.POST.get("application_initial_review_target_hours"),
        )
        messages.success(
            request,
            maneg_views._text(
                request,
                "Application review target updated.",
                "تم تحديث مستهدف مراجعة طلبات الانضمام.",
            ),
        )
    else:
        maneg_views._require(request, "platform_ops.view_applicationreviewconfiguration")
    return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-9-commercial-settings"))


def commercial_settings(request):
    if not _can_any(
        request.user,
        "platform_ops.view_applicationreviewconfiguration",
        "subscriptions.view_subscriptionplanpolicy",
        "subscriptions.view_teaminvitationconfiguration",
        "finance.view_finance_policy_governance",
    ):
        raise PermissionDenied("Commercial settings visibility is not allowed for this staff role.")

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "application_review_target":
            try:
                config, _ = ApplicationReviewConfiguration.objects.get_or_create(singleton_key=1)
                _update_application_review_target(
                    request=request,
                    config=config,
                    raw_hours=request.POST.get("hours"),
                )
                messages.success(request, maneg_views._text(request, "Application review target updated.", "تم تحديث مستهدف مراجعة طلبات الانضمام."))
            except ValidationError as exc:
                messages.error(request, str(exc))
        elif action == "team_invitation_expiry":
            maneg_views._require(request, "subscriptions.change_teaminvitationconfiguration")
            try:
                days = int(request.POST.get("days", ""))
                config, _ = TeamInvitationConfiguration.objects.get_or_create(singleton_key=1)
                config.invitation_expiry_days = days
                config.updated_by = request.user
                config.full_clean()
                config.save()
                record_audit_event(
                    actor=request.user,
                    action="subscription.team_invitation_configuration_changed",
                    instance=config,
                    metadata={"invitation_expiry_days": days},
                    request=request,
                )
                messages.success(request, maneg_views._text(request, "Team invitation expiry updated.", "تم تحديث مدة صلاحية دعوة الفريق."))
            except (TypeError, ValueError, ValidationError) as exc:
                messages.error(request, str(exc))
        else:
            raise ValidationError("Unsupported commercial-settings action.")
        return HttpResponseRedirect(reverse("fabinzi_admin:maneg-v2-9-commercial-settings"))

    application_config = ApplicationReviewConfiguration.objects.filter(singleton_key=1).first()
    team_config = TeamInvitationConfiguration.objects.filter(singleton_key=1).first()
    plans = SubscriptionPlanPolicy.objects.order_by("audience", "code", "-version") if request.user.has_perm("subscriptions.view_subscriptionplanpolicy") else SubscriptionPlanPolicy.objects.none()
    finance_policies = FinancePolicy.objects.order_by("-created_at", "-id") if _can_any(request.user, "finance.view_finance_policy_governance") else FinancePolicy.objects.none()

    context = maneg_views._context(
        request,
        section="commercial",
        title_en="Commercial Settings",
        title_ar="الإعدادات التجارية",
        application_review_hours=(application_config.application_initial_review_target_hours if application_config else ApplicationReviewConfiguration.DEFAULT_INITIAL_REVIEW_TARGET_HOURS),
        team_invitation_days=(team_config.invitation_expiry_days if team_config else TeamInvitationConfiguration.DEFAULT_EXPIRY_DAYS),
        subscription_plans=list(plans[:100]),
        finance_policies=list(finance_policies[:100]),
    )
    return maneg_views._render(request, "maneg/commercial_settings.html", **context)
