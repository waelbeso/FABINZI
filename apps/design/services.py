from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.media.designer_services import require_private_designer_asset
from apps.notifications.models import Notification
from apps.organizations.models import Membership, Organization
from apps.organizations.services import require_org_access, user_has_org_access
from .models import DecorationZone, DesignAsset, GarmentDesign, GarmentDesignVersion, SizeChartRow, TechnicalReview

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
    design.full_clean(); design.save()
    version = GarmentDesignVersion.objects.create(design=design, version_number=1, created_by=actor)
    record_audit_event(actor=actor, action="design.created", instance=design, metadata={"organization_id": organization.pk, "version_id": version.pk}, request=request)
    return design


@transaction.atomic
def create_revision(*, design, actor, request=None):
    require_design_access(actor, design, edit=True)
    latest = design.versions.order_by("-version_number").first()
    if latest and latest.status not in {GarmentDesignVersion.Status.REVISION_REQUIRED, GarmentDesignVersion.Status.APPROVED, GarmentDesignVersion.Status.REJECTED}:
        raise ValidationError("A new revision can only follow a reviewed version.")
    number = (design.versions.aggregate(m=Max("version_number"))["m"] or 0) + 1
    version = GarmentDesignVersion.objects.create(design=design, version_number=number, created_by=actor, summary=f"Revision {number}", base_material=latest.base_material if latest else "", construction_notes=latest.construction_notes if latest else "", technical_specs=latest.technical_specs if latest else {})
    if latest:
        for row in latest.size_rows.all(): SizeChartRow.objects.create(version=version, size_label=row.size_label, measurements=row.measurements, notes=row.notes, sort_order=row.sort_order)
        for zone in latest.decoration_zones.all(): DecorationZone.objects.create(version=version, name=zone.name, method=zone.method, placement=zone.placement, max_width_mm=zone.max_width_mm, max_height_mm=zone.max_height_mm, notes=zone.notes)
    design.status = GarmentDesign.Status.DRAFT; design.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="design.revision.created", instance=version, metadata={"design_id": design.pk}, request=request)
    return version


def validate_version_ready(version):
    if not version.base_material:
        raise ValidationError("Base material is required.")
    if not version.technical_specs:
        raise ValidationError("Technical specifications are required.")
    if not version.size_rows.exists():
        raise ValidationError("At least one size-chart row is required.")
    if not version.assets.filter(kind=DesignAsset.Kind.TECH_PACK).exists():
        raise ValidationError("A private tech pack is required.")
    if not version.assets.filter(kind=DesignAsset.Kind.PRODUCT_IMAGE).exists():
        raise ValidationError("At least one product image is required.")


@transaction.atomic
def submit_version(*, version, actor, request=None):
    require_design_access(actor, version.design, edit=True)
    if version.status != GarmentDesignVersion.Status.DRAFT:
        raise ValidationError("Only draft versions can be submitted.")
    validate_version_ready(version)
    version.status = GarmentDesignVersion.Status.SUBMITTED; version.submitted_at = timezone.now(); version.save(update_fields=["status", "submitted_at"])
    version.design.status = GarmentDesign.Status.IN_REVIEW; version.design.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="design.version.submitted", instance=version, metadata={"design_id": version.design_id}, request=request)
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
    version.status = decision; version.reviewed_at = timezone.now(); version.reviewed_by = reviewer; version.review_notes = notes
    version.save(update_fields=["status", "reviewed_at", "reviewed_by", "review_notes"])
    design_status = {TechnicalReview.Decision.APPROVED: GarmentDesign.Status.APPROVED, TechnicalReview.Decision.REVISION_REQUIRED: GarmentDesign.Status.REVISION_REQUIRED, TechnicalReview.Decision.REJECTED: GarmentDesign.Status.REJECTED}[decision]
    version.design.status = design_status; version.design.save(update_fields=["status", "updated_at"])
    title_en = {"approved":"Garment design approved","revision_required":"Garment design needs revision","rejected":"Garment design rejected"}[decision]
    title_ar = {"approved":"تم اعتماد تصميم القطعة","revision_required":"تصميم القطعة يحتاج إلى تعديلات","rejected":"تم رفض تصميم القطعة"}[decision]
    for membership in version.design.organization.memberships.filter(is_active=True).select_related("user"):
        Notification.objects.create(recipient=membership.user, type="garment_design_review", title_en=title_en, title_ar=title_ar, body_en=notes, body_ar=notes, destination=f"/designer/designs/{version.design_id}/")
    record_audit_event(actor=reviewer, action=f"design.version.{decision}", instance=version, metadata={"design_id": version.design_id, "notes_present": bool(notes)}, request=request)
    return version


def require_draft(version, actor):
    require_design_access(actor, version.design, edit=True)
    if version.status != GarmentDesignVersion.Status.DRAFT:
        raise ValidationError("Submitted/reviewed versions are immutable; create a new revision instead.")


@transaction.atomic
def add_asset(*, version, actor, media_asset, kind, label="", request=None):
    require_draft(version, actor)
    organization = version.design.organization
    if media_asset.access == media_asset.Access.PRIVATE:
        require_private_designer_asset(asset=media_asset, organization=organization, actor=actor)
    elif kind != DesignAsset.Kind.PRODUCT_IMAGE:
        raise ValidationError("Technical design assets must remain private.")
    elif media_asset.uploaded_by_id and media_asset.uploaded_by_id != actor.pk and not actor.is_staff:
        raise PermissionDenied("This media asset is not owned by the current user.")
    asset = DesignAsset(version=version, media_asset=media_asset, kind=kind, label=label); asset.full_clean(); asset.save()
    record_audit_event(actor=actor, action="design.asset.added", instance=asset, metadata={"design_id": version.design_id, "kind": kind}, request=request)
    return asset
