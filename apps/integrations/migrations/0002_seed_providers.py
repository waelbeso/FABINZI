from django.db import migrations

def seed(apps, schema_editor):
    IntegrationConfig = apps.get_model("integrations", "IntegrationConfig")
    for provider in ["cod", "paymob", "stripe", "mailgun", "twilio", "amazon_s3", "cloudflare_images", "sentry"]:
        IntegrationConfig.objects.get_or_create(provider=provider, defaults={"enabled": provider == "cod"})

def unseed(apps, schema_editor):
    apps.get_model("integrations", "IntegrationConfig").objects.all().delete()

class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
