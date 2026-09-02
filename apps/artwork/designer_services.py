import math

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from apps.organizations.models import Membership
from apps.organizations.services import require_org_access
from .models import ArtworkAsset, ArtworkPlacement, DesignedProduct
from .services import require_artwork_draft


def normalize_designed_product_transform(transform):
    """Normalize the accepted legacy center/scale UI transform into canonical 0..1 geometry."""
    source = transform or {}
    if all(key in source for key in ("x", "y", "width", "height")):
        return dict(source)
    try:
        x = float(source.get("x", 0.5))
        y = float(source.get("y", 0.5))
        scale = float(source.get("scale", 0.35))
        rotation = float(source.get("rotation", 0))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Artwork placement contains invalid normalized values.") from exc
    if not all(math.isfinite(v) for v in (x, y, scale, rotation)):
        raise ValidationError("Artwork placement contains invalid normalized values.")
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValidationError("Artwork placement coordinates must stay between 0 and 1.")
    if not (0.05 <= scale <= 1):
        raise ValidationError("Artwork placement scale must stay between 0.05 and 1.")
    rotation = ((rotation + 180.0) % 360.0) - 180.0
    half_extent = (scale / 2.0) * (
        abs(math.cos(math.radians(rotation))) + abs(math.sin(math.radians(rotation)))
    )
    if x - half_extent < 0 or x + half_extent > 1 or y - half_extent < 0 or y + half_extent > 1:
        raise ValidationError("Artwork placement extends outside the selected Decoration Zone workspace.")
    return {
        "x": round(x - (scale / 2.0), 5),
        "y": round(y - (scale / 2.0), 5),
        "width": round(scale, 5),
        "height": round(scale, 5),
        "rotation": round(rotation, 3),
    }


@transaction.atomic
def update_artwork_definition(*, artwork, version, actor, data, request=None):
    require_artwork_draft(version, actor)
    if version.artwork_id != artwork.pk:
        raise ValidationError("Artwork Version does not belong to this Artwork.")
    for field in ("title", "description", "tags"):
        if field in data:
            setattr(artwork, field, data[field])
    artwork.full_clean()
    artwork.save()
    record_audit_event(
        actor=actor,
        action="artwork.updated",
        instance=artwork,
        metadata={"version_id": version.pk},
        request=request,
    )
    return artwork


@transaction.atomic
def update_artwork_version_definition(*, version, actor, data, request=None):
    require_artwork_draft(version, actor)
    for field in ("color_profile", "production_notes", "metadata"):
        if field in data:
            setattr(version, field, data[field])
    version.full_clean()
    version.save()
    record_audit_event(
        actor=actor,
        action="artwork.version.updated",
        instance=version,
        metadata={"artwork_id": version.artwork_id},
        request=request,
    )
    return version


@transaction.atomic
def delete_artwork_asset(*, asset, actor, request=None):
    require_artwork_draft(asset.version, actor)
    version = asset.version
    asset_id = asset.pk
    asset.delete()
    record_audit_event(
        actor=actor,
        action="artwork.asset.removed",
        instance=version,
        metadata={"asset_id": asset_id, "artwork_id": version.artwork_id},
        request=request,
    )


@transaction.atomic
def add_validated_product_placement(*, product, actor, decoration_zone, transform, production_method, request=None):
    require_org_access(
        actor,
        product.organization,
        roles=[Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGNER, Membership.Role.DESIGN_MANAGER],
    )
    if product.status != DesignedProduct.Status.DRAFT:
        raise ValidationError("Only draft Designed Products can be edited.")
    if decoration_zone.version_id != product.garment_version_id:
        raise ValidationError("Decoration Zone must belong to this product's Garment Design Version.")
    placement = ArtworkPlacement(
        product=product,
        decoration_zone=decoration_zone,
        transform=normalize_designed_product_transform(transform),
        production_method=production_method,
    )
    placement.full_clean()
    placement.save()
    record_audit_event(
        actor=actor,
        action="designed_product.placement.added",
        instance=placement,
        metadata={"product_id": product.pk, "zone_id": decoration_zone.pk},
        request=request,
    )
    return placement


@transaction.atomic
def delete_product_placement(*, placement, actor, request=None):
    require_org_access(
        actor,
        placement.product.organization,
        roles=[Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGNER, Membership.Role.DESIGN_MANAGER],
    )
    if placement.product.status != DesignedProduct.Status.DRAFT:
        raise ValidationError("Only draft Designed Products can be edited.")
    product = placement.product
    placement_id = placement.pk
    placement.delete()
    record_audit_event(
        actor=actor,
        action="designed_product.placement.removed",
        instance=product,
        metadata={"placement_id": placement_id},
        request=request,
    )
