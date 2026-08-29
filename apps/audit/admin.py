from django.contrib import admin
from .models import AuditEvent
from apps.integrations.admin_site import fabinzi_admin_site

@admin.register(AuditEvent, site=fabinzi_admin_site)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "object_type", "object_id", "ip_address")
    search_fields = ("action", "object_type", "object_id", "actor__username", "actor__email")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
