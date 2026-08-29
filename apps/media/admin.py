from django.contrib import admin
from .models import MediaAsset
from apps.integrations.admin_site import fabinzi_admin_site

@admin.register(MediaAsset, site=fabinzi_admin_site)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "original_filename", "provider", "access", "mime_type", "size_bytes", "created_at")
    search_fields = ("original_filename", "provider_asset_id", "checksum_sha256")
    readonly_fields = ("created_at",)
