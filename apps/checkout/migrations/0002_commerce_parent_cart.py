import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_customer_purchases(apps, schema_editor):
    CustomerOrder = apps.get_model("checkout", "CustomerOrder")
    CustomerPurchase = apps.get_model("checkout", "CustomerPurchase")
    PaymentAttempt = apps.get_model("checkout", "PaymentAttempt")
    for order in CustomerOrder.objects.filter(purchase__isnull=True).iterator():
        if not order.checkout_id:
            continue
        purchase = CustomerPurchase.objects.create(number=order.number, checkout_id=order.checkout_id, customer_id=order.customer_id, status=order.status, payment_method=order.payment_method, subtotal=order.subtotal, shipping_amount=order.shipping_amount, discount_amount=order.discount_amount, total=order.total, currency=order.currency, shipping_snapshot=order.shipping_snapshot, confirmed_at=order.confirmed_at, cancelled_at=order.cancelled_at)
        CustomerPurchase.objects.filter(pk=purchase.pk).update(created_at=order.created_at, updated_at=order.updated_at)
        CustomerOrder.objects.filter(pk=order.pk).update(purchase_id=purchase.pk)
        PaymentAttempt.objects.filter(order_id=order.pk, purchase__isnull=True).update(purchase_id=purchase.pk)


class Migration(migrations.Migration):
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("checkout", "0001_initial"), ("storefront", "0001_initial")]
    operations = [
        migrations.CreateModel(name="Cart", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("status", models.CharField(choices=[("active", "Active"), ("converted", "Converted"), ("abandoned", "Abandoned")], db_index=True, default="active", max_length=20)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("customer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="carts", to=settings.AUTH_USER_MODEL))], options={"ordering": ("-updated_at",)}),
        migrations.AddConstraint(model_name="cart", constraint=models.UniqueConstraint(condition=models.Q(("status", "active")), fields=("customer",), name="unique_active_cart_per_customer")),
        migrations.AlterField(model_name="checkoutsession", name="studio_project", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="checkout_session", to="storefront.studioproject")),
        migrations.AddField(model_name="checkoutsession", name="cart", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="checkout_session", to="checkout.cart")),
        migrations.CreateModel(name="CustomerPurchase", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("number", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)), ("status", models.CharField(choices=[("pending_payment", "Pending payment"), ("confirmed", "Confirmed"), ("payment_failed", "Payment failed"), ("cancelled", "Cancelled"), ("refunded", "Refunded")], db_index=True, default="pending_payment", max_length=24)), ("payment_method", models.CharField(choices=[("cod", "Cash on Delivery"), ("paymob", "Paymob"), ("stripe", "Stripe")], max_length=20)), ("subtotal", models.DecimalField(decimal_places=2, max_digits=12)), ("shipping_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)), ("discount_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)), ("total", models.DecimalField(decimal_places=2, max_digits=12)), ("currency", models.CharField(max_length=3)), ("shipping_snapshot", models.JSONField(default=dict)), ("confirmed_at", models.DateTimeField(blank=True, null=True)), ("cancelled_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("checkout", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="purchase", to="checkout.checkoutsession")), ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_purchases", to=settings.AUTH_USER_MODEL))], options={"ordering": ("-created_at",), "indexes": [models.Index(fields=["customer", "status"], name="purchase_customer_status_idx")]}),
        migrations.AlterField(model_name="customerorder", name="checkout", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="order", to="checkout.checkoutsession")),
        migrations.AddField(model_name="customerorder", name="purchase", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="child_orders", to="checkout.customerpurchase")),
        migrations.AlterField(model_name="orderitem", name="studio_project", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="order_items", to="storefront.studioproject")),
        migrations.AlterField(model_name="paymentattempt", name="order", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payment_attempts", to="checkout.customerorder")),
        migrations.AddField(model_name="paymentattempt", name="purchase", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payment_attempts", to="checkout.customerpurchase")),
        migrations.CreateModel(name="CartItem", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("kind", models.CharField(choices=[("plain", "Plain product"), ("studio", "Studio customization"), ("ready_designed", "Ready designed product")], max_length=24)), ("quantity", models.PositiveIntegerField(default=1)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("cart", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="checkout.cart")), ("store_product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cart_items", to="storefront.storeproduct")), ("studio_project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="cart_items", to="storefront.studioproject")), ("variant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cart_items", to="storefront.productvariant"))], options={"ordering": ("created_at", "id")}),
        migrations.RunPython(backfill_customer_purchases, migrations.RunPython.noop),
    ]
