"""Designer public images through the existing Cloudflare Images integration."""

import hashlib
import json
import logging
import re
from urllib.parse import quote, urlsplit

import requests
from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import DatabaseError, transaction
from django.views.decorators.debug import sensitive_variables

from apps.audit.services import record_audit_event
from apps.integrations.models import IntegrationConfig
from apps.organizations.models import Membership, Organization
from apps.organizations.services import require_org_access
from .manufacturer_public_services import validate_public_image
from .models import MediaAsset

logger = logging.getLogger(__name__)
SAFE_ERROR = "Public image upload is unavailable. Please try again later. / رفع الصورة العامة غير متاح. يرجى المحاولة لاحقاً."


def designer_public_image_eligible(asset, organization):
    """Return whether a PUBLIC image can safely belong to this Designer profile."""
    if (
        organization.kind != Organization.Kind.DESIGNER
        or not asset
        or asset.access != MediaAsset.Access.PUBLIC
        or not asset.mime_type.startswith("image/")
    ):
        return False
    metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
    if "organization_id" in metadata:
        return str(metadata["organization_id"]) == str(organization.pk)
    if metadata.get("designer_public_upload") or metadata.get("manufacturer_public_upload"):
        return False

    # Legacy PUBLIC assets predate organization metadata. Preserve selection only
    # when the uploader belongs actively to this organization and to no other
    # professional organization, avoiding cross-organization ambiguity.
    memberships = Membership.objects.filter(
        user_id=asset.uploaded_by_id,
        is_active=True,
        organization__kind__in=[Organization.Kind.DESIGNER, Organization.Kind.MANUFACTURER],
    )
    return memberships.filter(organization=organization).exists() and not memberships.exclude(
        organization=organization
    ).exists()


def _delivery_url(variants):
    if isinstance(variants, list):
        for value in variants:
            if not isinstance(value, str) or any(c.isspace() for c in value) or "\\" in value:
                continue
            try:
                url = urlsplit(value)
            except ValueError:
                continue
            if (
                url.scheme == "https"
                and url.netloc == "imagedelivery.net"
                and url.path.count("/") >= 3
                and not url.query
                and not url.fragment
            ):
                return value
    raise ValidationError(SAFE_ERROR)


def _compensate(endpoint, image_id, headers, organization_id):
    try:
        response = requests.delete(
            f"{endpoint}/{quote(image_id, safe='')}",
            headers=headers,
            timeout=(5, 15),
            allow_redirects=False,
        )
        if not response.ok or response.json().get("success") is not True:
            raise ValueError
    except (requests.RequestException, ValueError, AttributeError):
        logger.error(
            "Designer image cleanup failed organization=%s image=%s",
            organization_id,
            image_id,
        )


@sensitive_variables("secrets", "token", "headers", "payload")
def create_designer_public_image(*, upload, organization, actor, purpose, request=None):
    if (
        organization.kind != Organization.Kind.DESIGNER
        or organization.verification_status != Organization.VerificationStatus.ACTIVE
    ):
        raise ValidationError(SAFE_ERROR)
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if purpose not in {"profile", "cover"}:
        raise ValidationError(SAFE_ERROR)

    payload, mime, extension, width, height = validate_public_image(upload)
    integration = IntegrationConfig.objects.filter(
        provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES,
        enabled=True,
    ).first()
    if not integration:
        raise ValidationError(SAFE_ERROR)
    try:
        account_id = integration.config.get("account_id", "")
        secrets = integration.get_secrets()
        token = secrets.get("api_token")
        if (
            not isinstance(account_id, str)
            or not re.fullmatch(r"[A-Za-z0-9]{32}", account_id)
            or not isinstance(token, str)
            or not token.strip()
        ):
            raise ValueError
    except (ImproperlyConfigured, InvalidToken, ValueError, TypeError, AttributeError):
        raise ValidationError(SAFE_ERROR) from None

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v1"
    headers = {"Authorization": f"Bearer {token}"}
    metadata = {
        "organization_id": organization.pk,
        "actor_id": actor.pk,
        "purpose": purpose,
        "designer_public_upload": True,
    }
    try:
        response = requests.post(
            endpoint,
            headers=headers,
            files={"file": (f"{purpose}.{extension}", payload, mime)},
            data={
                "requireSignedURLs": "false",
                "creator": str(actor.pk),
                "metadata": json.dumps(metadata),
            },
            timeout=(5, 30),
            allow_redirects=False,
        )
        body = response.json()
        result = body.get("result") or {}
        image_id = result.get("id")
        if (
            not response.ok
            or body.get("success") is not True
            or not isinstance(image_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,500}", image_id)
        ):
            raise ValueError
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        logger.warning(
            "Designer image upload failed organization=%s purpose=%s",
            organization.pk,
            purpose,
        )
        raise ValidationError(SAFE_ERROR) from None

    try:
        if result.get("requireSignedURLs") is not False:
            raise ValidationError(SAFE_ERROR)
        public_url = _delivery_url(result.get("variants"))
        with transaction.atomic():
            asset = MediaAsset.objects.create(
                provider=MediaAsset.Provider.CLOUDFLARE_IMAGES,
                provider_asset_id=image_id,
                original_filename=str(upload.name).replace("\\", "/").rsplit("/", 1)[-1][:255],
                mime_type=mime,
                size_bytes=len(payload),
                checksum_sha256=hashlib.sha256(payload).hexdigest(),
                access=MediaAsset.Access.PUBLIC,
                uploaded_by=actor,
                metadata={
                    **metadata,
                    "public_url": public_url,
                    "width": width,
                    "height": height,
                },
            )
            record_audit_event(
                actor=actor,
                action="designer.public_image.uploaded",
                instance=asset,
                metadata={
                    "organization_id": organization.pk,
                    "purpose": purpose,
                    "media_asset_id": asset.pk,
                },
                request=request,
            )
        return asset
    except (DatabaseError, ValidationError):
        _compensate(endpoint, image_id, headers, organization.pk)
        raise ValidationError(SAFE_ERROR) from None
