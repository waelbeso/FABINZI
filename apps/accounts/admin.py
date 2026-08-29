from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from .models import User
from apps.integrations.admin_site import fabinzi_admin_site

@admin.register(User, site=fabinzi_admin_site)
class FabinziUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("FABINZI preferences", {"fields": ("theme_preference", "language_preference")}),)
    list_display = ("username", "email", "is_staff", "is_active", "theme_preference", "language_preference")

fabinzi_admin_site.register(Group, GroupAdmin)
