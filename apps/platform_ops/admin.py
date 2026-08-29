from django.contrib import admin
from .models import MaintenanceWindow, PlatformAnnouncement
from apps.integrations.admin_site import fabinzi_admin_site
from apps.audit.services import record_audit_event

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
