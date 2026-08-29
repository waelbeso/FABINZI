from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name="IntegrationConfig", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("provider", models.CharField(choices=[("cod", "Cash on Delivery"), ("paymob", "Paymob"), ("stripe", "Stripe"), ("mailgun", "Mailgun"), ("twilio", "Twilio"), ("amazon_s3", "Amazon S3"), ("cloudflare_images", "Cloudflare Images"), ("sentry", "Sentry")], max_length=32, unique=True)),
        ("enabled", models.BooleanField(default=False)), ("config", models.JSONField(blank=True, default=dict)), ("encrypted_secrets", models.TextField(blank=True)),
        ("last_test_status", models.CharField(choices=[("never", "Never tested"), ("success", "Success"), ("failure", "Failure")], default="never", max_length=16)),
        ("last_tested_at", models.DateTimeField(blank=True, null=True)), ("last_test_message", models.CharField(blank=True, max_length=500)), ("updated_at", models.DateTimeField(auto_now=True)),
        ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
    ])]
