from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.urls import path, reverse

from apps.audit.services import record_audit_event
from apps.integrations.admin_site import fabinzi_admin_site
from .models import (
    ManufacturerOfferUsage,
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
    SubscriptionPeriod,
    SubscriptionPlanPolicy,
    SubscriptionReminderEvent,
    SubscriptionReminderMilestone,
    SubscriptionTrialException,
    TeamInvitation,
    TeamInvitationConfiguration,
)
from .services import (
    activate_paid_pro,
    confirm_subscription_billing,
    downgrade_to_starter,
    entitlement_summary,
    grant_manufacturer_trial_exception,
    require_subscription_operator,
)


@admin.register(SubscriptionPlanPolicy, site=fabinzi_admin_site)
class SubscriptionPlanPolicyAdmin(admin.ModelAdmin):
    list_display = ("code", "version", "audience", "monthly_price", "currency", "tax_inclusive", "team_subaccount_limit", "effective_from", "effective_to", "active")
    list_filter = ("audience", "active", "tax_inclusive")
    search_fields = ("code", "public_name_en", "public_name_ar")
    readonly_fields = ("created_by", "created_at")

    def save_model(self, request, obj, form, change):
        obj.created_by = obj.created_by or request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)
        record_audit_event(
            actor=request.user,
            action="subscription.plan_configuration_changed" if change else "subscription.plan_configuration_created",
            instance=obj,
            metadata={"code": obj.code, "version": obj.version, "effective_from": obj.effective_from.isoformat()},
            request=request,
        )


@admin.register(SubscriptionReminderMilestone, site=fabinzi_admin_site)
class SubscriptionReminderMilestoneAdmin(admin.ModelAdmin):
    list_display = ("code", "offset_days", "active", "updated_at")
    list_editable = ("offset_days", "active")
    search_fields = ("code", "label_en", "label_ar")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record_audit_event(actor=request.user, action="subscription.reminder_configuration_changed", instance=obj, metadata={"offset_days": obj.offset_days, "active": obj.active}, request=request)


@admin.register(TeamInvitationConfiguration, site=fabinzi_admin_site)
class TeamInvitationConfigurationAdmin(admin.ModelAdmin):
    list_display = ("invitation_expiry_days", "updated_at", "updated_by")
    readonly_fields = ("singleton_key", "updated_by", "updated_at")

    def has_add_permission(self, request):
        return not TeamInvitationConfiguration.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.singleton_key = 1
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        record_audit_event(actor=request.user, action="subscription.team_invitation_configuration_changed", instance=obj, metadata={"invitation_expiry_days": obj.invitation_expiry_days}, request=request)


@admin.register(SubscriptionBillingConfirmation, site=fabinzi_admin_site)
class SubscriptionBillingConfirmationAdmin(admin.ModelAdmin):
    list_display = ("organization", "plan_code", "amount", "currency", "provider", "provider_reference", "status", "confirmed_at", "confirmed_by")
    list_filter = ("status", "plan_code", "provider")
    search_fields = ("organization__display_name", "provider_reference", "idempotency_key")
    readonly_fields = ("status", "confirmed_by", "confirmed_at")

    def has_add_permission(self, request):
        try:
            require_subscription_operator(request.user)
        except PermissionDenied:
            return False
        return True

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            raise PermissionDenied("Billing confirmation evidence is immutable.")
        confirmation = confirm_subscription_billing(
            organization=obj.organization,
            actor=request.user,
            plan_code=obj.plan_code,
            amount=obj.amount,
            currency=obj.currency,
            provider=obj.provider,
            provider_reference=obj.provider_reference,
            idempotency_key=obj.idempotency_key,
            request=request,
        )
        obj.pk = confirmation.pk


