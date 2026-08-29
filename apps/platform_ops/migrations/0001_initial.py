from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="MaintenanceWindow", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("enabled", models.BooleanField(default=False)),
            ("mode", models.CharField(choices=[("banner", "Warning banner only"), ("restrict", "Restrict customer/business surfaces")], default="restrict", max_length=16)),
            ("message_ar", models.TextField()), ("message_en", models.TextField()), ("starts_at", models.DateTimeField()), ("ends_at", models.DateTimeField(blank=True, null=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="PlatformAnnouncement", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("enabled", models.BooleanField(default=False)),
            ("title_ar", models.CharField(max_length=220)), ("title_en", models.CharField(max_length=220)), ("message_ar", models.TextField()), ("message_en", models.TextField()),
            ("severity", models.CharField(choices=[("info", "Information"), ("success", "Success"), ("warning", "Warning"), ("maintenance", "Maintenance"), ("critical", "Critical")], default="info", max_length=20)),
            ("audience", models.CharField(choices=[("all", "All"), ("customers", "Customers"), ("designers", "Designers"), ("manufacturers", "Manufacturers"), ("staff", "Staff")], default="all", max_length=20)),
            ("starts_at", models.DateTimeField()), ("ends_at", models.DateTimeField(blank=True, null=True)), ("dismissible", models.BooleanField(default=True)),
            ("cta_label_ar", models.CharField(blank=True, max_length=120)), ("cta_label_en", models.CharField(blank=True, max_length=120)), ("cta_url", models.CharField(blank=True, max_length=500)),
            ("priority", models.PositiveSmallIntegerField(default=100)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="announcements_created", to=settings.AUTH_USER_MODEL)),
        ]),
    ]
