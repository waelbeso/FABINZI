from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("artwork", "0002_v2_creator_artwork_registration_rdp"),
    ]

    operations = [
        migrations.AlterField(
            model_name="artworkplacement",
            name="transform",
            field=models.JSONField(
                default=dict,
                help_text="Normalized x/y/width/height/rotation composition transform.",
            ),
        ),
    ]
