"""Designer public images through the existing Cloudflare Images integration."""

import hashlib
import json
import logging
import re
from urllib.parse import quote, urlsplit

import requests
from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
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
STORE_PRODUCT_PURPOSE = "store_product_image"
STORE_EDIT_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGN_MANAGER]


def _metadata(asset):
    return asset.metadata if asset and isinstance(asset.metadata, dict) else {}


def designer_store_product_image_eligible(asset, organization, product):
    """Return whether a PUBLIC image is explicitly bound to this Designer Store product."""
    if (
        organization.kind != Organization.Kind.DESIGNER
        or not product
        or product.storefront.organization_id != organization.pk
        or not asset
        or asset.access != MediaAsset.Access.PUBLIC
        or not asset.mime_type.startswith("image/")
    ):
        return False
    metadata = _metadata(asset)
    return bool(
        metadata.get("designer_store_product_upload") is True
        and metadata.get("purpose") == STORE_PRODUCT_PURPOSE
        and str(metadata.get("organization_id", "")) == str(organization.pk)
        and str(metadata.get("store_product_id", "")) == str(product.pk)
    )


def designer_public_image_eligible(asset, organization):
    """Return whether a PUBLIC image can safely belong to this Designer profile."""
    if (
        organization.kind != Organization.Kind.DESIGNER
        or not asset
        or asset.access != MediaAsset.Access.PUBLIC
        or not asset.mime_type.startswith("image/")
    ):
        return False
    metadata = _metadata(asset)
    # Phase 6 Store-product photography is a distinct public-media purpose and
    # must never become selectable as a Designer Profile/Cover image merely
    # because it carries the same organization_id.
    if metadata.get("designer_store_product_upload") is True or metadata.get("purpose") == STORE_PRODUCT_PURPOSE:
        return False
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
        # Provider identifiers and credentials stay out of logs. The organization
        # scope is sufficient for operator correlation with the surrounding audit.
        logger.error("Designer image cleanup failed organization=%s", organization_id)
        return False
    return True


def _provider_context():
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
    return (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v1",
        {"Authorization": f"Bearer {token}"},
    )


@sensitive_variables("headers", "payload")
def _create_provider_image(*, payload, mime, extension, actor, metadata, purpose, organization_id):
    endpoint, headers = _provider_context()
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
        logger.warning("Designer image upload failed organization=%s purpose=%s", organization_id, purpose)
        raise ValidationError(SAFE_ERROR) from None

    try:
        if result.get("requireSignedURLs") is not False:
            raise ValidationError(SAFE_ERROR)
        public_url = _delivery_url(result.get("variants"))
    except ValidationError:
        _compensate(endpoint, image_id, headers, organization_id)
        raise
    return endpoint, headers, image_id, public_url


def _public_media_asset(*, upload, payload, mime, width, height, image_id, public_url, actor, metadata):
    return MediaAsset(
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


@sensitive_variables("payload")
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
    metadata = {
        "organization_id": organization.pk,
        "actor_id": actor.pk,
        "purpose": purpose,
        "designer_public_upload": True,
    }
    endpoint, headers, image_id, public_url = _create_provider_image(
        payload=payload,
        mime=mime,
        extension=extension,
        actor=actor,
        metadata=metadata,
        purpose=purpose,
        organization_id=organization.pk,
    )

    try:
        with transaction.atomic():
            asset = _public_media_asset(
                upload=upload,
                payload=payload,
                mime=mime,
                width=width,
                height=height,
                image_id=image_id,
                public_url=public_url,
                actor=actor,
                metadata=metadata,
            )
            asset.save()
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


@sensitive_variables("payload")
def create_designer_store_product_image(*, upload, product, organization, actor, alt_en="", alt_ar="", request=None):
    """Upload, classify and attach genuine Store-product photography atomically."""
    from apps.storefront.models import StoreProduct
    from apps.storefront.services import add_product_image

    if (
        organization.kind != Organization.Kind.DESIGNER
        or organization.verification_status != Organization.VerificationStatus.ACTIVE
    ):
        raise ValidationError(SAFE_ERROR)
    require_org_access(actor, organization, roles=STORE_EDIT_ROLES)
    current = StoreProduct.objects.select_related("storefront__organization").filter(
        pk=product.pk,
        storefront__organization=organization,
    ).first()
    if current is None or current.status not in {StoreProduct.Status.DRAFT, StoreProduct.Status.HIDDEN}:
        raise ValidationError(
            "Hide the published product before changing public product images. / أخفِ المنتج المنشور قبل تغيير صور المنتج العامة."
        )

    # Actual-byte validation and all authorization/state checks happen before the
    # first provider request.
    payload, mime, extension, width, height = validate_public_image(upload)
    checksum = hashlib.sha256(payload).hexdigest()
    metadata = {
        "organization_id": organization.pk,
        "store_product_id": current.pk,
        "actor_id": actor.pk,
        "purpose": STORE_PRODUCT_PURPOSE,
        "designer_store_product_upload": True,
        "validated_format": extension,
        "width": width,
        "height": height,
        "checksum_sha256": checksum,
    }
    endpoint, headers, image_id, public_url = _create_provider_image(
        payload=payload,
        mime=mime,
        extension=extension,
        actor=actor,
        metadata=metadata,
        purpose=STORE_PRODUCT_PURPOSE,
        organization_id=organization.pk,
    )

    try:
        with transaction.atomic():
            locked = StoreProduct.objects.select_for_update().select_related("storefront__organization").get(pk=current.pk)
            if (
                locked.storefront.organization_id != organization.pk
                or locked.status not in {StoreProduct.Status.DRAFT, StoreProduct.Status.HIDDEN}
            ):
                raise ValidationError(
                    "The product changed while the image was uploading. Try again after hiding the product. / تغيّرت حالة المنتج أثناء رفع الصورة. حاول مرة أخرى بعد إخفاء المنتج."
                )
            asset = _public_media_asset(
                upload=upload,
                payload=payload,
                mime=mime,
                width=width,
                height=height,
                image_id=image_id,
                public_url=public_url,
                actor=actor,
                metadata=metadata,
            )
            asset.checksum_sha256 = checksum
            asset.save()
            image = add_product_image(
                product=locked,
                actor=actor,
                media_asset=asset,
                alt_en=alt_en,
                alt_ar=alt_ar,
                request=request,
            )
            record_audit_event(
                actor=actor,
                action="designer.store_product_image.uploaded",
                instance=image,
                metadata={
                    "organization_id": organization.pk,
                    "store_product_id": locked.pk,
                    "media_asset_id": asset.pk,
                },
                request=request,
            )
        return asset, image
    except Exception:
        # After the provider has accepted the image, every database/attachment/
        # ordering/audit failure must leave local state rolled back and attempt
        # provider compensation. The Designer receives only the controlled error.
        _compensate(endpoint, image_id, headers, organization.pk)
        raise ValidationError(SAFE_ERROR) from None
