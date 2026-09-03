from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("checkout", "0003_guest_commerce_pricing_snapshot"),
        ("manufacturer_marketplace", "0002_customer_order_routing"),
        ("operations", "0001_initial"),
        ("organizations", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="ProductionSpecification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("snapshot", models.JSONField(default=dict)),
                ("snapshot_sha256", models.CharField(db_index=True, max_length=64)),
                ("authorized_media_asset_ids", models.JSONField(default=list)),
                ("required_canonical_capabilities", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("release_block_reason", models.TextField(blank=True)),
                ("accepted_quote", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="production_specifications", to="manufacturer_marketplace.manufacturerquote")),
                ("assigned_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assigned_production_specifications", to=settings.AUTH_USER_MODEL)),
                ("job", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="production_specification", to="operations.productionjob")),
                ("manufacturer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="production_specifications", to="organizations.organization")),
                ("order_item", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="production_specification", to="checkout.orderitem")),
                ("released_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="released_production_specifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
