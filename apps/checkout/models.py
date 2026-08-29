import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class CheckoutSession(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PLACED = "placed", "Placed"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="checkout_sessions")
    studio_project = models.OneToOneField("storefront.StudioProject", on_delete=models.PROTECT, related_name="checkout_session")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    shipping_name = models.CharField(max_length=180, blank=True)
    shipping_phone = models.CharField(max_length=50, blank=True)
    shipping_email = models.EmailField(blank=True)
    shipping_address1 = models.CharField(max_length=255, blank=True)
    shipping_address2 = models.CharField(max_length=255, blank=True)
    shipping_city = models.CharField(max_length=120, blank=True)
    shipping_region = models.CharField(max_length=120, blank=True)
    shipping_country = models.CharField(max_length=2, default="EG")
    postal_code = models.CharField(max_length=30, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EGP")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    placed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-updated_at",)

    def clean(self):
        if self.studio_project_id and self.customer_id != self.studio_project.customer_id:
            raise ValidationError({"customer": "Checkout customer must own the Studio project."})
        if self.currency and len(self.currency) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})


class CustomerOrder(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        PAYMENT_FAILED = "payment_failed", "Payment failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    class PaymentMethod(models.TextChoices):
        COD = "cod", "Cash on Delivery"
        PAYMOB = "paymob", "Paymob"
        STRIPE = "stripe", "Stripe"

    number = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    checkout = models.OneToOneField(CheckoutSession, on_delete=models.PROTECT, related_name="order")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_orders")
    designer_organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="store_orders")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    shipping_snapshot = models.JSONField(default=dict)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["customer", "status"], name="order_customer_status_idx")]


class OrderItem(models.Model):
    order = models.OneToOneField(CustomerOrder, on_delete=models.PROTECT, related_name="item")
    store_product = models.ForeignKey("storefront.StoreProduct", on_delete=models.PROTECT, related_name="order_items")
    variant = models.ForeignKey("storefront.ProductVariant", on_delete=models.PROTECT, related_name="order_items")
    studio_project = models.ForeignKey("storefront.StudioProject", on_delete=models.PROTECT, related_name="order_items")
    sku = models.CharField(max_length=120)
    title = models.CharField(max_length=220)
    size = models.CharField(max_length=40, blank=True)
    color_name = models.CharField(max_length=80, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    customization_snapshot = models.JSONField(default=dict, blank=True)

    def clean(self):
        if self.variant_id and self.variant.product_id != self.store_product_id:
            raise ValidationError({"variant": "Order variant must belong to Store Product."})


class PaymentAttempt(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        REQUIRES_ACTION = "requires_action", "Requires action"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    order = models.ForeignKey(CustomerOrder, on_delete=models.PROTECT, related_name="payment_attempts")
    provider = models.CharField(max_length=20, choices=CustomerOrder.PaymentMethod.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    idempotency_key = models.CharField(max_length=80, unique=True)
    provider_reference = models.CharField(max_length=180, blank=True, db_index=True)
    redirect_url = models.URLField(blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    failure_code = models.CharField(max_length=80, blank=True)
    failure_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)


class PaymentWebhookEvent(models.Model):
    provider = models.CharField(max_length=20, choices=[("paymob", "Paymob"), ("stripe", "Stripe")])
    event_id = models.CharField(max_length=180)
    payload_hash = models.CharField(max_length=64)
    processed = models.BooleanField(default=False)
    processing_error = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "event_id"], name="unique_payment_webhook_event")]
        ordering = ("-received_at",)