@admin.register(OrganizationSubscription, site=fabinzi_admin_site)
class OrganizationSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("organization", "current_plan", "status", "trial_started_at", "trial_ends_at", "current_period_end", "next_billing_at", "updated_at")
    list_filter = ("status", "current_plan__audience", "current_plan__code")
    search_fields = ("organization__display_name", "organization__legal_name", "organization__email")
    readonly_fields = (
        "organization", "current_plan", "status", "started_at", "trial_started_at", "trial_ends_at", "trial_consumed",
        "current_period_start", "current_period_end", "next_billing_at", "grace_started_on", "grace_ends_on",
        "cancelled_at", "downgraded_at", "policy_snapshot", "price_snapshot", "updated_at", "usage_summary",
    )
    change_form_template = "admin/subscriptions/organizationsubscription/change_form.html"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def usage_summary(self, obj):
        if not obj or not obj.pk:
            return "—"
        summary = entitlement_summary(obj.organization)
        if obj.organization.kind == "designer":
            return f"Designs {summary['design_used']}/{summary['design_limit']} · Artworks {summary['artwork_used']}/{summary['artwork_limit']} · Team {summary['team_used']}/{summary['team_limit']}"
        return f"Offers {summary['offer_used']}/{summary['offer_limit']} · Team {summary['team_used']}/{summary['team_limit']}"

    def get_urls(self):
        custom = [
            path("<int:object_id>/activate-pro/", self.admin_site.admin_view(self.activate_pro_view), name="subscriptions_activate_pro"),
            path("<int:object_id>/downgrade-starter/", self.admin_site.admin_view(self.downgrade_view), name="subscriptions_downgrade_starter"),
            path("<int:object_id>/trial-exception/", self.admin_site.admin_view(self.trial_exception_view), name="subscriptions_trial_exception"),
        ]
        return custom + super().get_urls()

    def _obj(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            raise ValidationError("Subscription not found.")
        require_subscription_operator(request.user)
        return obj

    def activate_pro_view(self, request, object_id):
        try:
            obj = self._obj(request, object_id)
            if request.method != "POST":
                raise ValidationError("Lifecycle actions require POST.")
            confirmation_id = request.POST.get("billing_confirmation_id")
            confirmation = SubscriptionBillingConfirmation.objects.get(pk=confirmation_id, organization=obj.organization)
            activate_paid_pro(organization=obj.organization, actor=request.user, billing_confirmation=confirmation, request=request)
        except (ValidationError, PermissionDenied, SubscriptionBillingConfirmation.DoesNotExist) as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            self.message_user(request, "Confirmed Pro subscription activated.", messages.SUCCESS)
        return HttpResponseRedirect(reverse("fabinzi_admin:subscriptions_organizationsubscription_change", args=[object_id]))

    def downgrade_view(self, request, object_id):
        try:
            obj = self._obj(request, object_id)
            if request.method != "POST":
                raise ValidationError("Lifecycle actions require POST.")
            downgrade_to_starter(subscription=obj, actor=request.user, request=request)
        except (ValidationError, PermissionDenied) as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            self.message_user(request, "Subscription moved to Starter without deleting business records.", messages.SUCCESS)
        return HttpResponseRedirect(reverse("fabinzi_admin:subscriptions_organizationsubscription_change", args=[object_id]))

    def trial_exception_view(self, request, object_id):
        try:
            obj = self.get_object(request, object_id)
            if request.method != "POST":
                raise ValidationError("Lifecycle actions require POST.")
            reason = request.POST.get("reason", "").strip()
            grant_manufacturer_trial_exception(subscription=obj, actor=request.user, reason=reason, request=request)
        except (ValidationError, PermissionDenied) as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            self.message_user(request, "Superuser trial exception granted and audited.", messages.SUCCESS)
        return HttpResponseRedirect(reverse("fabinzi_admin:subscriptions_organizationsubscription_change", args=[object_id]))


@admin.register(SubscriptionPeriod, site=fabinzi_admin_site)
class SubscriptionPeriodAdmin(admin.ModelAdmin):
    list_display = ("subscription", "sequence", "plan_code", "status_snapshot", "period_start", "period_end", "billing_reference")
    readonly_fields = tuple(field.name for field in SubscriptionPeriod._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(ManufacturerOfferUsage, site=fabinzi_admin_site)
class ManufacturerOfferUsageAdmin(admin.ModelAdmin):
    list_display = ("organization", "quote", "plan_code", "period_start", "period_end", "consumed_at")
    readonly_fields = tuple(field.name for field in ManufacturerOfferUsage._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(TeamInvitation, site=fabinzi_admin_site)
class TeamInvitationAdmin(admin.ModelAdmin):
    list_display = ("organization", "email", "role", "status", "created_at", "expires_at")
    list_filter = ("status", "role", "organization__kind")
    search_fields = ("organization__display_name", "email")
    readonly_fields = tuple(field.name for field in TeamInvitation._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(SubscriptionReminderEvent, site=fabinzi_admin_site)
class SubscriptionReminderEventAdmin(admin.ModelAdmin):
    list_display = ("subscription", "due_date", "milestone", "notification", "created_at")
    readonly_fields = tuple(field.name for field in SubscriptionReminderEvent._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(SubscriptionTrialException, site=fabinzi_admin_site)
class SubscriptionTrialExceptionAdmin(admin.ModelAdmin):
    list_display = ("subscription", "actor", "created_at")
    readonly_fields = tuple(field.name for field in SubscriptionTrialException._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
