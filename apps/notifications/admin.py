from django.contrib import admin
from .models import Notification
from apps.integrations.admin_site import fabinzi_admin_site

@admin.register(Notification, site=fabinzi_admin_site)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "type", "is_read", "created_at")
    search_fields = ("recipient__username", "recipient__email", "title_en", "title_ar")
