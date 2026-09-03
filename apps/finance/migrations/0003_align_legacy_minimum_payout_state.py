from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0002_v2_finance_policy_recognition_payout")]

    operations = [
        migrations.AlterField(
            model_name="financepolicy",
            name="minimum_payout",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("100.00"),
                help_text="LEGACY ONLY; not a V2 policy input.",
                max_digits=12,
            ),
        ),
    ]
