from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name="Notification", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("type", models.CharField(max_length=80)),
        ("title_ar", models.CharField(max_length=220)), ("title_en", models.CharField(max_length=220)), ("body_ar", models.TextField(blank=True)), ("body_en", models.TextField(blank=True)),
        ("destination", models.CharField(blank=True, max_length=500)), ("is_read", models.BooleanField(default=False)), ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)), ("read_at", models.DateTimeField(blank=True, null=True)),
        ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
    ], options={"ordering": ("-created_at",)})]
