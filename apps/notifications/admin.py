from django.contrib import admin
from apps.integrations.admin_site import fabinzi_admin_site
from .models import Notification, NotificationDelivery, NotificationPreference
@admin.register(Notification,site=fabinzi_admin_site)
class NotificationAdmin(admin.ModelAdmin): list_display=("recipient","type","is_read","created_at"); list_filter=("type","is_read")
@admin.register(NotificationPreference,site=fabinzi_admin_site)
class NotificationPreferenceAdmin(admin.ModelAdmin): list_display=("user","email_enabled","sms_enabled","updated_at")
@admin.register(NotificationDelivery,site=fabinzi_admin_site)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display=("notification","channel","provider","status","attempt_count","updated_at"); list_filter=("channel","provider","status"); readonly_fields=("notification","channel","provider","status","attempt_count","last_error","created_at","updated_at","sent_at")
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
