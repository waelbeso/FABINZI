from django.contrib import admin

from apps.integrations.admin_site import fabinzi_admin_site
from .models import (
    FinanceAccount,
    FinanceAdjustment,
    FinancePolicy,
    FinanceRecognitionPending,
    LedgerEntry,
    OrderFinance,
    OrderFinanceComponent,
    PayoutProfile,
    SettlementRequest,
)


@admin.register(FinancePolicy, site=fabinzi_admin_site)
class FinancePolicyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "lifecycle_status", "currency", "activated_at", "retired_at", "updated_at")
    list_filter = ("lifecycle_status", "currency")
    search_fields = ("code", "name")
    readonly_fields = tuple(field.name for field in FinancePolicy._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PayoutProfile, site=fabinzi_admin_site)
class PayoutProfileAdmin(admin.ModelAdmin):
    list_display = ("organization", "method", "status", "bank_name", "account_holder", "destination_hint", "currency", "updated_at")
    list_filter = ("status", "method", "currency")
    exclude = ("iban_encrypted",)
    readonly_fields = ("destination_hint", "iban_last4", "verified_by", "verified_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FinanceAccount, site=fabinzi_admin_site)
class FinanceAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "account_type", "organization", "currency", "created_at")
    list_filter = ("account_type", "currency")


@admin.register(OrderFinance, site=fabinzi_admin_site)
class OrderFinanceAdmin(admin.ModelAdmin):
    list_display = ("order", "finance_policy", "gross_amount", "fabinzi_component", "manufacturer_payable", "garment_designer_royalty", "artwork_designer_royalty", "currency", "recognized_at", "available_at")
    list_filter = ("currency", "status")
    readonly_fields = tuple(field.name for field in OrderFinance._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderFinanceComponent, site=fabinzi_admin_site)
class OrderFinanceComponentAdmin(admin.ModelAdmin):
    list_display = ("order_finance", "component_type", "beneficiary_organization", "amount", "currency", "available_at")
    list_filter = ("component_type", "currency")
    readonly_fields = tuple(field.name for field in OrderFinanceComponent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FinanceRecognitionPending, site=fabinzi_admin_site)
class FinanceRecognitionPendingAdmin(admin.ModelAdmin):
    list_display = ("order", "currency", "status", "trigger_event", "block_reason", "created_at", "reconciled_at")
    list_filter = ("status", "currency", "trigger_event")
    readonly_fields = tuple(field.name for field in FinanceRecognitionPending._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerEntry, site=fabinzi_admin_site)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("account", "entry_type", "amount", "currency", "available_at", "created_at")
    list_filter = ("entry_type", "currency")
    readonly_fields = tuple(field.name for field in LedgerEntry._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SettlementRequest, site=fabinzi_admin_site)
class SettlementRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "amount", "currency", "status", "requested_at", "processing_at", "paid_at")
    list_filter = ("status", "currency")
    search_fields = ("organization__display_name", "external_reference", "idempotency_key")
    readonly_fields = tuple(field.name for field in SettlementRequest._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FinanceAdjustment, site=fabinzi_admin_site)
class FinanceAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("order_finance", "account", "amount", "reason", "created_by", "created_at")
    readonly_fields = ("order_finance", "account", "amount", "reason", "created_by", "created_at")

    def has_add_permission(self, request):
        return False
