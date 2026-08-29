from django.contrib import admin
from apps.integrations.admin_site import fabinzi_admin_site
from .models import FinanceAccount, FinanceAdjustment, FinancePolicy, LedgerEntry, OrderFinance, PayoutProfile, SettlementRequest

@admin.register(FinancePolicy,site=fabinzi_admin_site)
class FinancePolicyAdmin(admin.ModelAdmin): list_display=("name","platform_fee_bps","settlement_delay_days","minimum_payout","is_active","updated_at")
@admin.register(PayoutProfile,site=fabinzi_admin_site)
class PayoutProfileAdmin(admin.ModelAdmin): list_display=("organization","method","status","account_holder","destination_hint","updated_at"); list_filter=("status","method")
@admin.register(FinanceAccount,site=fabinzi_admin_site)
class FinanceAccountAdmin(admin.ModelAdmin): list_display=("id","account_type","organization","currency","created_at"); list_filter=("account_type","currency")
@admin.register(OrderFinance,site=fabinzi_admin_site)
class OrderFinanceAdmin(admin.ModelAdmin): list_display=("order","gross_amount","platform_fee","manufacturer_payable","designer_earnings","currency","recognized_at","available_at"); list_filter=("currency","status"); readonly_fields=("order","designer_account","manufacturer_account","gross_amount","platform_fee","manufacturer_payable","designer_earnings","currency","policy_snapshot","recognized_at","available_at")
    
    def has_add_permission(self,request): return False
@admin.register(LedgerEntry,site=fabinzi_admin_site)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display=("account","entry_type","amount","currency","available_at","created_at"); list_filter=("entry_type","currency"); readonly_fields=("account","order_finance","settlement","entry_type","amount","currency","available_at","memo","created_by","created_at")
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
@admin.register(SettlementRequest,site=fabinzi_admin_site)
class SettlementRequestAdmin(admin.ModelAdmin): list_display=("id","organization","amount","currency","status","requested_at","paid_at"); list_filter=("status","currency"); search_fields=("organization__display_name","external_reference")
@admin.register(FinanceAdjustment,site=fabinzi_admin_site)
class FinanceAdjustmentAdmin(admin.ModelAdmin):
    list_display=("order_finance","account","amount","reason","created_by","created_at"); readonly_fields=("order_finance","account","amount","reason","created_by","created_at")
    def has_add_permission(self,request): return False
