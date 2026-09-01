from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


def backfill_billing_policy_binding(apps, schema_editor):
    Confirmation = apps.get_model("subscriptions", "SubscriptionBillingConfirmation")
    Plan = apps.get_model("subscriptions", "SubscriptionPlanPolicy")
    for confirmation in Confirmation.objects.all().iterator():
        day = confirmation.confirmed_at.date()
        plan = (
            Plan.objects.filter(
                code=confirmation.plan_code,
                active=True,
                effective_from__lte=day,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=day))
            .order_by("-effective_from", "-version", "-pk")
            .first()
        )
        if plan is None:
            plan = Plan.objects.filter(code=confirmation.plan_code).order_by("-version", "-pk").first()
        if plan is None:
            raise RuntimeError(
                f"Cannot bind billing confirmation {confirmation.pk} to a subscription plan policy."
            )
        policy_snapshot = {
            "plan_policy_id": plan.pk,
            "code": plan.code,
            "version": plan.version,
            "audience": plan.audience,
            "public_name_ar": plan.public_name_ar,
            "public_name_en": plan.public_name_en,
            "tax_inclusive": plan.tax_inclusive,
            "trial_months": plan.trial_months,
            "designer_active_design_limit": plan.designer_active_design_limit,
            "designer_active_artwork_limit": plan.designer_active_artwork_limit,
            "manufacturer_monthly_offer_limit": plan.manufacturer_monthly_offer_limit,
            "team_subaccount_limit": plan.team_subaccount_limit,
            "effective_from": plan.effective_from.isoformat(),
            "effective_to": plan.effective_to.isoformat() if plan.effective_to else None,
        }
        price_snapshot = {
            "monthly_price": str(plan.monthly_price),
            "currency": plan.currency,
            "tax_inclusive": plan.tax_inclusive,
        }
        confirmation.plan_policy_id = plan.pk
        confirmation.plan_version = plan.version
        confirmation.tax_inclusive = plan.tax_inclusive
        confirmation.policy_snapshot = policy_snapshot
        confirmation.price_snapshot = price_snapshot
        confirmation.save(
            update_fields=[
                "plan_policy",
                "plan_version",
                "tax_inclusive",
                "policy_snapshot",
                "price_snapshot",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0002_bootstrap_v2_3_defaults")]

    operations = [
        migrations.AddField(
            model_name="subscriptionbillingconfirmation",
            name="plan_policy",
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="billing_confirmations",
                to="subscriptions.subscriptionplanpolicy",
            ),
        ),
        migrations.AddField(
            model_name="subscriptionbillingconfirmation",
            name="plan_version",
            field=models.PositiveIntegerField(default=0, editable=False),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="subscriptionbillingconfirmation",
            name="tax_inclusive",
            field=models.BooleanField(default=True, editable=False),
        ),
        migrations.AddField(
            model_name="subscriptionbillingconfirmation",
            name="policy_snapshot",
            field=models.JSONField(default=dict, editable=False),
        ),
        migrations.AddField(
            model_name="subscriptionbillingconfirmation",
            name="price_snapshot",
            field=models.JSONField(default=dict, editable=False),
        ),
        migrations.AddField(
            model_name="subscriptionbillingconfirmation",
            name="consumed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="subscriptionbillingconfirmation",
            name="consumed_period",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="billing_confirmation",
                to="subscriptions.subscriptionperiod",
            ),
        ),
        migrations.RunPython(backfill_billing_policy_binding, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="subscriptionbillingconfirmation",
            name="plan_policy",
            field=models.ForeignKey(
                editable=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="billing_confirmations",
                to="subscriptions.subscriptionplanpolicy",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="subscriptionbillingconfirmation",
            name="unique_subscription_provider_reference",
        ),
        migrations.AlterField(
            model_name="subscriptionbillingconfirmation",
            name="provider_reference",
            field=models.CharField(max_length=180, unique=True),
        ),
    ]
