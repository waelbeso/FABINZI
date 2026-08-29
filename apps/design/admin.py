from django.contrib import admin
from apps.integrations.admin_site import fabinzi_admin_site
from .models import DecorationZone, DesignAsset, GarmentDesign, GarmentDesignVersion, SizeChartRow, TechnicalReview


class VersionInline(admin.TabularInline):
    model = GarmentDesignVersion
    extra = 0
    readonly_fields = ("version_number","status","submitted_at","reviewed_at","reviewed_by")


@admin.register(GarmentDesign, site=fabinzi_admin_site)
class GarmentDesignAdmin(admin.ModelAdmin):
    list_display = ("title","organization","status","updated_at")
    list_filter = ("status","organization")
    search_fields = ("title","organization__display_name")
    inlines = [VersionInline]


for model in (GarmentDesignVersion, SizeChartRow, DecorationZone, DesignAsset, TechnicalReview):
    try: fabinzi_admin_site.register(model)
    except admin.sites.AlreadyRegistered: pass
