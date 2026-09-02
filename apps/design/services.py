from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.media.designer_services import claim_or_require_private_designer_asset
from apps.notifications.models import Notification
from apps.organizations.models import Membership, Organization
from apps.organizations.services import require_org_access, user_has_org_access
from .models import (
    DecorationZone,
    DesignAsset,
    DesignColorway,
    DesignColorwayImage,
    DesignMaterial,
    DesignPatternRequirement,
    DesignPointOfMeasure,
    DesignPOMValue,
    GarmentDesign,
    GarmentDesignVersion,
    SizeChartRow,
    TechnicalBlocker,
    TechnicalReview,
)

DESIGN_EDIT_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGNER, Membership.Role.DESIGN_MANAGER]
DESIGN_MANAGE_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGN_MANAGER]


def user_can_view_design(user, design):
    return bool(user and user.is_authenticated and (user.is_staff or user_has_org_access(user, design.organization)))


def require_design_access(user, design, *, edit=False):
    if user.is_staff and not edit:
        return True
    roles = DESIGN_EDIT_ROLES if edit else None
    return require_org_access(user, design.organization, roles=roles)


def _require_active_designer_org(organization):
    if organization.kind != Organization.Kind.DESIGNER or organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("An approved active Designer business is required.")


@transaction.atomic
def create_design(*, organization, actor, title, description="", category="", request=None):
    _require_active_designer_org(organization)
    require_org_access(actor, organization, roles=DESIGN_EDIT_ROLES)
    design = GarmentDesign(organization=organization, title=title, description=description, category=category, created_by=actor)
    design.full_clean()
    design.save()
    version = GarmentDesignVersion.objects.create(design=design, version_number=1, created_by=actor)
    record_audit_event(actor=actor, action="design.created", instance=design, metadata={"organization_id": organization.pk, "version_id": version.pk}, request=request)
    record_audit_event(actor=actor, action="design.version.created", instance=version, metadata={"design_id": design.pk, "version_number": 1}, request=request)
    return design


