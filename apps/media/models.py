from django.conf import settings
from django.db import models

class MediaAsset(models.Model):
    class Provider(models.TextChoices):
        LOCAL_DEV = "local_dev", "Local development"
        AMAZON_S3 = "amazon_s3", "Amazon S3"
        CLOUDFLARE_IMAGES = "cloudflare_images", "Cloudflare Images"
    class Access(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"
    provider = models.CharField(max_length=32, choices=Provider.choices)
    provider_asset_id = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=160)
    size_bytes = models.PositiveBigIntegerField()
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    access = models.CharField(max_length=16, choices=Access.choices, default=Access.PRIVATE)
    metadata = models.JSONField(default=dict, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=["provider", "provider_asset_id"])]
