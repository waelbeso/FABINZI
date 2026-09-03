from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from .models import (
    DecorationZone,
    DesignAsset,
    DesignColorway,
    DesignColorwayImage,
    DesignMaterial,
    DesignPOMValue,
    DesignPatternRequirement,
    DesignPointOfMeasure,
    GarmentDesignVersion,
)
from .services import evaluate_version_eligibility, require_draft, technical_completeness


def _decimal_or_none(value, field):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field: "Enter a valid decimal value."}) from exc


def _int_or_none(value, field):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: "Enter a valid integer value."}) from exc


@transaction.atomic
def save_version_policy(
    *, version, actor, product_class, size_system, decoration_applicability,
    requires_3d_source, qc_requirements, technical_policy=None, request=None,
):
    require_draft(version, actor)
    if product_class not in dict(GarmentDesignVersion.ProductClass.choices):
        raise ValidationError({"product_class": "Unsupported product class."})
    if size_system not in dict(GarmentDesignVersion.SizeSystem.choices):
        raise ValidationError({"size_system": "Unsupported size system."})
    if decoration_applicability not in dict(GarmentDesignVersion.DecorationApplicability.choices):
        raise ValidationError({"decoration_applicability": "Unsupported Decoration applicability."})
    if decoration_applicability == GarmentDesignVersion.DecorationApplicability.NOT_APPLICABLE and version.decoration_zones.exists():
        raise ValidationError("Remove existing Decoration Zones before declaring Decoration not applicable.")
    version.product_class = product_class
    version.size_system = size_system
    version.decoration_applicability = decoration_applicability
    version.requires_3d_source = bool(requires_3d_source)
    version.qc_requirements = qc_requirements or {}
    if technical_policy is not None:
        version.technical_policy = technical_policy or {}
    version.full_clean()
    version.save(update_fields=["product_class", "size_system", "decoration_applicability", "requires_3d_source", "qc_requirements", "technical_policy"])
    record_audit_event(actor=actor, action="design.version.technical_policy.updated", instance=version, metadata={"design_id": version.design_id}, request=request)
    return version


@transaction.atomic
def save_point_of_measure(
    *, version, actor, point=None, symbolic_ref, name, unit, tolerance_plus=None,
    tolerance_minus=None, required=True, sort_order=0, request=None,
):
    require_draft(version, actor)
    if point and point.version_id != version.pk:
        raise ValidationError("POM does not belong to this Garment Design Version.")
    if unit not in dict(DesignPointOfMeasure.Unit.choices):
        raise ValidationError({"unit": "Unsupported measurement unit."})
    point = point or DesignPointOfMeasure(version=version)
    point.symbolic_ref = str(symbolic_ref or "").strip()
    point.name = str(name or "").strip()
    point.unit = unit
    point.tolerance_plus = _decimal_or_none(tolerance_plus, "tolerance_plus")
    point.tolerance_minus = _decimal_or_none(tolerance_minus, "tolerance_minus")
    point.required = bool(required)
    point.sort_order = int(sort_order or 0)
    point.full_clean(); point.save()
    record_audit_event(actor=actor, action="design.pom.saved", instance=point, metadata={"gdv_id": version.pk}, request=request)
    return point


@transaction.atomic
def save_pom_value(*, point, size, actor, value, request=None):
    version = point.version
    require_draft(version, actor)
    if size.version_id != version.pk:
        raise ValidationError("POM value size must belong to the same Garment Design Version.")
    decimal_value = _decimal_or_none(value, "value")
    if decimal_value is None:
        raise ValidationError({"value": "POM value is required."})
    obj, _ = DesignPOMValue.objects.update_or_create(point=point, size=size, defaults={"value": decimal_value})
    obj.full_clean(); obj.save()
    record_audit_event(actor=actor, action="design.pom_value.saved", instance=obj, metadata={"gdv_id": version.pk}, request=request)
    return obj


@transaction.atomic
def save_material(
    *, version, actor, material=None, symbolic_ref, role, name, composition="",
    gsm=None, specifications=None, sort_order=0, request=None,
):
    require_draft(version, actor)
    if material and material.version_id != version.pk:
        raise ValidationError("Material does not belong to this Garment Design Version.")
    material = material or DesignMaterial(version=version)
    material.symbolic_ref = str(symbolic_ref or "").strip()
    material.role = str(role or "").strip()
    material.name = str(name or "").strip()
    material.composition = str(composition or "").strip()
    material.gsm = _decimal_or_none(gsm, "gsm")
    material.specifications = specifications or {}
    material.sort_order = int(sort_order or 0)
    material.full_clean(); material.save()
    record_audit_event(actor=actor, action="design.material.saved", instance=material, metadata={"gdv_id": version.pk}, request=request)
    return material


