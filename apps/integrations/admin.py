from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone
from .admin_site import fabinzi_admin_site
from .models import IntegrationConfig
from .forms import IntegrationConfigAdminForm
from .services import test_connection
from apps.audit.services import record_audit_event

@admin.register(IntegrationConfig, site=fabinzi_admin_site)
class IntegrationConfigAdmin(admin.ModelAdmin):
    form = IntegrationConfigAdminForm
    change_form_template = "admin/integrations/integrationconfig/change_form.html"
    list_display = ("provider", "enabled", "last_test_status", "last_tested_at", "updated_at")
    readonly_fields = ("last_test_status", "last_tested_at", "last_test_message", "updated_by", "updated_at")
    fieldsets = (("Provider", {"fields": ("provider", "enabled")}), ("Non-secret configuration", {"fields": ("config",)}), ("Secrets", {"fields": ("secret_payload",), "description": "Secret values are encrypted at rest and never shown again after save."}), ("Connection health", {"fields": ("last_test_status", "last_tested_at", "last_test_message")}), ("Audit metadata", {"fields": ("updated_by", "updated_at")}))
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        secret_payload = form.cleaned_data.get("secret_payload")
        if secret_payload is not None:
            obj.set_secrets(secret_payload)
        super().save_model(request, obj, form, change)
        record_audit_event(actor=request.user, action="integration.config.updated", instance=obj, metadata={"provider": obj.provider, "enabled": obj.enabled}, request=request)
    def get_urls(self):
        return [path("<int:object_id>/test-connection/", self.admin_site.admin_view(self.test_connection_view), name="integrations_integrationconfig_test")] + super().get_urls()
    def test_connection_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            self.message_user(request, "Integration not found.", messages.ERROR)
            return HttpResponseRedirect(reverse("fabinzi_admin:integrations_integrationconfig_changelist"))
        if request.method != "POST":
            return render(request, "admin/integrations/integrationconfig/test_connection.html", {**self.admin_site.each_context(request), "object": obj, "title": f"Test {obj}"})
        result = test_connection(obj)
        obj.last_test_status = obj.TestStatus.SUCCESS if result.ok else obj.TestStatus.FAILURE
        obj.last_tested_at = timezone.now()
        obj.last_test_message = result.message[:500]
        obj.updated_by = request.user
        obj.save(update_fields=["last_test_status", "last_tested_at", "last_test_message", "updated_by", "updated_at"])
        record_audit_event(actor=request.user, action="integration.connection.tested", instance=obj, metadata={"provider": obj.provider, "ok": result.ok}, request=request)
        self.message_user(request, result.message, messages.SUCCESS if result.ok else messages.ERROR)
        return HttpResponseRedirect(reverse("fabinzi_admin:integrations_integrationconfig_change", args=[obj.pk]))
