from django.contrib import admin

from apps.integrations.admin_site import fabinzi_admin_site
from .models import Cart, CartItem, CheckoutSession, CustomerOrder, CustomerPurchase, OrderItem, PaymentAttempt, PaymentWebhookEvent


@admin.register(Cart, site=fabinzi_admin_site)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "buyer_type", "status", "merged_into", "updated_at")
    list_filter = ("status",)
    search_fields = ("customer__username", "customer__email")
    readonly_fields = ("guest_key_hash", "merged_into")

    @admin.display(description="Buyer")
    def buyer_type(self, obj):
        return "Guest" if obj.customer_id is None else "Authenticated"


@admin.register(CartItem, site=fabinzi_admin_site)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("id", "cart", "kind", "store_product", "variant", "quantity", "updated_at")
    list_filter = ("kind",)
    search_fields = ("variant__sku", "store_product__title_en")


@admin.register(CheckoutSession, site=fabinzi_admin_site)
class CheckoutSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "status", "total", "currency", "updated_at")
    list_filter = ("status", "currency")
    search_fields = ("customer__username", "shipping_phone", "shipping_email")
    readonly_fields = ("placement_key", "pricing_snapshot")


@admin.register(CustomerPurchase, site=fabinzi_admin_site)
class CustomerPurchaseAdmin(admin.ModelAdmin):
    list_display = ("number", "buyer_type", "customer", "status", "payment_method", "total", "currency", "guest_confirmation_email_status", "created_at")
    list_filter = ("status", "payment_method", "currency", "guest_confirmation_email_status")
    search_fields = ("number", "customer__username", "customer__email")
    readonly_fields = ("number", "shipping_snapshot", "pricing_snapshot", "guest_confirmation_email_status", "guest_confirmation_email_updated_at")

    @admin.display(description="Buyer")
    def buyer_type(self, obj):
        return "Guest" if obj.customer_id is None else "Authenticated"


@admin.register(CustomerOrder, site=fabinzi_admin_site)
class CustomerOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "purchase", "customer", "designer_organization", "status", "total", "currency", "created_at")
    list_filter = ("status", "payment_method", "currency")
    search_fields = ("number", "purchase__number", "customer__username")


@admin.register(OrderItem, site=fabinzi_admin_site)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "purchase_kind", "sku", "quantity", "unit_price", "line_total")
    list_filter = ("purchase_kind",)
    readonly_fields = ("pricing_snapshot", "production_snapshot", "customization_snapshot")


@admin.register(PaymentAttempt, site=fabinzi_admin_site)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = ("purchase", "order", "provider", "status", "amount", "currency", "provider_reference", "created_at")
    list_filter = ("provider", "status")
    readonly_fields = ("idempotency_key", "request_fingerprint", "provider_payload")


@admin.register(PaymentWebhookEvent, site=fabinzi_admin_site)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_id", "processed", "received_at")
    list_filter = ("provider", "processed")
    readonly_fields = ("provider", "event_id", "payload_hash", "processed", "processing_error", "received_at", "processed_at")

    def has_add_permission(self, request):
        return False
