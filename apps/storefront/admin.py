from django.contrib import admin
from apps.integrations.admin_site import fabinzi_admin_site
from .models import CustomerCustomization, CustomizationElement, ProductVariant, StoreProduct, StoreProductImage, Storefront, StudioProject

class ProductInline(admin.TabularInline):
    model=StoreProduct; extra=0; fields=("title_en","slug","status","base_price","currency","customization_enabled")

@admin.register(Storefront,site=fabinzi_admin_site)
class StorefrontAdmin(admin.ModelAdmin):
    list_display=("name_en","organization","slug","status","updated_at"); list_filter=("status",); search_fields=("name_en","name_ar","slug","organization__display_name"); inlines=[ProductInline]

@admin.register(StoreProduct,site=fabinzi_admin_site)
class StoreProductAdmin(admin.ModelAdmin):
    list_display=("title_en","storefront","status","base_price","currency","customization_enabled","featured"); list_filter=("status","customization_enabled","featured","fulfillment_mode"); search_fields=("title_en","title_ar","slug")

@admin.register(StudioProject,site=fabinzi_admin_site)
class StudioProjectAdmin(admin.ModelAdmin):
    list_display=("id","customer","product","variant","status","quantity","updated_at"); list_filter=("status",); readonly_fields=("created_at","updated_at","ready_at")

for model in (ProductVariant,StoreProductImage,CustomerCustomization,CustomizationElement):
    try: fabinzi_admin_site.register(model)
    except admin.sites.AlreadyRegistered: pass
