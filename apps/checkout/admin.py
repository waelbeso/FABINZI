from django.contrib import admin
from apps.integrations.admin_site import fabinzi_admin_site
from .models import CheckoutSession, CustomerOrder, OrderItem, PaymentAttempt, PaymentWebhookEvent

@admin.register(CheckoutSession,site=fabinzi_admin_site)
class CheckoutSessionAdmin(admin.ModelAdmin): list_display=("id","customer","status","total","currency","updated_at"); list_filter=("status","currency"); search_fields=("customer__username","shipping_phone","shipping_email")
@admin.register(CustomerOrder,site=fabinzi_admin_site)
class CustomerOrderAdmin(admin.ModelAdmin): list_display=("number","customer","status","payment_method","total","currency","created_at"); list_filter=("status","payment_method","currency"); search_fields=("number","customer__username")
@admin.register(OrderItem,site=fabinzi_admin_site)
class OrderItemAdmin(admin.ModelAdmin): list_display=("order","sku","quantity","unit_price","line_total")
@admin.register(PaymentAttempt,site=fabinzi_admin_site)
class PaymentAttemptAdmin(admin.ModelAdmin): list_display=("order","provider","status","amount","currency","provider_reference","created_at"); list_filter=("provider","status"); readonly_fields=("idempotency_key","provider_payload")
@admin.register(PaymentWebhookEvent,site=fabinzi_admin_site)
class PaymentWebhookEventAdmin(admin.ModelAdmin): list_display=("provider","event_id","processed","received_at"); list_filter=("provider","processed"); readonly_fields=("provider","event_id","payload_hash","processed","processing_error","received_at","processed_at")
    
    def has_add_permission(self,request): return False
