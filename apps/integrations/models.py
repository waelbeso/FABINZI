import json
from django.conf import settings
from django.db import models
from .crypto import decrypt_text, encrypt_text

class IntegrationConfig(models.Model):
    class Provider(models.TextChoices):
        COD = "cod", "Cash on Delivery"
        PAYMOB = "paymob", "Paymob"
        STRIPE = "stripe", "Stripe"
        MAILGUN = "mailgun", "Mailgun"
        TWILIO = "twilio", "Twilio"
        AMAZON_S3 = "amazon_s3", "Amazon S3"
        CLOUDFLARE_IMAGES = "cloudflare_images", "Cloudflare Images"
        SENTRY = "sentry", "Sentry"
    class TestStatus(models.TextChoices):
        NEVER = "never", "Never tested"
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"
    provider = models.CharField(max_length=32, choices=Provider.choices, unique=True)
    enabled = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)
    encrypted_secrets = models.TextField(blank=True)
    last_test_status = models.CharField(max_length=16, choices=TestStatus.choices, default=TestStatus.NEVER)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_message = models.CharField(max_length=500, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)
    def set_secrets(self, values: dict):
        self.encrypted_secrets = encrypt_text(json.dumps(values)) if values else ""
    def get_secrets(self) -> dict:
        if not self.encrypted_secrets:
            return {}
        return json.loads(decrypt_text(self.encrypted_secrets))
    def __str__(self):
        return self.get_provider_display()
