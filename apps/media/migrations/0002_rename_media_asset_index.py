from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("media", "0001_initial")]

    operations = [
        migrations.RenameIndex(
            model_name="mediaasset",
            old_name="media_media_provide_1ec23a_idx",
            new_name="media_media_provide_39f057_idx",
        ),
    ]
