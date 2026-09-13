from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0005_manufacturer_subscription_upgrade_request"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DesignerSubscriptionUpgradeRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plan_code", models.CharField(editable=False, max_length=64)),
                ("plan_version", models.PositiveIntegerField(editable=False)),
                ("policy_snapshot", models.JSONField(default=dict, editable=False)),
                ("price_snapshot", models.JSONField(default=dict, editable=False)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="pending", max_length=16)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("rejection_reason", models.TextField(blank=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="designer_subscription_upgrade_requests", to="organizations.organization")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requested_designer_subscription_upgrades", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_designer_subscription_upgrades", to=settings.AUTH_USER_MODEL)),
                ("target_plan_policy", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="designer_upgrade_requests", to="subscriptions.subscriptionplanpolicy")),
            ],
            options={
                "ordering": ("-requested_at", "-id"),
                "indexes": [models.Index(fields=["status", "requested_at"], name="dsr_upg_status_req_idx")],
                "constraints": [models.UniqueConstraint(condition=models.Q(("status", "pending")), fields=("organization",), name="unique_pending_dsr_upgrade")],
            },
        ),
    ]
