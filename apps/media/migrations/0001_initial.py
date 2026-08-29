from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name="MediaAsset", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("provider", models.CharField(choices=[("local_dev", "Local development"), ("amazon_s3", "Amazon S3"), ("cloudflare_images", "Cloudflare Images")], max_length=32)),
        ("provider_asset_id", models.CharField(max_length=500)), ("original_filename", models.CharField(max_length=255)), ("mime_type", models.CharField(max_length=160)), ("size_bytes", models.PositiveBigIntegerField()),
        ("checksum_sha256", models.CharField(blank=True, max_length=64)), ("access", models.CharField(choices=[("public", "Public"), ("private", "Private")], default="private", max_length=16)), ("metadata", models.JSONField(blank=True, default=dict)), ("created_at", models.DateTimeField(auto_now_add=True)),
        ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
    ], options={"indexes":[models.Index(fields=["provider","provider_asset_id"], name="media_media_provide_1ec23a_idx")]})]
