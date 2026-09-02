from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("public_profiles", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="manufacturercapabilityverification",
            name="capability",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="public_verifications",
                to="manufacturer_marketplace.manufacturercapability",
            ),
        ),
        migrations.AddConstraint(
            model_name="manufacturercapabilityverification",
            constraint=models.UniqueConstraint(
                fields=("capability", "canonical_code"),
                name="uniq_public_capability_canonical_code",
            ),
        ),
        migrations.AddIndex(
            model_name="manufacturercapabilityverification",
            index=models.Index(
                fields=["canonical_code", "status"],
                name="pubcap_code_status_idx",
            ),
        ),
    ]