@transaction.atomic
def create_revision(*, design, actor, request=None):
    require_design_access(actor, design, edit=True)
    latest = design.versions.order_by("-version_number").first()
    if latest and latest.status not in {GarmentDesignVersion.Status.REVISION_REQUIRED, GarmentDesignVersion.Status.APPROVED, GarmentDesignVersion.Status.REJECTED}:
        raise ValidationError("A new revision can only follow a reviewed version.")
    number = (design.versions.aggregate(m=Max("version_number"))["m"] or 0) + 1
    version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=number,
        created_by=actor,
        summary=f"Revision {number}",
        base_material=latest.base_material if latest else "",
        construction_notes=latest.construction_notes if latest else "",
        technical_specs=latest.technical_specs if latest else {},
        technical_schema_version=latest.technical_schema_version if latest else "2.4",
        product_class=latest.product_class if latest else GarmentDesignVersion.ProductClass.APPAREL,
        size_system=latest.size_system if latest else GarmentDesignVersion.SizeSystem.MULTI_SIZE,
        decoration_applicability=latest.decoration_applicability if latest else GarmentDesignVersion.DecorationApplicability.UNDECLARED,
        requires_3d_source=latest.requires_3d_source if latest else True,
        technical_policy=latest.technical_policy if latest else {},
        qc_requirements=latest.qc_requirements if latest else {},
    )
    if latest:
        size_map = {}
        for row in latest.size_rows.all():
            size_map[row.pk] = SizeChartRow.objects.create(version=version, size_label=row.size_label, measurements=row.measurements, notes=row.notes, sort_order=row.sort_order)
        asset_map = {}
        for row in latest.assets.all():
            asset_map[row.pk] = DesignAsset.objects.create(
                version=version,
                kind=row.kind,
                media_asset=row.media_asset,
                label=row.label,
                technical_role=row.technical_role,
                size_label=row.size_label,
                reference_only=row.reference_only,
            )
        pom_map = {}
        for point in latest.points_of_measure.all():
            pom_map[point.pk] = DesignPointOfMeasure.objects.create(
                version=version,
                symbolic_ref=point.symbolic_ref,
                name=point.name,
                unit=point.unit,
                tolerance_plus=point.tolerance_plus,
                tolerance_minus=point.tolerance_minus,
                required=point.required,
                sort_order=point.sort_order,
            )
        for point in latest.points_of_measure.all():
            for value in point.values.all():
                DesignPOMValue.objects.create(point=pom_map[point.pk], size=size_map[value.size_id], value=value.value)
        for material in latest.materials.all():
            DesignMaterial.objects.create(version=version, symbolic_ref=material.symbolic_ref, role=material.role, name=material.name, composition=material.composition, gsm=material.gsm, specifications=material.specifications, sort_order=material.sort_order)
        for req in latest.pattern_requirements.all():
            DesignPatternRequirement.objects.create(version=version, size=size_map[req.size_id], required=req.required, declared_scale_1_to_1=req.declared_scale_1_to_1, pattern_asset=asset_map.get(req.pattern_asset_id), notes=req.notes)
        colorway_map = {}
        for colorway in latest.colorways.all():
            colorway_map[colorway.pk] = DesignColorway.objects.create(version=version, symbolic_ref=colorway.symbolic_ref, name=colorway.name, hex_color=colorway.hex_color, sort_order=colorway.sort_order)
        for colorway in latest.colorways.all():
            for image in colorway.images.all():
                DesignColorwayImage.objects.create(colorway=colorway_map[colorway.pk], asset=asset_map[image.asset_id], role=image.role, sort_order=image.sort_order)
        for zone in latest.decoration_zones.all():
            DecorationZone.objects.create(version=version, name=zone.name, surface=zone.surface, method=zone.method, allowed_methods=zone.allowed_methods, placement=zone.placement, max_width_mm=zone.max_width_mm, max_height_mm=zone.max_height_mm, minimum_dpi=zone.minimum_dpi, embroidery_constraints=zone.embroidery_constraints, reference_only=zone.reference_only, notes=zone.notes)
        for blocker in latest.technical_blockers.filter(status=TechnicalBlocker.Status.OPEN):
            TechnicalBlocker.objects.create(version=version, code=blocker.code, description=blocker.description, reference_only=blocker.reference_only)
    design.status = GarmentDesign.Status.DRAFT
    design.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="design.revision.created", instance=version, metadata={"design_id": design.pk, "version_number": number}, request=request)
    return version


