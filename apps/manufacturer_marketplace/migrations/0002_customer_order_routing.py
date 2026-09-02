from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("checkout", "0003_guest_commerce_pricing_snapshot"),
        ("manufacturer_marketplace", "0001_initial"),
    ]
    operations = [
        migrations.AddField(model_name="rfq", name="source", field=models.CharField(choices=[("designer_sourcing", "Designer sourcing"), ("customer_order", "Customer order routing")], db_index=True, default="designer_sourcing", max_length=24)),
        migrations.AddField(model_name="rfq", name="order_item", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="manufacturing_rfq", to="checkout.orderitem")),
        migrations.AddField(model_name="rfq", name="routing_snapshot", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="rfq", name="routed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddIndex(model_name="rfq", index=models.Index(fields=["source", "status"], name="rfq_source_status_idx")),
    ]
