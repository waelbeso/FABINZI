from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from .models import DecorationZone, DesignAsset, GarmentDesignVersion, SizeChartRow
from .services import require_draft


def _normalized_anchor(placement):
    placement = dict(placement or {})
    for key in ("x", "y"):
        if key in placement and placement[key] not in (None, ""):
            try:
                value = float(placement[key])
            except (TypeError, ValueError) as exc:
                raise ValidationError({"placement": f"{key.upper()} must be a normalized number."}) from exc
            if not 0 <= value <= 1:
                raise ValidationError({"placement": f"{key.upper()} must stay between 0 and 1."})
            placement[key] = round(value, 5)
    return placement


@transaction.atomic
def update_version_definition(*, version, actor, data, request=None):
    require_draft(version, actor)
    for field in ("summary", "base_material", "construction_notes", "technical_specs"):
        if field in data:
            setattr(version, field, data[field])
    version.full_clean()
    version.save()
    record_audit_event(
        actor=actor,
        action="design.version.updated",
        instance=version,
        metadata={"design_id": version.design_id},
        request=request,
    )
    return version


@transaction.atomic
def save_size_row(*, version, actor, row=None, size_label, measurements, notes="", sort_order=0, request=None):
    require_draft(version, actor)
    if row and row.version_id != version.pk:
        raise ValidationError("Size row does not belong to this Garment Design Version.")
    row = row or SizeChartRow(version=version)
    row.size_label = str(size_label or "").strip()
    row.measurements = measurements or {}
    row.notes = str(notes or "").strip()
    row.sort_order = int(sort_order or 0)
    row.full_clean()
    row.save()
    record_audit_event(
        actor=actor,
        action="design.size_row.saved",
        instance=row,
        metadata={"design_id": version.design_id, "version_id": version.pk},
        request=request,
    )
    return row


@transaction.atomic
def delete_size_row(*, row, actor, request=None):
    require_draft(row.version, actor)
    version = row.version
    row_id = row.pk
    row.delete()
    record_audit_event(
        actor=actor,
        action="design.size_row.removed",
        instance=version,
        metadata={"row_id": row_id, "design_id": version.design_id},
        request=request,
    )


@transaction.atomic
def save_decoration_zone(*, version, actor, zone=None, name, method, placement, max_width_mm=None, max_height_mm=None, notes="", request=None):
    require_draft(version, actor)
    if zone and zone.version_id != version.pk:
        raise ValidationError("Decoration Zone does not belong to this Garment Design Version.")
    zone = zone or DecorationZone(version=version)
    zone.name = str(name or "").strip()
    zone.method = method
    zone.placement = _normalized_anchor(placement)
    zone.max_width_mm = max_width_mm or None
    zone.max_height_mm = max_height_mm or None
    zone.notes = str(notes or "").strip()
    zone.full_clean()
    zone.save()
    record_audit_event(
        actor=actor,
        action="design.decoration_zone.saved",
        instance=zone,
        metadata={"design_id": version.design_id, "version_id": version.pk},
        request=request,
    )
    return zone


@transaction.atomic
def delete_decoration_zone(*, zone, actor, request=None):
    require_draft(zone.version, actor)
    version = zone.version
    zone_id = zone.pk
    try:
        zone.delete()
    except Exception as exc:
        if exc.__class__.__name__ == "ProtectedError":
            raise ValidationError("This Decoration Zone is already referenced and cannot be removed.") from exc
        raise
    record_audit_event(
        actor=actor,
        action="design.decoration_zone.removed",
        instance=version,
        metadata={"zone_id": zone_id, "design_id": version.design_id},
        request=request,
    )


@transaction.atomic
def delete_design_asset(*, asset, actor, request=None):
    require_draft(asset.version, actor)
    version = asset.version
    asset_id = asset.pk
    asset.delete()
    record_audit_event(
        actor=actor,
        action="design.asset.removed",
        instance=version,
        metadata={"asset_id": asset_id, "design_id": version.design_id},
        request=request,
    )