def _completeness_errors(version):
    errors = []
    if not version.base_material:
        errors.append("Base material is required.")
    if not version.construction_notes:
        errors.append("Construction information is required.")
    if not version.technical_specs:
        errors.append("Technical specifications are required.")
    if not version.qc_requirements:
        errors.append("QC/reference requirements are required.")

    sizes = list(version.size_rows.all())
    if not sizes:
        errors.append("At least one declared size is required.")
    elif version.size_system in {GarmentDesignVersion.SizeSystem.ONE_SIZE, GarmentDesignVersion.SizeSystem.ONE_SIZE_ACCESSORY} and len(sizes) != 1:
        errors.append("ONE_SIZE systems must declare exactly one size row.")

    required_points = list(version.points_of_measure.filter(required=True))
    if not required_points:
        errors.append("At least one required Point of Measure is required.")
    for point in required_points:
        covered_size_ids = set(point.values.values_list("size_id", flat=True))
        missing = [size.size_label for size in sizes if size.pk not in covered_size_ids]
        if missing:
            errors.append(f"POM {point.symbolic_ref} is missing values for: {', '.join(missing)}.")

    for size in sizes:
        requirement = version.pattern_requirements.filter(size=size, required=True).select_related("pattern_asset__media_asset").first()
        if requirement is None or requirement.pattern_asset_id is None:
            errors.append(f"A production Pattern is required for size {size.size_label}.")
        elif not requirement.declared_scale_1_to_1:
            errors.append(f"Pattern scale declaration is required for size {size.size_label}.")
        elif requirement.pattern_asset.media_asset.access != requirement.pattern_asset.media_asset.Access.PRIVATE:
            errors.append(f"Pattern for size {size.size_label} must remain private.")

    if version.requires_3d_source and not version.assets.filter(kind=DesignAsset.Kind.THREE_D, media_asset__access="private").exists():
        errors.append("A private 3D/source asset is required by this technical policy.")
    if not version.assets.filter(kind=DesignAsset.Kind.TECH_PACK, media_asset__access="private").exists():
        errors.append("A private Tech Pack is required.")
    if not version.assets.filter(kind=DesignAsset.Kind.TECHNICAL, media_asset__access="private").exists():
        errors.append("At least one private technical source file is required.")

    colorways = list(version.colorways.all())
    if not colorways:
        errors.append("At least one colorway is required.")
    for colorway in colorways:
        if not colorway.images.filter(asset__kind=DesignAsset.Kind.PRODUCT_IMAGE).exists():
            errors.append(f"Colorway {colorway.name} requires at least one product image.")

    if not version.materials.exists():
        errors.append("Structured material/BOM data is required.")

    if version.decoration_applicability == GarmentDesignVersion.DecorationApplicability.UNDECLARED:
        errors.append("Decoration applicability must be explicitly configured or marked not applicable.")
    elif version.decoration_applicability == GarmentDesignVersion.DecorationApplicability.CONFIGURED:
        if not version.decoration_zones.exists():
            errors.append("At least one Decoration Zone is required when decoration is configured.")
        for zone in version.decoration_zones.all():
            if not zone.effective_methods():
                errors.append(f"Decoration Zone {zone.name} has no allowed production method.")
            try:
                zone.full_clean()
            except ValidationError:
                errors.append(f"Decoration Zone {zone.name} is invalid.")
    elif version.decoration_zones.exists():
        errors.append("Decoration Zones must not exist when decoration is explicitly not applicable.")

    if version.technical_blockers.filter(status=TechnicalBlocker.Status.OPEN, reference_only=False).exists():
        errors.append("Unresolved production technical blockers remain open.")
    return errors


def technical_completeness(version):
    errors = _completeness_errors(version)
    return {"complete": not errors, "errors": errors}


def design_submission_readiness(version):
    """Historical Design review readiness, deliberately separate from production completeness."""
    errors = []
    if not version.base_material:
        errors.append("Base material is required.")
    if not version.technical_specs:
        errors.append("Technical specifications are required.")
    if not version.size_rows.exists():
        errors.append("At least one size-chart row is required.")
    if not version.assets.filter(kind=DesignAsset.Kind.TECH_PACK, media_asset__access="private").exists():
        errors.append("A private tech pack is required.")
    if not version.assets.filter(kind=DesignAsset.Kind.PRODUCT_IMAGE).exists():
        errors.append("At least one product image is required.")
    return {"ready": not errors, "errors": errors}


def validate_version_ready(version):
    result = design_submission_readiness(version)
    if not result["ready"]:
        raise ValidationError(result["errors"])
    return result


def _validate_production_completeness(version):
    result = technical_completeness(version)
    if not result["complete"]:
        raise ValidationError(result["errors"])
    return result


def evaluate_version_eligibility(version):
    provenance = getattr(version, "reference_provenance", None)
    package = provenance.package if provenance else None
    completeness = technical_completeness(version)
    technical_approved = version.status == GarmentDesignVersion.Status.APPROVED
    open_blockers = version.technical_blockers.filter(status=TechnicalBlocker.Status.OPEN).exists()
    reference_approved = bool(package and package.status == package.Status.APPROVED_REFERENCE)
    is_frozen_reference = bool(package and package.synthetic_reference)
    commercial_eligible = bool(technical_approved and completeness["complete"] and not open_blockers and not is_frozen_reference)
    production_eligible = bool(commercial_eligible and version.production_engineering_validated)
    if package and not package.production_engineering_validated:
        production_eligible = False
    return {
        "reference_approved": reference_approved,
        "technical_complete": completeness["complete"],
        "technical_approved": technical_approved,
        "commercial_eligible": commercial_eligible,
        "production_eligible": production_eligible,
        "production_engineering_validated": bool(version.production_engineering_validated),
        "blockers": completeness["errors"],
    }


