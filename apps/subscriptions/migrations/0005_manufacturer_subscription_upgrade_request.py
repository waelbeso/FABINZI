from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0004_onboarding_plan_selection"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ManufacturerSubscriptionUpgradeRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plan_code", models.CharField(editable=False, max_length=64)),
                ("plan_version", models.PositiveIntegerField(editable=False)),
                ("policy_snapshot", models.JSONField(default=dict, editable=False)),
                ("price_snapshot", models.JSONField(default=dict, editable=False)),
                ("status", models.CharField(choices=[("requested", "Requested"), ("completed", "Completed"), ("cancelled", "Cancelled")], db_index=True, default="requested", max_length=16)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("billing_confirmation", models.OneToOneField(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="manufacturer_upgrade_request", to="subscriptions.subscriptionbillingconfirmation")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="manufacturer_subscription_upgrade_requests", to="organizations.organization")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requested_manufacturer_subscription_upgrades", to=settings.AUTH_USER_MODEL)),
                ("resolved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resolved_manufacturer_subscription_upgrades", to=settings.AUTH_USER_MODEL)),
                ("target_plan_policy", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="manufacturer_upgrade_requests", to="subscriptions.subscriptionplanpolicy")),
            ],
            options={
                "ordering": ("-requested_at", "-id"),
                "indexes": [models.Index(fields=["status", "requested_at"], name="mfr_upgrade_status_idx")],
                "constraints": [models.UniqueConstraint(condition=models.Q(("status", "requested")), fields=("organization",), name="unique_requested_mfr_upgrade")],
            },
        ),
    ]