@transaction.atomic
def save_pattern_requirement(
    *, version, actor, size, required=True, declared_scale_1_to_1=False,
    pattern_asset=None, notes="", request=None,
):
    require_draft(version, actor)
    if size.version_id != version.pk:
        raise ValidationError("Pattern requirement size does not belong to this Garment Design Version.")
    if pattern_asset:
        if pattern_asset.version_id != version.pk or pattern_asset.kind != DesignAsset.Kind.PATTERN:
            raise ValidationError("Pattern asset must be a Pattern on this Garment Design Version.")
        if pattern_asset.media_asset.access != pattern_asset.media_asset.Access.PRIVATE:
            raise ValidationError("Production Pattern assets must remain private.")
    requirement, _ = DesignPatternRequirement.objects.update_or_create(
        version=version, size=size,
        defaults={"required": bool(required), "declared_scale_1_to_1": bool(declared_scale_1_to_1), "pattern_asset": pattern_asset, "notes": str(notes or "").strip()},
    )
    requirement.full_clean(); requirement.save()
    record_audit_event(actor=actor, action="design.pattern_requirement.saved", instance=requirement, metadata={"gdv_id": version.pk}, request=request)
    return requirement


@transaction.atomic
def save_colorway(*, version, actor, colorway=None, symbolic_ref, name, hex_color="", sort_order=0, request=None):
    require_draft(version, actor)
    if colorway and colorway.version_id != version.pk:
        raise ValidationError("Colorway does not belong to this Garment Design Version.")
    colorway = colorway or DesignColorway(version=version)
    colorway.symbolic_ref = str(symbolic_ref or "").strip()
    colorway.name = str(name or "").strip()
    colorway.hex_color = str(hex_color or "").strip()
    colorway.sort_order = int(sort_order or 0)
    colorway.full_clean(); colorway.save()
    record_audit_event(actor=actor, action="design.colorway.saved", instance=colorway, metadata={"gdv_id": version.pk}, request=request)
    return colorway


@transaction.atomic
def attach_colorway_image(*, colorway, actor, asset, role, sort_order=0, request=None):
    version = colorway.version
    require_draft(version, actor)
    if role not in dict(DesignColorwayImage.Role.choices):
        raise ValidationError({"role": "Unsupported image role."})
    if asset.version_id != version.pk or asset.kind != DesignAsset.Kind.PRODUCT_IMAGE:
        raise ValidationError("Colorway images must use a Product Image asset on the same Garment Design Version.")
    row, _ = DesignColorwayImage.objects.update_or_create(colorway=colorway, role=role, asset=asset, defaults={"sort_order": int(sort_order or 0)})
    row.full_clean(); row.save()
    record_audit_event(actor=actor, action="design.colorway_image.attached", instance=row, metadata={"gdv_id": version.pk}, request=request)
    return row


@transaction.atomic
def save_decoration_zone_contract(
    *, version, actor, zone=None, symbolic_ref, name, surface, allowed_methods,
    placement, max_width_mm=None, max_height_mm=None, minimum_dpi=None,
    embroidery_constraints=None, notes="", request=None,
):
    require_draft(version, actor)
    if version.decoration_applicability == GarmentDesignVersion.DecorationApplicability.NOT_APPLICABLE:
        raise ValidationError("Decoration is explicitly NOT APPLICABLE for this Garment Design Version.")
    if zone and zone.version_id != version.pk:
        raise ValidationError("Decoration Zone does not belong to this Garment Design Version.")
    methods = list(dict.fromkeys(allowed_methods or []))
    valid_methods = {choice for choice, _ in DecorationZone.ProductionMethod.choices}
    if not methods or set(methods) - valid_methods:
        raise ValidationError({"allowed_methods": "Choose one or more supported production methods."})
    zone = zone or DecorationZone(version=version)
    zone.symbolic_ref = str(symbolic_ref or "").strip() or None
    zone.name = str(name or "").strip()
    zone.surface = str(surface or "").strip()
    zone.allowed_methods = methods
    zone.method = DecorationZone.Method.EMBROIDERY if methods == [DecorationZone.ProductionMethod.EMBROIDERY] else DecorationZone.Method.PRINT
    zone.placement = placement or {}
    zone.max_width_mm = _decimal_or_none(max_width_mm, "max_width_mm")
    zone.max_height_mm = _decimal_or_none(max_height_mm, "max_height_mm")
    zone.minimum_dpi = _int_or_none(minimum_dpi, "minimum_dpi")
    zone.embroidery_constraints = embroidery_constraints or {}
    zone.reference_only = False
    zone.notes = str(notes or "").strip()
    zone.full_clean(); zone.save()
    if version.decoration_applicability != GarmentDesignVersion.DecorationApplicability.CONFIGURED:
        version.decoration_applicability = GarmentDesignVersion.DecorationApplicability.CONFIGURED
        version.save(update_fields=["decoration_applicability"])
    record_audit_event(actor=actor, action="design.decoration_zone_contract.saved", instance=zone, metadata={"gdv_id": version.pk, "methods": methods}, request=request)
    return zone


def technical_workspace_state(version):
    completeness = technical_completeness(version)
    return {
        "technical_complete": completeness["complete"],
        "completeness_errors": completeness["errors"],
        "eligibility": evaluate_version_eligibility(version),
    }