@transaction.atomic
def submit_version(*, version, actor, request=None):
    require_design_access(actor, version.design, edit=True)
    if version.status != GarmentDesignVersion.Status.DRAFT:
        raise ValidationError("Only draft versions can be submitted.")
    validate_version_ready(version)

    from apps.subscriptions.services import assert_designer_slot_available

    assert_designer_slot_available(
        organization=version.design.organization,
        kind="design",
        object_id=version.design_id,
    )

    version.status = GarmentDesignVersion.Status.SUBMITTED
    version.submitted_at = timezone.now()
    version.save(update_fields=["status", "submitted_at"])
    version.design.status = GarmentDesign.Status.IN_REVIEW
    version.design.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="design.version.submitted", instance=version, metadata={"design_id": version.design_id, "technical_schema_version": version.technical_schema_version}, request=request)
    return version


@transaction.atomic
def review_version(*, version, reviewer, decision, notes="", request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if version.status != GarmentDesignVersion.Status.SUBMITTED:
        raise ValidationError("Only submitted versions can be reviewed.")
    if decision not in dict(TechnicalReview.Decision.choices):
        raise ValidationError("Unsupported technical review decision.")
    TechnicalReview.objects.create(version=version, reviewer=reviewer, decision=decision, notes=notes)
    version.status = decision
    version.reviewed_at = timezone.now()
    version.reviewed_by = reviewer
    version.review_notes = notes
    version.save(update_fields=["status", "reviewed_at", "reviewed_by", "review_notes"])
    design_status = {
        TechnicalReview.Decision.APPROVED: GarmentDesign.Status.APPROVED,
        TechnicalReview.Decision.REVISION_REQUIRED: GarmentDesign.Status.REVISION_REQUIRED,
        TechnicalReview.Decision.REJECTED: GarmentDesign.Status.REJECTED,
    }[decision]
    version.design.status = design_status
    version.design.save(update_fields=["status", "updated_at"])
    title_en = {"approved": "Garment design approved", "revision_required": "Garment design needs revision", "rejected": "Garment design rejected"}[decision]
    title_ar = {"approved": "تم اعتماد تصميم القطعة", "revision_required": "تصميم القطعة يحتاج إلى تعديلات", "rejected": "تم رفض تصميم القطعة"}[decision]
    for membership in version.design.organization.memberships.filter(is_active=True).select_related("user"):
        Notification.objects.create(recipient=membership.user, type="garment_design_review", title_en=title_en, title_ar=title_ar, body_en=notes, body_ar=notes, destination=f"/designer/designs/{version.design_id}/")
    record_audit_event(actor=reviewer, action=f"design.version.{decision}", instance=version, metadata={"design_id": version.design_id, "notes_present": bool(notes), "eligibility": evaluate_version_eligibility(version)}, request=request)
    return version


@transaction.atomic
def set_production_engineering_validation(*, version, reviewer, validated, notes="", request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if validated and version.status != GarmentDesignVersion.Status.APPROVED:
        raise ValidationError("Technical approval is required before production engineering validation.")
    if validated:
        _validate_production_completeness(version)
        if getattr(version, "reference_provenance", None) and not version.reference_provenance.package.production_engineering_validated:
            raise ValidationError("Frozen Golden reference packages cannot be production-validated through ordinary workflow.")
    version.production_engineering_validated = bool(validated)
    version.production_engineering_notes = notes
    version.save(update_fields=["production_engineering_validated", "production_engineering_notes"])
    record_audit_event(actor=reviewer, action="design.production_engineering.validation_changed", instance=version, metadata={"validated": bool(validated), "notes_present": bool(notes)}, request=request)
    return version


def require_draft(version, actor):
    require_design_access(actor, version.design, edit=True)
    if version.status != GarmentDesignVersion.Status.DRAFT:
        raise ValidationError("Submitted/reviewed versions are immutable; create a new revision instead.")
    if getattr(version, "reference_provenance", None):
        raise PermissionDenied("Frozen reference versions are not editable through Designer workflows.")


@transaction.atomic
def update_technical_definition(*, version, actor, data, request=None):
    require_draft(version, actor)
    allowed = {"summary", "base_material", "construction_notes", "technical_specs", "product_class", "size_system", "decoration_applicability", "qc_requirements"}
    changed = []
    for field in allowed:
        if field in data:
            setattr(version, field, data[field])
            changed.append(field)
    version.full_clean()
    if changed:
        version.save(update_fields=changed)
        record_audit_event(actor=actor, action="design.technical_data.updated", instance=version, metadata={"fields": sorted(changed)}, request=request)
    return version


@transaction.atomic
def add_asset(*, version, actor, media_asset, kind, label="", symbolic_ref=None, technical_role="", size_label="", reference_only=False, request=None):
    require_draft(version, actor)
    organization = version.design.organization
    if media_asset.access == media_asset.Access.PRIVATE:
        claim_or_require_private_designer_asset(asset=media_asset, organization=organization, actor=actor, purpose=f"design_{kind}")
    elif kind != DesignAsset.Kind.PRODUCT_IMAGE:
        raise ValidationError("Technical design assets must remain private.")
    elif media_asset.uploaded_by_id and media_asset.uploaded_by_id != actor.pk and not actor.is_staff:
        raise PermissionDenied("This media asset is not owned by the current user.")
    asset = DesignAsset(version=version, media_asset=media_asset, kind=kind, label=label, symbolic_ref=symbolic_ref, technical_role=technical_role, size_label=size_label, reference_only=reference_only)
    asset.full_clean()
    asset.save()
    record_audit_event(actor=actor, action="design.asset.added", instance=asset, metadata={"design_id": version.design_id, "kind": kind, "role": technical_role}, request=request)
    return asset


@transaction.atomic
def remove_asset(*, asset, actor, request=None):
    require_draft(asset.version, actor)
    version = asset.version
    if asset.pattern_requirements.exists() or asset.colorway_roles.exists():
        raise ValidationError("Detach this asset from technical requirements before removing it.")
    asset_id = asset.pk
    kind = asset.kind
    asset.delete()
    record_audit_event(actor=actor, action="design.asset.removed", instance=version, metadata={"design_id": version.design_id, "asset_id": asset_id, "kind": kind}, request=request)


@transaction.atomic
def add_or_update_blocker(*, version, actor, code, description, reference_only=False, request=None):
    if not actor.is_staff:
        raise PermissionDenied("Staff access required.")
    blocker, created = TechnicalBlocker.objects.update_or_create(version=version, code=code, defaults={"description": description, "status": TechnicalBlocker.Status.OPEN, "reference_only": reference_only, "resolved_at": None, "resolved_by": None})
    record_audit_event(actor=actor, action="design.blocker.added" if created else "design.blocker.reopened", instance=blocker, metadata={"version_id": version.pk, "code": code}, request=request)
    return blocker


@transaction.atomic
def resolve_blocker(*, blocker, actor, request=None):
    if not actor.is_staff:
        raise PermissionDenied("Staff access required.")
    blocker.status = TechnicalBlocker.Status.RESOLVED
    blocker.resolved_at = timezone.now()
    blocker.resolved_by = actor
    blocker.save(update_fields=["status", "resolved_at", "resolved_by"])
    record_audit_event(actor=actor, action="design.blocker.resolved", instance=blocker, metadata={"version_id": blocker.version_id, "code": blocker.code}, request=request)
    return blocker
