from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("public_inquiries", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="publicinquiryemailchallenge",
            name="consumed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
