from django.contrib import admin
from apps.integrations.admin_site import fabinzi_admin_site
from .models import FulfillmentEvent, FulfillmentRecord, ProductionAsset, ProductionJob, ProductionMilestone, QCInspection


class MilestoneInline(admin.TabularInline):
    model=ProductionMilestone; extra=0

@admin.register(ProductionJob,site=fabinzi_admin_site)
class ProductionJobAdmin(admin.ModelAdmin):
    list_display=("id","order","manufacturer","status","updated_at"); list_filter=("status","manufacturer"); search_fields=("order__number","manufacturer__display_name"); inlines=[MilestoneInline]

@admin.register(QCInspection,site=fabinzi_admin_site)
class QCInspectionAdmin(admin.ModelAdmin):
    list_display=("job","decision","inspected_by","created_at"); list_filter=("decision",); readonly_fields=("job","decision","checklist","notes","inspected_by","created_at")
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False

@admin.register(FulfillmentRecord,site=fabinzi_admin_site)
class FulfillmentRecordAdmin(admin.ModelAdmin):
    list_display=("order","status","carrier","tracking_number","updated_at"); list_filter=("status","carrier"); search_fields=("order__number","tracking_number")

@admin.register(FulfillmentEvent,site=fabinzi_admin_site)
class FulfillmentEventAdmin(admin.ModelAdmin):
    list_display=("fulfillment","status","actor","created_at"); readonly_fields=("fulfillment","status","note","actor","created_at")
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False

fabinzi_admin_site.register(ProductionAsset)
