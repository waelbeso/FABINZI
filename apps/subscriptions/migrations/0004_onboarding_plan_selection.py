from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0003_billing_evidence_corrections"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OnboardingPlanSelection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plan_code", models.CharField(editable=False, max_length=64)),
                ("plan_version", models.PositiveIntegerField(editable=False)),
                ("policy_snapshot", models.JSONField(default=dict, editable=False)),
                ("price_snapshot", models.JSONField(default=dict, editable=False)),
                ("selected_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("payment_due_at", models.DateTimeField(blank=True, db_index=True, editable=False, null=True)),
                ("application", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="plan_selection", to="organizations.onboardingapplication")),
                ("selected_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="onboarding_plan_selections", to=settings.AUTH_USER_MODEL)),
                ("selected_plan_policy", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="onboarding_selections", to="subscriptions.subscriptionplanpolicy")),
            ],
            options={"ordering": ("-selected_at", "-id")},
        ),
    ]
