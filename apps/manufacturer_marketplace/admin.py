from django.contrib import admin
from apps.integrations.admin_site import fabinzi_admin_site
from .models import ManufacturerCapability, ManufacturerListing, ManufacturerPortfolioAsset, ManufacturerQuote, ManufacturerSelection, RFQ, RFQInvitation


class CapabilityInline(admin.TabularInline):
    model=ManufacturerCapability
    extra=0


@admin.register(ManufacturerListing,site=fabinzi_admin_site)
class ManufacturerListingAdmin(admin.ModelAdmin):
    list_display=("organization","status","accepts_rfq","min_order_quantity","available_monthly_capacity","updated_at")
    list_filter=("status","accepts_rfq","sample_orders")
    search_fields=("organization__display_name","headline_en","headline_ar")
    inlines=[CapabilityInline]


@admin.register(RFQ,site=fabinzi_admin_site)
class RFQAdmin(admin.ModelAdmin):
    list_display=("title","designer_organization","quantity","status","updated_at")
    list_filter=("status","currency")
    search_fields=("title","designer_organization__display_name")


@admin.register(ManufacturerQuote,site=fabinzi_admin_site)
class ManufacturerQuoteAdmin(admin.ModelAdmin):
    list_display=("invitation","unit_price","currency","production_lead_days","status","updated_at")
    list_filter=("status","currency")


for model in (ManufacturerPortfolioAsset,RFQInvitation,ManufacturerSelection):
    try: fabinzi_admin_site.register(model)
    except admin.sites.AlreadyRegistered: pass
