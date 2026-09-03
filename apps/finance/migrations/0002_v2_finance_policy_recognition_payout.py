from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def retire_legacy_policies(apps, schema_editor):
    FinancePolicy = apps.get_model("finance", "FinancePolicy")
    for policy in FinancePolicy.objects.all().iterator():
        policy.code = policy.code or f"LEGACY-FIN-POL-{policy.pk:04d}"
        policy.lifecycle_status = "retired"
        policy.is_active = False
        policy.save(update_fields=["code", "lifecycle_status", "is_active"])


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0001_initial"),
        ("media", "0001_initial"),
        ("manufacturer_marketplace", "0002_customer_order_routing"),
        ("operations", "0002_production_specification"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(name="financepolicy", options={"ordering": ("-created_at", "-id"), "permissions": [("view_finance_policy_governance", "Can view V2 Finance Policy governance"), ("manage_finance_policy_governance", "Can create and edit V2 Finance Policy drafts"), ("activate_finance_policy_governance", "Can activate or retire V2 Finance Policy versions"), ("reconcile_finance_recognition", "Can reconcile blocked V2 finance recognition"), ("execute_finance_payout", "Can execute V2 payout lifecycle transitions")]}),
        migrations.AlterField(model_name="financepolicy", name="is_active", field=models.BooleanField(db_index=True, default=False, help_text="LEGACY ONLY; V2 uses lifecycle_status.")),
        migrations.AlterField(model_name="financepolicy", name="platform_fee_bps", field=models.PositiveIntegerField(default=1000, help_text="LEGACY ONLY; not a V2 policy input.")),
        migrations.AlterField(model_name="financepolicy", name="settlement_delay_days", field=models.PositiveIntegerField(default=7, help_text="LEGACY ONLY; not a V2 policy input.")),
        migrations.AlterField(model_name="financepolicy", name="minimum_payout", field=models.DecimalField(decimal_places=2, default="100.00", help_text="LEGACY ONLY; not a V2 policy input.", max_digits=12)),
        migrations.AddField(model_name="financepolicy", name="code", field=models.CharField(blank=True, max_length=40, null=True, unique=True)),
        migrations.AddField(model_name="financepolicy", name="lifecycle_status", field=models.CharField(choices=[("draft","Draft"),("active","Active"),("retired","Retired")], db_index=True, default="draft", max_length=16)),
        migrations.AddField(model_name="financepolicy", name="currency", field=models.CharField(blank=True, max_length=3)),
        migrations.AddField(model_name="financepolicy", name="fabinzi_rule_type", field=models.CharField(blank=True, choices=[("percentage","Percentage of line gross"),("fixed","Fixed amount per order line"),("per_unit","Amount per unit")], max_length=16)),
        migrations.AddField(model_name="financepolicy", name="fabinzi_rule_value", field=models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
        migrations.AddField(model_name="financepolicy", name="garment_royalty_rule_type", field=models.CharField(blank=True, choices=[("percentage","Percentage of line gross"),("fixed","Fixed amount per order line"),("per_unit","Amount per unit")], max_length=16)),
        migrations.AddField(model_name="financepolicy", name="garment_royalty_rule_value", field=models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
        migrations.AddField(model_name="financepolicy", name="artwork_royalty_rule_type", field=models.CharField(blank=True, choices=[("percentage","Percentage of line gross"),("fixed","Fixed amount per order line"),("per_unit","Amount per unit")], max_length=16)),
        migrations.AddField(model_name="financepolicy", name="artwork_royalty_rule_value", field=models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
        migrations.AddField(model_name="financepolicy", name="manufacturer_include_unit_price", field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="manufacturer_include_setup_fee", field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="manufacturer_include_sample_fee", field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="manufacturer_include_shipping_estimate", field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="settlement_trigger", field=models.CharField(blank=True, choices=[("delivery","Fulfillment delivered"),("payment_and_delivery","Payment succeeded and fulfillment delivered")], max_length=32)),
        migrations.AddField(model_name="financepolicy", name="settlement_hold_days", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="v2_minimum_payout", field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name="financepolicy", name="validated_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="activated_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="retired_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="created_at", field=models.DateTimeField(auto_now_add=True, null=True)),
        migrations.AddField(model_name="financepolicy", name="created_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_finance_policies", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="financepolicy", name="activated_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="activated_finance_policies", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="financepolicy", name="retired_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="retired_finance_policies", to=settings.AUTH_USER_MODEL)),
        migrations.RunPython(retire_legacy_policies, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="financepolicy", constraint=models.UniqueConstraint(condition=models.Q(("lifecycle_status", "active")), fields=("currency",), name="one_active_v2_finance_policy_per_currency")),
        migrations.AddField(model_name="payoutprofile", name="bank_name", field=models.CharField(blank=True, max_length=180)),
        migrations.AddField(model_name="payoutprofile", name="iban_encrypted", field=models.TextField(blank=True)),
        migrations.AddField(model_name="payoutprofile", name="iban_last4", field=models.CharField(blank=True, max_length=4)),
        migrations.AddField(model_name="payoutprofile", name="country", field=models.CharField(blank=True, max_length=2)),
        migrations.AddField(model_name="payoutprofile", name="currency", field=models.CharField(blank=True, max_length=3)),
        migrations.AddField(model_name="payoutprofile", name="bank_proof", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="finance_bank_proofs", to="media.mediaasset")),
        migrations.AddField(model_name="orderfinance", name="order_item", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="finance_records", to="checkout.orderitem")),
        migrations.AddField(model_name="orderfinance", name="finance_policy", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="order_finances", to="finance.financepolicy")),
        migrations.AddField(model_name="orderfinance", name="garment_designer_account", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="garment_royalty_finance", to="finance.financeaccount")),
        migrations.AddField(model_name="orderfinance", name="artwork_designer_account", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="artwork_royalty_finance", to="finance.financeaccount")),
        migrations.AddField(model_name="orderfinance", name="platform_account", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="platform_order_finance", to="finance.financeaccount")),
        migrations.AddField(model_name="orderfinance", name="fabinzi_component", field=models.DecimalField(decimal_places=2, default=0, max_digits=12)),
        migrations.AddField(model_name="orderfinance", name="garment_designer_royalty", field=models.DecimalField(decimal_places=2, default=0, max_digits=12)),
        migrations.AddField(model_name="orderfinance", name="artwork_designer_royalty", field=models.DecimalField(decimal_places=2, default=0, max_digits=12)),
        migrations.AddField(model_name="orderfinance", name="source_snapshot", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="orderfinance", name="pricing_snapshot", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="settlementrequest", name="idempotency_key", field=models.CharField(blank=True, max_length=80, null=True, unique=True)),
        migrations.AddField(model_name="settlementrequest", name="execution_evidence", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="settlementrequest", name="reserved_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="settlementrequest", name="processing_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(model_name="settlementrequest", name="status", field=models.CharField(choices=[("requested","Requested"),("under_review","Under review"),("approved","Approved"),("processing","Processing"),("paid","Paid"),("rejected","Rejected"),("cancelled","Cancelled"),("failed","Failed")], db_index=True, default="requested", max_length=20)),
        migrations.AddField(model_name="ledgerentry", name="event_key", field=models.CharField(blank=True, max_length=120, null=True, unique=True)),
        migrations.AlterField(model_name="ledgerentry", name="entry_type", field=models.CharField(choices=[("designer_earning","Legacy Designer earning"),("manufacturer_earning","Legacy Manufacturer earning"),("platform_fee","Legacy Platform fee"),("garment_designer_royalty","Garment Designer royalty"),("artwork_designer_royalty","Artwork Designer royalty"),("manufacturer_payable","Manufacturer payable"),("fabinzi_component","FABINZI component"),("settlement","Settlement"),("adjustment","Adjustment"),("reversal","Reversal")], max_length=40)),
        migrations.CreateModel(name="OrderFinanceComponent", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("component_type", models.CharField(choices=[("manufacturer_payable","Manufacturer payable"),("garment_royalty","Garment Designer royalty"),("artwork_royalty","Artwork Designer royalty"),("fabinzi_component","FABINZI component")], max_length=32)), ("amount", models.DecimalField(decimal_places=2, max_digits=12)), ("currency", models.CharField(max_length=3)), ("available_at", models.DateTimeField()), ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="finance_components", to="finance.financeaccount")), ("beneficiary_organization", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="finance_components", to="organizations.organization")), ("order_finance", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="components", to="finance.orderfinance"))], options={"constraints": [models.UniqueConstraint(fields=("order_finance","component_type"), name="unique_v2_finance_component_type")]}),
        migrations.CreateModel(name="FinanceRecognitionPending", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("status", models.CharField(choices=[("blocked","Blocked for finance policy"),("reconciled","Reconciled")], db_index=True, default="blocked", max_length=16)), ("currency", models.CharField(max_length=3)), ("trigger_event", models.CharField(choices=[("fulfillment.delivered","Fulfillment delivered")], max_length=40)), ("block_reason", models.CharField(max_length=255)), ("source_snapshot", models.JSONField(default=dict)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("last_attempt_at", models.DateTimeField(blank=True, null=True)), ("reconciled_at", models.DateTimeField(blank=True, null=True)), ("manufacturer_quote", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pending_finance_recognitions", to="manufacturer_marketplace.manufacturerquote")), ("order", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="pending_finance_recognition", to="checkout.customerorder")), ("order_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pending_finance_recognitions", to="checkout.orderitem")), ("production_specification", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pending_finance_recognitions", to="operations.productionspecification")), ("purchase", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pending_finance_recognitions", to="checkout.customerpurchase")), ("reconciled_finance", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="recognition_source", to="finance.orderfinance"))], options={"ordering": ("created_at","id"), "indexes": [models.Index(fields=["status","created_at"], name="finance_pending_status_idx")]})
    ]
