import hashlib
import io
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, UnidentifiedImageError

from apps.integrations.models import IntegrationConfig
from .models import MediaAsset


class ProductionStorageUnavailable(ImproperlyConfigured):
    pass


STUDIO_IMAGE_MAX_BYTES = 10 * 1024 * 1024
STUDIO_IMAGE_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
}


def active_provider(provider: str):
    try:
        return IntegrationConfig.objects.get(provider=provider, enabled=True)
    except IntegrationConfig.DoesNotExist as exc:
        raise ProductionStorageUnavailable(f"{provider} is not configured and enabled") from exc


def private_media_storage_mode():
    mode = str(getattr(settings, "PRIVATE_MEDIA_STORAGE_MODE", "")).strip().lower()
    environment = str(getattr(settings, "ENVIRONMENT", "development")).strip().lower()
    if mode not in {"local", "s3"}:
        raise ProductionStorageUnavailable("PRIVATE_MEDIA_STORAGE_MODE must be either 'local' or 's3'")
    if mode == "local" and environment not in {"development", "dev", "test", "testing"}:
        raise ProductionStorageUnavailable("Private local media storage is not permitted outside development/test")
    return mode


def assert_production_file_storage():
    if private_media_storage_mode() == "s3":
        active_provider(IntegrationConfig.Provider.AMAZON_S3)


def _s3_client(config):
    cfg = config.config or {}
    secrets = config.get_secrets()
    return boto3.client(
        "s3",
        aws_access_key_id=secrets.get("access_key_id"),
        aws_secret_access_key=secrets.get("secret_access_key"),
        region_name=cfg.get("region"),
        endpoint_url=cfg.get("endpoint_url") or None,
        config=Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 2}),
    )


def validate_studio_image(upload):
    if not upload:
        raise ValidationError("Choose an image to upload.")
    size = getattr(upload, "size", 0) or 0
    if size <= 0:
        raise ValidationError("The uploaded image is empty.")
    if size > STUDIO_IMAGE_MAX_BYTES:
        raise ValidationError("The image is larger than the 10 MB Studio limit.")
    payload = upload.read()
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
        with Image.open(io.BytesIO(payload)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("The uploaded file is not a valid supported image.") from exc
    if image_format not in STUDIO_IMAGE_FORMATS:
        raise ValidationError("Studio accepts PNG, JPEG and WebP images.")
    if width < 1 or height < 1:
        raise ValidationError("The uploaded image has invalid dimensions.")
    mime_type, extension = STUDIO_IMAGE_FORMATS[image_format]
    return payload, mime_type, extension, width, height


def create_private_studio_image(*, upload, owner):
    if not getattr(owner, "is_authenticated", False):
        raise ValidationError("Sign in before uploading Studio artwork.")
    payload, mime_type, extension, width, height = validate_studio_image(upload)
    checksum = hashlib.sha256(payload).hexdigest()
    key = f"studio-private/{owner.pk}/{uuid.uuid4().hex}{extension}"
    filename = Path(getattr(upload, "name", "studio-image")).name[:255]
    storage_mode = private_media_storage_mode()

    if storage_mode == "local":
        stored_key = default_storage.save(key, ContentFile(payload))
        provider = MediaAsset.Provider.LOCAL_DEV
    else:
        integration = active_provider(IntegrationConfig.Provider.AMAZON_S3)
        bucket = (integration.config or {}).get("bucket", "")
        if not bucket:
            raise ProductionStorageUnavailable("Amazon S3 bucket is not configured")
        _s3_client(integration).put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType=mime_type,
            CacheControl="private, no-store",
        )
        stored_key = key
        provider = MediaAsset.Provider.AMAZON_S3

    return MediaAsset.objects.create(
        provider=provider,
        provider_asset_id=stored_key,
        original_filename=filename,
        mime_type=mime_type,
        size_bytes=len(payload),
        checksum_sha256=checksum,
        access=MediaAsset.Access.PRIVATE,
        metadata={"width": width, "height": height, "studio_private_upload": True},
        uploaded_by=owner,
    )


def private_media_response(asset):
    if asset.access != MediaAsset.Access.PRIVATE:
        raise ValidationError("This media asset is not private Studio media.")
    if asset.provider == MediaAsset.Provider.LOCAL_DEV:
        if private_media_storage_mode() != "local":
            raise ProductionStorageUnavailable("Local private Studio media cannot be served in this environment")
        return default_storage.open(asset.provider_asset_id, "rb")
    if asset.provider == MediaAsset.Provider.AMAZON_S3:
        integration = active_provider(IntegrationConfig.Provider.AMAZON_S3)
        bucket = (integration.config or {}).get("bucket", "")
        if not bucket:
            raise ProductionStorageUnavailable("Amazon S3 bucket is not configured")
        return _s3_client(integration).generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": asset.provider_asset_id},
            ExpiresIn=300,
        )
    raise ValidationError("Private Studio media provider is not supported for direct viewing.")
