import hashlib
import uuid
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.integrations.models import IntegrationConfig
from .models import MediaAsset
from .services import (
    ProductionStorageUnavailable,
    _s3_client,
    active_provider,
    private_media_storage_mode,
)

DESIGNER_PRIVATE_FILE_MAX_BYTES = 50 * 1024 * 1024


def create_private_designer_asset(*, upload, owner, organization, purpose="technical"):
    if not getattr(owner, "is_authenticated", False):
        raise ValidationError("Authentication is required before uploading Designer files.")
    if organization.kind != "designer":
        raise ValidationError("Designer private assets require a Designer organization.")
    if not upload:
        raise ValidationError("Choose a file to upload.")
    size = int(getattr(upload, "size", 0) or 0)
    if size <= 0:
        raise ValidationError("The uploaded file is empty.")
    if size > DESIGNER_PRIVATE_FILE_MAX_BYTES:
        raise ValidationError("The file is larger than the 50 MB Designer workspace limit.")

    payload = upload.read()
    if not payload:
        raise ValidationError("The uploaded file is empty.")
    checksum = hashlib.sha256(payload).hexdigest()
    filename = Path(getattr(upload, "name", "designer-file")).name[:255]
    extension = Path(filename).suffix.lower()[:16]
    key = f"designer-private/{organization.pk}/{owner.pk}/{uuid.uuid4().hex}{extension}"
    mime_type = str(getattr(upload, "content_type", "") or "application/octet-stream")[:160]
    mode = private_media_storage_mode()

    if mode == "local":
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
        metadata={
            "designer_private_upload": True,
            "organization_id": organization.pk,
            "purpose": str(purpose or "technical")[:80],
        },
        uploaded_by=owner,
    )
