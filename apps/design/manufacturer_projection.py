from django.core.exceptions import PermissionDenied, ValidationError

from apps.organizations.models import Organization
from apps.organizations.services import user_has_org_access
from .models import DesignAsset, GarmentDesignVersion
from .services import evaluate_version_eligibility


def _asset_projection(row, *, include_private):
    media = row.media_asset
    if media.access == media.Access.PRIVATE and not include_private:
        return None
    return {
        "asset_id": row.pk,
        "symbolic_ref": row.symbolic_ref,
        "kind": row.kind,
        "role": row.technical_role,
        "size_label": row.size_label,
        "access": media.access,
        "mime_type": media.mime_type,
        "size_bytes": media.size_bytes,
        "sha256": media.checksum_sha256,
        "reference_only": row.reference_only,
    }


def manufacturer_technical_projection(*, version, manufacturer_organization, actor):
    """Read-only manufacturing projection of the canonical GDV.

    This deliberately returns a projection, not a persisted Manufacturer Tech Pack.
    Private asset metadata is exposed only to staff or an authenticated member of the
    supplied active Manufacturer organization. URLs/provider object keys are not exposed.
    """
    if not isinstance(version, GarmentDesignVersion):
        raise ValidationError("A Garment Design Version is required.")
    if manufacturer_organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Manufacturer technical projection requires a Manufacturer organization.")
    if manufacturer_organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise PermissionDenied("An active Manufacturer organization is required.")
    authorized = bool(actor and actor.is_authenticated and (actor.is_staff or user_has_org_access(actor, manufacturer_organization)))
    if not authorized:
        raise PermissionDenied("Manufacturer technical access denied.")

    provenance = getattr(version, "reference_provenance", None)
    package = provenance.package if provenance else None
    private_assets = []
    public_assets = []
    for row in version.assets.select_related("media_asset").all():
        projected = _asset_projection(row, include_private=True)
        if row.media_asset.access == row.media_asset.Access.PRIVATE:
            private_assets.append(projected)
        else:
            public_assets.append(projected)

    return {
        "projection_contract": "FABINZI_MANUFACTURER_GDV_PROJECTION_V2_4",
        "design_id": version.design_id,
        "design_ref": version.design.symbolic_ref,
        "gdv_id": version.pk,
        "gdv_ref": version.symbolic_ref,
        "gdv_status": version.status,
        "same_gdv_invariant": True,
        "source_reference": {
            "dataset": package.dataset.dataset_name if package else None,
            "dataset_version": package.dataset.dataset_version if package else None,
            "product_ref": package.product_ref if package else None,
            "package_sha256": package.package_sha256 if package else None,
        },
        "product_class": version.product_class,
        "size_system": version.size_system,
        "sizes": [
            {
                "id": row.pk,
                "label": row.size_label,
                "measurements": row.measurements,
                "pom_values": [
                    {"pom_ref": value.point.symbolic_ref, "name": value.point.name, "unit": value.point.unit, "value": str(value.value)}
                    for value in row.pom_values.select_related("point").all()
                ],
            }
            for row in version.size_rows.all()
        ],
        "materials": [
            {"ref": row.symbolic_ref, "role": row.role, "name": row.name, "composition": row.composition, "gsm": str(row.gsm) if row.gsm is not None else None, "specifications": row.specifications}
            for row in version.materials.all()
        ],
        "construction": version.construction_notes,
        "technical_specs": version.technical_specs,
        "qc_requirements": version.qc_requirements,
        "colorways": [
            {"ref": row.symbolic_ref, "name": row.name, "hex_color": row.hex_color, "image_roles": list(row.images.values_list("role", flat=True))}
            for row in version.colorways.all()
        ],
        "decoration_applicability": version.decoration_applicability,
        "decoration_zones": [
            {
                "id": zone.pk,
                "ref": zone.symbolic_ref,
                "name": zone.name,
                "surface": zone.surface,
                "geometry": zone.placement,
                "max_width_mm": str(zone.max_width_mm) if zone.max_width_mm is not None else None,
                "max_height_mm": str(zone.max_height_mm) if zone.max_height_mm is not None else None,
                "allowed_methods": zone.effective_methods(),
                "minimum_dpi": zone.minimum_dpi,
                "embroidery_constraints": zone.embroidery_constraints,
                "reference_only": zone.reference_only,
            }
            for zone in version.decoration_zones.all()
        ],
        "pattern_requirements": [
            {
                "size_label": row.size.size_label,
                "required": row.required,
                "declared_scale_1_to_1": row.declared_scale_1_to_1,
                "asset_id": row.pattern_asset_id,
            }
            for row in version.pattern_requirements.select_related("size").all()
        ],
        "assets": {"public": public_assets, "authorized_private": private_assets},
        "technical_blockers": [
            {"code": row.code, "description": row.description, "status": row.status, "reference_only": row.reference_only}
            for row in version.technical_blockers.all()
        ],
        "eligibility": evaluate_version_eligibility(version),
    }
