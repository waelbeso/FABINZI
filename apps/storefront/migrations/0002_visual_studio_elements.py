from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("artwork", "0001_initial"),
        ("storefront", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customizationelement",
            name="kind",
            field=models.CharField(
                choices=[
                    ("text", "Text"),
                    ("image", "Customer image"),
                    ("artwork", "Marketplace artwork"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="customizationelement",
            name="artwork_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="customer_customization_elements",
                to="artwork.artworkversion",
            ),
        ),
        migrations.AddField(
            model_name="customizationelement",
            name="production_method",
            field=models.CharField(
                blank=True,
                choices=[("print", "Print"), ("embroidery", "Embroidery")],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="customizationelement",
            name="rights_confirmed",
            field=models.BooleanField(default=False),
        ),
    ]
