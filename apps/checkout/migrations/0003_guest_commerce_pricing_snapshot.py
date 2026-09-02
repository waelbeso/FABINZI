import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def populate_placement_keys_and_purchase_kinds(apps, schema_editor):
    CheckoutSession = apps.get_model("checkout", "CheckoutSession")
    OrderItem = apps.get_model("checkout", "OrderItem")
    for session in CheckoutSession.objects.filter(placement_key__isnull=True).iterator():
        session.placement_key = uuid.uuid4()
        session.save(update_fields=["placement_key"])
    for item in OrderItem.objects.select_related("store_product__designed_product").iterator():
        if item.studio_project_id:
            kind = "studio"
        else:
            designed_product = item.store_product.designed_product
            kind = "ready_designed" if designed_product.placements.exists() else "plain"
        OrderItem.objects.filter(pk=item.pk).update(purchase_kind=kind)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("checkout", "0002_commerce_parent_cart"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="cart", name="unique_active_cart_per_customer"),
        migrations.AlterField(
            model_name="cart",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="carts", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(model_name="cart", name="guest_key_hash", field=models.CharField(blank=True, db_index=True, default="", max_length=64)),
        migrations.AddField(
            model_name="cart",
            name="merged_into",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="merged_guest_carts", to="checkout.cart"),
        ),
        migrations.AddConstraint(
            model_name="cart",
            constraint=models.UniqueConstraint(condition=models.Q(("customer__isnull", False), ("status", "active")), fields=("customer",), name="unique_active_cart_per_customer"),
        ),
        migrations.AddConstraint(
            model_name="cart",
            constraint=models.UniqueConstraint(
                condition=models.Q(("customer__isnull", True), ("status", "active")) & ~models.Q(("guest_key_hash", "")),
                fields=("guest_key_hash",),
                name="unique_active_guest_cart_per_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="cart",
            constraint=models.CheckConstraint(
                condition=models.Q(("customer__isnull", False), ("guest_key_hash", "")) | (models.Q(("customer__isnull", True)) & ~models.Q(("guest_key_hash", ""))),
                name="cart_exactly_one_owner_identity",
            ),
        ),
        migrations.AlterField(
            model_name="checkoutsession",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="checkout_sessions", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(model_name="checkoutsession", name="placement_key", field=models.UUIDField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name="checkoutsession", name="pricing_snapshot", field=models.JSONField(blank=True, default=dict)),
        migrations.AlterField(
            model_name="customerpurchase",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="customer_purchases", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="customerpurchase",
            name="guest_confirmation_email_status",
            field=models.CharField(choices=[("not_required", "Not required"), ("queued", "Queued"), ("sent", "Sent"), ("skipped", "Skipped"), ("failed", "Failed")], db_index=True, default="not_required", max_length=16),
        ),
        migrations.AddField(model_name="customerpurchase", name="guest_confirmation_email_updated_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="customerpurchase", name="pricing_snapshot", field=models.JSONField(blank=True, default=dict)),
        migrations.AlterField(
            model_name="customerorder",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="customer_orders", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="purchase_kind",
            field=models.CharField(choices=[("plain", "Plain product"), ("studio", "Studio customization"), ("ready_designed", "Ready designed product")], default="plain", max_length=24),
        ),
        migrations.AddField(model_name="orderitem", name="pricing_snapshot", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="orderitem", name="production_snapshot", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="paymentattempt", name="request_fingerprint", field=models.CharField(blank=True, max_length=64)),
        migrations.RunPython(populate_placement_keys_and_purchase_kinds, migrations.RunPython.noop),
        migrations.AlterField(model_name="checkoutsession", name="placement_key", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
    ]
