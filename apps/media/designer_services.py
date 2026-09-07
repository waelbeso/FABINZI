import hashlib
import uuid
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import DatabaseError

from apps.integrations.models import IntegrationConfig
from apps.organizations.models import Organization
from apps.organizations.services import require_org_access
from .models import MediaAsset
from .services import (
    ProductionStorageUnavailable,
    _s3_client,
    active_provider,
    private_media_storage_mode,
)

DESIGNER_PRIVATE_FILE_MAX_BYTES = 50 * 1024 * 1024
_SAFE_STORAGE_ERROR = "Private file storage is temporarily unavailable."


def designer_asset_organization_id(asset):
    metadata = asset.metadata or {}
    if not metadata.get("designer_private_upload"):
        return None
    try:
        return int(metadata.get("organization_id"))
    except (TypeError, ValueError):
        return None


def require_private_designer_asset(*, asset, organization, actor=None, purposes=None):
    if asset.access != MediaAsset.Access.PRIVATE:
        raise ValidationError("Designer workflow files must remain private.")
    if (asset.metadata or {}).get("studio_private_upload"):
        raise ValidationError("Customer Studio uploads cannot be used as Designer business files.")
    if designer_asset_organization_id(asset) != organization.pk:
        raise PermissionDenied("This private asset belongs to another Designer organization.")
    if organization.kind != Organization.Kind.DESIGNER:
        raise ValidationError("Designer private assets require a Designer organization.")
    if actor is not None:
        require_org_access(actor, organization)
    if purposes:
        purpose = str((asset.metadata or {}).get("purpose") or "")
        if purpose not in set(purposes):
            raise ValidationError("This private asset is not valid for the requested Designer workflow.")
    return asset


def claim_or_require_private_designer_asset(*, asset, organization, actor, purpose="legacy_claimed"):
    """Safely bind pre-Designer-Portal private uploads on first business attachment.

    New uploads are always tenant-tagged at creation. This compatibility path only
    accepts an unscoped PRIVATE asset owned by the same authenticated actor, rejects
    Studio customer uploads, and permanently stamps the selected Designer tenant so
    the asset cannot later cross organizations.
    """
    if (asset.metadata or {}).get("designer_private_upload"):
        return require_private_designer_asset(asset=asset, organization=organization, actor=actor)
    if asset.access != MediaAsset.Access.PRIVATE:
        raise ValidationError("Designer workflow files must remain private.")
    if (asset.metadata or {}).get("studio_private_upload"):
        raise ValidationError("Customer Studio uploads cannot be used as Designer business files.")
    require_org_access(actor, organization)
    if asset.uploaded_by_id != getattr(actor, "pk", None):
        raise PermissionDenied("This private asset is not owned by the current user.")
    metadata = dict(asset.metadata or {})
    metadata.update({
        "designer_private_upload": True,
        "organization_id": organization.pk,
        "purpose": str(purpose or "legacy_claimed")[:80],
        "legacy_designer_claim": True,
    })
    asset.metadata = metadata
    asset.save(update_fields=["metadata"])
    return asset


def _delete_private_storage_object(*, provider, stored_key):
    if provider == MediaAsset.Provider.LOCAL_DEV:
        default_storage.delete(stored_key)
        return
    if provider == MediaAsset.Provider.AMAZON_S3:
        integration = active_provider(IntegrationConfig.Provider.AMAZON_S3)
        bucket = (integration.config or {}).get("bucket", "")
        if not bucket:
            raise ProductionStorageUnavailable(_SAFE_STORAGE_ERROR)
        _s3_client(integration).delete_object(Bucket=bucket, Key=stored_key)


def _designer_media_has_references(asset):
    for relation in asset._meta.related_objects:
        accessor = relation.get_accessor_name()
        if not accessor:
            continue
        if relation.one_to_one:
            try:
                getattr(asset, accessor)
            except ObjectDoesNotExist:
                continue
            return True
        related_manager = getattr(asset, accessor)
        if related_manager.exists():
            return True
    return False


def cleanup_unattached_private_designer_asset(asset):
    """Remove only a newly-created, unreferenced Designer-private upload.

    If storage cleanup cannot be completed safely, preserve the database row so the
    storage object remains traceable rather than deleting the pointer to it.
    """
    if not asset or asset.access != MediaAsset.Access.PRIVATE:
        return False
    if not (asset.metadata or {}).get("designer_private_upload"):
        return False
    if _designer_media_has_references(asset):
        return False
    try:
        _delete_private_storage_object(
            provider=asset.provider,
            stored_key=asset.provider_asset_id,
        )
    except (ProductionStorageUnavailable, BotoCoreError, ClientError, OSError):
        return False
    asset.delete()
    return True


def create_private_designer_asset(*, upload, owner, organization, purpose="technical"):
    if not getattr(owner, "is_authenticated", False):
        raise ValidationError("Authentication is required before uploading Designer files.")
    if organization.kind != Organization.Kind.DESIGNER:
        raise ValidationError("Designer private assets require a Designer organization.")
    require_org_access(owner, organization)
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
        try:
            stored_key = default_storage.save(key, ContentFile(payload))
        except OSError as exc:
            raise ProductionStorageUnavailable(_SAFE_STORAGE_ERROR) from exc
        provider = MediaAsset.Provider.LOCAL_DEV
    else:
        integration = active_provider(IntegrationConfig.Provider.AMAZON_S3)
        bucket = (integration.config or {}).get("bucket", "")
        if not bucket:
            raise ProductionStorageUnavailable(_SAFE_STORAGE_ERROR)
        try:
            _s3_client(integration).put_object(
                Bucket=bucket,
                Key=key,
                Body=payload,
                ContentType=mime_type,
                CacheControl="private, no-store",
            )
        except (BotoCoreError, ClientError) as exc:
            raise ProductionStorageUnavailable(_SAFE_STORAGE_ERROR) from exc
        stored_key = key
        provider = MediaAsset.Provider.AMAZON_S3

    try:
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
    except DatabaseError:
        try:
            _delete_private_storage_object(provider=provider, stored_key=stored_key)
        except (ProductionStorageUnavailable, BotoCoreError, ClientError, OSError):
            pass
        raise
