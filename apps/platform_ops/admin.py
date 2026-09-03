from django.contrib import admin

from apps.audit.services import record_audit_event
from apps.integrations.admin_site import fabinzi_admin_site
from .models import ApplicationReviewConfiguration, MaintenanceWindow, PlatformAnnouncement


class AuditedOpsAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        if hasattr(obj, "created_by") and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        record_audit_event(actor=request.user, action=f"platform_ops.{obj._meta.model_name}.updated", instance=obj, metadata={"enabled": obj.enabled}, request=request)


@admin.register(PlatformAnnouncement, site=fabinzi_admin_site)
class PlatformAnnouncementAdmin(AuditedOpsAdmin):
    list_display = ("title_en", "severity", "audience", "enabled", "starts_at", "ends_at", "priority")
    list_filter = ("severity", "audience", "enabled")


@admin.register(MaintenanceWindow, site=fabinzi_admin_site)
class MaintenanceWindowAdmin(AuditedOpsAdmin):
    list_display = ("starts_at", "ends_at", "mode", "enabled")


@admin.register(ApplicationReviewConfiguration, site=fabinzi_admin_site)
class ApplicationReviewConfigurationAdmin(admin.ModelAdmin):
    fields = (
        "application_initial_review_target_hours",
        "updated_by",
        "updated_at",
    )
    readonly_fields = ("updated_by", "updated_at")

    def has_add_permission(self, request):
        if ApplicationReviewConfiguration.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.singleton_key = 1
        obj.updated_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)
        record_audit_event(
            actor=request.user,
            action="control_center.application_review_configuration.updated",
            instance=obj,
            metadata={
                "application_initial_review_target_hours": obj.application_initial_review_target_hours,
            },
            request=request,
        )
